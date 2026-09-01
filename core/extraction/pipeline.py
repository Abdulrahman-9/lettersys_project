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
from core.extraction.matchers.strict_ref import (canonical_sender_number,
                                                 strict_ref_match)
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
        # موضع قصّ العدد اليدويّ مُطبَّعاً [x0,y0,x1,y1] (0-1) — ميتاداتا تدريب التوضيع
        # تُلتقَط عند الحفظ؛ None حين لا يُقرأ العدد يدوياً. (رافعة Fable: أزواج تدريب CRNN.)
        self.sender_number_bbox: Optional[list] = None
        self.sender_number_bbox_source: str = ''      # 'crnn' (قراءةٌ واثقة) أو 'detector'
        self.sender_number_bbox_dims: Optional[list] = None   # [W, H] المقاس المرجعيّ
        # قصاصةُ شريط «التأريخ» اليدويّ (data URL) لعرضها بجوار حقل الإدخال (خيار F،
        # فيبل15/16): الكاتب — القارئ الموثوق — ينسخها بنظرة. لا تُقرأ آلياً ولا تُبثّ
        # في الكاش/الحفظ؛ تعيش في scan_data (استجابة HTTP عابرة) فقط. None حين لا شريط.
        self.sender_date_crop: Optional[str] = None
        # اقتراحُ قارئ التاريخ (D2) — قاموسٌ منفصلٌ لا يُكتب في الحقل
        self.sender_date_suggestion: Optional[dict] = None

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


NUMBER_EMISSION_ENABLED = False
"""إصدار حقل «عدد الجهة» إلى الكاتب — **مُغلَقٌ** حتى تُعيد T2.4 تدريب القارئ.

قِيس على خطّ الأساس المُعتمَد (تشغيلة A، 100 كتابٍ نظيف، فاشل 0):

    إجمالاً        إصابة  4 · صامت 72 · **خاطئ 24**
    مسار CRNN      إصابة  1 · **خاطئ 6 — كلّها بثقة >= 0.90**
    المسار المطبوع إصابة  3 · خاطئ 18 (بثقةٍ ثابتة 0.70)

والحاسم أنّ الواجهة **بلا عتبة عرض**: `extraction_smart.js` يكتب أيّ اقتراحٍ في الحقل
مهما كانت ثقته، والثقة تُغيّر لون الشارة لا ظهور القيمة. أي أنّ أربعةً وعشرين رقماً
خاطئاً تُملأ في نموذج الكاتب ويجب أن ينتبه ويحذفها — كلفةُ انتباهٍ تفوق ما توفّره
الإصابات الأربع. وستٌّ منها تُعرض بأعلى ثقةٍ ممكنة، وهي أسوأ صنف.

**نفس المبدأ طُبِّق ثلاث مرّات اليوم:** أُغلق إصدار قصاصة الكاشف مرّتين لخرقه بند
«واثقٌ‑ومخطئ»، ولا يجوز إبقاء مسارٍ قديمٍ حيّاً عند 6 بنسبة إصابةٍ أسوأ.

**ما لا يتأثّر:** دولاب التعلّم كاملاً — الصندوق ومقاسه ومصدره وقيمةُ الكاتب النهائيّة
تُحفَظ في `additional_data` بصرف النظر عن الإصدار، فزوج (قصاصة، حقيقة) سليم. ومرساةُ
قصاصة التاريخ تعمل. والاقتراح الفارغ لا يُنشئ صفَّ تغذيةٍ راجعة (`capture.py:184`
يشترط `original`)، فتبقى دلالة «الكاتب صحّح ما عرضناه» نظيفة.

**شرط إعادة الفتح** (مُسجَّلٌ في `docs/EVAL_REGISTRY.md`): إعادة تدريب CRNN على قصاصات
الكاشف عند بلوغ 300 قصاصةٍ مؤكَّدة (`manage.py capture_stats`)، ثمّ نظرةٌ على المجموعة
e2e-B ببوّابةٍ مُسجَّلةٍ مسبقاً. لا يُفتح بقلب هذه الرايةِ وحدها.
"""


def _sender_number_survives_emission(result) -> bool:
    """مرآةُ سياسة الكتم: هل تبلغ القيمةُ الحاليّةُ الكاتبَ لو صدرت الآن؟

    **لماذا مرآةٌ لا شرطٌ حرفيّ** (خطّة فيبل 2026-08-26): كان المسارُ البصريّ
    محكوماً بـ`if not result.sender_number` — فقيمةٌ نصّيّةٌ **محكومٌ عليها بالكتم**
    تمنع القراءةَ البصريّة من أن تُحاوَل أصلاً، ثمّ تُسكَت هي نفسُها، فنخسر
    الاثنين معاً. مقيسٌ على e2e-C: **15 من 19 صامتاً** حُجبوا هكذا، والقارئُ
    يقرأ صناديقَهم 14/14 ويصيب 10 بثقاتٍ 0.95–1.00.

    وربطُ الشرط بالسياسة (لا بقيمةٍ حرفيّة مثل `== 'crnn'`) يجعله يصحّ يومَ
    تتغيّر السياسة: لو رُفع الكتمُ النصّيّ غداً، لن يدهس البصريُّ قيمةً ناجية.
    """
    if not getattr(result, 'sender_number', None):
        return False
    if NUMBER_EMISSION_ENABLED:
        return True
    return getattr(result, 'sender_number_bbox_source', '') == 'crnn'


def _known_prefixes(prof) -> set:
    """كلُّ بادئةٍ مؤكَّدةٍ لأيّ جهةٍ في الفهرس — حارسُ النقض العالميّ.

    الجهةُ **مقترحةٌ لا مؤكَّدة** (تعرّفُ top-1 مقيسٌ 60%)، فنقضٌ يعتمد قالبَ
    جهةٍ واحدةٍ قد يكتم قيمةً صحيحةً نُسبت لجهةٍ خاطئة. والحارس: لا يُنقَض إلّا
    ما لم يكن بادئةً مؤكَّدةً **لأحدٍ إطلاقاً** — فـ`llK` المشوَّهة تسقط، و`MF`
    السليمةُ على جهةٍ خاطئة تنجو.
    """
    prof._ensure_index()
    out = set()
    for profile in prof._profiles.values():
        for bucket in (profile.get('prefixes') or {}, profile.get('ctx_prefixes') or {}):
            for px in bucket.values():
                out.update(p.upper() for p, c in px.items() if c >= 2)
    return out


