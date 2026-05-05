# -*- coding: utf-8 -*-
"""
Book detail/edit/status views.
"""

import json
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Prefetch
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from ..document_types import DEFAULT_DOCUMENT_TYPE_BY_KIND, get_document_type_options
from ..forms import AttachmentForm, BookForm
from ..models import Attachment, Book, BookHistory, Entity
from .books_helpers import _resolve_entities, compute_time_state

logger = logging.getLogger(__name__)


@login_required
def book_detail(request, pk):
    """عرض تفاصيل كتاب واحد مع المرفقات والسجل."""
    book = get_object_or_404(
        Book.objects.select_related('created_by').prefetch_related(
            'issuing_entities',
            'receiving_entities',
            Prefetch(
                'attachments',
                queryset=Attachment.objects.filter(is_deleted=False)
                    .prefetch_related('versions')
                    .order_by('-uploaded_at')
            ),
            Prefetch(
                'history',
                queryset=BookHistory.objects.select_related('by').order_by('-created_at')
            )
        ),
        pk=pk,
        is_deleted=False
    )

    has_permission = (
        request.user.is_superuser or
        request.user.is_staff or
        book.created_by == request.user
    )

    if not has_permission:
        logger.warning(
            f"Unauthorized book access attempt: user_id={request.user.id} "
            f"username={request.user.username} book_id={pk}"
        )
        raise PermissionDenied("ليس لديك صلاحية الوصول لهذا الكتاب")

    if request.method == 'POST' and 'file' in request.FILES:
        form = AttachmentForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                with transaction.atomic():
                    att = form.save(commit=False)
                    att.book = book
                    att.uploaded_by = request.user
                    att.save()

                    BookHistory.objects.create(
                        book=book,
                        action="attach",
                        by=request.user,
                        notes=f"أضاف مرفق: {att.file.name}",
                        attachment=att
                    )

                    logger.info(f"Attachment uploaded: book_id={pk} file={att.file.name} user={request.user.username}")
                    messages.success(request, f"تم رفع المرفق '{att.file.name}' بنجاح.")
                    return redirect("book_detail", pk=pk)
            except Exception:
                logger.exception(f"Failed to upload attachment for book {pk}")
                messages.error(request, "حدث خطأ أثناء رفع المرفق. يرجى المحاولة مرة أخرى.")
        else:
            for error in form.errors.get('file', []):
                messages.error(request, error)

    book.time_state, book.delay_days = compute_time_state(book)

    back_url = f"{reverse('extraction-smart-desktop')}?kind={book.kind}"
    back_label = "إدخال كتاب جديد"
    if request.GET.get("from") == "list":
        back_url = reverse("book_list")
        back_label = "العودة للقائمة"

    attachments = book.attachments.all()
    comments = book.comments.select_related('created_by').all()

    return render(
        request,
        "core/book_detail.html",
        {
            "book": book,
            "attachments": attachments,
            "comments": comments,
            "back_url": back_url,
            "back_label": back_label
        },
    )


