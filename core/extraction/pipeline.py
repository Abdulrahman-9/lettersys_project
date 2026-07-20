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
import re
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any, Callable
from pathlib import Path
import hashlib
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

from django.db import transaction
from django.utils import timezone

from core.extraction.ocr.image import ImageProcessor, BatchImageProcessor
from core.extraction.ocr.service import OCRService, ArabicOCROptimizer
from core.extraction.ocr.providers import (
    build_offline_provider_from_settings,
    build_online_provider_from_settings,
)
from core.models import AIIntegrationSettings
from core.extraction.matchers.pattern import PatternMatcher, DateParser
from core.extraction.matchers.entity import EntityMatcher
from core.extraction.matchers.profile import SenderNumberProfiles
from core.models import (
    OCRResult, DataExtractionResult, ExtractionFeedback,
    ExtractionStatistics, ExtractionCache, Attachment, Book, Entity
)

logger = logging.getLogger(__name__)

# ─── ثوابت ─────────────────────────────────────────────────────────────────────
_MANUAL_REVIEW_THRESHOLD = 0.70

_FRIENDLY_ERRORS = {
    'list index out of range': 'فشل تحليل الصورة — تأكد من وضوح المستند وجودته',
    'image is None': 'تعذّر قراءة الصورة — قد يكون الملف تالفاً أو بصيغة غير مدعومة',
    'No module named': 'مكتبة OCR غير مثبّتة في الخادم — تواصل مع المسؤول',
    'out of memory': 'حجم الصورة كبير جداً — حاول بدقة أقل أو ملف أصغر',
    'timeout': 'استغرقت المعالجة وقتاً طويلاً — حاول مرة أخرى',
    'Connection': 'تعذّر الاتصال بخدمة OCR السحابية — يتم استخدام المعالجة المحلية',
    'MemoryError': 'حجم الصورة كبير جداً — حاول بدقة أقل أو ملف أصغر',
}


def _user_friendly_error(exc: Exception) -> str:
    """تحويل استثناء تقني إلى رسالة مفهومة للمستخدم."""
    raw = str(exc)
    for key, friendly in _FRIENDLY_ERRORS.items():
        if key.lower() in raw.lower():
            return friendly
    return 'حدث خطأ أثناء معالجة المستند — حاول مرة أخرى أو تواصل مع الدعم الفني'


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

        self.sender_date: Optional[str] = None
        self.sender_date_confidence: float = 0.0

        self.sender_number: Optional[str] = None
        self.sender_number_confidence: float = 0.0

        self.title: str = ""
        self.title_confidence: float = 0.0

        self.margin_text: str = ""
        self.margin_confidence: float = 0.0

        self.secret_level: str = ""
        self.secret_level_confidence: float = 0.0

        self.book_kind: str = ""
        self.book_kind_confidence: float = 0.0

        # قوانين المجال: نوع الوثيقة المطبوع، رمز سجلّ المُصدِر، سطر المُخاطَب
        self.document_type: str = ""
        self.document_type_confidence: float = 0.0
        self.register_code: str = ""
        self.recipient_text: str = ""

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
        self.user_message: str = ""   # رسالة مفهومة للمستخدم
        self.progress_stage: str = ""  # المرحلة الحالية للعرض في الواجهة
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
            'document_type': self.document_type,
            'document_type_confidence': self.document_type_confidence,
            'register_code': self.register_code,
            'issuing_entity_id': self.issuing_entity_id,
            'issuing_entity_name': self.issuing_entity_name,
            'issuing_entity_confidence': self.issuing_entity_confidence,
            'receiving_entity_id': self.receiving_entity_id,
            'receiving_entity_name': self.receiving_entity_name,
            'receiving_entity_confidence': self.receiving_entity_confidence,
            'overall_confidence': self.overall_confidence,
            'field_confidences': self.field_confidences,
            'status': self.status,
            'user_message': self.user_message,
            'progress_stage': self.progress_stage,
            'processing_time': self.processing_time,
            'timestamp': self.timestamp.isoformat(),
        }


# كلمات شائعة تكشف أن الطبقة لغةٌ حقيقية لا خردة — تُقاس كثافتُها لا عددُها:
# طبقات الملفات القديمة الخردة تحوي إنكليزية حقيقية قليلة في الترويسة
# («Ministry of Oil») تخدع العدّ المطلق، لكن كثافتها بين الرُّكام تفضحها.
_COMMON_EN = {'the', 'of', 'to', 'and', 'for', 'we', 'is', 'in', 'on', 'at', 'as',
              'are', 'this', 'that', 'you', 'your', 'our', 'be', 'by', 'from', 'with',
              'it', 'or', 'has', 'have', 'will', 'was', 'were', 'not', 'dear',
              'subject', 'date', 'no', 'company', 'oil', 'please', 'letter',
              'request', 'kindly', 'regarding', 'reference', 'attached'}
_COMMON_AR = {'في', 'من', 'الى', 'إلى', 'على', 'عن', 'رقم', 'العدد', 'السيد', 'وزارة',
              'شركة', 'قسم', 'الموضوع', 'التاريخ', 'بعد', 'تحية', 'المحترم', 'مدير', 'كتاب'}
