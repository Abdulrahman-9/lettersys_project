"""
core.extraction.ocr
====================
OCR engine layer.

Classes:
  OCRService, ArabicOCROptimizer  — from .service  (wraps EasyOCR)
  ImageProcessor, BatchImageProcessor — from .image  (image preprocessing)
  BaseOCRProvider, EasyOCROfflineProvider, AzureOCRProvider — from .providers
  build_online_provider_from_settings — from .providers
"""

from .service import OCRService, ArabicOCROptimizer
from .image import ImageProcessor, BatchImageProcessor
from .providers import (
    BaseOCRProvider,
    EasyOCROfflineProvider,
    AzureOCRProvider,
    build_online_provider_from_settings,
)

__all__ = [
    'OCRService',
    'ArabicOCROptimizer',
    'ImageProcessor',
    'BatchImageProcessor',
    'BaseOCRProvider',
    'EasyOCROfflineProvider',
    'AzureOCRProvider',
    'build_online_provider_from_settings',
]
