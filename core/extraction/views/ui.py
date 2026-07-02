# -*- coding: utf-8 -*-
"""
core.extraction.views.ui
=========================
Django template views for the extraction UI workflow.

Routes (all under /extract/ in core/urls.py):
  /extract/quick-start/         → extraction_quick_start
  /extract/wizard/              → extraction_wizard
  /extract/smart-desktop/       → extraction_smart_desktop
  /extract/results/<id>/        → extraction_results
"""

import json
from pathlib import Path

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from core.extraction.kinds import (
    BOOK_KIND_CHOICES,
    DEFAULT_BOOK_KIND,
    get_kind_direction,
    get_kind_label,
    get_kind_scope,
    normalize_book_kind,
)
from core.document_types import DEFAULT_DOCUMENT_TYPE_BY_KIND, DOCUMENT_TYPE_OPTIONS_BY_KIND
from core.models import Book, BookSequence, DataExtractionResult


def _confidence_percent(value):
    try:
        numeric = float(value or 0)
    except (TypeError, ValueError):
        numeric = 0.0
    if numeric <= 1:
        numeric *= 100
    return max(0, min(100, round(numeric)))


def _confidence_state(value):
    percent = _confidence_percent(value)
    if percent >= 85:
        return "high"
    if percent >= 70:
        return "medium"
    return "low"


@login_required
def extraction_quick_start(request):
    """تحويل من المسار القديم للواجهة الذكية الجديدة."""
    from django.shortcuts import redirect
    return redirect(reverse('extraction-smart-desktop'))


@login_required
def extraction_wizard(request):
    """Redirect legacy wizard entry to the active smart desktop flow."""
    target = reverse('extraction-smart-desktop')
    kind = request.GET.get('kind')
    if kind:
        target = f"{target}?kind={kind}"
    return redirect(target)


@login_required
def extraction_smart_desktop(request):
    """نظام الاستخراج الذكي المحسّن للـ Desktop — يدعم وضع التعديل عبر edit_pk"""
    from django.core.exceptions import PermissionDenied
    from core.models import Book

    edit_pk = request.GET.get('edit_pk', '').strip()
    edit_book_json = 'null'

    if edit_pk:
        try:
            book = Book.objects.prefetch_related('issuing_entities', 'receiving_entities').get(
                pk=edit_pk, is_deleted=False
            )
        except (Book.DoesNotExist, ValueError):
            book = None

        if book is not None:
            has_permission = (
                request.user.is_superuser or
                request.user.is_staff or
                book.created_by == request.user
            )
            if not has_permission:
                raise PermissionDenied

            # قاعدة موحّدة لاختيار الأساسي (تطابق لوحة الإدارة وشارة «أساسي»)
            from core.attachment_service import pick_primary_attachment
            _att = pick_primary_attachment(book.attachments.filter(is_deleted=False))
            _att_info = ({'id': _att.id, 'name': (_att.file.name or '').rsplit('/', 1)[-1]}
                         if _att and _att.file else None)
            edit_book_json = json.dumps({
                'pk': book.pk,
                'attachment': _att_info,
                'kind': book.kind,
                'our_number': book.our_number or '',
                'sender_number': book.sender_number or '',
                'title': book.title or '',
                'date': str(book.date) if book.date else '',
                'sender_date': str(book.sender_date) if book.sender_date else '',
                'due_date': str(book.due_date) if book.due_date else '',
                'needs_followup': bool(book.due_date) and not book.is_archived,
                'secret_level': book.secret_level or 'normal',
                'margin': book.margin or '',
                'document_type': book.document_type or '',
                'issuing_entities': [{'id': e.id, 'name': e.name, 'code': e.code or ''} for e in book.issuing_entities.all()],
                'receiving_entities': [{'id': e.id, 'name': e.name, 'code': e.code or ''} for e in book.receiving_entities.all()],
            }, ensure_ascii=False)

    kind_raw = normalize_book_kind(request.GET.get('kind'), DEFAULT_BOOK_KIND)
    if edit_pk and edit_book_json != 'null':
        # في وضع التعديل نستخدم نوع الكتاب القائم
        import json as _json
        _d = _json.loads(edit_book_json)
        kind = normalize_book_kind(_d.get('kind'), kind_raw)
    else:
        kind = kind_raw

    kind_label = get_kind_label(kind)
    kind_direction = get_kind_direction(kind)
    kind_scope = get_kind_scope(kind)

    all_kinds = [k for k, _ in BOOK_KIND_CHOICES]
    seq_map = {}
    for k in all_kinds:
        data = BookSequence.get_next(k)
        seq_map[k] = data.get('formatted') or str(data.get('number', ''))

    # وجهة العودة (زر الإلغاء + بعد حفظ التعديل) — يُتحقَّق منها لتفادي open-redirect
    from django.utils.http import url_has_allowed_host_and_scheme
    _next = (request.GET.get('next') or '').strip()
    back_url = _next if url_has_allowed_host_and_scheme(_next, allowed_hosts={request.get_host()}) else ''

    # آخر الكتب المسجّلة (ودجة إغلاق الحلقة) — وضع الإدخال فقط، بترتيب حداثة التسجيل
    # (created_at لا date)، وبنفس بوابة وصول القائمة (المشرف/الطاقم يرى الكل، وغيرهما كتبه فقط).
    recent_books = []
    if edit_book_json == 'null':
        _rb = Book.objects.filter(is_deleted=False)
        if not (request.user.is_superuser or request.user.is_staff):
            _rb = _rb.filter(created_by=request.user)
        recent_books = list(
            _rb.order_by('-created_at', '-id').only('id', 'our_number', 'title', 'kind', 'created_at')[:4]
        )
        # ملاحظة: القالب يعرض rb.kind_label (خاصية Book جاهزة) — لا حاجة لتعيينها.

    return render(
        request,
        'core/extraction_smart_desktop.html',
        {
            'initial_kind': kind,
            'initial_kind_label': kind_label,
            'initial_kind_direction': kind_direction,
            'initial_kind_scope': kind_scope,
            'document_type_catalog_json': json.dumps(DOCUMENT_TYPE_OPTIONS_BY_KIND, ensure_ascii=False),
            'document_type_defaults_json': json.dumps(DEFAULT_DOCUMENT_TYPE_BY_KIND, ensure_ascii=False),
            'seq_map': seq_map,
            'edit_book_json': edit_book_json,
            'back_url': back_url,
            'recent_books': recent_books,
        },
    )