def _printed_number_vetoed(result) -> bool:
    """نقضٌ بنيويٌّ لتشويه OCR — **نقضٌ لا كاتب**: يمنع، ولا يقترح ولا يرفع ثقة.

    الإشارة (استشارة فيبل 2026-08-27): `repair()` لا يُعيد قيمةً إلّا حين تكون
    البادئةُ الملتقطة تشويهاً بمسافة تحرير 1–2 من بادئةٍ مؤكَّدةٍ **لنفس الجهة**
    والقالبُ المُصحَّح معروفٌ لها — ويُعيد None للسليمة. فوجودُ اقتراحِ إصلاحٍ
    **هو** دليلُ التشويه. مقيسٌ على إيميلات الإنتاج: `llK-20260257` بدل `NK-…`.

    ولا `hasattr` هنا: الحراسةُ بها هي التي جعلت النسخةَ الأولى **خاملةً صامتة**
    (صفرُ نقضٍ بلا خطأٍ ولا تنبيه). الواجهةُ تُستدعى مباشرةً، واختبارُ حرزٍ يفشل
    صاخباً إن انجرفت.

    والقيمةُ المكتومة واقتراحُ إصلاحها يُحفظان في `additional_data` — مادّةُ
    تعلّمٍ لأنماط OCR لا تُهدَر بالتصفير.
    """
    val = getattr(result, 'sender_number', None)
    ent = getattr(result, 'issuing_entity_id', None)
    if not val or not ent:
        return False
    try:
        import re as _re
        from core.extraction.matchers.profile import SenderNumberProfiles
        prof = SenderNumberProfiles()
        m = _re.match(r'([A-Za-z]{1,7})([-/].+)$', str(val).strip())
        if not m:
            return False
        if m.group(1).upper() in _known_prefixes(prof):
            return False                      # بادئةٌ مؤكَّدةٌ لأحدٍ ⟵ لا نقض
        fixed = prof.repair(val, ent)
        if not fixed:
            return False
        logger.info('[emission] نقضٌ بنيويّ: %r بادئةٌ مشوَّهة (الإصلاحُ المرجَّح %r)',
                    val, fixed)
        extra = getattr(result, 'additional_data', None)
        if isinstance(extra, dict):
            extra['sender_number_vetoed'] = str(val)[:50]
            extra['sender_number_veto_fix'] = str(fixed)[:50]
        return True
    except Exception as exc:
        logger.warning('[emission] النقضُ البنيويّ تعذّر (%s) — لا نقض',
                       type(exc).__name__)
        return False


def _strict_ref_skips_visual(result) -> bool:
    """هل يُغني المرجعُ المطبوعُ الصارم عن استدعاء المسار البصريّ كلِّه؟

    **شرطان معاً، وكلاهما لازم:**
      ١. منشأُ القيمة `strict_ref` — المقيسُ 32 إصابةً وصفرَ خطأٍ على صفّه مقابل
         11 إصابةً وخطأين للبصريّ على نفس المستندات.
      ٢. `sender_date` مملوء — فـ`want_date_crop` يصير `False`، وعندها **كلُّ جسم
         `_read_handwritten_sender_number` عملٌ ضائع** إلّا صندوقَ التدريب. أمّا
         حين يصمت التاريخُ فالنداءُ يبقى: تخطّيه يقتل قصاصةَ التاريخ واقتراحَه
         (سبعةُ مفاتيح التقاطٍ في `capture.py`) — ثمنٌ لا يُدفع مقابل ثوانٍ.

    **ولا تُمسّ `_sender_number_survives_emission`**: تلك المرآةُ تحرس **محاولةَ**
    البصريّ، ولو نجا فيها منشأٌ نصّيٌّ لامتنعت المحاولةُ فانتُقض S3′ صامتاً.
    الشرطُ هنا منفصلٌ عنها عمداً، فيبقى حرزُ `test_mirror_stays_crnn_only` صادقاً
    بلا التفافٍ عليه.

    والمكسبُ المقيس حين يتحقّق الشرطان: **3.9 ث/مستند** (رسمان بـ300/175dpi +
    `pytesseract.image_to_data` على صفحةٍ كاملة + استدلالا YOLO) مقابل 0.094 ث.
    """
    return (getattr(result, 'sender_number_source', '') == 'strict_ref'
            and bool(getattr(result, 'sender_number', None))
            and bool(getattr(result, 'sender_date', None)))


