# -*- coding: utf-8 -*-
"""
Book detail/edit/status views.
"""

import logging
from urllib.parse import urlencode, urlparse

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Prefetch
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from ..forms import AttachmentForm
from ..models import Attachment, Book, BookHistory
from core.scoping import (
    ACCESS_STUB, can_open_content, can_view_book, is_privileged, secret_access,
)

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

    # كانت هذه نسخةً يدويّةً ثامنةً وعشرين من قاعدة الرؤية، نجت من التوحيد لأنّها
    # موزَّعةٌ على أربعة أسطر — فبقيت الصفحةُ الرئيسة على القاعدة القديمة
    # (staff يرى الكلّ، والقسمُ لا أثر له). صارت من المصدر الوحيد.
    if not can_view_book(book, request.user):
        logger.warning(
            f"Unauthorized book access attempt: user_id={request.user.id} "
            f"username={request.user.username} book_id={pk}"
        )
        raise PermissionDenied("ليس لديك صلاحية الوصول لهذا الكتاب")

    # الصفُّ مرئيٌّ والمحتوى قد لا يكون: قالبٌ مقيَّدٌ مستقلّ بدل رشّ الشروط في
    # قالبٍ من خمسمئة سطر — قائمةٌ بيضاء لا استثناءاتٌ من سوداء.
    if secret_access(request.user, book) == ACCESS_STUB:
        return render(request, 'core/book_detail_secret.html', {'book': book})

    if request.method == 'POST' and 'file' in request.FILES:
        _ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'
        form = AttachmentForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                from ..attachment_service import create_attachment
                with transaction.atomic():
                    # المرور عبر نقطة الإنشاء الموحّدة (تحويل الصور إلى PDF) للحفاظ على
                    # ثابتة «المرفق دائماً PDF» التي يعتمدها العرض والدمج وحذف الصفحات.
                    att = create_attachment(book, form.cleaned_data['file'], user=request.user)

                    BookHistory.objects.create(
                        book=book,
                        action="attach",
                        by=request.user,
                        notes=f"أضاف مرفق: {att.file.name}",
                        attachment=att
                    )

                    logger.info(f"Attachment uploaded: book_id={pk} file={att.file.name} user={request.user.username}")
                if _ajax:
                    return JsonResponse({'success': True, 'message': f"تم إرفاق «{att.filename}» بنجاح.", 'attachment_id': att.id})
                messages.success(request, f"تم رفع المرفق '{att.file.name}' بنجاح.")
                return redirect("book_detail", pk=pk)
            except Exception:
                logger.exception(f"Failed to upload attachment for book {pk}")
                if _ajax:
                    return JsonResponse({'success': False, 'message': 'حدث خطأ أثناء رفع المرفق.'}, status=500)
                messages.error(request, "حدث خطأ أثناء رفع المرفق. يرجى المحاولة مرة أخرى.")
        else:
            if _ajax:
                _errs = form.errors.get('file', []) or ['ملف غير صالح.']
                return JsonResponse({'success': False, 'message': '؛ '.join(_errs)}, status=400)
            for error in form.errors.get('file', []):
                messages.error(request, error)

    # وجهة العودة = من حيث دخل المستخدم فعلاً:
    #   next صريح ← أو المُحيل Referer الداخلي (يحفظ حالة القائمة: التبويب/الفلتر/الصفحة)
    #   ← أو القائمة الموحّدة كاحتياطي آمن (الدخول المباشر/التحديث).
    # (الفرع القديم from=list كان ميتاً لأن لا مسار يمرّره؛ استُبدل بمنطق عام يغطّي كل
    #  مصادر الدخول: القائمة، الجهة، البريد، الأضابير، التقارير…)
    _candidate = (request.GET.get("next") or "").strip() or request.META.get("HTTP_REFERER", "")
    back_url, back_label = "", ""
    if _candidate and url_has_allowed_host_and_scheme(
        _candidate, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        _path = urlparse(_candidate).path
        # تجاهُل العودة لصفحة هذا الكتاب نفسها (تفاصيل/تعديل) تفادياً للحلقة بعد POST يعيد التوجيه
        if _path != request.path and not _path.rstrip("/").endswith(f"/{book.pk}"):
            back_url, back_label = _candidate, "عودة"
    if not back_url:
        back_url = reverse("book_unified")
        back_label = "العودة للقائمة"

    # الـ Prefetch أعلاه يُرشّح is_deleted=False مسبقاً؛ نستخدم .all() لإعادة استخدام كاش الـ prefetch
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

    # تحويل GET لصفحة الاستخراج الذكي في وضع التعديل (مع تمرير وجهة العودة إن وُجدت)
    if request.method == "GET":
        params = {'edit_pk': book.pk, 'kind': book.kind}
        nxt = (request.GET.get('next') or '').strip()
        if nxt:
            params['next'] = nxt
        return redirect(f"{reverse('extraction-smart-desktop')}?{urlencode(params)}")


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


@login_required
def book_report(request, pk):
    """
    تقرير دورة حياة الكتاب — صفحة طباعة مستقلة (A4، سطح المكتب).

    يجمع في وثيقة واحدة رسمية: هوية الكتاب + الحالة + المُدد الزمنية (عمر/استحقاق/آخر نشاط)
    + الملاحظات + التعليقات الداخلية + المراسلات والأجوبة الملحقة (BookEmailLog) + سجل دورة
    الحياة الكامل (BookHistory) — لتتبّع المؤسسة للمستند بالتفصيل.
    """
    from datetime import timedelta
    from django.utils import timezone
    from ..models import BookEmailLog

    book = get_object_or_404(
        Book.objects.select_related("created_by").prefetch_related(
            "issuing_entities",
            "receiving_entities",
            Prefetch(
                "attachments",
                queryset=Attachment.objects.filter(is_deleted=False)
                    .prefetch_related("versions").order_by("-uploaded_at"),
            ),
            Prefetch(
                "history",
                queryset=BookHistory.objects.select_related("by").order_by("created_at"),
            ),
        ),
        pk=pk,
        is_deleted=False,
    )

    if not can_open_content(book, request.user):
        logger.warning(
            f"Unauthorized book report attempt: user_id={request.user.id} "
            f"username={request.user.username} book_id={pk}"
        )
        raise PermissionDenied("ليس لديك صلاحية عرض تقرير هذا الكتاب")

    comments = book.comments.select_related("created_by").order_by("created_at")
    email_logs = BookEmailLog.objects.filter(book=book).order_by("sent_at")
    history = list(book.history.all())  # مُرتَّب تصاعدياً (أقدم → أحدث) عبر الـ prefetch

    # ── المُدد الزمنية لدورة الحياة ──
    today = timezone.localdate()
    age_in_system = (today - book.created_at.date()).days if book.created_at else None
    # قيمة سالبة (كتاب بتاريخ مستقبلي) تُربك العرض → نثبّتها عند 0
    since_book_date = max(0, (today - book.date).days) if book.date else None
    # موجب = أيام متبقية حتى الاستحقاق، سالب = أيام تأخّر
    due_delta = (book.due_date - today).days if book.due_date else None

    # ── تحليلات دورة المتابعة (من السجل) — تُثري التقرير: كم مرة أُعيد الفتح/أُرشف،
    #    كم مرة تأخّر، كم مرة حُدِّث المستند، وإجمالي مدة المتابعة النشطة (تقديري). ──
    reopen_count = archive_count = update_count = overdue_episodes = 0
    _events = []
    if book.created_at:
        _events.append((book.created_at, "open"))  # الدورة الأولى تبدأ بالإنشاء
    for h in history:
        act = h.action or ""
        notes = h.notes or ""
        if act == "status":
            if "فتح" in notes:
                reopen_count += 1
                _events.append((h.created_at, "open"))
            elif "أرشف" in notes or "إنهاء" in notes:
                archive_count += 1
                _events.append((h.created_at, "close"))
        elif act in ("attach", "replace-attachment", "merge-pages"):
            update_count += 1
        elif act == "overdue":
            overdue_episodes += 1

    _events.sort(key=lambda e: e[0])
    total_active = timedelta()
    _open_at = None
    for ts, kind in _events:
        if kind == "open" and _open_at is None:
            _open_at = ts
        elif kind == "close" and _open_at is not None:
            total_active += (ts - _open_at)
            _open_at = None
    if _open_at is not None:  # ما زالت المتابعة نشطة
        total_active += (timezone.now() - _open_at)

    followup = {
        "cycles": reopen_count + 1,
        "reopens": reopen_count,
        "archives": archive_count,
        "updates": update_count,
        "overdue_episodes": overdue_episodes,
        "active_days": total_active.days,
        "currently_overdue": book.followup_state == "overdue",
        "current_overdue_days": book.delay_days if book.followup_state == "overdue" else 0,
    }

    return render(
        request,
        "core/book_report.html",
        {
            "book": book,
            "attachments": list(book.attachments.all()),
            "comments": comments,
            "email_logs": email_logs,
            "history": history,
            "age_in_system": age_in_system,
            "since_book_date": since_book_date,
            "due_delta": due_delta,
            "followup": followup,
            "last_event": history[-1] if history else None,
            "generated_at": timezone.now(),
            "generated_by": request.user,
        },
    )


__all__ = ['book_detail', 'book_edit', 'book_change_status', 'book_report']
