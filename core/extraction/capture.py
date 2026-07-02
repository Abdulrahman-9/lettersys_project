# -*- coding: utf-8 -*-
"""
core.extraction.capture
========================
حلقة التقاط بيانات التدريب: تحفظ زوج (نصّ OCR → الحقول المؤكَّدة) + تصحيحات
المستخدم عند حفظ كتاب ممسوح، لتغذية نماذج التعلّم المستقبلية (نوع/عنوان/جهة/أرقام).

مبدأ السلامة الأعلى: **لا يرفع استثناءً أبداً** — فشل الالتقاط لا يُفشل حفظ الكتاب.
"""
import logging

from django.utils import timezone
from django.utils.dateparse import parse_date

from core.models import OCRResult, DataExtractionResult, ExtractionFeedback, LetterheadMemory

logger = logging.getLogger('lettersys')


def _persist_letterhead_memory(book, text):
    """يخزّن (ترويسة المستند → الجهة المؤكَّدة) لتحسين اقتراح الجهة مستقبلاً.

    هذا جوهر التعلّم من الداتا بيس: كلّ كتاب محفوظ يعلّم النظام ربط ترويسة المُرسِل
    بالجهة التي أسندها المستخدم — فيكسر سقف الوحدات الداخلية غير المطبوعة على الورق."""
    from core.extraction.matchers.entity import letterhead_region
    head = letterhead_region(text)
    if not head or LetterheadMemory.objects.filter(book=book).exists():
        return   # لا نصّ، أو ذاكرة هذا الكتاب موجودة (لا نكرّر عند إعادة الحفظ)
    issuing = book.issuing_entities.first()
    receiving = book.receiving_entities.first()
    if issuing or receiving:
        LetterheadMemory.objects.create(
            letterhead=head, issuing_entity=issuing, receiving_entity=receiving, book=book)

# الحقول المتتبَّعة للتصحيح: (مفتاح اقتراح OCR ، مفتاح القيمة النهائية المحفوظة).
# نقتصر على الحقول **متطابقة التمثيل** فقط لإشارة تصحيح نظيفة:
#   - book_number ↔ our_number و book_kind ↔ kind مستبعدان: النظام يُعيد تنسيق
#     الرقم ويُفصّل النوع (incoming→incoming_internal) فتختلف الصيغة دائماً = ضوضاء.
#   - التاريخ مستبعد: فرق صيغة ISO/Date يعطي إيجابيات كاذبة.
# كل الاقتراحات (رقم/نوع/تاريخ) تبقى مخزَّنة في DataExtractionResult للسجل والتحليل.
_FIELD_MAP = (
    ('title',        'title'),
    ('secret_level', 'secret_level'),
)


def _to_float(v):
    try:
        return float(v or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _norm_secret(v):
    """secret_level في DataExtractionResult محدود بـ normal/secret/topsecret."""
    v = (v or '').strip()
    return v if v in ('normal', 'secret', 'topsecret') else None


def _parse_iso_date(v):
    if not v:
        return None
    try:
        return parse_date(str(v)[:10])
    except Exception:
        return None


def persist_extraction_capture(*, book, attachment, suggested, final, user=None):
    """يحفظ OCRResult + DataExtractionResult + ExtractionFeedback لزوج تدريب واحد.

    Args:
        book:       الكتاب المحفوظ (Book)
        attachment: المرفق الممسوح (Attachment) — لازم لربط OCRResult
        suggested:  قاموس اقتراحات OCR (كاش scan_token): raw_text + الحقول المُقترَحة
        final:      قاموس القيم النهائية المحفوظة (our_number/title/kind/secret_level)
        user:       المستخدم المؤكِّد

    Returns:
        DataExtractionResult عند النجاح، أو None عند غياب البيانات/الفشل.
    """
    if attachment is None or not suggested:
        return None
    try:
        raw_text = suggested.get('raw_text') or ''
        cleaned_text = suggested.get('cleaned_text') or raw_text
        if not (raw_text or cleaned_text):
            return None  # لا نصّ = لا قيمة تدريبية

        ocr = OCRResult.objects.create(
            attachment=attachment,
            status='completed',
            raw_text=raw_text,
            cleaned_text=cleaned_text,
            confidence_score=_to_float(suggested.get('overall_confidence')),
            num_characters=len(raw_text),
            processed_by=suggested.get('ocr_engine') or 'tesseract',
        )
        extraction = DataExtractionResult.objects.create(
            ocr_result=ocr,
            attachment=attachment,
            book=book,
            status='reviewed',
            book_number=(suggested.get('book_number') or '')[:50],
            book_number_confidence=_to_float(suggested.get('book_number_confidence')),
            book_date=_parse_iso_date(suggested.get('book_date')),
            book_date_confidence=_to_float(suggested.get('book_date_confidence')),
            title=(suggested.get('title') or '')[:500],
            title_confidence=_to_float(suggested.get('title_confidence')),
            secret_level=_norm_secret(suggested.get('secret_level')),
            secret_level_confidence=_to_float(suggested.get('secret_level_confidence')),
            book_kind=suggested.get('book_kind') or None,
            book_kind_confidence=_to_float(suggested.get('book_kind_confidence')),
            overall_confidence=_to_float(suggested.get('overall_confidence')),
            reviewed_by=user,
            reviewed_at=timezone.now(),
        )

        # تصحيحات المستخدم: حيث اختلف المُقترَح عن النهائي → إشارة تعلّم
        for sug_key, final_key in _FIELD_MAP:
            original = str(suggested.get(sug_key) or '').strip()
            corrected = str(final.get(final_key) or '').strip()
            if original and original != corrected:
                ExtractionFeedback.objects.create(
                    extraction=extraction,
                    field_name=final_key,
                    feedback_type='incorrect' if corrected else 'partial',
                    original_value=original,
                    corrected_value=corrected,
                    created_by=user,
                )

        # ذاكرة الترويسة → الجهة المؤكَّدة (تعلّمٌ تراكمي لاقتراح الجهة)
        _persist_letterhead_memory(book, cleaned_text or raw_text)
        return extraction
    except Exception as exc:  # noqa: BLE001 — الالتقاط لا يُفشل الحفظ أبداً
        logger.warning('[capture] فشل التقاط التدريب (الحفظ غير متأثّر): %s', exc, exc_info=True)
        return None
