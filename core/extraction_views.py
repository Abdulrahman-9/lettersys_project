# -*- coding: utf-8 -*-
"""extraction_views.py — SHIM — الكود انتقل إلى core.extraction.api.endpoints"""
from core.extraction.api.endpoints import *  # noqa: F401, F403
from core.extraction.api.endpoints import (
    start_extraction,
    get_extraction_result,
    submit_feedback,
    review_extraction,
    extraction_statistics,
    smart_extract_direct,
    suggestions_api,
)