@login_required
def extraction_results(request, extraction_id):
    """Desktop review page for a stored extraction result."""
    extraction = get_object_or_404(
        DataExtractionResult.objects.select_related(
            'attachment', 'ocr_result', 'book', 'reviewed_by', 'approved_by'
        ),
        pk=extraction_id,
    )

    normalized_kind = normalize_book_kind(extraction.book_kind, DEFAULT_BOOK_KIND)
    attachment_name = f"مرفق #{extraction.attachment_id}"
    if extraction.attachment and extraction.attachment.file:
        attachment_name = Path(extraction.attachment.file.name).name

    context = {
        'extraction': extraction,
        'kind_choices': BOOK_KIND_CHOICES,
        'normalized_book_kind': normalized_kind,
        'normalized_book_kind_label': get_kind_label(normalized_kind),
        'kind_direction': get_kind_direction(normalized_kind),
        'kind_scope': get_kind_scope(normalized_kind),
        'is_legacy_kind_guess': (extraction.book_kind or '').lower() in ('incoming', 'outgoing'),
        'attachment_display_name': attachment_name,
        'review_status_label': dict(DataExtractionResult.STATUS_CHOICES).get(extraction.status, extraction.status),
        'overall_confidence_percent': _confidence_percent(extraction.overall_confidence),
        'overall_confidence_state': _confidence_state(extraction.overall_confidence),
        'ocr_confidence_percent': _confidence_percent(getattr(extraction.ocr_result, 'confidence_score', 0)),
        'ocr_confidence_state': _confidence_state(getattr(extraction.ocr_result, 'confidence_score', 0)),
        'book_number_confidence_percent': _confidence_percent(extraction.book_number_confidence),
        'book_number_confidence_state': _confidence_state(extraction.book_number_confidence),
        'book_date_confidence_percent': _confidence_percent(extraction.book_date_confidence),
        'book_date_confidence_state': _confidence_state(extraction.book_date_confidence),
        'title_confidence_percent': _confidence_percent(extraction.title_confidence),
        'title_confidence_state': _confidence_state(extraction.title_confidence),
        'secret_level_confidence_percent': _confidence_percent(extraction.secret_level_confidence),
        'secret_level_confidence_state': _confidence_state(extraction.secret_level_confidence),
        'book_kind_confidence_percent': _confidence_percent(extraction.book_kind_confidence),
        'book_kind_confidence_state': _confidence_state(extraction.book_kind_confidence),
        'margin_confidence_percent': _confidence_percent(extraction.margin_confidence),
        'margin_confidence_state': _confidence_state(extraction.margin_confidence),
        'entity_candidate_total': len(extraction.issuing_entity_candidates or []) + len(extraction.receiving_entity_candidates or []),
        'feedback_count': extraction.feedbacks.count(),
    }
    return render(request, 'core/extraction_results.html', context)
