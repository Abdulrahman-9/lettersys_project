# -*- coding: utf-8 -*-
"""
Book detail/edit/status views.
"""

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from ..forms import AttachmentForm
from ..models import Attachment, Book, BookHistory

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

    back_url = f"{reverse('extraction-smart-desktop')}?kind={book.kind}"
    back_label = "إدخال كتاب جديد"
    if request.GET.get("from") == "list":
        back_url = reverse("book_unified")
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

    # تحويل GET لصفحة الاستخراج الذكي في وضع التعديل
    if request.method == "GET":
        target = f"{reverse('extraction-smart-desktop')}?edit_pk={book.pk}&kind={book.kind}"
        return redirect(target)


@login_required
def book_change_status(request, pk):
    """
    تبديل حالة المتابعة (أرشفة / إعادة فتح).
    POST action ∈ {'archived', 'reopen'}.
    """
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
        action = (request.POST.get("action") or request.POST.get("final_status") or "").strip()
        if action not in ("archived", "reopen"):
            messages.error(request, "إجراء غير صالح.")
            return redirect("book_detail", pk=pk)

        if action == "reopen" and not book.due_date:
            messages.error(request, "لا يمكن إعادة فتح المتابعة بدون تاريخ متابعة — حدّد تاريخاً من صفحة التعديل.")
            return redirect("book_detail", pk=pk)

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
            logger.info(
                f"Followup state changed: book_id={pk} user={request.user.username} action={action}"
            )
            messages.success(request, "تم تحديث الحالة بنجاح.")

    return redirect("book_detail", pk=pk)


__all__ = ['book_detail', 'book_edit', 'book_change_status']
