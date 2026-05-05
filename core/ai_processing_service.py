# -*- coding: utf-8 -*-
"""ai_processing_service.py — SHIM — الكود انتقل إلى core.extraction.pipeline"""
from core.extraction.pipeline import *  # noqa: F401, F403
from core.extraction.pipeline import (
    AIExtractionService,
    AIExtractionResult,
    process_extraction_task,
)
