"""
core.extraction
================
Consolidated AI extraction package for LetterSys.

Replaces the legacy flat-file layout:
  core/ai_processing_service.py  → core.extraction.pipeline
  core/ai_ocr_service.py         → core.extraction.ocr.service
  core/ai_image_processor.py     → core.extraction.ocr.image
  core/ai_providers.py           → core.extraction.ocr.providers
  core/ai_entity_matcher.py      → core.extraction.matchers.entity
  core/ai_pattern_matcher.py     → core.extraction.matchers.pattern
  core/extraction_kinds.py       → core.extraction.kinds
  core/extraction_helpers.py     → core.extraction.helpers
  core/extraction_views.py       → core.extraction.api.endpoints
  core/extraction_ui_views.py    → core.extraction.views.ui

Subpackages:
  ocr/       — OCR engines (EasyOCR, Azure, image preprocessor)
  matchers/  — Pattern and entity matchers
  api/       — REST API endpoints
  views/     — Web UI views
"""

# ── Convenience re-exports from this package ────────────────────
# NOTE: pipeline is NOT imported here to avoid a circular-import with core.models.
# Import directly:  from core.extraction.pipeline import AIExtractionService
from .kinds import (
    DEFAULT_BOOK_KIND,
    BOOK_KIND_CHOICES,
    BOOK_KIND_LABELS,
    normalize_book_kind,
    get_kind_label,
    is_incoming_kind,
    is_outgoing_kind,
)

__all__ = [
    'DEFAULT_BOOK_KIND',
    'BOOK_KIND_CHOICES',
    'BOOK_KIND_LABELS',
    'normalize_book_kind',
    'get_kind_label',
    'is_incoming_kind',
    'is_outgoing_kind',
]