def _suppress_sender_number_emission(result) -> None:
    """يمنع أيّ قيمةِ عددٍ من بلوغ الكاتب — **من كلّ الكُتّاب الخمسة**.

    جردُ الكُتّاب (2026-08-18): الأنماط المطبوعة · احتياط `ref_num` بثقة 0.65 ·
    `number_profiles.find` · `number_profiles.repair` · قراءة CRNN. والموضع هنا **بعدهم
    جميعاً**، فالهيمنة بالبناء لا بالتعداد — ولو أُضيف كاتبٌ سادسٌ غداً لسقط تحته أيضاً.

    الصندوق ومقاسه ومصدره **تبقى**: هي مادّة التدريب لا مادّة العرض.
    """
    if NUMBER_EMISSION_ENABLED:
        return
    # **S4 (2026-08-26):** كاتبُ مرساة الرأس المطبوعة يُفتح وحده بثقةٍ ثابتة 0.70
    # ووسمٍ صريح. قياسُ الإيميلات: العدد يُستخرَج صحيحاً في 7 من 12 مستنداً
    # رقميّاً ثمّ يُكتَم — خسارةٌ بقرارِ سياسةٍ لا بعجزِ قراءة. و0.70 **دون عتبة
    # «الواثق» (0.90) بنائيّاً**، فلا يستطيع هذا المسار خرقَ الحارس رياضيّاً.
    # ⚠️ ولا يُضاف هذا المنشأ إلى `_sender_number_survives_emission` أبداً: تلك
    # المرآةُ تحرس **محاولةَ** المسار البصريّ، ولو نجا فيها المطبوعُ لمُنعت
    # المحاولةُ ونُقض S3′ صامتاً. البصريُّ يُجرَّب دائماً ويُزيح المطبوع إن كتب.
    if (getattr(result, 'sender_number_source', '') == 'printed_anchor'
            and getattr(result, 'sender_number', None)
            and not _printed_number_vetoed(result)):
        return
    # **المرجعُ المطبوعُ الصارم (2026-08-30)** — منشأٌ مستقلٌّ عن `printed_anchor`
    # عمداً: ذاك يقبل أيَّ التقاطِ مرساةٍ بثقة 0.70، وهذا يشترط بادئةً معتمدةً
    # ومنطقةً رأسيّةً وسطرَ حقلٍ لا نثر — فقِيس 32 إصابةً **وصفرَ خطأ**، وعلى
    # المجموعة الرقميّة المختومة يُطلق مرّةً واحدةً صحيحة. والنقضُ البنيويُّ
    # يسري عليه كما يسري على المطبوع.
    # ⚠️ ولا يُضاف إلى `_sender_number_survives_emission` أبداً — فخُّ المرآة.
    if (getattr(result, 'sender_number_source', '') == 'strict_ref'
            and getattr(result, 'sender_number', None)
            and not _printed_number_vetoed(result)):
        return
    # **إعادةُ نطاقٍ بأمر المالك (2026-08-19):** القراءة البصريّة (CRNN على قصاصة
    # الكاشف أو شريط المُموضِع، `bbox_source == 'crnn'`) **تُعرض بثقتها الحقيقيّة**
    # والواجهة تؤشّر الضعيف. أمّا الكُتّاب النصّيّون (أنماط المتن · احتياط 0.65 ·
    # بصمات الجهات) فيبقون مكتومين — قياسُهم 2 صواب مقابل 17 خطأً لكلّ مئة، وكلّ
    # أخطائهم بثقة 0.70 التي تُعرض أصفر لا أحمر.
    if (getattr(result, 'sender_number_bbox_source', '') == 'crnn'
            and getattr(result, 'sender_number', None)):
        return
    if getattr(result, 'sender_number', None):
        logger.info('[emission] عددٌ مكتومٌ عن الكاتب: %r (ثقة %.2f) — حقل العدد مُسكَتٌ '
                    'حتى إعادة تدريب القارئ', result.sender_number,
                    result.sender_number_confidence or 0.0)
    result.sender_number = None
    result.sender_number_confidence = 0.0


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
        self._hw_date_locator = None   # مُموضِع «التأريخ» لقصاصة الواجهة (خيار F)

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

    def _profile_entity_matches(self, text, etype):
        """مرشّحو الجهة من مُعرّف البروفايل (كلماتٌ مميّزة + ترجيح رمز السجلّ).
        يُستدعى **بعد** ذاكرة الترويسة ليملأ فجوتها (جهةٌ جديدة بلا تاريخ)، فلا
        يزاحم ترشيحاً واثقاً. أي خطأٍ داخليّ ⟵ قائمةٌ فارغة (تدهورٌ رشيق)."""
        if not (text or '').strip():
            return []
        try:
            from core.extraction.entity_profiles import EntityResolver
            out = []
            for score, eid, name in EntityResolver.get().resolve(text, top_k=3):
                if score <= 0:
                    continue
                out.append({'entity_id': eid, 'entity_name': name,
                            'score': round(min(1.0, score) * 100, 1),
                            'match_type': 'profile'})
            return out
        except Exception as exc:
            logger.warning('[pipeline] مُعرّف البروفايل تعذّر (%s) — تدهورٌ رشيق',
                           type(exc).__name__)
            return []

    def _read_handwritten_sender_number(self, image_path, entity_id, want_date_crop=False):
        """مرحلة 3 — رقم الجهة المخربش بخط اليد حيث تعجز كل الطبقات المطبوعة:
        تموضعٌ بمرساة «العدد» وبصمة تخطيط الجهة ← قصّ الشريط ← قراءة CRNN (v5:
        94.5% على شرائط محجوزة) ← بوابة الثقة المُعايَرة.

        يعيد `(number_result, date_crop)`: `number_result` = (نص، ثقة، bbox) أو None؛
        و`date_crop` = data URL لشريط «التأريخ» اليدويّ (خيار F) أو None. القصاصةُ تركب
        نفس الرسم+TSV (بلا مسحٍ ثانٍ — فيبل16) وتُحسَب **باستقلالٍ عن ارتدادات العدد**.
        أيّ فشلٍ داخليّ يتدهور بصمت — القارئ لا يُسقط الأنبوب أبداً."""
        try:
            from core.extraction.handwriting import EntityLayoutPriors, NumberStripLocator
            from core.extraction.handwriting.reader import CONF_GATE, HandwrittenNumberReader

            if self._hw_reader is None:
                self._hw_reader = HandwrittenNumberReader()
                priors = EntityLayoutPriors(os.path.join('var', 'handwriting_layout_priors.json'))
                self._hw_locator = NumberStripLocator(priors)
                # مُموضِع «التأريخ» بلا priors: لا بصمةَ تاريخٍ لكل جهةٍ بعد (فيبل16)،
                # فمرساةُ التسمية المطبوعة وحدها تقود — ونقبل source='label' فقط.
                self._hw_date_locator = NumberStripLocator(None, field='date')
            if not self._hw_reader.available:
                return None, None

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

            # ── العدد اليدويّ (قراءة) ── لا early-return: نحسب التاريخ من نفس الرسم+TSV
            number_result = None
            num_label_floor = None    # أرضيّة قصاصة التاريخ: تسمية «العدد» (قانون المجال)
            located = self._hw_locator.locate(img, tsv, entity_id=entity_id)
            if located is not None:
                strip, _label = located
                if getattr(_label, 'source', '') != 'label':
                    # ارتداد البصمة (شريطٌ أعمى حول نقطة الجهة الوسطيّة) — مقيسٌ
                    # 2026-07-21: 80/2,958 = **2.7%** إصابة على الأشرطة المحصودة،
                    # و0 صواب من 17 قصاصة على الـ38 مقابل انبعاثٍ خاطئ واحد.
                    # يبقى متاحاً للحصاد (توليد مرشّحات) ولا يصل الحقل أبداً.
                    logger.info('[handwriting] قصاصة ارتداد البصمة — لا تُصدَر')
                else:
                    # تُراجِعٌ 2026-07-22: توصيل `printed_region_veto` هنا **قِيس فتراجَع** —
                    # البطاقة 18.1%→14.0% (حذف 12 انبعاثاً: 10 صحيحة/2 خاطئة). السبب بالعين:
                    # Tesseract **يقرأ الأرقام العربية-الهندية الواضحة** (١١٣، ٦٩) فتُنقَض قراءةٌ
                    # يدويّةٌ صحيحة. الفرضيّة «Tesseract≈0% على خطّ اليد» أضعف من أن تصمد.
                    # النقض يصيب اقتباسات المتن «رقم في تاريخ» بحقّ، لكنّ تلك دون البوّابة أصلاً —
                    # فالمكسب صفر والكلفة 10 صحيحة. الإصلاح الصحيح واعٍ بالسياق (نمط «في+تاريخ»)
                    # لا رقمين مجرّدين. `guards.printed_region_veto` يبقى مكتوباً غير موصول.
                    text, conf = self._hw_reader.read_best(strip)
                    # موضع القصّ مُطبَّعاً [x0,y0,x1,y1] — يُعاد حسابه من التسمية (حتميّ، لا
                    # يمسّ الاستخراج). ميتاداتا تدريب التوضيع: أين قصّ المُموضِع حين انبعث العدد.
                    loc = self._hw_locator
                    fy = loc.rule_above(img, _label.top) or 0
                    bx = loc.strip_bbox(_label, img.width, img.height, floor_y=fy)
                    W, H = img.width, img.height
                    bbox_norm = [round(bx[0] / W, 4), round(bx[1] / H, 4),
                                 round(bx[2] / W, 4), round(bx[3] / H, 4)]
                    if text and text.isdigit() and 1 <= len(text) <= 6 and conf >= CONF_GATE:
                        number_result = (text, conf, bbox_norm)
                    else:
                        logger.info('[handwriting] قراءة دون البوابة: %r (ثقة %.2f)', text, conf)
                    # قانون المجال (بلاغ المالك 2026-08-11): تاريخ الجهة بعد «التاريخ»
                    # **أسفل «العدد»** — لا «Date Rev» الإيزو وسط الترويسة فوقه. تسمية
                    # العدد أرضيّةٌ لبحث التاريخ (بتسامح ارتفاعِ تسميةٍ ونصف للصفّ نفسه).
                    num_label_floor = max(0, _label.top - int(1.5 * _label.height))
                del strip

            # ── صندوق الكاشف — من الملفّ الأصليّ بوصفة التدريب، مرّةً واحدة ──
            # يُحفَظ حتى حين يمتنع القارئ (عيّنات الحالات الصعبة هي ما يُعلّم؛
            # قِيس: صفٌّ واحدٌ من 12 كان يحمل صندوقاً)، ويُغذّي مرساةَ قصاصة التاريخ.
            det_box = None
            if number_result is None or want_date_crop:
                det_box = self._detector_box_from_file(image_path)

            # ── قراءة CRNN على قصاصة الكاشف حين يُخفق المُموضِع القديم ─────────
            # تفكيك e2e‑A: في 35/100 وجد الكاشفُ الصندوقَ وبقي الحقل صامتاً لأن
            # القارئ لا يصل قصاصته أصلاً — المُموضِع القديم (تسمية Tesseract) هو
            # الطريق الوحيد إليه. هنا يُفتح طريقٌ ثانٍ بنفس بوّابة الثقة تماماً:
            # لا يرتفع «واثقٌ‑ومخطئ» بالبناء، لأن العتبة والقارئ هما نفساهما.
            # ── قراءة قصاصة الكاشف — **أُعيد فتحها بأمر المالك** (2026-08-19) ──
            # التاريخ الكامل في السجلّ. أُغلقت 2026-08-18 بعد خرقين لبوّابة
            # «واثقٌ‑ومخطئ» — وكان الخرقان بحشو 0.30/0.40 وبصيغة ثقة الرموز. ثمّ
            # تغيّر الاقتصاد برافعتين **مقيستين**:
            #   · صفرُ الحشو: 51.5% ⟵ **66.5%** مطابقةً تامّة (عيّنتان مستقلّتان) —
            #     الحشو الموروث كان يُدخل رمز السجلّ فيُفسد القراءة
            #   · ثقةُ السلسلة (CTC الأماميّة): فصلُ الحذف AUROC **0.903** مقابل 0.734
            # وأمرُ المالك صريح: «لا يكون خانة العدد صامتاً — يكتب ما يقرأ، وإذا كانت
            # دقّته ضعيفةً يؤشّر». فالبوّابة هنا تسقط، والتأشير مسؤوليّة الواجهة
            # بالثقة الحقيقيّة. منحنى الدقّة/التغطية مقيسٌ (n=260، صفر حشو):
            #   >=0.95 ⟵ دقّة 93% (58% من الصفحات) · >=0.80 ⟵ 82% · الكلّ ⟵ 67%
            #   وما دون 0.80 دقّتُه ~7% — تعرضه الواجهة **أحمرَ** «يجب التصحيح يدوياً».
            if number_result is None and det_box is not None:
                bx0, by0, bx1, by1 = det_box
                pw, ph = img.width, img.height
                crop2 = img.crop((max(0, int(bx0 * pw)), max(0, int(by0 * ph)),
                                  min(pw, int(bx1 * pw)), min(ph, int(by1 * ph))))
                text2, conf2 = self._hw_reader.read_best(crop2)
                del crop2
                if text2 and text2.isdigit() and 1 <= len(text2) <= 6:
                    number_result = (text2, conf2, [round(v, 4) for v in det_box])
                    logger.info('[handwriting] قراءةٌ من قصاصة الكاشف (صفر حشو): %r '
                                '(ثقة %.3f)', text2, conf2)

            # ── قصاصة «التأريخ»: تُقرأ وتُعرض من **الصورة نفسها** ────────────
            # حين يوجد صندوقُ كاشفٍ نقصّ بهندسة `x` (هندسةُ تدريب القارئ، وبوّابةُ
            # عينٍ n=100: حبرٌ ظاهر 96%) فنقرأها ونعرضها معاً — لئلّا يُصادق الكاتبُ
            # على صورةٍ غيرِ التي قرأها النموذج. وحين يصمت الكاشف (~35% من الصفحات
            # مقيسةً في e2e-C) يبقى مسارُ التسمية القديم **عرضاً فقط بلا اقتراح**:
            # توزيعُه لم يُقَس، وإطعامُ القارئ قصاصةً غريبةً يكسر عقد «توزيعٌ واحد».
            date_crop, date_suggestion = None, None
            if want_date_crop:
                if det_box is not None:
                    from core.extraction.handwriting.date_geometry import (
                        GEOMETRY_TAG, crop_below_box)
                    dcrop = crop_below_box(img, det_box)
                    if dcrop is not None:
                        date_crop = self._to_data_url(dcrop)
                        date_suggestion = self._suggest_date(dcrop, det_box, GEOMETRY_TAG)
                        del dcrop
                if date_crop is None:
                    date_crop = self._crop_date_strip(img, tsv, min_top=num_label_floor,
                                                      det_box=det_box)

            W, H = img.width, img.height
            del tsv, img
            return number_result, date_crop, date_suggestion, (det_box, W, H)
        except Exception as exc:
            logger.warning('[handwriting] فشل مسار خط اليد: %s — تدهور رشيق',
                           type(exc).__name__)
            return None, None, None, (None, 0, 0)

    def _suggest_date(self, crop, det_box, geometry_tag):
        """اقتراحُ تاريخٍ من قصاصة `x` — **لا يُكتب في الحقل أبداً**.

        يُعاد قاموسٌ بمفتاحٍ منفصل (`sender_date_suggestion`) لا في `sender_date`:
        مسارات ملء الواجهة تكتب `sender_date` في الحقل صامتاً
        (`extraction_smart.js:832`)، فوضعُ قراءةٍ بدقّة 71% هناك = إعادةُ بناء
        جذر تسميم التواريخ الذي اجتُثّ. والفصلُ يعزل أيضاً سُلَّمَي ثقةٍ غير
        متقارنين: ثقةُ المطبوع مجدولةٌ يدويّاً، وهذه معايَرةٌ بـH6.

        `iso` قد يكون None مع `parse` = invalid/ambiguous — وذاك امتناعٌ مقصود:
        القصاصةُ معروضةٌ والكاتب يحسم، ولا تخمينَ باحتمالٍ غالب.
        """
        try:
            from core.extraction.handwriting.date_parse import parse_drawn_date
            from core.extraction.handwriting.date_reader import (
                DATE_CONF_GREEN, get_date_reader)
            rd = get_date_reader()
            if not rd.available:
                return None
            raw, conf = rd.read(crop.convert('L'))
            if not raw:
                return None
            iso, status = parse_drawn_date(raw, entry_date=timezone.localdate())
            logger.info('[handwriting] اقتراح تاريخ: %r ⟵ %s (ثقة %.3f · %s)',
                        raw, iso or '—', conf, status)
            return {
                'raw': raw,
                'iso': iso,
                'parse': status,
                'confidence': round(float(conf), 4),
                'green_threshold': DATE_CONF_GREEN,
                'bbox': [round(float(v), 4) for v in det_box],
                'geometry': geometry_tag,
                'source': 'crnn_d2',
            }
        except Exception as exc:
            logger.warning('[handwriting] اقتراح التاريخ تعذّر: %s', type(exc).__name__)
            return None

    @staticmethod
    def _number_label_floor(tsv):
        """أرضيّةُ بحثِ التاريخ = صفُّ تسمية «العدد» في TSV (بلا قراءةٍ ولا قصّ).

        بلاغ المالك (2026-08-11، مُكرَّر): القصاصة كانت تلتقط **تاريخ اعتماد نموذج
        الإيزو** («Date Rev» وسط ترويسة نظام الإدارة المتكامل)، بينما تاريخ الجهة —
        وبنسبةٍ عالية في المذكّرات الداخليّة — يقع **تحت العدد بعد كلمة «التاريخ»**.
        الأرضيّةُ الأولى تُشتقّ من مسار العدد، لكنّه يصمت في ~42% من الصفحات؛ فهنا
        نشتقّها مباشرةً من TSV كي لا تبقى ثغرةٌ يتسلّل منها تاريخ الترويسة. تُعاد
        None إن لم تُقرأ تسمية «العدد» إطلاقاً (فلا نخنق الحالات المشروعة)."""
        try:
            from core.extraction.handwriting.localize import _LABEL_RES, _norm_label
            num_re = _LABEL_RES['number']
            tops = [tsv['top'][i] for i, raw in enumerate(tsv.get('text', []))
                    if _norm_label(raw) and num_re.search(_norm_label(raw))]
            if not tops:
                return None
            page_h = max(tsv.get('top') or [0]) or 0
            top = min(tops)
            # حارسٌ مقيسٌ بالعين (2026-08-11): «العدد» يردُ في اقتباسات المتن أيضاً.
            # أرضيّةٌ مشتقّةٌ من اقتباسٍ منخفض **تخنق حقلَ التاريخ الحقيقيّ فوقه**
            # (#11287/11253/11254: الحقل y=625 والاقتباس y=1018). فلا نثق بالأرضيّة
            # إلا إن جاءت من ترويسةٍ حقيقيّة — أعلى ~45% من ارتفاع المحتوى.
            if page_h and top > 0.45 * page_h:
                return None
            heights = [h for h in tsv.get('height', []) if h] or [30]
            return max(0, top - int(1.5 * (sum(heights) / len(heights))))
        except Exception:
            return None

    _last_detector_arm = 'det2'   # يُحدَّث في `_detector_box_from_file`

    @staticmethod
    def _detector_box_from_file(image_path):
        """صندوق «العدد» من **الملفّ الأصليّ** مرسوماً بوصفة التدريب حرفيّاً (175dpi، RGB).

        الجذر المقيس لفجوة e2e‑A (45/100 بلا صندوق): الأنبوب كان يُغذّي الكاشف صورته
        الرماديّة (`csGRAY` عند 300dpi) بينما دُرِّب على رسمٍ خام RGB — حبرُ القلم
        الأزرق يفقد تباينه رماديّاً. A/B على 12 صفحةً صامتة (2026-08-18): الرسم الخام
        يُطلق **10/12** والرماديّ **0/12**. الرسمُ هنا جزءٌ من عقد الهندسة كالقصّ سواء:
        يجري داخل الوحدة كي لا يستطيع مُستدعٍ أن يخطئ في تكراره."""
        try:
            from core.extraction.handwriting.detector import detect_number_box
            from PIL import Image as PILImage
            if image_path.lower().endswith('.pdf'):
                import fitz
                doc = fitz.open(image_path)
                page = doc[0]
                zoom = 175 / 72.0
                longer = max(page.rect.width, page.rect.height) * zoom
                if longer > 3500:
                    zoom *= 3500 / longer
                pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
                im = PILImage.frombytes('RGB', (pix.width, pix.height), pix.samples)
                doc.close()
                del pix
            else:
                im = PILImage.open(image_path).convert('RGB')
            got = detect_number_box(im)
            arm = 'det2'
            if not got:
                # **S1**: حين يصمت det2 يُجرَّب det1 احتياطيّاً. لا يعمل إلّا على
                # صفحةٍ كانت ستبقى صامتة، فأسوأُ حالاته صندوقٌ زائفٌ ⟵ قراءةٌ دون
                # بوّابة الثقة لا تمسّ حارس «واثقٌ‑ومخطئ».
                from core.extraction.handwriting.detector import detect_number_box_fallback
                got = detect_number_box_fallback(im)
                arm = 'det1' if got else 'none'
            del im
            if not got:
                return None
            box, _conf = got
            # ذراعُ المصدر يُنشر مع الصندوق — بدونه يتسمّم الحصادُ القادم
            # بهندساتٍ مختلطة (درسُ recrop المدفوعُ ثمنُه مرّةً).
            AIExtractionService._last_detector_arm = arm
            # نفس حارس الارتفاع: صندوقٌ منخفض اقتباسُ متنٍ يخنق حقلَ التاريخ فوقه
            return box if box[1] <= 0.45 else None
        except Exception as exc:
            logger.warning('[handwriting] كاشفٌ من الملفّ تعذّر: %s', type(exc).__name__)
            return None

    @staticmethod
    def _detector_box(img):
        """صندوق «العدد» من الكاشف — `[x0,y0,x1,y1]` مُطبَّعاً على الصفحة أو None."""
        try:
            from core.extraction.handwriting.detector import detect_number_box
            got = detect_number_box(img)
            if not got:
                return None
            box, _conf = got
            # نفس حارس `_number_label_floor`: مرساةٌ منخفضةٌ تخنق حقلَ التاريخ فوقها.
            return box if box[1] <= 0.45 else None
        except Exception as exc:
            logger.warning('[handwriting] الكاشف تعذّر: %s', type(exc).__name__)
            return None

    @staticmethod
    def _to_data_url(crop, max_w=760):
        """قصاصةُ PIL ⟵ data URL للعرض. التصغيرُ للعرض فقط، بعد القراءة دائماً."""
        try:
            import base64
            import io
            if crop.width > max_w:
                r = max_w / crop.width
                crop = crop.resize((max_w, max(1, int(crop.height * r))))
            buf = io.BytesIO()
            crop.save(buf, format='PNG', optimize=True)
            return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode('ascii')
        except Exception as exc:
            logger.warning('[handwriting] ترميز القصاصة تعذّر: %s', type(exc).__name__)
            return None

    @staticmethod
    def _crop_below_box(img, box):
        """قصاصةُ التاريخ **مرساةً بصندوق العدد** — بالهندسة المعتمدة `x`.

        قانون المالك: التاريخ يقع تحت العدد مباشرةً. المسار القديم يحتاج Tesseract أن
        يقرأ كلمة «التاريخ» كي يُموضِع — وهو يفشل في صفحاتٍ كثيرة فلا تظهر قصاصةٌ
        إطلاقاً. الصندوق يتجاوز القراءة.

        الهندسةُ تُستورد من `date_geometry` ولا تُنسَخ هنا: هي بعينها التي دُرِّب
        عليها قارئ التاريخ، وهي بعينها التي يقصّها الحصاد. ونصُّ «الإفراط مجّانيّ
        لأن العرض بشريّ» سقط لحظةَ صارت القصاصةُ مقروءةً آليّاً ومعروضةً للتصديق:
        الكاتب يجب أن يرى **الصورة نفسها التي قرأها النموذج**.
        """
        from core.extraction.handwriting.date_geometry import crop_below_box
        crop = crop_below_box(img, box)
        return AIExtractionService._to_data_url(crop) if crop is not None else None

    @staticmethod
    def _detector_floor_from_box(box, img):
        """أرضيّةُ بحثِ التاريخ من **صندوق الكاشف** — تُستعمل فقط حين يصمت مسار TSV.

        بلاغ المالك: القصاصة تلتقط تاريخ اعتماد نموذج الإيزو («Date Rev» وسط ترويسة
        نظام الإدارة المتكامل) بدل تاريخ الجهة الواقع **تحت العدد**. الأرضيّة تمنع ذلك،
        لكنّها كانت مشتقّةً من تسمية «العدد» التي يقرأها Tesseract — وهي **تصمت في
        ~42% من الصفحات** (موثَّقٌ في `_number_label_floor`)، فتبقى ثغرةٌ يتسلّل منها
        تاريخ الترويسة. الكاشف يُطلق على 164/165 (99.4%) بمركزٍ صحيحٍ 96%، فيسدّها.

        **لا يُزيح المسار القائم** (قرار فيبل 2026-08-17): تسمية TSV تبقى الحَكَم حين
        تُقرأ — سلوكٌ متحقَّقٌ منه — والكاشف يملأ صمتها فقط. أضيق تدخّلٍ وأقلّ سطحِ تراجع.
        """
        try:
            if not box:
                return None
            H = img.height
            top_px = box[1] * H
            # تسامحٌ بارتفاع الصندوق تقريباً فوقه: التاريخ قد يشترك مع العدد في صفٍّ
            # واحد (ترويسة اللجان المشتركة: «العدد:» يميناً و«التاريخ:» تحته مباشرة).
            return max(0, int(top_px - 0.8 * (box[3] - box[1]) * H))
        except Exception as exc:
            logger.warning('[handwriting] أرضيّة الكاشف تعذّرت: %s', type(exc).__name__)
            return None

    def _crop_date_strip(self, img, tsv, min_top=None, det_box=None):
        """قصاصةُ شريط «التأريخ» اليدويّ للعرض في الواجهة (خيار F) — لا قراءة، الكاتب
        ينسخها. **هندسةٌ فضفاضةٌ متناظرة عمداً**: تمركزٌ حول التسمية وامتدادٌ للجهتين
        (القيمة العربيّة يساراً والإنجليزيّة يميناً) + حشوٌ رأسيّ سخيّ — الإفراطُ في
        القصّ مجّانيٌّ (بشريُّ العرض) والتقصيرُ وحده يُفقِد القيمة (فيبل16). لا نُعيد
        استعمال صندوق القارئ الضيّق. يُعيد data URL (PNG رماديّ) أو None."""
        try:
            if min_top is None:
                min_top = self._number_label_floor(tsv)
            if min_top is None:
                min_top = self._detector_floor_from_box(det_box, img)
            located = self._hw_date_locator.locate(img, tsv, entity_id=None,
                                                   min_top=min_top)
            if located is None or getattr(located[1], 'source', '') != 'label':
                # لا تسمية «التاريخ» مقروءة ⟵ **المرساة هي صندوق العدد نفسه**.
                # قانون المالك: «التاريخ دائماً تحت العدد». قِيس (2026-08-18) أنّ
                # الأرضيّة وحدها لا تُنتج قصاصةً هنا: هي تُرتّب مرشّحي المُموضِع ولا
                # تخلقهم، وعلى هذه الصفحات لا يقرأ Tesseract «التاريخ» إطلاقاً.
                # القصّ تحت الصندوق يتجاوز القراءة كلّها.
                return self._crop_below_box(img, det_box)
            _strip, label = located
            import base64
            import io
            W, H = img.width, img.height
            lw = max(label.width, 40)
            x0 = max(0, label.left - int(6.5 * lw))
            x1 = min(W, label.left + label.width + int(6.5 * lw))
            pad = int(1.2 * label.height)
            y0 = max(0, label.top - pad)
            y1 = min(H, label.top + label.height + pad)
            crop = img.crop((x0, y0, x1, y1))
            if crop.width > 760:                  # رفيعٌ ورخيص (~بضعة KB)
                r = 760 / crop.width
                crop = crop.resize((760, max(1, int(crop.height * r))))
            buf = io.BytesIO()
            crop.save(buf, format='PNG', optimize=True)
            return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode('ascii')
        except Exception as exc:
            logger.warning('[handwriting] قصاصة التاريخ تعذّرت: %s', type(exc).__name__)
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
        on_progress: Optional[Callable[[str, Dict[str, Any]], None]] = None,
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
        on_progress: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> AIExtractionResult:
        """المعالجة الداخلية — تُستدعى داخل thread منفصل."""

        def _progress(stage: str) -> None:
            """يُعلن المرحلة التالية ويُمرّر لقطة الحقول المستخرَجة **حتى الآن**.

            المراحل تُعلَن قبل تنفيذها، فاللقطة تعكس ما اكتمل فعلاً (مثلاً عند إعلان
            entity_matching تكون حقول pattern_matching جاهزة) — وهذا ما يتيح للواجهة
            ملء الحقول تدريجياً برسائل صادقة بدل انتظار الحصيلة كاملةً.
            """
            if not on_progress:
                return
            try:
                on_progress(stage, partial_scan_data(result))
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
                # **منشأُ القيمة** — يفصل كاتبَ مرساة الرأس (المفتوحُ في S4) عن
                # بقيّة الكُتّاب النصّيّين (احتياطُ ref_num والبصمات) الذين يبقون
                # مكتومين. الوسمُ هنا عند الكتابة لا عند العرض، فلا يلتبس مصدران.
                if result.sender_number:
                    result.sender_number_source = 'printed_anchor'
                result.title = patterns.get('title') or ''
                # ثقةٌ صادقةٌ بحسب المسار (فيبل 2026-08-17): كانت تبقى 0.0 دائماً فتُظهر
                # الواجهة 0% لكلّ عنوان — بما فيه مسار العلامة المقيس 64% صالحاً.
                result.title_confidence = float(patterns.get('title_confidence') or 0.0)
                # جهاتٌ (Slb) تضع رقم صادرها داخل سطر الموضوع («Ref-135, Akkas…») —
                # نقتطعه رقماً وننظّف العنوان (16 كتاباً محفوظاً تُثبت النمط).
                if result.title:
                    ref_num, clean_title = self.pattern_matcher.split_ref_from_title(result.title)
                    if ref_num:
                        result.title = clean_title
                        if not result.sender_number:
                            result.sender_number = ref_num
                            result.sender_number_confidence = 0.65
                # ── «النصُّ يسبق البصريّ» (أمر المالك 2026-08-30) ───────────────
                # مطابقةٌ صارمةٌ على **طبقة النصّ الخامّة** لا على `probe`: بنيةُ
                # السطور هي الدليل (`clean_text` تطوي `\n` فتُلغي كلَّ الطبقات).
                # المقاس على e2e-E (34 حقيقةً محكَّمةً بالعين): الصارمُ 32 إصابةً
                # وصفرَ خطأٍ بـ0.094 ث، مقابل البصريّ 11 إصابةً وخطأين بـ3.92 ث.
                # وعلى e2e-D المختومة يُطلق **مرّةً واحدةً صحيحة** — حارسُ التعميم.
                # الثقةُ 0.85: عاليةٌ لأنّها مقيسة، ودون عتبة «الواثق» (0.90)
                # بنائيّاً لأنّ الأدلّة كلَّها من مجموعةِ تطويرٍ حتّى تُبنى e2e-F.
                if pdf_text:
                    _strict_raw = strict_ref_match(pdf_text)
                    _strict_val = canonical_sender_number(_strict_raw) if _strict_raw else ''
                    if _strict_val:
                        if result.sender_number and result.sender_number != _strict_val:
                            logger.info('[strict_ref] أزاح %r ⟵ %r (مطبوعٌ خامّ %r)',
                                        result.sender_number, _strict_val, _strict_raw)
                        result.sender_number = _strict_val
                        result.sender_number_confidence = 0.85
                        result.sender_number_source = 'strict_ref'
                        # المرجعُ المطبوع كاملاً أثراً (`NK-20260233`). لا يُمرَّر إلى
                        # `result_to_scan_data`: كلُّ مفتاحٍ هناك عقدٌ في
                        # `capture_schema` وحرزُه يفشل صاخباً — ولا حاجةَ قِيست بعد.
                        result.sender_number_printed_ref = _strict_raw
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
                  1) ذاكرة الترويسة (تعلّمٌ من مستندات سابقة مؤكَّدة) — **الأقوى**،
                  2) مطابقة اسم الجهة في الترويسة،
                  3) أنماط «من/إلى X» — الأضعف.
                الأرقام القديمة هنا (85%/18-27%/0-3%) كانت **مُسرَّبة**: قِيست بترك-واحد
                على كتبٍ لها صفٌّ في LetterheadMemory، فتعرّف المستند على ترويسة نفسه
                بتشابه 1.0. الصادق (2026-08-17، `exclude_book_id`): **top-1 60% ·
                top-3 73%** على 30 نصّاً، و**49.0%** على 1000 استعلامٍ مُجمَّد.
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
                _plan = entity_source_plan(etype, str(getattr(result, 'book_kind', '') or ''),
                                           bool(getattr(result, 'recipient_text', '')))
                if 'recipient_line_first' in _plan:
                    _extend(lambda: self.entity_matcher.match_entity(
                        result.recipient_text, entity_type='receiver')[:3], 'recipient_line')
                _extend(lambda: self.entity_matcher.match_from_memory(cleaned, entity_type=etype, top_k=3),
                        'memory')
                if 'recipient_line_after_memory' in _plan:
                    _extend(lambda: self.entity_matcher.match_entity(
                        result.recipient_text, entity_type='receiver')[:3], 'recipient_line')
                # مُعرّف البروفايل: كلماتٌ مميّزة من اسم الجهة + ترجيحُ رمز السجلّ، على
                # **المنطقة الصحيحة بحسب الاتجاه** (المُصدِرة من الترويسة، المُخاطَب من
                # سطر «الى/») — قانون المالك: «الوارد ليس كالصادر». يأتي **بعد** الذاكرة
                # فلا يزاحم ترشيحها الواثق، ويملأ ما تعجز عنه: جهةٌ جديدة أو أوّل كتابٍ
                # منها لا ذاكرةَ لها. مقيس على 80 (نصّ مخزَّن): دمجُه مع الذاكرة أنقذ 2
                # وأفسد 0 (top-1 55→57، top-3 63→66)؛ وحده 23%.
                _extend(lambda: self._profile_entity_matches(
                    (getattr(result, 'recipient_text', '') if etype == 'receiver' else cleaned), etype),
                    'profile')
                if len(ranked) < 3 and 'letterhead' in _plan:
                    _extend(lambda: self.entity_matcher.match_from_letterhead(cleaned, entity_type=etype, top_k=3),
                            'letterhead')
                pattern_match = (self.entity_matcher.match_issuing_entity if etype == 'issuer'
                                 else self.entity_matcher.match_receiving_entity)
                for entity_text in entity_candidates:
                    _extend(lambda: pattern_match(entity_text), 'patterns')
                    if len(ranked) > 3:
                        break
                if etype == 'issuer':
                    ranked = prefer_jmc_committee(ranked, cleaned)
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
                #   بروفايل (top-1 ≈ 23% وحده) → 0.45 — اقتراحٌ يملأ فجوة الذاكرة لا يحسم.
                cap = {'memory': 0.85, 'letterhead': 0.5, 'profile': 0.45}.get(best.get('match_type'))
                setattr(result, conf_attr, min(score, cap) if cap else score)

            _assign_entity(_resolve_entity('issuer'), 'issuing_entity_id',
                           'issuing_entity_name', 'issuing_entity_confidence', 'issuing_entity_matches')
            _assign_entity(_resolve_entity('receiver'), 'receiving_entity_id',
                           'receiving_entity_name', 'receiving_entity_confidence', 'receiving_entity_matches')

            # نوع الوثيقة — prior الجهة: القاعدة العامّة تصمت غالباً (مقيس 2% فقط على
            # 38 كتاباً)، بينما لكل جهةٍ نوعٌ مهيمنٌ في كتبها المؤكَّدة («مذكرة داخلية»
            # للأقسام، «اعمام»…). يُطبَّق **فقط حين تصمت القاعدة** فلا يزاحمها أبداً
            # (استحالة تراجعٍ بنيويّة)، وبثقةٍ منخفضة لأنه ترجيحٌ إحصائيّ لا قراءةٌ من
            # المستند. مقيس: 2% ⟵ ~36% (يغطّي 21/36، يصيب 61% منها).
            if not (getattr(result, 'document_type', '') or '').strip() \
                    and getattr(result, 'issuing_entity_id', None):
                try:
                    from core.extraction.entity_profiles import EntityProfileStore
                    prior = EntityProfileStore.get().doc_type_prior(result.issuing_entity_id)
                    if prior:
                        result.document_type = prior
                        result.document_type_confidence = 0.40
                except Exception as exc:
                    logger.warning('[pipeline] prior نوع الوثيقة تعذّر (%s) — تدهورٌ رشيق',
                                   type(exc).__name__)

            # بصمة الجهة: بعد معرفة المُرسِل، ابحث عن رقمٍ بقالب أرقامه المُتعلَّم من
            # كتبه المؤكَّدة — يلتقط ما فاتته العلامات العامة ويُصحّح الالتقاط الناقص
            # (مثل «195» بدل «MF-2026-195»).
            if getattr(result, 'issuing_entity_id', None) and result.cleaned_text:
                hit = self.number_profiles.find(result.cleaned_text, result.issuing_entity_id)
                _strict_held = getattr(result, 'sender_number_source', '') == 'strict_ref'
                if hit and hit.value != (result.sender_number or '') and not _strict_held:
                    if not result.sender_number or hit.confidence >= (result.sender_number_confidence or 0.0):
                        logger.info('[profile] sender_number %r → %r (قالب %s)',
                                    result.sender_number, hit.value, hit.template)
                        result.sender_number = hit.value
                        result.sender_number_confidence = hit.confidence
                        # **تسريبٌ مقيسٌ أُغلق**: كان `sender_number_source` يُكتب
                        # مرّةً واحدةً عند كاتب مرساة الرأس ولا يُحدَّث — فقيمةُ
                        # البصمة هذه ترث وسمَ `printed_anchor` **فتنجو من الكتم
                        # بوسمٍ ليس لها** (شوهد في e2e-E: قيمةٌ بثقة 0.85 وصلت
                        # المخرَجَ عبر هذا المسار). الوسمُ الآن عند كلّ كتابة.
                        result.sender_number_source = 'entity_profile'
                # إصلاح بادئة شوّهها OCR (llK-20260257 → NK-20260257) ببادئات
                # الجهة المؤكَّدة نفسها — معيار الجهات الخمس، كتاب 11237.
                if result.sender_number:
                    repaired = self.number_profiles.repair(result.sender_number,
                                                           result.issuing_entity_id)
                    if repaired:
                        logger.info('[profile] إصلاح بادئة: %r → %r',
                                    result.sender_number, repaired)
                        result.sender_number = repaired
                        result.sender_number_source = 'entity_profile'

            # Step 5.5: رقم الجهة المخربش بخط اليد — الملاذ الأخير حين تصمت كل
            # الطبقات المطبوعة (قياس الأرشيف: أغلبية الأرقام يدوية، Tesseract ≈ 0%
            # عليها). يعمل في مسارَي OCR والكاش كليهما (يحتاج ملف الصورة فقط).
            # ويركب نفسَ الرسم+TSV قصاصةُ «التأريخ» اليدويّ للواجهة (خيار F) حين خلا
            # تاريخُ الجهة من الطبقات المطبوعة — بلا مسحٍ ثانٍ (فيبل16).
            if (result.image_path and not _sender_number_survives_emission(result)
                    and not _strict_ref_skips_visual(result)):
                _progress('handwritten_number')
                want_crop = not result.sender_date
                (num_res, date_crop, date_suggestion,
                 (det_box, _pw, _ph)) = self._read_handwritten_sender_number(
                    result.image_path, getattr(result, 'issuing_entity_id', None),
                    want_date_crop=want_crop)
                # المرجعُ المطبوعُ الصارم **لا يُزاح**: قِيس 32/32 على صفّه مقابل
                # 11 إصابةً وخطأين للبصريّ على نفس المستندات. والنداءُ هنا لم
                # يُتخطَّ إلّا لأنّ التاريخ صامتٌ ونحتاج قصاصتَه — فيُؤخذ التاريخُ
                # ويُترك العدد، ويُسجَّل الخلافُ مادّةً للدراسة.
                _strict_holds = getattr(result, 'sender_number_source', '') == 'strict_ref'
                if num_res and _strict_holds:
                    if num_res[0] and num_res[0] != result.sender_number:
                        logger.info('[strict_ref] خلافٌ مع البصريّ: نصّيّ %r · بصريّ '
                                    '%r (ثقة %.2f) — النصّيُّ يبقى',
                                    result.sender_number, num_res[0], num_res[1] or 0.0)
                    num_res = None
                if num_res:
                    _displaced = getattr(result, 'sender_number', None)
                    result.sender_number, result.sender_number_confidence, result.sender_number_bbox = num_res
                    result.sender_number_bbox_source = 'crnn'
                    if _displaced:
                        logger.info('[handwriting] البصريُّ أزاح قيمةً نصّيّةً مكتومة: '
                                    '%r ⟵ %r', _displaced, result.sender_number)
                    logger.info('[handwriting] رقم الجهة من خط اليد: %r (ثقة %.2f)',
                                result.sender_number, result.sender_number_confidence)
                elif det_box:
                    # لا قراءة، لكنّ الموضع معروف ⟵ عيّنةُ تدريبٍ **للحالة الصعبة**
                    result.sender_number_bbox = [round(v, 4) for v in det_box]
                    result.sender_number_bbox_source = 'detector'
                if _pw and _ph:
                    # مقاسٌ مرجعيٌّ صريح: الصندوق مُطبَّعٌ عليه. بدونه لا يستطيع
                    # مستهلكٌ لاحق إعادة بناء البكسلات — وذاك فخّ 1600/2600/3500.
                    result.sender_number_bbox_dims = [_pw, _ph]
                if date_crop:
                    result.sender_date_crop = date_crop
                    logger.info('[handwriting] قصاصة تاريخ الجهة للواجهة (خيار F)')
                if date_suggestion:
                    # مفتاحٌ منفصل عمداً — انظر `_suggest_date`. ولا يدخل
                    # `field_confidences` أدناه: ثقةُ اقتراحٍ منخفضة كانت ستجرّ
                    # `overall_confidence` فتقلب كتباً إلى manual_review صامتاً.
                    result.sender_date_suggestion = date_suggestion

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

            # Step 7.9: **إسكاتُ إصدار حقل العدد** — نقطةٌ واحدةٌ بعد كلّ الكُتّاب
            _suppress_sender_number_emission(result)

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


