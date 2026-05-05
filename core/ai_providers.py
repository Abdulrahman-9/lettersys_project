# -*- coding: utf-8 -*-
"""ai_providers.py — SHIM — الكود انتقل إلى core.extraction.ocr.providers"""
from core.extraction.ocr.providers import *  # noqa: F401, F403
from core.extraction.ocr.providers import (
    BaseOCRProvider,
    EasyOCROfflineProvider,
    AzureOCRProvider,
    build_online_provider_from_settings,
)
