# -*- coding: utf-8 -*-
"""
Book JSON/mutation API views.
save_book_api, delete, bulk-delete, bulk-status, undo, detail-json, inline-status.
"""

import json
import logging
import os
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db import transaction
from django.db.models import Prefetch
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from ..decorators import rate_limit
from ..document_types import resolve_document_type
from ..extraction_kinds import normalize_book_kind
from ..models import (
    Attachment,
    Book,
    BookHistory,
    BookSequence,
)
from .books_helpers import (
    _normalize_secret_level_value,
    _resolve_entities,
    compute_time_state,
)

logger = logging.getLogger(__name__)


@login_required
@rate_limit('save_book', max_attempts=30, window_seconds=60, by='user')
def save_book_api(request):
    """
    API لحفظ كتاب جديد من صفحة الاستخراج الذكي.
    يدعم إنشاء جهات جديدة، رفع مرفقات، وحساب تاريخ الاستحقاق.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed', 'error_code': 'METHOD_NOT_ALLOWED'}, status=405)
    try:
        data = request.POST

        our_number = (data.get('our_number') or data.get('book_number') or '').strip()
        sender_number = (data.get('sender_number') or data.get('outgoing_incoming_number') or '').strip()
        title = (data.get('title') or '').strip()
        book_date_str = (data.get('date') or '').strip()
        sender_date_str = (data.get('sender_date') or '').strip()
        due_date_str = (data.get('due_date') or data.get('dueDate') or '').strip()
        kind_value = (data.get('kind') or data.get('book_kind') or 'incoming_internal').strip()
        needs_followup = (data.get('needs_followup') or 'false').lower() in ('true', '1', 'on')
        secret_level = _normalize_secret_level_value(data.get('secret_level'))
        kind_value = normalize_book_kind(kind_value, 'incoming_internal')
        document_type = resolve_document_type(kind_value, data.get('document_type') or data.get('book_type_name'))

        required_values = {
            'our_number': our_number,
            'title': title,
            'date': book_date_str,
        }
        for field, value in required_values.items():
            if not value:
                return JsonResponse({
                    'success': False,
                    'message': f'الحقل {field} مطلوب',
                    'error_code': 'MISSING_FIELD'
                }, status=400)

        issuing_ids = request.POST.getlist('issuing_entity_ids[]')
        issuing_new = request.POST.getlist('issuing_entity_new[]')
        receiving_ids = request.POST.getlist('receiving_entity_ids[]')
        receiving_new = request.POST.getlist('receiving_entity_new[]')

        if not issuing_ids and not issuing_new:
            single_id = (data.get('issuing_entity_id') or '').strip()
            single_name = (data.get('issuing_entity') or '').strip()
            if single_id:
                issuing_ids = [single_id]
            elif single_name:
                issuing_new = [single_name]

        if not receiving_ids and not receiving_new:
            single_id = (data.get('receiving_entity_id') or '').strip()
            single_name = (data.get('receiving_entity') or '').strip()
            if single_id:
                receiving_ids = [single_id]
            elif single_name:
                receiving_new = [single_name]

        issuing_entities_list = _resolve_entities(issuing_ids, issuing_new, 'issuer')
        receiving_entities_list = _resolve_entities(receiving_ids, receiving_new, 'receiver')

        due_date = None
        sender_date = None
        try:
            from datetime import datetime
            book_date = datetime.strptime(book_date_str, '%Y-%m-%d').date()
            if sender_date_str:
                sender_date = datetime.strptime(sender_date_str, '%Y-%m-%d').date()
            if needs_followup and not due_date_str:
                due_date = book_date + timedelta(days=7)
            elif due_date_str:
                due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date()
        except Exception as e:
            logger.warning(f'Error parsing date: {e}')
            return JsonResponse({
                'success': False,
                'message': 'صيغة التاريخ غير صحيحة',
                'error_code': 'INVALID_DATE'
            }, status=400)

        reservation = None
        reservation_id = (data.get('reservation_id') or '').strip()
        auto_number = (data.get('auto_number') or 'false').lower() in ('true', '1')

        if reservation_id:
            from ..models import BookNumberReservation
            try:
                reservation = BookNumberReservation.objects.get(
                    pk=reservation_id,
                    user=request.user,
                )
            except BookNumberReservation.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'message': 'رقم القيد المحجوز غير صالح أو انتهت صلاحيته',
                    'error_code': 'INVALID_RESERVATION',
                    'refresh_reservation': True,
                }, status=409)

            if reservation.status == BookNumberReservation.STATUS_USED:
                return JsonResponse({
                    'success': False,
                    'message': 'تم استخدام رقم القيد المحجوز سابقاً.',
                    'error_code': 'RESERVATION_ALREADY_USED',
                    'book_id': reservation.book_id,
                    'refresh_reservation': False,
                }, status=409)

            if reservation.status == BookNumberReservation.STATUS_VOIDED:
                return JsonResponse({
                    'success': False,
                    'message': 'تم إلغاء حجز رقم القيد السابق.',
                    'error_code': 'RESERVATION_VOIDED',
                    'refresh_reservation': True,
                }, status=409)

            if reservation.status == BookNumberReservation.STATUS_EXPIRED or reservation.is_expired:
                try:
                    if reservation.status != BookNumberReservation.STATUS_EXPIRED:
                        reservation.mark_expired()
                except Exception:
                    pass
                return JsonResponse({
                    'success': False,
                    'message': 'انتهت صلاحية الحجز — يرجى إعادة طلب الرقم',
                    'error_code': 'RESERVATION_EXPIRED',
                    'refresh_reservation': True,
                }, status=409)

            if reservation.status not in [
                BookNumberReservation.STATUS_ACTIVE,
                BookNumberReservation.STATUS_REACTIVATED,
            ]:
                return JsonResponse({
                    'success': False,
                    'message': 'حالة الحجز الحالية لا تسمح بإتمام الحفظ.',
                    'error_code': 'INVALID_RESERVATION_STATUS',
                    'refresh_reservation': True,
                }, status=409)

            if reservation.kind and reservation.kind != kind_value:
                return JsonResponse({
                    'success': False,
                    'message': 'نوع الكتاب لا يطابق نوع الحجز',
                    'error_code': 'RESERVATION_KIND_MISMATCH',
                    'refresh_reservation': True,
                }, status=409)

            our_number = reservation.formatted
        elif auto_number:
            seq = BookSequence.consume_next(kind_value)
            our_number = seq['formatted']
        elif our_number:
            if Book.objects.filter(our_number=our_number, kind=kind_value).exists():
                return JsonResponse({
                    'success': False,
                    'message': f'الرقم {our_number} مستخدم بالفعل لكتاب آخر من نفس النوع.',
                    'error_code': 'DUPLICATE_NUMBER',
                }, status=409)

        try:
            with transaction.atomic():
                book = Book.objects.create(
                    our_number=our_number,
                    sender_number=sender_number,
                    title=title,
                    document_type=document_type,
                    date=book_date,
                    due_date=due_date if needs_followup else None,
                    sender_date=sender_date,
                    secret_level=secret_level,
                    kind=kind_value,
                    margin=data.get('margin') or data.get('margin_text', ''),
                    needs_followup=needs_followup,
                    final_status='pending' if needs_followup else 'archived',
                    created_by=request.user
                )

                book.issuing_entities.set(issuing_entities_list)
                book.receiving_entities.set(receiving_entities_list)

                if 'file' in request.FILES:
                    file_obj = request.FILES['file']
                    Attachment.objects.create(book=book, file=file_obj)
                    logger.info(f'Attachment saved: book_id={book.id}, file={file_obj.name}')

                BookHistory.objects.create(book=book, action='create', by=request.user)

                if reservation:
                    reservation.mark_used(book)

                try:
                    from core.messaging.engines.smtp import send_book_saved_notification
                    send_book_saved_notification(book, sent_by=request.user)
                except Exception as email_err:
                    logger.warning(f'[EmailNotify] Failed after save book={book.pk}: {email_err}')
        except Exception:
            if reservation is not None:
                logger.warning(
                    'Save failed after reservation %s validated; keeping reservation active for retry.',
                    reservation.pk,
                )
            raise

        logger.info(f'Book saved via API: book_id={book.id}, user_id={request.user.id}')
        return JsonResponse({
            'success': True,
            'message': 'تم حفظ الكتاب بنجاح',
            'book_id': book.id,
            'book_number': book.our_number
        }, status=201)

    except Exception as e:
        logger.error(f'Error saving book: {e}', exc_info=True)
        debug_payload = {}
        if getattr(settings, 'DEBUG', False):
            debug_payload = {'debug_error': f'{type(e).__name__}: {e}'}
        return JsonResponse({
            'success': False,
            'message': 'حدث خطأ في حفظ الكتاب',
            'error_code': 'SERVER_ERROR',
            **debug_payload,
        }, status=500)


@login_required
@rate_limit('delete_book', max_attempts=30, window_seconds=60, by='user')
def api_delete_book(request, book_id):
    """حذف كتاب (نقل لسلة المهملات)."""
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    book = get_object_or_404(Book, id=book_id)

    if not (request.user.is_superuser or request.user.is_staff or book.created_by == request.user):
        return JsonResponse({"error": "Unauthorized"}, status=403)

    try:
        book.is_deleted = True
        book.deleted_at = timezone.now()
        book.deleted_by = request.user
        book.save(update_fields=["is_deleted", "deleted_at", "deleted_by"])

        BookHistory.objects.create(
            book=book,
            action="delete",
            by=request.user,
            notes="Book moved to trash via AJAX"
        )

        return JsonResponse({
            "success": True,
            "message": "تم نقل الكتاب إلى سلة المهملات",
            "book_id": book.id
        })
    except Exception as e:
        logger.error(f"Error deleting book {book_id}: {e}", exc_info=True)
        return JsonResponse({"error": str(e)}, status=500)


@login_required
@rate_limit('bulk_delete_books', max_attempts=10, window_seconds=60, by='user')
def api_bulk_delete_books(request):
    """حذف عدة كتب دفعة واحدة."""
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    try:
        data = json.loads(request.body)
        book_ids = data.get("book_ids", [])

        if not book_ids:
            return JsonResponse({"error": "No book IDs provided"}, status=400)

        now = timezone.now()
        books_qs = Book.objects.filter(id__in=book_ids, is_deleted=False)
        if not (request.user.is_superuser or request.user.is_staff):
            books_qs = books_qs.filter(created_by=request.user)

        allowed_ids = list(books_qs.values_list('id', flat=True))
        failed_ids = [bid for bid in book_ids if bid not in allowed_ids]

        if allowed_ids:
            books_qs.filter(id__in=allowed_ids).update(
                is_deleted=True,
                deleted_at=now,
                deleted_by=request.user,
            )
            BookHistory.objects.bulk_create([
                BookHistory(
                    book_id=bid,
                    action="delete",
                    by=request.user,
                    notes="Book moved to trash via bulk delete",
                )
                for bid in allowed_ids
            ], ignore_conflicts=True)

        return JsonResponse({
            "success": True,
            "deleted_count": len(allowed_ids),
            "failed_ids": failed_ids,
            "message": f"تم حذف {len(allowed_ids)} كتاب"
        })
    except Exception as e:
        logger.error(f"Error in bulk delete: {e}", exc_info=True)
        return JsonResponse({"error": str(e)}, status=500)


@login_required
@rate_limit('bulk_update_status', max_attempts=20, window_seconds=60, by='user')
def api_bulk_update_status_books(request):
    """تحديث حالة عدة كتب دفعة واحدة."""
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    try:
        data = json.loads(request.body)
        book_ids = data.get("book_ids", [])
        status = (data.get("status") or "").strip()

        if not book_ids:
            return JsonResponse({"error": "No book IDs provided"}, status=400)

        valid_status = dict(Book._meta.get_field("final_status").choices)
        if status not in valid_status:
            return JsonResponse({"error": "Invalid status"}, status=400)

        try:
            clean_ids = [int(bid) for bid in book_ids]
        except (TypeError, ValueError):
            return JsonResponse({"error": "book_ids must be integers"}, status=400)

        books_qs = Book.objects.filter(id__in=clean_ids, is_deleted=False)
        if not (request.user.is_superuser or request.user.is_staff):
            books_qs = books_qs.filter(created_by=request.user)

        old_statuses = {b.id: b.final_status for b in books_qs.only('id', 'final_status')}
        to_update = [bid for bid, old in old_statuses.items() if old != status]
        failed_ids = [bid for bid in clean_ids if bid not in old_statuses]

        if to_update:
            books_qs.filter(id__in=to_update).update(
                final_status=status,
                updated_at=timezone.now(),
            )
            BookHistory.objects.bulk_create([
                BookHistory(
                    book_id=bid,
                    action="status",
                    by=request.user,
                    notes=f"تغيير الحالة من {old_statuses[bid]} إلى {status} (bulk)",
                )
                for bid in to_update
            ], ignore_conflicts=True)

        return JsonResponse({
            "success": True,
            "updated_count": len(to_update),
            "failed_ids": failed_ids,
            "status": status,
            "status_label": valid_status.get(status, status),
            "message": f"تم تحديث حالة {len(to_update)} كتاب",
        })
    except Exception as e:
        logger.error(f"Error in bulk status update: {e}", exc_info=True)
        return JsonResponse({"error": str(e)}, status=500)


@login_required
def api_undo_delete_book(request, book_id):
    """استرجاع كتاب محذوف."""
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    try:
        book = get_object_or_404(Book, id=book_id, is_deleted=True)

        if not (request.user.is_superuser or request.user.is_staff or book.created_by == request.user):
            return JsonResponse({"error": "Unauthorized"}, status=403)

        book.is_deleted = False
        book.deleted_at = None
        book.deleted_by = None
        book.save(update_fields=["is_deleted", "deleted_at", "deleted_by"])

        book.attachments.filter(is_deleted=True).update(
            is_deleted=False,
            deleted_at=None,
            deleted_by=None
        )

        BookHistory.objects.create(
            book=book,
            action="restore",
            by=request.user,
            notes="Book restored from trash via AJAX"
        )

        return JsonResponse({
            "success": True,
            "message": "تم استرجاع الكتاب بنجاح",
            "book_id": book.id
        })
    except Exception as e:
        logger.error(f"Error undoing delete for book {book_id}: {e}", exc_info=True)
        return JsonResponse({"error": str(e)}, status=500)


@login_required
@require_http_methods(["GET"])
def api_book_detail_json(request, pk):
    """API: إرجاع تفاصيل كتاب كـ JSON للمودال الموحد."""
    try:
        book = Book.objects.select_related('created_by').prefetch_related(
            'issuing_entities', 'receiving_entities',
            Prefetch('attachments', queryset=Attachment.objects.filter(is_deleted=False).order_by('-uploaded_at'))
        ).get(pk=pk, is_deleted=False)
    except Book.DoesNotExist:
        return JsonResponse({'error': 'الكتاب غير موجود'}, status=404)

    has_permission = (
        request.user.is_superuser or request.user.is_staff or book.created_by == request.user
    )
    if not has_permission:
        return JsonResponse({'error': 'ليس لديك صلاحية'}, status=403)

    book.time_state, book.delay_days = compute_time_state(book)

    attachments = [{
        'id': a.id,
        'name': os.path.basename(a.file.name) if a.file else '',
        'url': a.file.url if a.file else '',
        'size': a.file.size if a.file else 0,
    } for a in book.attachments.all()]

    data = {
        'id': book.pk,
        'our_number': book.our_number or '',
        'sender_number': book.sender_number or '',
        'kind': book.kind,
        'kind_label': book.kind_label,
        'kind_direction': book.kind_direction,
        'is_incoming': book.is_incoming,
        'is_outgoing': book.is_outgoing,
        'title': book.title,
        'date': str(book.date) if book.date else '',
        'sender_date': str(book.sender_date) if book.sender_date else '',
        'secret_level': book.get_secret_level_display(),
        'margin': book.margin or '',
        'needs_followup': book.needs_followup,
        'due_date': str(book.due_date) if book.due_date else '',
        'final_status': book.final_status,
        'status_label': book.status_label,
        'is_overdue': book.is_overdue,
        'time_state': book.time_state,
        'delay_days': book.delay_days,
        'issuing_entities': [{'id': e.id, 'name': e.name} for e in book.issuing_entities.all()],
        'receiving_entities': [{'id': e.id, 'name': e.name} for e in book.receiving_entities.all()],
        'created_by': book.created_by.get_full_name() or book.created_by.username if book.created_by else '',
        'created_at': book.created_at.strftime('%Y-%m-%d %H:%M') if book.created_at else '',
        'attachments': attachments,
        'edit_url': reverse('book_edit', args=[book.pk]),
        'detail_url': reverse('book_detail', args=[book.pk]),
    }
    return JsonResponse(data)


@login_required
def api_book_inline_status(request, pk):
    """Update book status inline for unified list UI (JSON response)."""
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    book = get_object_or_404(Book, pk=pk, is_deleted=False)
    has_permission = (
        request.user.is_superuser
        or request.user.is_staff
        or book.created_by == request.user
    )
    if not has_permission:
        return JsonResponse({"error": "Unauthorized"}, status=403)

    try:
        payload = json.loads(request.body)
        status = (payload.get("status") or "").strip()
    except (json.JSONDecodeError, AttributeError):
        status = (request.POST.get("status") or "").strip()

    valid_status = dict(Book._meta.get_field("final_status").choices)
    if status not in valid_status:
        return JsonResponse({"error": "Invalid status"}, status=400)

    old_status = book.final_status
    if old_status != status:
        book.final_status = status
        book.save(update_fields=["final_status", "updated_at"])
        BookHistory.objects.create(
            book=book,
            action="status",
            by=request.user,
            notes=f"تغيير الحالة من {old_status} إلى {status} (inline)",
        )

    return JsonResponse({
        "success": True,
        "book_id": book.id,
        "status": book.final_status,
        "status_label": valid_status.get(book.final_status, book.final_status),
        "message": "تم تحديث الحالة بنجاح",
    })


__all__ = [
    'save_book_api',
    'api_delete_book',
    'api_bulk_delete_books',
    'api_bulk_update_status_books',
    'api_undo_delete_book',
    'api_book_detail_json',
    'api_book_inline_status',
]