def partial_scan_data(result: 'AIExtractionResult') -> Dict[str, Any]:
    """لقطة الحقول المكتملة حتى اللحظة (غير الفارغة فقط) — وقود البثّ التدريجي.

    نُرسل ما اكتمل فقط كي تملأ الواجهة حقلاً حقلاً بلا أن تمسح قيمةً لم تُستخرَج بعد
    (الحقول الفارغة تُحذف من اللقطة بدل إرسالها فارغة).
    """
    snap: Dict[str, Any] = {}
    for field, conf in (
        ('book_number', 'book_number_confidence'),
        ('book_date', 'book_date_confidence'),
        ('sender_date', 'sender_date_confidence'),
        ('sender_number', 'sender_number_confidence'),
        ('title', 'title_confidence'),
        ('secret_level', 'secret_level_confidence'),
        ('book_kind', 'book_kind_confidence'),
    ):
        value = getattr(result, field, None)
        if value not in (None, '', []):
            snap[field] = value
            snap[conf] = getattr(result, conf, 0.0)
    if getattr(result, 'document_type', ''):
        snap['document_type'] = result.document_type
    if getattr(result, 'issuing_entity_name', ''):
        snap['issuing_entity'] = result.issuing_entity_name
        snap['issuing_entity_confidence'] = result.issuing_entity_confidence
        snap['issuing_entity_matches'] = slim_entity_matches(result.issuing_entity_matches)
    if getattr(result, 'receiving_entity_name', ''):
        snap['receiving_entity'] = result.receiving_entity_name
        snap['receiving_entity_confidence'] = result.receiving_entity_confidence
        snap['receiving_entity_matches'] = slim_entity_matches(result.receiving_entity_matches)
    return snap


