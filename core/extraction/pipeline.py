# -*- coding: utf-8 -*-
"""
core.extraction.pipeline
=========================
AI Processing Service — Main Orchestrator

Combines all AI services (image processing, OCR, pattern matching, entity matching)
into a unified data extraction pipeline.

This module coordinates the complete AI extraction workflow:
1. Image Enhancement
2. Text Extraction (OCR)
3. Structured Data Extraction (Patterns)
4. Entity Recognition & Matching
5. Result Aggregation & Confidence Calculation

Usage:
    from core.extraction.pipeline import AIExtractionService

    service = AIExtractionService()
    result = service.process_image('path/to/image.jpg')
    print(result.book_number, result.overall_confidence)
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any
from pathlib import Path
import hashlib
import time

from django.db import transaction
from django.utils import timezone

from core.extraction.ocr.image import ImageProcessor, BatchImageProcessor
from core.extraction.ocr.service import OCRService, ArabicOCROptimizer
from core.extraction.ocr.providers import EasyOCROfflineProvider, build_online_provider_from_settings
from core.models import AIIntegrationSettings
from core.extraction.matchers.pattern import PatternMatcher, DateParser
from core.extraction.matchers.entity import EntityMatcher, EnhancedEntityMatcher
from core.models import (
    OCRResult, DataExtractionResult, ExtractionFeedback,
    ExtractionStatistics, ExtractionCache, Attachment, Book, Entity
)

logger = logging.getLogger(__name__)


class AIExtractionResult:
    """
    Unified result object containing all extracted data and confidence scores.
    Combines outputs from all AI services.
    """

    def __init__(self):
        self.image_path: str = ""
        self.image_hash: str = ""
        self.cached: bool = False

        # OCR results
        self.raw_text: str = ""
        self.cleaned_text: str = ""
        self.ocr_confidence: float = 0.0
        self.ocr_processing_time: float = 0.0
        self.detected_language: str = "ar"
        self.ocr_engine: str = "easyocr"

        # Extracted structured data
        self.book_number: str = ""
        self.book_number_confidence: float = 0.0

        self.book_date: Optional[str] = None
        self.book_date_confidence: float = 0.0

        self.title: str = ""
        self.title_confidence: float = 0.0

        self.margin_text: str = ""
        self.margin_confidence: float = 0.0

        self.secret_level: str = ""
        self.secret_level_confidence: float = 0.0

        self.book_kind: str = ""
        self.book_kind_confidence: float = 0.0

        # Entity matching results
        self.issuing_entity_matches: List[Dict] = []
        self.issuing_entity_id: Optional[int] = None
        self.issuing_entity_name: str = ""
        self.issuing_entity_confidence: float = 0.0

        self.receiving_entity_matches: List[Dict] = []
        self.receiving_entity_id: Optional[int] = None
        self.receiving_entity_name: str = ""
        self.receiving_entity_confidence: float = 0.0

        # Aggregated confidence
        self.overall_confidence: float = 0.0
        self.field_confidences: Dict[str, float] = {}

        # Processing metadata
        self.status: str = "pending"  # pending, completed, failed, manual_review
        self.error_message: Optional[str] = None
        self.processing_time: float = 0.0
        self.timestamp: datetime = timezone.now()

        # Database references
        self.ocr_result_id: Optional[int] = None
        self.data_extraction_result_id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary for JSON serialization"""
        return {
            'image_path': self.image_path,
            'cached': self.cached,
            'raw_text': self.raw_text,
            'cleaned_text': self.cleaned_text,
            'ocr_confidence': self.ocr_confidence,
            'detected_language': self.detected_language,
            'book_number': self.book_number,
            'book_number_confidence': self.book_number_confidence,
            'book_date': self.book_date,
            'book_date_confidence': self.book_date_confidence,
            'title': self.title,
            'title_confidence': self.title_confidence,
            'margin_text': self.margin_text,
            'secret_level': self.secret_level,
            'secret_level_confidence': self.secret_level_confidence,
            'book_kind': self.book_kind,
            'book_kind_confidence': self.book_kind_confidence,
            'issuing_entity_id': self.issuing_entity_id,
            'issuing_entity_name': self.issuing_entity_name,
            'issuing_entity_confidence': self.issuing_entity_confidence,
            'receiving_entity_id': self.receiving_entity_id,
            'receiving_entity_name': self.receiving_entity_name,
            'receiving_entity_confidence': self.receiving_entity_confidence,
            'overall_confidence': self.overall_confidence,
            'field_confidences': self.field_confidences,
            'status': self.status,
            'processing_time': self.processing_time,
            'timestamp': self.timestamp.isoformat(),
        }


