# -*- coding: utf-8 -*-
"""extraction_kinds.py — SHIM — الكود انتقل إلى core.extraction.kinds"""
from core.extraction.kinds import *  # noqa: F401, F403
from core.extraction.kinds import (
    DEFAULT_BOOK_KIND,
    BOOK_KIND_CHOICES,
    BOOK_KIND_LABELS,
    LEGACY_KIND_MAP,
    DIRECTION_LABELS,
    EXTRACTION_KIND_CHOICES,
    normalize_book_kind,
    is_incoming_kind,
    is_outgoing_kind,
    get_kind_direction,
    get_kind_scope,
    get_kind_label,
)
