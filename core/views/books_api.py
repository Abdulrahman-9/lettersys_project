# -*- coding: utf-8 -*-
"""
Book JSON/mutation API views.
save_book_api, delete, bulk-delete, bulk-status, undo, detail-json, inline-status.
"""

import json
import logging
import mimetypes
import os
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db import IntegrityError, transaction
from django.db.models import Prefetch
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from django.core.exceptions import ValidationError
from ..attachment_service import create_attachment, validate_attachment_file
from ..decorators import rate_limit
from ..document_types import resolve_document_type
from ..extraction.kinds import normalize_book_kind
from ..models import (
    Attachment,
    Book,
    BookHistory,
    BookSequence,
)
from .books_helpers import (
    _normalize_secret_level_value,
    _resolve_entities,
    find_duplicate_candidates,
)

logger = logging.getLogger(__name__)


def _strip_sender_fields_for_outgoing(kind, sender_number, sender_date_str):
    """حقول الجهة المُرسِلة لا معنى لها في الصادر — تُفرَّغ **على الخادم**.

    الجذر المقيس (2026-08-18): البوّابة كانت في الواجهة وحدها — `extraction_smart.js`
    يُخفي الحقلين عند `showSenderFields:false`، لكنّ مسار رمز المسح يملأ
    `senderDate`/`senderNumber` **بلا شرط** ولا يستدعي `syncKindUI`، فيحتفظ حقلٌ مخفيٌّ
    بقيمته ويُرسَل عند الحفظ. القاعدة تحمل الأثر: **11 كتاباً صادراً** تسرّبت إليه حقول
    جهةٍ (تاريخٌ في 2 · عددٌ في 9) من 1,777. نادرٌ لكنّه حيّ.

    والضرر ليس تجميليّاً: `SenderNumberProfiles._ensure_index` يقرأ كلّ كتابٍ بعددِ جهةٍ
    **بلا مرشِّح نوع** (profile.py:120-125)، فكتابٌ صادرٌ ملوَّث يُدرّب قالبَ أرقامٍ
    لقسمٍ من أقسامنا نحن كأنّه جهةٌ مُرسِلة. البوّابةُ على الخادم تجعل التسرّب مستحيلاً
    لا نادراً — والواجهة تبقى طبقةَ راحةٍ لا طبقةَ صحّة.
    """
    from core.extraction.kinds import is_incoming_kind
    if is_incoming_kind(kind):
        return sender_number, sender_date_str
    return '', ''


