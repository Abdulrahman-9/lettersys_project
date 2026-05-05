# -*- coding: utf-8 -*-
"""ai_ocr_service.py — SHIM — الكود انتقل إلى core.extraction.ocr.service"""
from core.extraction.ocr.service import *  # noqa: F401, F403
from core.extraction.ocr.service import (
    OCRService,
    ArabicOCROptimizer,
    extract_text_simple,
    extract_text_with_details,
)