_JMC_RE = re.compile(r'لجنة\s*الاداره?|لجنة\s*الإدارة|joint\s*management', re.I)


def prefer_jmc_committee(ranked: list, text: str) -> list:
    """عُرف المالك (2026-08-16): في كتب **اللجان المشتركة** الجهةُ المُصدِرة هي
    **اللجنة** لا الشركة المُشغِّلة — ونماذج JMC تحمل شعار المُشغِّل واسمَ اللجنة معاً،
    فيتصدّر اسمُ الشركة أحياناً (#8720: «NK Petroleum» بدل «لجنة الادارة المشتركة
    لرقعة…»).

    **إعادةُ ترتيبٍ لا إقصاء**: تُطلق فقط حين تحمل الترويسة «لجنة الإدارة المشتركة»
    ويكون المتصدّر غيرَ لجنةٍ ويوجد مرشّحُ لجنةٍ في القائمة — فلا تخسر شيئاً حين لا
    يوجد بديل. مقيسٌ على 30 نصّاً حقيقيّاً: 73% → **77%**، أُطلقت مرّةً واحدة وأصابت،
    وصفر تراجع. والقاعدة تسند العُرف: 1,476 صفّ ذاكرةٍ ترويستها JMC، **73%** منها
    سجّل الكاتب لجنةً (والـ27% الباقية أقسامٌ داخليّة لنا — حالةٌ أخرى لا مخالفة)."""
    if not ranked or not _JMC_RE.search(text or ''):
        return ranked
    top_name = (ranked[0].get('entity_name') or '') if isinstance(ranked[0], dict) else ''
    if _JMC_RE.search(top_name):
        return ranked
    for i, m in enumerate(ranked[1:], start=1):
        if _JMC_RE.search((m.get('entity_name') or '') if isinstance(m, dict) else ''):
            return [ranked[i]] + ranked[:i] + ranked[i + 1:]
    return ranked