def _duplicate_guard(request, data, *, kind, title, sender_number,
                     cmp_date, party_entities, exclude_id=None):
    """حارس التكرار المشترك (الحفظ + التعديل). يُعيد JsonResponse(409) للمنع/التنبيه،
    أو None للسماح بالمتابعة. يُستدعى قبل استهلاك أي رقم تسلسلي.

    - 4/4 (مكرر مؤكَّد): يُمنَع؛ المشرف وحده يتجاوز بإرسال confirm_duplicate=true
      (يُفحَص في الخادم — لا يكفي علم الواجهة).
    - 3/4 (مشابه): تنبيه ذكي؛ أيّ مستخدم يتجاوزه بإرسال confirm_duplicate=true.
    """
    candidates = find_duplicate_candidates(
        kind=kind, title=title, cmp_date=cmp_date,
        party_number=sender_number, party_entities=party_entities,
        exclude_id=exclude_id,
    )
    if not candidates:
        return None

    confirm = (data.get('confirm_duplicate') or 'false').lower() in ('true', '1', 'on')
    is_admin = bool(request.user.is_superuser or request.user.is_staff)
    top = candidates[0]['match_count']

    if top >= 4 and not (confirm and is_admin):
        return JsonResponse({
            'success': False,
            'error_code': 'DUPLICATE_BOOK',
            'message': 'هذا الكتاب مُدخَل مسبقاً — تطابق تامّ (العنوان والتاريخ والجهة والرقم).',
            'duplicates': candidates,
            'can_override': is_admin,
        }, status=409)
    if top == 3 and not confirm:
        return JsonResponse({
            'success': False,
            'error_code': 'SIMILAR_BOOK',
            'message': 'قد يكون هذا الكتاب مشابهاً لكتابٍ مُدخَلٍ سابقاً — راجِع ثم تابِع أو ألغِ.',
            'duplicates': candidates,
            'can_override': True,
        }, status=409)
    return None


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
        scan_token = (data.get('scan_token') or '').strip()  # لحلقة التقاط التدريب

        our_number = (data.get('our_number') or data.get('book_number') or '').strip()
        sender_number = (data.get('sender_number') or data.get('outgoing_incoming_number') or '').strip()
        title = (data.get('title') or '').strip()
        book_date_str = (data.get('date') or '').strip()
        sender_date_str = (data.get('sender_date') or '').strip()
        due_date_str = (data.get('due_date') or data.get('dueDate') or '').strip()
        kind_value = (data.get('kind') or data.get('book_kind') or 'incoming_internal').strip()
        sender_number, sender_date_str = _strip_sender_fields_for_outgoing(
            kind_value, sender_number, sender_date_str)
        # توافق رجعي: needs_followup كانت تُستخدم كعَلَم تفعيل المتابعة
        # الآن: وجود due_date نفسه يحدّد المتابعة (is_archived يُحسَب تلقائياً)
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

        # ── كشف التكرار (قبل استهلاك أي رقم تسلسلي — لا يُحرَق رقم عند الرفض) ──
        _dup_incoming = kind_value in ('incoming_internal', 'incoming_external')
        _dup_resp = _duplicate_guard(
            request, data, kind=kind_value, title=title, sender_number=sender_number,
            cmp_date=(sender_date if _dup_incoming else book_date),
            party_entities=(issuing_entities_list if _dup_incoming else receiving_entities_list),
        )
        if _dup_resp is not None:
            return _dup_resp

        reservation = None
        reservation_id = (data.get('reservation_id') or '').strip()
        auto_number = (data.get('auto_number') or 'false').lower() in ('true', '1')
        # "بلا رقم": استثناء يُسمح به للكتب الداخلية فقط — يأخذ رقماً تقنياً ببادئة سجل 0
        numberless = (data.get('numberless') or 'false').lower() in ('true', '1')
        numberless_internal = numberless and kind_value in ('incoming_internal', 'outgoing_internal')
        if numberless_internal:
            reservation_id = ''   # نتجاهل أي حجز
            auto_number = False
            # استهلاك الرقم يتم داخل المعاملة (B2) كي لا يُحرق رقم سجل إن فشل الإنشاء

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
            pass  # استهلاك الرقم التلقائي يتم داخل المعاملة (B2)
        elif our_number:
            if Book.objects.filter(our_number=our_number, kind=kind_value).exists():
                return JsonResponse({
                    'success': False,
                    'message': f'الرقم {our_number} مستخدم بالفعل لكتاب آخر من نفس النوع.',
                    'error_code': 'DUPLICATE_NUMBER',
                }, status=409)

        # تحقّق موحّد من الملف قبل بدء المعاملة (يُرجِع 400 نظيفاً بلا استهلاك رقم) — #12
        if 'file' in request.FILES:
            try:
                validate_attachment_file(request.FILES['file'])
            except ValidationError as ve:
                return JsonResponse({
                    'success': False,
                    'message': '؛ '.join(ve.messages),
                    'error_code': 'INVALID_FILE',
                }, status=400)

        # المنطق الموحّد: due_date موجود ⇒ نشط (is_archived=False)، غير ذلك ⇒ مؤرشف
        effective_due_date = due_date if needs_followup else None
        attachment = None  # يُلتقط من create_attachment لربط حلقة التدريب لاحقاً
        try:
            with transaction.atomic():
                # تعيين الرقم التلقائي داخل المعاملة (B2): لا يُستهلك رقم السجل الرسمي
                # إلا إذا اكتمل إنشاء الكتاب — يمنع فجوات الترقيم عند فشل الإنشاء.
                if numberless_internal:
                    # «بلا رقم»: الحقل يبقى فارغاً ولا يُستهلك رقمٌ من السلسلة —
                    # منحُه رقماً كان يبتلع رقماً لا يظهر على أي ورقة.
                    our_number = BookSequence.consume_next(kind_value, numberless=True)['formatted']
                elif auto_number and not reservation_id:
                    our_number = BookSequence.consume_next(kind_value)['formatted']

                book = Book.objects.create(
                    our_number=our_number,
                    sender_number=sender_number,
                    title=title,
                    document_type=document_type,
                    date=book_date,
                    due_date=effective_due_date,
                    sender_date=sender_date,
                    secret_level=secret_level,
                    kind=kind_value,
                    margin=data.get('margin') or data.get('margin_text', ''),
                    is_archived=(effective_due_date is None),
                    created_by=request.user
                )

                book.issuing_entities.set(issuing_entities_list)
                book.receiving_entities.set(receiving_entities_list)

                if 'file' in request.FILES:
                    file_obj = request.FILES['file']
                    attachment = create_attachment(book, file_obj, user=request.user)
                    logger.info(f'Attachment saved: book_id={book.id}, file={file_obj.name}')

                BookHistory.objects.create(book=book, action='create', by=request.user)

                if reservation:
                    reservation.mark_used(book)
        except IntegrityError:
            # سباق نادر: رقم اجتاز فحص exists() ثم اصطدم بقيد القاعدة الفريد (B1).
            # المعاملة تراجعت كاملةً (الرقم التلقائي/الحجز لم يُحرَق).
            return JsonResponse({
                'success': False,
                'message': f'الرقم {our_number} مستخدم بالفعل لكتاب آخر من نفس النوع.',
                'error_code': 'DUPLICATE_NUMBER',
            }, status=409)
        except Exception:
            if reservation is not None:
                logger.warning(
                    'Save failed after reservation %s validated; keeping reservation active for retry.',
                    reservation.pk,
                )
            raise

        # الإشعار بعد تأكيد المعاملة (خارج القفل): لا نُخطر إلا بعد الحفظ الفعلي،
        # ولا نُطيل قفل صف التسلسل بمكالمة SMTP بطيئة (نتيجة #8 + B2).
        try:
            from core.messaging.engines.smtp import send_book_saved_notification
            send_book_saved_notification(book, sent_by=request.user)
        except Exception as email_err:
            logger.warning(f'[EmailNotify] Failed after save book={book.pk}: {email_err}')

        # حلقة التقاط التدريب (post-commit، مَحُوطة — لا تُفشل الحفظ أبداً): تحفظ
        # زوج (نصّ OCR → الحقول المؤكَّدة) + تصحيحات المستخدم لتغذية نماذج التعلّم.
        if scan_token and attachment is not None:
            try:
                from django.core.cache import cache as _scan_cache
                from core.extraction.capture import persist_extraction_capture
                suggested = _scan_cache.get(f'scan_token:{scan_token}')
                if not suggested:
                    # الكاش خاب (عمليّةٌ أخرى · إعادةُ تشغيل · انقضاءُ مهلة) ⟵ الجدول
                    # الدائم. بدون هذا الارتداد يضيع ذهبُ التدريب بالصدفة لا بالخطأ.
                    from core.models import ScanPayload
                    _row = ScanPayload.objects.filter(token=scan_token).first()
                    suggested = _row.data if _row else None
                    if suggested:
                        logger.info('[capture] حمولة المسح من الجدول الدائم (الكاش خاب)')
                if suggested:
                    persist_extraction_capture(
                        book=book, attachment=attachment, suggested=suggested,
                        final={'our_number': book.our_number, 'title': book.title,
                               'secret_level': book.secret_level, 'kind': book.kind,
                               # العدد النهائي = حقيقة التدريب لحلقة العدد الجديدة
                               'sender_number': book.sender_number or '',
                               'sender_date': str(book.sender_date or ''),
                               # تاريخُ القيد ومصدرُ قيمة تاريخ الجهة — يُرشِّحان
                               # ذهبَ التدريب لاحقاً (فارقٌ صفر = قراءةُ ختمنا
                               # مُحتمَلة · ومؤكَّدٌ بنقرةٍ ≠ مكتوبٌ بيد).
                               'date': str(book.date or ''),
                               'sender_date_provenance': (
                                   request.POST.get('sender_date_provenance') or '')},
                        user=request.user)
            except Exception as cap_err:
                logger.warning('[capture] تعذّر التقاط التدريب: %s', cap_err)

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
    """
    تحديث حالة عدة كتب دفعة واحدة — فقط أرشفة أو إعادة فتح المتابعة.
    status ∈ {'archived', 'reopen'}
        - 'archived': إنهاء المتابعة (is_archived=True)
        - 'reopen':   إعادة فتح المتابعة (is_archived=False) — يتطلب وجود due_date
    """
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    try:
        data = json.loads(request.body)
        book_ids = data.get("book_ids", [])
        action = (data.get("status") or data.get("action") or "").strip()

        if not book_ids:
            return JsonResponse({"error": "No book IDs provided"}, status=400)
        if action not in ("archived", "reopen"):
            return JsonResponse({"error": "Invalid action — use 'archived' or 'reopen'"}, status=400)

        try:
            clean_ids = [int(bid) for bid in book_ids]
        except (TypeError, ValueError):
            return JsonResponse({"error": "book_ids must be integers"}, status=400)

        books_qs = Book.objects.filter(id__in=clean_ids, is_deleted=False)
        if not (request.user.is_superuser or request.user.is_staff):
            books_qs = books_qs.filter(created_by=request.user)

        if action == "archived":
            target_value, action_label = True, "أُرشفت"
            eligible_qs = books_qs.filter(is_archived=False)
        else:  # reopen
            target_value, action_label = False, "أُعيد فتحها"
            eligible_qs = books_qs.filter(is_archived=True, due_date__isnull=False)

        eligible_ids = list(eligible_qs.values_list('id', flat=True))
        found_ids = set(books_qs.values_list('id', flat=True))
        failed_ids = [bid for bid in clean_ids if bid not in found_ids]

        if eligible_ids:
            eligible_qs.update(is_archived=target_value, updated_at=timezone.now())
            BookHistory.objects.bulk_create([
                BookHistory(
                    book_id=bid,
                    action="status",
                    by=request.user,
                    notes=f"{action_label} (bulk)",
                )
                for bid in eligible_ids
            ], ignore_conflicts=True)

        return JsonResponse({
            "success": True,
            "updated_count": len(eligible_ids),
            "failed_ids": failed_ids,
            "action": action,
            "message": f"تم تحديث {len(eligible_ids)} كتاب",
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

    image_exts = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.tif', '.tiff')

    def _safe_size(att):
        # ملف مفقود على القرص لا يجب أن يُسقط المودال (الذي صار يعتمد على هذه النقطة)
        try:
            return att.file.size if att.file else 0
        except (OSError, ValueError):
            return 0

    attachments = []
    for a in book.attachments.all():
        name = os.path.basename(a.file.name) if a.file else ''
        lower = name.lower()
        content_type, _ = mimetypes.guess_type(name) if name else (None, None)
        attachments.append({
            'id': a.id,
            'name': name,
            'url': a.file.url if a.file else '',
            'size': _safe_size(a),
            'is_pdf': lower.endswith('.pdf'),
            'is_image': lower.endswith(image_exts),
            'content_type': content_type or '',
            'is_primary': False,
        })

    # المستند الأساسي للعرض المضمّن: أول PDF، وإلا أول صورة، وإلا أول مرفق
    primary = (
        next((a for a in attachments if a['is_pdf']), None)
        or next((a for a in attachments if a['is_image']), None)
        or (attachments[0] if attachments else None)
    )
    if primary is not None:
        primary['is_primary'] = True

    data = {
        'id': book.pk,
        'our_number': book.our_number or '',                 # المخزَّن — للمطابقة
        'our_number_display': book.our_number_display,       # المعروض — «825/2025»
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
        'due_date': str(book.due_date) if book.due_date else '',
        'is_archived': book.is_archived,
        'followup_state': book.followup_state,
        'followup_label': book.followup_label,
        'delay_days': book.delay_days,
        'issuing_entities': [{'id': e.id, 'name': e.name} for e in book.issuing_entities.all()],
        'receiving_entities': [{'id': e.id, 'name': e.name} for e in book.receiving_entities.all()],
        'created_by': book.created_by.get_full_name() or book.created_by.username if book.created_by else '',
        'created_at': book.created_at.strftime('%Y-%m-%d %H:%M') if book.created_at else '',
        'attachments': attachments,
        'edit_url': reverse('book_edit', args=[book.pk]),
        'detail_url': reverse('book_detail', args=[book.pk]),
        'inline_status_url': reverse('api_book_inline_status', args=[book.pk]),
    }
    return JsonResponse(data)


@login_required
def api_book_inline_status(request, pk):
    """
    تبديل حالة المتابعة من قائمة الكتب الموحَّدة (inline).
    action ∈ {'archived', 'reopen'}:
        - 'archived': إنهاء المتابعة
        - 'reopen':   إعادة فتح المتابعة (يتطلب وجود due_date)
    """
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
        action = (payload.get("status") or payload.get("action") or "").strip()
    except (json.JSONDecodeError, AttributeError):
        action = (request.POST.get("status") or request.POST.get("action") or "").strip()

    if action not in ("archived", "reopen"):
        return JsonResponse({"error": "Invalid action — use 'archived' or 'reopen'"}, status=400)

    if action == "reopen" and not book.due_date:
        return JsonResponse({
            "error": "لا يمكن إعادة فتح المتابعة بدون تاريخ متابعة — حدّد تاريخاً أولاً عبر صفحة التعديل.",
        }, status=400)

    new_archived = (action == "archived")
    if book.is_archived != new_archived:
        book.is_archived = new_archived
        book.save(update_fields=["is_archived", "updated_at"])
        BookHistory.objects.create(
            book=book,
            action="status",
            by=request.user,
            notes=("أُرشف يدوياً (إنهاء متابعة)" if new_archived else "أُعيد فتح المتابعة"),
        )

    return JsonResponse({
        "success": True,
        "book_id": book.id,
        "is_archived": book.is_archived,
        "followup_state": book.followup_state,
        "followup_label": book.followup_label,
        "message": "تم تحديث الحالة بنجاح",
    })


@login_required
@rate_limit('update_book', max_attempts=30, window_seconds=60, by='user')
def update_book_api(request):
    """API لتعديل كتاب قائم من صفحة الاستخراج الذكي."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'Method not allowed', 'error_code': 'METHOD_NOT_ALLOWED'}, status=405)
    try:
        data = request.POST
        edit_pk = (data.get('edit_pk') or '').strip()
        if not edit_pk:
            return JsonResponse({'success': False, 'message': 'edit_pk مطلوب', 'error_code': 'MISSING_EDIT_PK'}, status=400)

        book = get_object_or_404(Book, pk=edit_pk, is_deleted=False)
        has_permission = (
            request.user.is_superuser or
            request.user.is_staff or
            book.created_by == request.user
        )
        if not has_permission:
            return JsonResponse({'success': False, 'message': 'ليس لديك صلاحية تعديل هذا الكتاب', 'error_code': 'PERMISSION_DENIED'}, status=403)

        sender_number = (data.get('sender_number') or '').strip()
        title = (data.get('title') or '').strip()
        book_date_str = (data.get('date') or '').strip()
        sender_date_str = (data.get('sender_date') or '').strip()
        sender_number, sender_date_str = _strip_sender_fields_for_outgoing(
            (data.get('kind') or getattr(book, 'kind', '') or ''), sender_number, sender_date_str)
        due_date_str = (data.get('due_date') or data.get('dueDate') or '').strip()
        needs_followup = (data.get('needs_followup') or 'false').lower() in ('true', '1', 'on')
        secret_level = _normalize_secret_level_value(data.get('secret_level'))
        document_type = resolve_document_type(book.kind, data.get('document_type') or data.get('book_type_name'))

        if not title:
            return JsonResponse({'success': False, 'message': 'العنوان مطلوب', 'error_code': 'MISSING_FIELD'}, status=400)
        if not book_date_str:
            return JsonResponse({'success': False, 'message': 'التاريخ مطلوب', 'error_code': 'MISSING_FIELD'}, status=400)

        try:
            from datetime import datetime
            book_date = datetime.strptime(book_date_str, '%Y-%m-%d').date()
            sender_date = datetime.strptime(sender_date_str, '%Y-%m-%d').date() if sender_date_str else None
            due_date = None
            if needs_followup and not due_date_str:
                due_date = book_date + timedelta(days=7)
            elif due_date_str:
                due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date()
        except Exception:
            return JsonResponse({'success': False, 'message': 'صيغة التاريخ غير صحيحة', 'error_code': 'INVALID_DATE'}, status=400)

        issuing_ids = request.POST.getlist('issuing_entity_ids[]')
        issuing_new = request.POST.getlist('issuing_entity_new[]')
        receiving_ids = request.POST.getlist('receiving_entity_ids[]')
        receiving_new = request.POST.getlist('receiving_entity_new[]')
        issuing_entities_list = _resolve_entities(issuing_ids, issuing_new, 'issuer')
        receiving_entities_list = _resolve_entities(receiving_ids, receiving_new, 'receiver')

        # لا كشف تكرار عند التعديل: الكتاب محفوظ مسبقاً — التنبيه للإدخال الأوّل فقط.

        # تحقّق موحّد من الملف قبل المعاملة (400 نظيف) — #12
        if 'file' in request.FILES:
            try:
                validate_attachment_file(request.FILES['file'])
            except ValidationError as ve:
                return JsonResponse({
                    'success': False,
                    'message': '؛ '.join(ve.messages),
                    'error_code': 'INVALID_FILE',
                }, status=400)

        with transaction.atomic():
            book.sender_number = sender_number
            book.title = title
            book.document_type = document_type
            book.date = book_date
            book.sender_date = sender_date
            effective_due_date = due_date if needs_followup else None
            book.due_date = effective_due_date
            book.secret_level = secret_level
            book.margin = data.get('margin') or ''
            # إذا أزال المستخدم تاريخ المتابعة ⇒ يصبح مؤرشفاً تلقائياً (في save())
            # إذا أضاف/أبقى تاريخ متابعة ⇒ نشط (نعكس الأرشفة)
            if effective_due_date is not None:
                book.is_archived = False
            book.save()
            book.issuing_entities.set(issuing_entities_list)
            book.receiving_entities.set(receiving_entities_list)
            _had_new_file = 'file' in request.FILES
            if _had_new_file:
                file_obj = request.FILES['file']
                # وضع التعديل = استبدال المرفق المُعدَّل تحديداً، لا أرشفة كل المرفقات:
                # نستهدف المرفق الذي عُدِّلت صفحاته (attachment_id من الواجهة)، وإلا الأساسي.
                # يمنع هذا أن يؤرشف تدويرُ/حذفُ صفحةٍ في مرفقٍ بقيةَ مرفقات الكتاب (فقدان/تدقيق).
                active_attachments = book.attachments.filter(is_deleted=False)
                target_attachment = None
                _target_id = (request.POST.get('attachment_id') or '').strip()
                if _target_id:
                    target_attachment = active_attachments.filter(pk=_target_id).first()
                if target_attachment is None:
                    from core.attachment_service import pick_primary_attachment
                    target_attachment = pick_primary_attachment(active_attachments)
                if target_attachment is not None:
                    target_attachment.is_deleted = True
                    target_attachment.deleted_at = timezone.now()
                    target_attachment.deleted_by = request.user
                    target_attachment.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])
                create_attachment(book, file_obj, user=request.user)
            # سجّل استبدال المستند صراحةً عند رفع ملف جديد (يُحتسب في تحليلات دورة الحياة
            # «مرّة حُدِّث/أُرفق المستند»)؛ وإلا فهو تعديل بيانات فقط.
            BookHistory.objects.create(
                book=book,
                action='replace-attachment' if _had_new_file else 'edit',
                by=request.user,
                notes='تحديث المستند المرفق عبر التعديل' if _had_new_file else '',
            )

        logger.info('Book updated via API: book_id=%s user_id=%s', book.id, request.user.id)
        return JsonResponse({
            'success': True,
            'message': 'تم حفظ التعديلات بنجاح',
            'book_id': book.id,
            'book_number': book.our_number,
            'redirect_url': reverse('book_detail', args=[book.pk]),
        }, status=200)

    except Exception as e:
        logger.error('Error updating book: %s', e, exc_info=True)
        debug_payload = {}
        if getattr(settings, 'DEBUG', False):
            debug_payload = {'debug_error': f'{type(e).__name__}: {e}'}
        return JsonResponse({'success': False, 'message': 'حدث خطأ في حفظ التعديلات', 'error_code': 'SERVER_ERROR', **debug_payload}, status=500)


__all__ = [
    'save_book_api',
    'update_book_api',
    'api_delete_book',
    'api_bulk_delete_books',
    'api_bulk_update_status_books',
    'api_undo_delete_book',
    'api_book_detail_json',
    'api_book_inline_status',
]