# إنكليزيةٌ تظهر على **كل** ترويسة (بما فيها الممسوحة العربية ذات الطبقة المعطوبة):
# جدول IMS «Integrated management system / Doc No. / Date Rev» وشعار الشركة
# «Midland Oil Company / Ministry / Republic of Iraq». هذه لا تُثبت أن الطبقة
# طبقةُ رسالةٍ إنكليزية مقروءة — فلا تُحسب دليلاً (ثغرة #11246: خردةٌ لاتينية-الحرف
# عبرت البوّابة بجواز ترويستها). قِيس بالعين 2026-07-16.
_EN_LETTERHEAD = {'no', 'date', 'oil', 'company', 'ministry', 'republic', 'iraq',
                  'integrated', 'management', 'system', 'doc', 'rev', 'midland',
                  'state', 'gas', 'ims'}


def _text_layer_is_readable(text: str) -> bool:
    """بوّابة جودة لطبقة النصّ المضمّنة: بعض برامج المسح تُضمّن OCR خاصّاً بها —
    عربيةً مقروءةً بمحرّك لاتيني («.hiill;Jljo» بدل «وزارة النفط») أو عربيةً
    بأشكال العرض (ترتيب بصري) — طولُها يخدع لكن مطابقتنا العربية تنكسر عليها.
    القبول: عربيةٌ سليمة (كلمتان شائعتان + خلوّ من أشكال العرض) أو إنكليزيةٌ
    حقيقية (كثافة كلمات شائعة ≥5% بين الرموز اللاتينية و≥3 إصابات — الخردة
    المرصودة ≈1-2%). الرفض غير مُكلف — يعني OCR المُدرَّب كالسابق."""
    presentation = sum(1 for c in text if 'ﭐ' <= c <= '﻿')
    arabic = sum(1 for c in text if '؀' <= c <= 'ۿ') + presentation
    if presentation > 0.10 * max(1, arabic):
        return False
    lower = text.lower()
    ar_tokens = set(re.findall(r'[؀-ۿ]{2,}', lower))
    if len(ar_tokens & _COMMON_AR) >= 2:
        return True

    # **ثغرة قِيست بالقراءة بالعين (2026-07-14):** كتابٌ عربيّ ممسوح طبقتُه العربية
    # خردة («a.,.ri+Jl .rLrf») كان يعبر البوّابة بجواز سفرٍ إنكليزيّ — لأن ترويسة
    # نظام الجودة تحمل إنكليزيةً سليمة («Integrated management system», «Doc No.»,
    # «Midland Oil Company»)! فيبني المحرّك على ركامٍ ويُخرج عناوين خردة.
    # القاعدة: **المستند العربيُّ الغالب يجب أن تكون عربيّتُه مقروءة** — ولا تشفع
    # له إنكليزيةُ ترويسته. الرفض يعني OCR المُدرَّب (الأدقّ للعربية أصلاً).
    latin_chars = sum(1 for c in lower if 'a' <= c <= 'z')
    ar_chars = sum(1 for c in text if '؀' <= c <= 'ۿ')
    if ar_chars > 120 and ar_chars >= 0.30 * max(1, ar_chars + latin_chars):
        return False

    latin_tokens = re.findall(r'[a-z]{2,}', lower)
    if not latin_tokens:
        return False
    # كلماتُ محتوىً حقيقية فقط — بويلربليت الترويسة (Doc/No/Date/Company/Midland…)
    # يظهر على الممسوحة العربية أيضاً فلا يُثبت طبقةً إنكليزية مقروءة.
    hits = sum(1 for t in latin_tokens if t in _COMMON_EN and t not in _EN_LETTERHEAD)
    return hits >= 3 and hits / len(latin_tokens) >= 0.05


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
        self.number_profiles = SenderNumberProfiles()

        # قارئ الأرقام اليدوية (مرحلة 3) — كسول: يُبنى عند أول حاجة فقط
        self._hw_reader = None
        self._hw_locator = None

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
            self._offline_provider = build_offline_provider_from_settings(self._settings)

        if self._online_provider is None and self._settings.get('AI_PROVIDER') != 'offline':
            self._online_provider = build_online_provider_from_settings(self._settings)

    def _extract_pdf_text_layer(self, path: str, min_chars: int = 120, min_words: int = 20):
        """يُعيد نصّ طبقة PDF المضمّنة إن كانت غنيّة (مستند رقمي/مُصدَّر أو مُمسوح-ومُعالَج)،
        وإلا None (صورة ممسوحة بلا نصّ → يلزم OCR).

        للإيميلات المطبوعة وملفّات PDF الرقمية، النصّ المضمّن جاهزٌ ودقيق — أسرع وأخفّ
        ذاكرة بكثير من إعادة الرسم + Tesseract، ويعالج كل الصفحات تلقائياً. عتبة الطول
        والكلمات تحرس من طبقة ضئيلة (ختم/أثر)، وبوّابة المقروئية تحرس من طبقات
        برامج المسح الخردة — فتسقط كلتاهما إلى OCR الكامل المُدرَّب."""
        if not str(path).lower().endswith('.pdf'):
            return None
        try:
            import fitz
            doc = fitz.open(path)
            try:
                # sort=True: **ترتيبٌ بصريّ (أعلى→أسفل) لا بترتيب كتل الملفّ**.
                # قِيس بالقراءة بالعين (2026-07-14): برامج المسح تكتب كتل النصّ
                # بترتيبٍ عشوائي، فيقع سطر «Date» — وهو أعلى الصفحة بصرياً — عند
                # السطر 21-23 في التيار، أي خارج «منطقة الرأس» فيضيع التاريخ رغم
                # وضوحه التام في الصورة (كتب qurnain/EBS/NORTH). بالترتيب يعود
                # إلى السطر 7-9 حيث ينتمي. يفيد كلَّ الحقول لا التاريخَ وحده.
                text = '\n'.join(doc[i].get_text('text', sort=True)
                                 for i in range(doc.page_count)).strip()
            finally:
                doc.close()
        except Exception as exc:
            logger.warning('[pipeline] فحص طبقة نصّ PDF فشل: %s', exc)
            return None
        words = [w for w in text.split() if len(w) >= 2]
        if len(text) < min_chars or len(words) < min_words:
            return None
        if not _text_layer_is_readable(text):
            logger.info('[pipeline] طبقة النصّ المضمّنة غير مقروءة (خردة/تشكيل بصري) — OCR بديلاً')
            return None
        return text

    def _read_handwritten_sender_number(self, image_path, entity_id):
        """مرحلة 3 — رقم الجهة المخربش بخط اليد حيث تعجز كل الطبقات المطبوعة:
        تموضعٌ بمرساة «العدد» وبصمة تخطيط الجهة ← قصّ الشريط ← قراءة CRNN (v5:
        94.5% على شرائط محجوزة) ← بوابة الثقة المُعايَرة. يعيد (نص، ثقة) أو None؛
        أي فشلٍ داخلي يتدهور بصمت — القارئ لا يُسقط الأنبوب أبداً."""
        try:
            from core.extraction.handwriting import EntityLayoutPriors, NumberStripLocator
            from core.extraction.handwriting.reader import CONF_GATE, HandwrittenNumberReader

            if self._hw_reader is None:
                self._hw_reader = HandwrittenNumberReader()
                priors = EntityLayoutPriors(os.path.join('var', 'handwriting_layout_priors.json'))
                self._hw_locator = NumberStripLocator(priors)
            if not self._hw_reader.available:
                return None

            from PIL import Image as PILImage
            if image_path.lower().endswith('.pdf'):
                import fitz
                doc = fitz.open(image_path)
                page = doc[0]
                zoom = 300 / 72.0
                longer = max(page.rect.width, page.rect.height) * zoom
                if longer > 3500:
                    zoom *= 3500 / longer
                pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom),
                                      colorspace=fitz.csGRAY, alpha=False)
                img = PILImage.frombytes('L', (pix.width, pix.height), pix.samples)
                doc.close()
                del pix
            else:
                img = PILImage.open(image_path).convert('L')

            self._ensure_ocr_stack()
            prov = self._offline_provider
            pt = prov._pytesseract
            pt.pytesseract.tesseract_cmd = prov.cmd
            if prov.tessdata_dir:
                os.environ['TESSDATA_PREFIX'] = prov.tessdata_dir
            tsv = pt.image_to_data(img, lang=prov.lang, config=f'--psm {prov.psm}',
                                   output_type=pt.Output.DICT)
            located = self._hw_locator.locate(img, tsv, entity_id=entity_id)
            del tsv
            if located is None:
                return None
            strip, _label = located
            text, conf = self._hw_reader.read_best(strip)
            del img, strip
            if text and text.isdigit() and 1 <= len(text) <= 6 and conf >= CONF_GATE:
                return text, conf
            logger.info('[handwriting] قراءة دون البوابة: %r (ثقة %.2f)', text, conf)
            return None
        except Exception as exc:
            logger.warning('[handwriting] فشل مسار خط اليد: %s — تدهور رشيق',
                           type(exc).__name__)
            return None

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

            # الكاش ناقل نصّ فقط — الحقول المستنبَطة (أنماط/جهات) يعيد الأنبوب
            # حسابها حيّةً عند كل إصابة، فلا تتجمّد على منطقِ يومِ التخزين.
            result = AIExtractionResult()
            result.cached = True
            cached_data = cache.cached_extraction
            result.raw_text = cached_data.get('raw_text', '')
            result.cleaned_text = cached_data.get('cleaned_text', '')
            result.ocr_confidence = cached_data.get('ocr_confidence', 0.0)
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
            # نصّ الـ OCR وثقته فقط — انظر check_cache: المستنبَطات لا تُخزَّن.
            cache_data = {
                'raw_text': result.raw_text,
                'cleaned_text': result.cleaned_text,
                'ocr_confidence': result.ocr_confidence,
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

    def process_image(
        self,
        image_path: str,
        skip_ocr: bool = False,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> AIExtractionResult:
        """
        Process single image through complete extraction pipeline.

        Args:
            image_path:   Path to image file
            skip_ocr:     Skip OCR step (for testing)
            on_progress:  Optional callback(stage_label) called at each stage

        Returns:
            AIExtractionResult with all extracted data
        """
        from django.conf import settings as django_settings
        timeout_sec = getattr(django_settings, 'AI_EXTRACTION_TIMEOUT', 60)

        # تنفيذ المعالجة الداخلية مع حد زمني
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                self._process_image_internal, image_path, skip_ocr, on_progress
            )
            try:
                return future.result(timeout=timeout_sec)
            except FuturesTimeout:
                result = AIExtractionResult()
                result.image_path = image_path
                result.status = 'failed'
                result.error_message = f'timeout after {timeout_sec}s'
                result.user_message = _FRIENDLY_ERRORS['timeout']
                result.progress_stage = 'timeout'
                logger.error('[pipeline] process_image timed out after %ds', timeout_sec)
                return result

    def _process_image_internal(
        self,
        image_path: str,
        skip_ocr: bool = False,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> AIExtractionResult:
        """المعالجة الداخلية — تُستدعى داخل thread منفصل."""

        def _progress(stage: str) -> None:
            if on_progress:
                try:
                    on_progress(stage)
                except Exception as cb_exc:
                    logger.debug('[pipeline] progress callback failed: %s', cb_exc)

        start_time = time.time()
        result = AIExtractionResult()
        result.image_path = image_path
        enhanced_image_path: Optional[str] = None

        try:
            # Step 1: فحص الكاش — يختصر الغالي فقط (OCR/طبقة النص) ولا يُرجِع
            # نتيجة نهائية: الأنماط والجهات تُعادان حيّتين دائماً، لأن ذاكرة
            # الترويسة تتعلّم والجهات تُدمَج والمُستخرِجات تتحسّن — تجميدها في
            # الكاش كان يُعيد اقتراحات بائتة بل يُسقط الجهات ورقم/تاريخ الجهة
            # كلياً (الكاش لا يخزّنها؛ بلاغ المالك: «المرة الثانية لم يستخرج الجهة»).
            _progress('cache_check')
            result.image_hash = self.compute_image_hash(image_path)
            cached_result = self.check_cache(result.image_hash)
            if cached_result:
                result.cached = True
                result.raw_text = cached_result.raw_text
                result.cleaned_text = cached_result.cleaned_text
                result.ocr_confidence = cached_result.ocr_confidence
                result.detected_language = 'ar'
                result.ocr_engine = 'cache'

            # Step 2/3: طبقة النصّ المضمّنة أولاً — للمستندات الرقمية (إيميلات مطبوعة،
            # PDF مُصدَّر أو مُمسوح-ومُعالَج) نصٌّ جاهز أدقّ وأسرع وأخفّ ذاكرة من إعادة
            # الرسم + Tesseract، ويعالج كل الصفحات تلقائياً. نسقط إلى تحسين الصورة + OCR
            # فقط للصور الممسوحة بلا طبقة نصّ غنيّة.
            pdf_text = None if (skip_ocr or result.cached) else self._extract_pdf_text_layer(image_path)
            if pdf_text:
                # «الطبقة تكسب مكانها»: بعض الطبقات متنُها إنكليزية سليمة (تعبر
                # بوّابة الكثافة) لكن ترويستها خردة — فيضيع الرأس كله. نقبل الطبقة
                # فقط إن أثمرت حقلَ رأسٍ واحداً على الأقل (رقم أو تاريخ الجهة)؛
                # وإلا فالمسار البصري المُدرَّب أجدى.
                self._ensure_ocr_stack()
                probe = self.ocr_service.clean_text(pdf_text)
                p_num, _ = self.pattern_matcher.extract_sender_number(probe)
                p_date, _ = self.pattern_matcher.extract_sender_date(probe)
                if not p_num and not p_date:
                    logger.info('[pipeline] طبقة النصّ بلا حقول رأس (رقم/تاريخ) — OCR بديلاً')
                    pdf_text = None
            if pdf_text:
                _progress('ocr')
                result.progress_stage = 'قراءة النص'
                self._ensure_ocr_stack()   # لأجل ocr_service.clean_text
                result.raw_text = pdf_text
                result.cleaned_text = self.ocr_service.clean_text(pdf_text)
                result.ocr_confidence = 0.9
                result.detected_language = 'ar'
                result.ocr_engine = 'pdf_text_layer'
                logger.info('Used embedded PDF text layer (%d chars) — skipped image OCR', len(pdf_text))
            elif not result.cached:
                # Step 2: تحسين الصورة
                _progress('image_enhancement')
                result.progress_stage = 'تحسين الصورة'
                logger.info('Processing image: %s', image_path)
                from django.conf import settings as dj_settings
                ocr_engine = getattr(dj_settings, 'AI_OFFLINE_ENGINE', 'tesseract')
                if ocr_engine == 'tesseract':
                    # Tesseract يطبّق تحسينه داخلياً؛ صورة رمادية نظيفة أدقّ من المعالجة
                    # الثقيلة (التي تخفض جودته). max_ocr_dim=3500: يطابق مسح الوكيل
                    # 300DPI لصفحة A4 (3508px) بلا تصغيرٍ مُهدِر — توجيه المالك: دقّة
                    # المسح كاملةً أولوية على السرعة (كان 2600 ≈ 222DPI فعلية).
                    image_processor = ImageProcessor(image_path, preprocess_pdf=False, max_ocr_dim=3500)
                    image_processor.light_pipeline()
                else:
                    image_processor = ImageProcessor(image_path)
                    image_processor.full_pipeline()
                enhanced_image = image_processor.get_image()
                # الصورة المُحسَّنة تُكتَب في مجلد النظام المؤقّت — لا بجوار الأصل.
                # الكتابة بجوار الأصل تجعل مراقب المجلد (ScanWatcher) يلتقطها
                # كملفّ ممسوح جديد ويُعالجها في حلقة.
                _ext = os.path.splitext(image_path)[1].lower()
                if _ext not in ('.jpg', '.jpeg', '.png'):
                    _ext = '.png'
                _fd, enhanced_image_path = tempfile.mkstemp(suffix=_ext, prefix='lettersys_ocr_')
                os.close(_fd)
                image_processor.save(enhanced_image_path)
                del image_processor, enhanced_image

                # Step 3: OCR
                if not skip_ocr:
                    _progress('ocr')
                    result.progress_stage = 'قراءة النص'
                    self._ensure_ocr_stack()

                    offline_res = self._offline_provider.extract(enhanced_image_path)
                    result.raw_text = offline_res.get('raw_text', '')
                    result.cleaned_text = self.ocr_service.clean_text(result.raw_text)
                    result.ocr_confidence = float(offline_res.get('avg_confidence', 0.0))
                    result.detected_language = 'ar'
                    ocr_engine_used = self._offline_provider.name  # 'tesseract' أو 'easyocr'
                    logger.info('OCR (offline) confidence %.2f', result.ocr_confidence)

                    # Fallback إلى Azure عند ثقة منخفضة
                    if self._settings.get('AI_FALLBACK_ON_LOW_CONFIDENCE', True) and self._online_provider:
                        threshold = float(self._settings.get('AI_LOW_CONFIDENCE_THRESHOLD', 0.4))
                        if result.ocr_confidence < threshold:
                            _progress('ocr_azure_fallback')
                            result.progress_stage = 'تحسين القراءة (سحابة)'
                            logger.info('OCR below threshold %.2f; trying online provider...', threshold)
                            try:
                                online_res = self._online_provider.extract(enhanced_image_path)
                                online_conf = float(online_res.get('avg_confidence', 0.0))
                                if online_conf > result.ocr_confidence and online_res.get('raw_text'):
                                    result.raw_text = online_res.get('raw_text', '')
                                    result.cleaned_text = self.ocr_service.clean_text(result.raw_text)
                                    result.ocr_confidence = online_conf
                                    ocr_engine_used = 'azure'
                                    logger.info('Online OCR improved confidence to %.2f', online_conf)
                            except Exception as azure_exc:
                                logger.warning('[pipeline] Azure fallback failed: %s', azure_exc, exc_info=True)

                    result.ocr_engine = ocr_engine_used
                else:
                    result.raw_text = ''
                    result.cleaned_text = ''
                    result.ocr_confidence = 0.0

            # Step 4: Pattern Matching
            _progress('pattern_matching')
            result.progress_stage = 'تحليل البيانات'
            if result.cleaned_text:
                patterns = self.pattern_matcher.extract_all_data(result.cleaned_text)
                # `extract_all_data` يُعيد قاموساً مسطّحاً: القيمة و«*_confidence» مفتاحان
                # منفصلان (لا tuple واحد)، ومفتاح التاريخ اسمه 'date'. نقرأ المفاتيح
                # الفعلية، و«or default» يحمي من قيمة None لمفتاح موجود.
                result.book_number = patterns.get('book_number') or ''
                result.book_number_confidence = patterns.get('book_number_confidence') or 0.0
                # قاعدة المالك: أيُّ تاريخ يُستخرَج من المستند = تاريخ الجهة المُرسِلة
                # دائماً. تاريخنا (book_date) = تاريخ الإدخال (اليوم) في الواجهة — لا
                # يُستخرَج إطلاقاً. لذا: sender_date = علامة «التاريخ/Date» وإلا أيُّ
                # تاريخ في المستند؛ و book_date يبقى فارغاً (تحفظه الواجهة على اليوم).
                result.book_date = None
                result.book_date_confidence = 0.0
                # تاريخ الجهة من المُستخرِج المنضبط بمنطقة الرأس **فقط** — السقوطُ
                # لمُستخرِج التاريخ العام كان باباً خلفياً يلتقط تواريخ إحالات المتن
                # (معيار الجهات الخمس: كل تواريخ الأقسام العربية «الخاطئة» جاءت منه).
                # الفراغ الصادق خيرٌ من تاريخٍ خاطئ — مبدأ المالك.
                result.sender_date = patterns.get('sender_date')
                result.sender_date_confidence = (patterns.get('sender_date_confidence') or 0.0) \
                    if result.sender_date else 0.0
                result.sender_number = patterns.get('sender_number')
                result.sender_number_confidence = patterns.get('sender_number_confidence') or 0.0
                result.title = patterns.get('title') or ''
                # جهاتٌ (Slb) تضع رقم صادرها داخل سطر الموضوع («Ref-135, Akkas…») —
                # نقتطعه رقماً وننظّف العنوان (16 كتاباً محفوظاً تُثبت النمط).
                if result.title:
                    ref_num, clean_title = self.pattern_matcher.split_ref_from_title(result.title)
                    if ref_num:
                        result.title = clean_title
                        if not result.sender_number:
                            result.sender_number = ref_num
                            result.sender_number_confidence = 0.65
                result.secret_level = patterns.get('secret_level') or ''
                result.secret_level_confidence = patterns.get('secret_level_confidence') or 0.0
                result.book_kind = patterns.get('book_kind') or ''
                result.book_kind_confidence = patterns.get('book_kind_confidence') or 0.0
                # قوانين المجال (توجيه المالك، مقيسة على 9,155 كتاباً): نوع الوثيقة
                # مطبوعٌ في ترويسة نظام الجودة، ورمز السجلّ «ش13» يسبق العدد ويُعرّف
                # الجهة المُصدِرة، والمُخاطَب يقع بعد «الى/» في الرأس.
                result.document_type = patterns.get('document_type') or ''
                result.document_type_confidence = patterns.get('document_type_confidence') or 0.0
                result.register_code = patterns.get('register_code') or ''
                result.recipient_text = patterns.get('recipient') or ''
                logger.info('Pattern matching done: book_number=%s', result.book_number)

            # Step 5: Entity Matching
            _progress('entity_matching')
            result.progress_stage = 'مطابقة الجهات'
            # `extract_entities` يُعيد List[Tuple[str, float]] — مرشّحات «من/الجهة».
            entity_candidates = [
                text for (text, _conf) in self.pattern_matcher.extract_entities(result.cleaned_text or '')
            ]

            def _resolve_entity(etype: str):
                """ترتيب المصادر بحسب دقّتها المقيسة على بيانات حقيقية:
                  1) ذاكرة الترويسة (تعلّمٌ من مستندات سابقة مؤكَّدة) — hit@3 ≈ 85%،
                  2) مطابقة اسم الجهة في الترويسة — hit@3 ≈ 18-27%،
                  3) أنماط «من/إلى X» — hit@3 ≈ 0-3%.
                كلٌّ يملأ ما نقص عن أفضل-3 دون إزاحة الأعلى أو تكرار، وفشلُ أي
                مصدرٍ (MemoryError تحت ضغط 8GB مثلاً) يُسقطه وحده لا الخطوة كلها."""
                cleaned = result.cleaned_text or ''
                ranked, seen = [], set()

                def _extend(fetch, label):
                    try:
                        for m in fetch():
                            if m['entity_id'] not in seen:
                                ranked.append(m); seen.add(m['entity_id'])
                    except Exception as exc:
                        logger.warning('[pipeline] مصدر الجهات %s فشل (%s) — تدهور رشيق',
                                       label, type(exc).__name__)

                # رمز السجلّ («العدد: ش13/…») معرِّفٌ قاطعٌ للجهة المُصدِرة — يتصدّر
                # كل شيء (قانون المجال: لكل قسم رمزٌ مسجَّل عندنا)، ويسدّ ثغرة
                # الأقسام الجديدة التي لا ذاكرةَ ترويسةٍ لها بعد.
                if etype == 'issuer' and getattr(result, 'register_code', ''):
                    _extend(lambda: self.entity_matcher.match_by_register_code(
                        result.register_code, entity_type='issuer'), 'register_code')
                # المُخاطَب مكتوبٌ صراحةً بعد «الى/» في الرأس — أدقّ من مسح الترويسة كلها
                if etype == 'receiver' and getattr(result, 'recipient_text', ''):
                    _extend(lambda: self.entity_matcher.match_entity(
                        result.recipient_text, entity_type='receiver')[:3], 'recipient_line')
                _extend(lambda: self.entity_matcher.match_from_memory(cleaned, entity_type=etype, top_k=3),
                        'memory')
                if len(ranked) < 3:
                    _extend(lambda: self.entity_matcher.match_from_letterhead(cleaned, entity_type=etype, top_k=3),
                            'letterhead')
                pattern_match = (self.entity_matcher.match_issuing_entity if etype == 'issuer'
                                 else self.entity_matcher.match_receiving_entity)
                for entity_text in entity_candidates:
                    _extend(lambda: pattern_match(entity_text), 'patterns')
                    if len(ranked) > 3:
                        break
                return ranked[:3]

            def _assign_entity(matches, id_attr, name_attr, conf_attr, matches_attr):
                if not matches:
                    return
                best = matches[0]
                setattr(result, matches_attr, matches)
                setattr(result, id_attr, best.get('entity_id'))
                setattr(result, name_attr, best.get('entity_name', ''))
                score = best.get('score', 0.0) / 100.0
                # سقوف الثقة بحسب موثوقية المصدر المقيسة (كلّها اقتراحيّة للمراجعة):
                #   رمز السجلّ = معرِّف مسجَّل (لا تخمين) → بلا سقف؛
                #   ذاكرة (hit@1 ≈ 62%) → 0.85، ترويسة (≈ 11%) → 0.5، نمط صريح → كاملة.
                cap = {'memory': 0.85, 'letterhead': 0.5}.get(best.get('match_type'))
                setattr(result, conf_attr, min(score, cap) if cap else score)

            _assign_entity(_resolve_entity('issuer'), 'issuing_entity_id',
                           'issuing_entity_name', 'issuing_entity_confidence', 'issuing_entity_matches')
            _assign_entity(_resolve_entity('receiver'), 'receiving_entity_id',
                           'receiving_entity_name', 'receiving_entity_confidence', 'receiving_entity_matches')

            # بصمة الجهة: بعد معرفة المُرسِل، ابحث عن رقمٍ بقالب أرقامه المُتعلَّم من
            # كتبه المؤكَّدة — يلتقط ما فاتته العلامات العامة ويُصحّح الالتقاط الناقص
            # (مثل «195» بدل «MF-2026-195»).
            if getattr(result, 'issuing_entity_id', None) and result.cleaned_text:
                hit = self.number_profiles.find(result.cleaned_text, result.issuing_entity_id)
                if hit and hit.value != (result.sender_number or ''):
                    if not result.sender_number or hit.confidence >= (result.sender_number_confidence or 0.0):
                        logger.info('[profile] sender_number %r → %r (قالب %s)',
                                    result.sender_number, hit.value, hit.template)
                        result.sender_number = hit.value
                        result.sender_number_confidence = hit.confidence
                # إصلاح بادئة شوّهها OCR (llK-20260257 → NK-20260257) ببادئات
                # الجهة المؤكَّدة نفسها — معيار الجهات الخمس، كتاب 11237.
                if result.sender_number:
                    repaired = self.number_profiles.repair(result.sender_number,
                                                           result.issuing_entity_id)
                    if repaired:
                        logger.info('[profile] إصلاح بادئة: %r → %r',
                                    result.sender_number, repaired)
                        result.sender_number = repaired

            # Step 5.5: رقم الجهة المخربش بخط اليد — الملاذ الأخير حين تصمت كل
            # الطبقات المطبوعة (قياس الأرشيف: أغلبية الأرقام يدوية، Tesseract ≈ 0%
            # عليها). يعمل في مسارَي OCR والكاش كليهما (يحتاج ملف الصورة فقط).
            if not result.sender_number and result.image_path:
                _progress('handwritten_number')
                hw = self._read_handwritten_sender_number(result.image_path,
                                                          getattr(result, 'issuing_entity_id', None))
                if hw:
                    result.sender_number, result.sender_number_confidence = hw
                    logger.info('[handwriting] رقم الجهة من خط اليد: %r (ثقة %.2f)',
                                result.sender_number, result.sender_number_confidence)

            # Step 6: حساب الثقة الإجمالية
            _progress('confidence')
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
            confidence_values = [v for v in result.field_confidences.values() if v > 0]
            result.overall_confidence = (
                sum(confidence_values) / len(confidence_values) if confidence_values
                else result.ocr_confidence
            )

            # Step 7: تحديد الحالة
            if result.overall_confidence < _MANUAL_REVIEW_THRESHOLD:
                result.status = 'manual_review'
                result.user_message = 'الثقة منخفضة — يُنصح بمراجعة الحقول يدوياً'
                logger.warning('Low confidence: %.2f', result.overall_confidence)
            else:
                result.status = 'completed'
                result.user_message = 'تم الاستخراج بنجاح'

            # Step 8: حفظ في الكاش (الإصابة لا تعيد الكتابة — تحفظ عدّاد hit_count)
            if not result.cached:
                self.save_to_cache(result.image_hash, result)
            result.progress_stage = 'completed'
            result.processing_time = time.time() - start_time
            logger.info('Image processing done in %.2fs, confidence %.2f%%',
                        result.processing_time, result.overall_confidence * 100)
            return result

        except Exception as e:
            logger.error('Error processing image: %s', e, exc_info=True)
            result.status = 'failed'
            result.error_message = str(e)
            result.user_message = _user_friendly_error(e)
            result.progress_stage = 'error'
            result.processing_time = time.time() - start_time
            return result
        finally:
            try:
                if enhanced_image_path and os.path.exists(enhanced_image_path):
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


def slim_entity_matches(matches) -> List[Dict[str, Any]]:
    """يُشذِّب مرشّحي الجهة top-3 للواجهة: اسم + درجة 0-1 + مصدر المطابقة فقط
    (لا يُسرَّب باقي حمولة المطابقة الداخلية)."""
    slim = []
    for m in (matches or [])[:3]:
        name = (m.get('entity_name') or '').strip()
        if not name:
            continue
        slim.append({
            'entity_id': m.get('entity_id'),
            'entity_name': name,
            'score': round(min(m.get('score', 0.0) / 100.0, 1.0), 3),
            'match_type': m.get('match_type', ''),
        })
    return slim


def result_to_scan_data(result: 'AIExtractionResult') -> Dict[str, Any]:
    """يحوّل نتيجة الاستخراج إلى dict مفاتيح المسح/الواجهة (المُشكِّل القانوني الموحّد).

    raw_text/cleaned_text/ocr_engine تُمرَّر أيضاً لحلقة التقاط التدريب (تُحفَظ في
    OCRResult عند الحفظ) — الواجهة تتجاهل المفاتيح الزائدة.
    """
    return {
        'raw_text': result.raw_text,
        'cleaned_text': result.cleaned_text,
        'ocr_engine': getattr(result, 'ocr_engine', ''),
        'book_number': result.book_number,
        'book_number_confidence': result.book_number_confidence,
        'book_date': result.book_date,
        'book_date_confidence': result.book_date_confidence,
        'sender_date': result.sender_date,
        'sender_date_confidence': result.sender_date_confidence,
        'sender_number': result.sender_number,
        'sender_number_confidence': result.sender_number_confidence,
        'title': result.title,
        'title_confidence': result.title_confidence,
        'issuing_entity': result.issuing_entity_name,
        'issuing_entity_confidence': result.issuing_entity_confidence,
        'issuing_entity_matches': slim_entity_matches(result.issuing_entity_matches),
        'receiving_entity': result.receiving_entity_name,
        'receiving_entity_confidence': result.receiving_entity_confidence,
        'receiving_entity_matches': slim_entity_matches(result.receiving_entity_matches),
        'secret_level': result.secret_level,
        'secret_level_confidence': result.secret_level_confidence,
        'book_kind': result.book_kind,
        'book_kind_confidence': result.book_kind_confidence,
        'overall_confidence': result.overall_confidence,
        'needs_review': result.status == 'manual_review',
        'user_message': result.user_message,
    }


def run_ocr_inprocess(image_path: str) -> Dict[str, Any]:
    """يشغّل الاستخراج داخل عملية الخادم مباشرةً — آمن مع Tesseract (برنامج خارجي،
    لا يُسقِط Django بـ segfault مثل EasyOCR/PyTorch) وأسرع من run_ocr_isolated
    (بلا إعادة إقلاع Django ~5-11ث). الأخطاء تُعاد كـ needs_review بلا رفع استثناء."""
    try:
        result = AIExtractionService().process_image(image_path)
        return result_to_scan_data(result)
    except Exception as exc:  # noqa: BLE001 — فشل OCR لا يُهدر المسح
        logger.error('[OCR-inprocess] خطأ: %s', exc, exc_info=True)
        return {'needs_review': True, '_error': str(exc)}


def run_ocr_isolated(image_path: str, timeout: int = 150) -> Dict[str, Any]:
    """
    يشغّل الاستخراج في عملية فرعية معزولة عبر `manage.py ocr_process`.

    محرّك OCR (EasyOCR/PyTorch) قد يُحدث segfault لا يُلتقَط بـ try/except —
    وتشغيله داخل خادم الويب يُسقطه. هذه الدالة تعزله في عملية فرعية،
    فيبقى أيّ تعطّل محصوراً فيها والخادم سليم.

    تُعيد dict نتيجة الاستخراج (نفس مفاتيح ScanWatcher)؛ وعند الفشل
    تُعيد {'needs_review': True, '_error': '...'} بدل أن ترمي استثناءً.
    """
    import subprocess
    import sys
    from django.conf import settings as dj_settings

    manage_py = os.path.join(str(dj_settings.BASE_DIR), 'manage.py')
    out_fd, out_path = tempfile.mkstemp(suffix='.json', prefix='ocr_result_')
    os.close(out_fd)

    env = dict(os.environ)
    env['PYTHONIOENCODING'] = 'utf-8'

    try:
        proc = subprocess.run(
            [sys.executable, manage_py, 'ocr_process', image_path, out_path],
            capture_output=True, text=True, timeout=timeout, env=env,
        )
        if proc.returncode != 0:
            tail = (proc.stderr or '').strip()[-300:]
            logger.error('[OCR-isolated] تعطّلت العملية الفرعية rc=%s: %s', proc.returncode, tail)
            return {'needs_review': True, '_error': f'تعذّرت المعالجة (كود الخروج {proc.returncode})'}
        with open(out_path, encoding='utf-8') as f:
            payload = json.load(f)
        return payload.get('data') or {'needs_review': True, '_error': 'لا توجد بيانات ناتجة'}
    except subprocess.TimeoutExpired:
        logger.error('[OCR-isolated] انتهت المهلة بعد %ss', timeout)
        return {'needs_review': True, '_error': f'انتهت مهلة المعالجة ({timeout} ثانية)'}
    except Exception as exc:
        logger.error('[OCR-isolated] خطأ غير متوقّع: %s', exc, exc_info=True)
        return {'needs_review': True, '_error': str(exc)}
    finally:
        try:
            os.remove(out_path)
        except OSError:
            pass


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
