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
from core.models import BookSequence, DataExtractionResult


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
    """صفحة البداية السريعة للاستخراج"""
    return render(request, 'core/extraction_quick_start.html')


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
    """نظام الاستخراج الذكي المحسّن للـ Desktop"""
    kind = normalize_book_kind(request.GET.get('kind'), DEFAULT_BOOK_KIND)
    kind_label = get_kind_label(kind)
    kind_direction = get_kind_direction(kind)
    kind_scope = get_kind_scope(kind)

    # جلب أرقام العدادات لجميع الأنواع مرة واحدة
    all_kinds = [k for k, _ in BOOK_KIND_CHOICES]
    seq_map = {}
    for k in all_kinds:
        data = BookSequence.get_next(k)
        seq_map[k] = data.get('formatted') or str(data.get('number', ''))

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
