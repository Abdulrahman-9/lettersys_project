# -*- coding: utf-8 -*-
"""ai_image_processor.py — SHIM — الكود انتقل إلى core.extraction.ocr.image"""
from core.extraction.ocr.image import *  # noqa: F401, F403
from core.extraction.ocr.image import (
    ImageProcessor,
    BatchImageProcessor,
    process_image_for_ocr,
    compare_images,
)