class AIExtractionService:
    """
    Main service orchestrating all AI extraction components.

    This service manages:
    - Image enhancement
    - OCR processing
    - Pattern-based data extraction
    - Entity recognition and database matching
    - Confidence scoring
    - Result caching
    - Database persistence
    """

    def __init__(self, use_cache: bool = True):
        """
        Initialize AI Extraction Service

        Args:
            use_cache: Whether to use extraction caching for similar images
        """
        self.use_cache = use_cache

        # Initialize all sub-services (image processor يُنشأ لكل صورة لاحقاً)
        self.image_processor = None
        self.ocr_service = None
        self.arabic_ocr = None
        self.pattern_matcher = PatternMatcher()
        self.entity_matcher = EntityMatcher()
        self.enhanced_entity_matcher = EnhancedEntityMatcher()

        # OCR providers are initialized lazily after the document is confirmed loadable.
        self._offline_provider = None
        self._settings = None
        self._online_provider = None

        logger.info("AI Extraction Service initialized successfully")

    def _ensure_ocr_stack(self) -> None:
        if self.ocr_service is None:
            self.ocr_service = OCRService()
            self.arabic_ocr = ArabicOCROptimizer(self.ocr_service)

        if self._settings is None:
            self._settings = AIIntegrationSettings.get_active_settings()

        if self._offline_provider is None:
            self._offline_provider = EasyOCROfflineProvider()

        if self._online_provider is None and self._settings.get('AI_PROVIDER') != 'offline':
            self._online_provider = build_online_provider_from_settings(self._settings)

    def compute_image_hash(self, image_path: str) -> str:
        """
        Compute MD5 hash of image file

        Args:
            image_path: Path to image file

        Returns:
            MD5 hash string
        """
        md5 = hashlib.md5()
        with open(image_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                md5.update(chunk)
        return md5.hexdigest()

    def check_cache(self, image_hash: str) -> Optional[AIExtractionResult]:
        """
        Check if extraction result exists in cache

        Args:
            image_hash: MD5 hash of image

        Returns:
            Cached result if found, None otherwise
        """
        if not self.use_cache:
            return None

        try:
            cache = ExtractionCache.objects.get(image_hash=image_hash)
            cache.hit_count += 1
            cache.last_used = timezone.now()
            cache.save()

            logger.info(f"Cache hit for image hash {image_hash}")

            # Reconstruct result from cached data
            result = AIExtractionResult()
            result.cached = True
            cached_data = cache.cached_extraction

            # Populate from cache
            result.raw_text = cached_data.get('raw_text', '')
            result.cleaned_text = cached_data.get('cleaned_text', '')
            result.ocr_confidence = cached_data.get('ocr_confidence', 0.0)
            result.book_number = cached_data.get('book_number', '')
            result.book_number_confidence = cached_data.get('book_number_confidence', 0.0)
            result.book_date = cached_data.get('book_date')
            result.book_date_confidence = cached_data.get('book_date_confidence', 0.0)
            result.title = cached_data.get('title', '')
            result.title_confidence = cached_data.get('title_confidence', 0.0)
            result.secret_level = cached_data.get('secret_level', '')
            result.secret_level_confidence = cached_data.get('secret_level_confidence', 0.0)
            result.book_kind = cached_data.get('book_kind', '')
            result.book_kind_confidence = cached_data.get('book_kind_confidence', 0.0)
            result.overall_confidence = cached_data.get('overall_confidence', 0.0)
            result.status = 'completed'

            return result

        except ExtractionCache.DoesNotExist:
            return None
        except Exception as e:
            logger.error(f"Cache retrieval error: {str(e)}")
            return None

    def save_to_cache(self, image_hash: str, result: AIExtractionResult) -> bool:
        """
        Save extraction result to cache

        Args:
            image_hash: MD5 hash of image
            result: Extraction result to cache

        Returns:
            True if saved successfully
        """
        if not self.use_cache or result.status != 'completed':
            return False

        try:
            cache_data = {
                'raw_text': result.raw_text,
                'cleaned_text': result.cleaned_text,
                'ocr_confidence': result.ocr_confidence,
                'book_number': result.book_number,
                'book_number_confidence': result.book_number_confidence,
                'book_date': result.book_date,
                'book_date_confidence': result.book_date_confidence,
                'title': result.title,
                'title_confidence': result.title_confidence,
                'secret_level': result.secret_level,
                'secret_level_confidence': result.secret_level_confidence,
                'book_kind': result.book_kind,
                'book_kind_confidence': result.book_kind_confidence,
                'overall_confidence': result.overall_confidence,
            }

            ExtractionCache.objects.update_or_create(
                image_hash=image_hash,
                defaults={
                    'cached_extraction': cache_data,
                    'hit_count': 0,
                    'last_used': timezone.now()
                }
            )
            logger.info(f"Cached extraction for image hash {image_hash}")
            return True
        except Exception as e:
            logger.error(f"Cache save error: {str(e)}")
            return False

    def process_image(self, image_path: str, skip_ocr: bool = False) -> AIExtractionResult:
        """
        Process single image through complete extraction pipeline

        Args:
            image_path: Path to image file
            skip_ocr: Whether to skip OCR (for testing)

        Returns:
            AIExtractionResult with all extracted data
        """
        start_time = time.time()
        result = AIExtractionResult()
        result.image_path = image_path

        try:
            # Step 1: Compute image hash and check cache
            result.image_hash = self.compute_image_hash(image_path)

            cached_result = self.check_cache(result.image_hash)
            if cached_result:
                cached_result.processing_time = time.time() - start_time
                return cached_result

            # Step 2: Image Enhancement
            logger.info(f"Processing image: {image_path}")
            image_processor = ImageProcessor(image_path)
            image_processor.full_pipeline()
            enhanced_image = image_processor.get_image()
            enhanced_image_path = image_path.replace('.jpg', '_enhanced.jpg').replace('.png', '_enhanced.png')
            image_processor.save(enhanced_image_path)
            # تفريغ ذاكرة معالج الصور فوراً
            del image_processor, enhanced_image
            logger.info(f"Image enhanced and saved to {enhanced_image_path}")

            # Step 3: OCR Processing
            if not skip_ocr:
                self._ensure_ocr_stack()

                # First try offline provider
                offline_res = self._offline_provider.extract(enhanced_image_path)
                result.raw_text = offline_res.get('raw_text', '')
                result.cleaned_text = self.ocr_service.clean_text(result.raw_text)
                # Map avg_confidence to pipeline
                result.ocr_confidence = float(offline_res.get('avg_confidence', 0.0))
                result.detected_language = 'ar'
                ocr_engine_used = 'easyocr'
                logger.info(f"OCR (offline) confidence {result.ocr_confidence:.2f}")

                # Fallback to online if enabled and low confidence
                if self._settings.get('AI_FALLBACK_ON_LOW_CONFIDENCE', True) and self._online_provider:
                    threshold = float(self._settings.get('AI_LOW_CONFIDENCE_THRESHOLD', 0.4))
                    if result.ocr_confidence < threshold:
                        logger.info(f"OCR below threshold {threshold:.2f}; trying online provider...")
                        online_res = self._online_provider.extract(enhanced_image_path)
                        online_conf = float(online_res.get('avg_confidence', 0.0))
                        if online_conf > result.ocr_confidence and online_res.get('raw_text'):
                            result.raw_text = online_res.get('raw_text', '')
                            result.cleaned_text = self.ocr_service.clean_text(result.raw_text)
                            result.ocr_confidence = online_conf
                            ocr_engine_used = 'azure'
                            logger.info(f"Online OCR improved confidence to {online_conf:.2f}")
                # store engine in result for DB save
                result.ocr_engine = ocr_engine_used
            else:
                result.raw_text = ""
                result.cleaned_text = ""
                result.ocr_confidence = 0.0

            # Step 4: Pattern Matching (Structured Data Extraction)
            if result.cleaned_text:
                patterns = self.pattern_matcher.extract_all_data(result.cleaned_text)

                result.book_number, result.book_number_confidence = patterns.get('book_number', ('', 0.0))
                result.book_date, result.book_date_confidence = patterns.get('book_date', (None, 0.0))
                result.title, result.title_confidence = patterns.get('title', ('', 0.0))
                result.margin_text, result.margin_confidence = patterns.get('margin_text', ('', 0.0))
                result.secret_level, result.secret_level_confidence = patterns.get('secret_level', ('', 0.0))
                result.book_kind, result.book_kind_confidence = patterns.get('book_kind', ('', 0.0))

                logger.info(f"Pattern matching completed: book_number={result.book_number}")

            # Step 5: Entity Matching
            entities = self.pattern_matcher.extract_entities(result.cleaned_text)
            if entities:
                # Match issuing entity
                for entity_text in entities.get('issuing_entities', []):
                    matches = self.entity_matcher.match_issuing_entity(entity_text)
                    if matches:
                        best_match = matches[0]
                        result.issuing_entity_matches = matches[:3]  # Top 3 matches
                        result.issuing_entity_id = best_match.get('entity_id')
                        result.issuing_entity_name = best_match.get('entity_name', '')
                        result.issuing_entity_confidence = best_match.get('score', 0.0) / 100.0
                        break

                # Match receiving entity
                for entity_text in entities.get('receiving_entities', []):
                    matches = self.entity_matcher.match_receiving_entity(entity_text)
                    if matches:
                        best_match = matches[0]
                        result.receiving_entity_matches = matches[:3]  # Top 3 matches
                        result.receiving_entity_id = best_match.get('entity_id')
                        result.receiving_entity_name = best_match.get('entity_name', '')
                        result.receiving_entity_confidence = best_match.get('score', 0.0) / 100.0
                        break

                logger.info(f"Entity matching completed")

            # Step 6: Calculate Overall Confidence
            result.field_confidences = {
                'book_number': result.book_number_confidence,
                'book_date': result.book_date_confidence,
                'title': result.title_confidence,
                'secret_level': result.secret_level_confidence,
                'book_kind': result.book_kind_confidence,
                'issuing_entity': result.issuing_entity_confidence,
                'receiving_entity': result.receiving_entity_confidence,
                'ocr': result.ocr_confidence,
            }

            # Overall confidence: weighted average
            confidence_values = [v for v in result.field_confidences.values() if v > 0]
            if confidence_values:
                result.overall_confidence = sum(confidence_values) / len(confidence_values)
            else:
                result.overall_confidence = result.ocr_confidence

            # Step 7: Determine if manual review is needed
            if result.overall_confidence < 0.70:
                result.status = 'manual_review'
                logger.warning(f"Low confidence detected: {result.overall_confidence}")
            else:
                result.status = 'completed'

            # Step 8: Save to cache
            self.save_to_cache(result.image_hash, result)

            result.processing_time = time.time() - start_time
            logger.info(f"Image processing completed in {result.processing_time:.2f}s with confidence {result.overall_confidence:.2%}")

            return result

        except Exception as e:
            logger.error(f"Error processing image: {str(e)}", exc_info=True)
            result.status = 'failed'
            result.error_message = str(e)
            result.processing_time = time.time() - start_time
            return result
        finally:
            # تنظيف ملف الصورة المحسّنة من القرص
            try:
                if 'enhanced_image_path' in locals() and os.path.exists(enhanced_image_path):
                    os.remove(enhanced_image_path)
            except OSError:
                pass

    def process_batch(self, image_paths: List[str]) -> List[AIExtractionResult]:
        """
        Process multiple images

        Args:
            image_paths: List of paths to image files

        Returns:
            List of extraction results
        """
        results = []
        for image_path in image_paths:
            try:
                result = self.process_image(image_path)
                results.append(result)
            except Exception as e:
                logger.error(f"Batch processing error for {image_path}: {str(e)}")
                result = AIExtractionResult()
                result.image_path = image_path
                result.status = 'failed'
                result.error_message = str(e)
                results.append(result)

        return results

    @transaction.atomic
    def save_to_database(self, result: AIExtractionResult, attachment=None) -> Tuple[Optional[OCRResult], Optional[DataExtractionResult]]:
        """
        Save extraction result to database

        Args:
            result: Extraction result
            attachment: Attachment object (optional)

        Returns:
            Tuple of (OCRResult, DataExtractionResult) objects
        """
        try:
            # Save OCR result
            ocr_result = OCRResult.objects.create(
                attachment=attachment,
                status=result.status,
                raw_text=result.raw_text,
                cleaned_text=result.cleaned_text,
                confidence_score=result.ocr_confidence,
                processing_time=result.ocr_processing_time,
                language=result.detected_language,
                processed_by=getattr(result, 'ocr_engine', 'easyocr')
            )
            result.ocr_result_id = ocr_result.id
            logger.info(f"Saved OCR result: {ocr_result.id}")

            # Save data extraction result
            if not attachment:
                logger.warning("No attachment supplied for data extraction save; skipping DataExtractionResult creation")
                return ocr_result, None

            normalized_status = 'extracted' if result.status == 'completed' else result.status

            data_result = DataExtractionResult.objects.create(
                ocr_result=ocr_result,
                attachment=attachment,
                book_number=result.book_number or '',
                book_number_confidence=result.book_number_confidence or 0.0,
                book_date=result.book_date,
                book_date_confidence=result.book_date_confidence or 0.0,
                title=result.title or '',
                title_confidence=result.title_confidence or 0.0,
                margin_text=result.margin_text,
                margin_confidence=result.margin_confidence or 0.0,
                secret_level=result.secret_level or '',
                secret_level_confidence=result.secret_level_confidence or 0.0,
                book_kind=result.book_kind or '',
                book_kind_confidence=result.book_kind_confidence or 0.0,
                issuing_entity_id=result.issuing_entity_id,
                receiving_entity_id=result.receiving_entity_id,
                overall_confidence=result.overall_confidence or 0.0,
                status=normalized_status,
                additional_data={
                    'field_confidences': result.field_confidences,
                    'issuing_entity_matches': result.issuing_entity_matches,
                    'receiving_entity_matches': result.receiving_entity_matches,
                },
            )
            result.data_extraction_result_id = data_result.id
            logger.info(f"Saved data extraction result: {data_result.id}")

            return ocr_result, data_result

        except Exception as e:
            logger.error(f"Database save error: {str(e)}", exc_info=True)
            return None, None

    def get_statistics(self, days: int = 7) -> Dict[str, Any]:
        """
        Get extraction statistics for the specified period

        Args:
            days: Number of days to look back

        Returns:
            Dictionary with statistics
        """
        start_date = timezone.now() - timedelta(days=days)

        stats = ExtractionStatistics.objects.filter(
            date__gte=start_date.date()
        ).order_by('-date')

        if not stats:
            return {}

        latest = stats.first()
        return {
            'total_images_processed': latest.total_images_processed,
            'successful_extractions': latest.successful_extractions,
            'failed_extractions': latest.failed_extractions,
            'manual_review_required': latest.manual_review_required,
            'average_confidence': latest.average_confidence,
            'average_processing_time': latest.average_processing_time,
            'min_processing_time': latest.min_processing_time,
            'max_processing_time': latest.max_processing_time,
            'field_stats': latest.field_stats,
            'date': latest.date.isoformat(),
        }


def process_extraction_task(image_path: str, attachment_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Standalone function for Celery task to process image extraction

    Args:
        image_path: Path to image file
        attachment_id: ID of Attachment model (optional)

    Returns:
        Dictionary with extraction results
    """
    service = AIExtractionService()
    result = service.process_image(image_path)

    attachment = None
    if attachment_id:
        try:
            attachment = Attachment.objects.get(id=attachment_id)
        except Attachment.DoesNotExist:
            logger.warning(f"Attachment not found: {attachment_id}")

    ocr_result, data_result = service.save_to_database(result, attachment)

    result.ocr_result_id = ocr_result.id if ocr_result else None
    result.data_extraction_result_id = data_result.id if data_result else None

    return result.to_dict()