def entity_source_plan(etype: str, kind: str, has_recipient: bool) -> set:
    """أيّ مصادر الجهات تُستعمَل ولأيّ ترتيب — **بحسب اتّجاه الكتاب** (فيبل 2026-08-16).

    قِيس على 30 نصّاً حقيقيّاً: الجهة المستلِمة **0/30**. الجذر ليس المطابقة بل
    **تأطير المهمّة**: في الوارد لا تُذكر جهتُنا المستلِمة في الكتاب أصلاً — سطر «الى/»
    يحمل المُخاطَب داخل جهة المُرسِل، بينما الكاتب يسجّل **وجهة التوجيه عندنا**
    (9,360 كتاباً: 45 قيمة فقط، السائدة 64.9%). وذاكرة الترويسة تخزّن هذا التوجيه
    أصلاً، لكنّ «الى/» كان يتصدّرها فيُفسدها. LOO على 300 صفّ ذاكرة: أساسٌ ثابت 51.3%
    مقابل ذاكرة **58.7%** (+7.4 — تجاوز بوّابة فيبل +5).

    القواعد: الصادر لا يُمسّ («الى/» هو المُخاطَب الحقيقيّ فيتصدّر) · الوارد الداخليّ
    يقدّم الذاكرة ثم «الى/» · الوارد الخارجيّ يُسقط «الى/» · والترويسة (اسمُ المُرسِل
    دائماً) تُمنع عن حقل المستلِمة في الوارد — وهو جذر خلط الاتّجاه في #11298."""
    incoming = str(kind or '').startswith('incoming')
    plan = {'memory', 'profile', 'patterns'}
    if etype == 'receiver':
        if has_recipient and kind != 'incoming_external':
            plan.add('recipient_line_after_memory' if incoming else 'recipient_line_first')
        if not incoming:
            plan.add('letterhead')
    else:
        plan.add('letterhead')
    return plan


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
        'sender_date_crop': result.sender_date_crop,   # قصاصة «التأريخ» اليدويّ للواجهة (خيار F) — عابرةٌ في الاستجابة فقط
        # اقتراحُ القارئ منفصلاً عن `sender_date` — الواجهةُ القديمة تتجاهله
        # بالبناء، فالنشرُ آمنٌ قبل توصيلها.
        'sender_date_suggestion': getattr(result, 'sender_date_suggestion', None),
        'sender_number': result.sender_number,
        'sender_number_confidence': result.sender_number_confidence,
        'sender_number_bbox': result.sender_number_bbox,   # موضع القصّ لالتقاط تدريب التوضيع
        'sender_number_bbox_source': getattr(result, 'sender_number_bbox_source', ''),
        'sender_number_bbox_dims': getattr(result, 'sender_number_bbox_dims', None),
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