@login_required
def book_edit(request, pk):
    """تعديل كتاب قائم."""
    book = get_object_or_404(Book, pk=pk, is_deleted=False)

    has_permission = (
        request.user.is_superuser or
        request.user.is_staff or
        book.created_by == request.user
    )

    if not has_permission:
        logger.warning(
            f"Unauthorized book edit attempt: user_id={request.user.id} "
            f"username={request.user.username} book_id={pk}"
        )
        raise PermissionDenied("ليس لديك صلاحية تعديل هذا الكتاب")

    active_entities = Entity.objects.filter(is_active=True).order_by("name")
    entity_suggestions = list(active_entities.values("id", "name", "code"))
    entity_suggestions_json = json.dumps(entity_suggestions, ensure_ascii=False)
    document_type_defaults_json = json.dumps(DEFAULT_DOCUMENT_TYPE_BY_KIND, ensure_ascii=False)
    document_type_suggestions = get_document_type_options()

    existing_issuing = list(book.issuing_entities.values("id", "name", "code"))
    existing_receiving = list(book.receiving_entities.values("id", "name", "code"))
    existing_issuing_json = json.dumps(existing_issuing, ensure_ascii=False)
    existing_receiving_json = json.dumps(existing_receiving, ensure_ascii=False)

    if request.method == "POST":
        form = BookForm(request.POST, instance=book)
        if form.is_valid():
            try:
                modified_book = form.save(commit=False)
                modified_book.created_by = book.created_by
                modified_book.save()

                issuing_ids = request.POST.getlist("issuing_entity_ids")
                new_issuing_names = request.POST.getlist("new_issuing_entities")
                receiving_ids = request.POST.getlist("receiving_entity_ids")
                new_receiving_names = request.POST.getlist("new_receiving_entities")

                with transaction.atomic():
                    list(Book.objects.select_for_update().filter(pk=book.pk))
                    issuing_entities = _resolve_entities(issuing_ids, new_issuing_names, 'issuer')
                    receiving_entities = _resolve_entities(receiving_ids, new_receiving_names, 'receiver')
                    modified_book.issuing_entities.set(issuing_entities)
                    modified_book.receiving_entities.set(receiving_entities)
                    BookHistory.objects.create(book=book, action="edit", by=request.user)
                messages.success(request, "تم حفظ التعديلات بنجاح.")
                return redirect("book_detail", pk=book.pk)
            except Exception as e:
                logger.error(f"Error saving book: {str(e)}", exc_info=True)
                messages.error(request, f"خطأ أثناء حفظ التعديلات: {str(e)}")
        else:
            error_messages = []
            for field, errors in form.errors.items():
                for error in errors:
                    if field == '__all__':
                        error_messages.append(str(error))
                    else:
                        field_label = form.fields.get(field, {}).label if field in form.fields else field
                        error_messages.append(f"{field_label}: {error}")

            for error_msg in error_messages:
                messages.error(request, error_msg)
            logger.warning(f"Form validation failed for book {pk}: {form.errors}")
    else:
        form = BookForm(instance=book)

    _KIND_META = {
        'outgoing_internal': ('صادر داخلي', 'cyan', '📤'),
        'outgoing_external': ('صادر خارجي', 'cyan', '🌐'),
        'incoming_internal': ('وارد داخلي', 'purple', '📥'),
        'incoming_external': ('وارد خارجي', 'purple', '📬'),
    }
    kind_label, kind_color, kind_emoji = _KIND_META.get(book.kind, (book.kind, 'secondary', '📄'))

    return render(
        request,
        "core/book_form.html",
        {
            "form": form,
            "attach_form": None,
            "is_edit": True,
            "entity_suggestions_json": entity_suggestions_json,
            "existing_issuing_json": existing_issuing_json,
            "existing_receiving_json": existing_receiving_json,
            "document_type_defaults_json": document_type_defaults_json,
            "document_type_suggestions": document_type_suggestions,
            "kind_label": kind_label,
            "kind_color": kind_color,
            "kind_emoji": kind_emoji,
        },
    )


@login_required
def book_change_status(request, pk):
    """تغيير حالة الكتاب."""
    book = get_object_or_404(Book, pk=pk, is_deleted=False)

    has_permission = (
        request.user.is_superuser or
        request.user.is_staff or
        book.created_by == request.user
    )

    if not has_permission:
        logger.warning(
            f"Unauthorized status change attempt: user_id={request.user.id} "
            f"username={request.user.username} book_id={pk}"
        )
        messages.error(request, "ليس لديك صلاحية تغيير حالة هذا الكتاب.")
        return redirect("book_detail", pk=pk)

    if request.method == "POST":
        status = request.POST.get("final_status")
        if status in dict(Book._meta.get_field("final_status").choices):
            old_status = book.final_status
            book.final_status = status
            book.save(update_fields=["final_status", "updated_at"])

            BookHistory.objects.create(
                book=book,
                action="status",
                by=request.user,
                notes=f"تغيير الحالة من {old_status} إلى {status}"
            )

            logger.info(
                f"Status changed: book_id={pk} user={request.user.username} "
                f"from={old_status} to={status}"
            )
            messages.success(request, "تم تحديث الحالة بنجاح.")
        else:
            messages.error(request, "الحالة المدخلة غير صحيحة.")

    return redirect("book_detail", pk=pk)


__all__ = ['book_detail', 'book_edit', 'book_change_status']
