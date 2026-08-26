# -*- coding: utf-8 -*-
"""
core.extraction.capture
========================
حلقة التقاط بيانات التدريب: تحفظ زوج (نصّ OCR → الحقول المؤكَّدة) + تصحيحات
المستخدم عند حفظ كتاب ممسوح، لتغذية نماذج التعلّم المستقبلية (نوع/عنوان/جهة/أرقام).

مبدأ السلامة الأعلى: **لا يرفع استثناءً أبداً** — فشل الالتقاط لا يُفشل حفظ الكتاب.
"""
import logging

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date

from core.extraction.capture_schema import (ALWAYS_CAPTURED_FIELDS,
                                            EVAL_HOLD_KEY, displayed_key,
                                            eval_hold_for,
                                            normalize_provenance)
from core.models import (DataExtractionResult, ExtractionFeedback,
                         LetterheadMemory, OCRResult)

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
#   - sender_number مُضاف 2026-07-22: يُخزَّن خاماً بلا إعادة تنسيق (قياس القاعدة:
#     أرقام صرفة للجهات الكبرى)، فالمقارنة نظيفة. **هذا هو أوّل توصيل لحلقة تعلّم
#     العدد** — كانت غائبةً كلّياً (لا قيمة ولا موضع).
#   - الموضع (bbox) اكتمل 2026-08-18: كان يُحفَظ فقط مع قراءةٍ تجتاز CONF_GATE=0.90
#     (صفٌّ واحدٌ من 12 مقيساً)، أي عيّناتٌ من الصفحات الناجحة أصلاً بينما التدريب
#     يحتاج الصعبة. صار صندوق الكاشف يُحفَظ عند امتناع القارئ أيضاً، موسوماً
#     بـ`_bbox_source` ومصحوباً بـ`_bbox_dims` (المقاس المرجعيّ).
# كل الاقتراحات (رقم/نوع/تاريخ) تبقى مخزَّنة في DataExtractionResult للسجل والتحليل.
_FIELD_MAP = (
    ('title',         'title'),
    ('secret_level',  'secret_level'),
    ('sender_number', 'sender_number'),
)

# العدد يُستخرَج للوارد فقط. الصادر يُفرّغ الحقل في الواجهة (showSenderFields:false)
# بينما الأنبوب يُصدر اقتراحاً — فبلا هذه البوّابة يُسجَّل كلّ حفظِ صادرٍ تصحيحاً
# كاذباً «154→''» = عيّنة تدريبٍ سالبةٌ مفبركة. (Fable، استشارة 9.)
_INCOMING_KINDS = ('incoming_internal', 'incoming_external')
# تطبيع نصّ الأرقام (عربية-هنديّة ← لاتينيّة) قبل مقارنة العدد: القاعدة تخزّنه لاتينياً
# اليوم (قياس: صفر عربية-هنديّة من 9,163) لكنّ الحارس يمنع تسجيل قراءةٍ صحيحةٍ بخطٍّ
# رقميٍّ مختلف كأنّها تصحيح إن أدخل موظّفٌ أرقاماً عربية مستقبلاً.
_AR_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')


def _to_float(v):
    try:
        return float(v or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _same_number(a, b):
    return (a or '').translate(_AR_DIGITS).strip() == (b or '').translate(_AR_DIGITS).strip()


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
        final:      قاموس القيم النهائية المحفوظة (our_number/title/kind/secret_level/
                    sender_number/sender_date) + وسمَي الواجهة: `*_provenance`
                    (مصدرُ القيمة) و`displayed_fields` (ما عُرض على الكاتب فعلاً)
        user:       المستخدم المؤكِّد

    Returns:
        DataExtractionResult عند النجاح، أو None عند غياب البيانات/الفشل.
    """
    if attachment is None or not suggested:
        return None
    raw_text = suggested.get('raw_text') or ''
    cleaned_text = suggested.get('cleaned_text') or raw_text
    if not (raw_text or cleaned_text):
        return None  # لا نصّ = لا قيمة تدريبية
    try:
        # savepoint: OCRResult وDataExtractionResult كلاهما OneToOne بالمرفق، فأيّ
        # فشلٍ في منتصف السلسلة يترك يتيماً يحجز الخانة ويُفشل أيّ التقاطٍ لاحق بصمت.
        # الالتفاف يجعلها كلًّا-أو-لا-شيء (الالتقاط post-commit فنحن في autocommit).
        with transaction.atomic():
            return _do_capture(book, attachment, suggested, final, user,
                               raw_text, cleaned_text)
    except Exception as exc:  # noqa: BLE001 — الالتقاط لا يُفشل الحفظ أبداً
        logger.warning('[capture] فشل التقاط التدريب (الحفظ غير متأثّر): %s', exc, exc_info=True)
        return None



def _capture_date_feedback(extraction, suggested, final, user, is_incoming):
    """إشارةُ تعلّمٍ لتاريخ الجهة — بمقارنة **كائنَي تاريخ** لا نصّين.

    فخّان يُتفاديان هنا بالبناء:
      1. `'2025-03-06T00:00:00' != '2025-03-06'` نصّيّاً بينما التاريخ واحد —
         وهذا كان سببَ استثناء الحقل أصلاً.
      2. المقارنةُ على `raw` (السلسلة كما رُسمت «2025/3/6») تُنتج تصحيحاً كاذباً
         في كلّ مرّة — المقارنةُ على `iso` وحده.
    وحين يمتنع المحلّل (`parse != 'ok'`) فلا إشارةَ إطلاقاً: لا يصحّ ادّعاء
    «تصحيحِ» اقتراحٍ لم يُنطق. والزوجُ يبقى ذهباً في `additional_data`.
    """
    if not is_incoming:
        return
    sd = suggested.get('sender_date_suggestion') or {}
    if (sd.get('parse') or '') != 'ok':
        return
    original = _parse_iso_date(sd.get('iso'))
    corrected = _parse_iso_date(final.get('sender_date'))
    if not original or original == corrected:
        return
    ExtractionFeedback.objects.create(
        extraction=extraction,
        field_name='sender_date',
        feedback_type='incorrect' if corrected else 'partial',
        original_value=original.isoformat(),
        corrected_value=corrected.isoformat() if corrected else '',
        created_by=user,
    )

def _do_capture(book, attachment, suggested, final, user, raw_text, cleaned_text):
    """جسم الالتقاط داخل savepoint — الاستثناءات تصعد إلى المُغلِّف (لا تُبلَع هنا)."""
    is_incoming = (book.kind or '') in _INCOMING_KINDS
    # ما عُرض على الكاتب فعلاً — من الواجهة وحدها. «وُجد اقتراح» ليس «عُرض
    # اقتراح»، وبلا هذا الفصل تختلط دلالةُ «لم يُصحَّح» بين «صحيحٌ» و«لم يره
    # أحد» عبر تبدّلات سياسة العرض (تبدّلت ثلاثاً في أسبوعين).
    displayed = {str(f) for f in (final.get('displayed_fields') or ())}
    # book_kind يُختم دائماً كي يُميّز المستهلك «صادر: الحقل غير منطبق» عن
    # «وارد: القارئ أخفق فعلاً» — وإلا صارا سواءً في البيانات.
    add_data = {
        'book_kind': book.kind or '',
        # الحجرُ يُحسم لحظةَ الالتقاط لا عند بناء الدفعة: قرارٌ لاحق يعني ترحيلاً
        # ممكناً من الحجز إلى التدريب بعد رؤية النتيجة.
        EVAL_HOLD_KEY: eval_hold_for(book.id),
    }
    for _f in ALWAYS_CAPTURED_FIELDS:
        add_data[displayed_key(_f)] = _f in displayed
    if is_incoming:
        add_data.update({
            'sender_number_suggested': (suggested.get('sender_number') or '')[:50],
            'sender_number_confidence': _to_float(suggested.get('sender_number_confidence')),
            'sender_number_final': str(final.get('sender_number') or '')[:50],
            # العدد هو الحقل الوحيد الذي تملؤه الواجهة تلقائيّاً، فكان الوحيد بلا
            # وسم مصدر: `autofilled` (حُفظ بلا لمس) يحمل خطأ النموذج نفسَه ⟵
            # يُستبعَد من التدريب كلّيّاً، وإلّا عزّز النموذجُ خطأه بنفسه.
            'sender_number_provenance': normalize_provenance(
                final.get('sender_number_provenance')),
            displayed_key('sender_number'): 'sender_number' in displayed,
            displayed_key('sender_date'): 'sender_date' in displayed,
            'sender_number_bbox': suggested.get('sender_number_bbox') or None,
            # مصدر الصندوق ومقاسه المرجعيّ: بدونهما لا يُعاد بناء البكسلات، ولا
            # يُميَّز صندوقُ قراءةٍ واثقة عن صندوقِ كاشفٍ امتنع القارئ عنده — وهما
            # عيّنتا تدريبٍ مختلفتا القيمة تماماً.
            'sender_number_bbox_source': suggested.get('sender_number_bbox_source') or '',
            'sender_number_bbox_dims': suggested.get('sender_number_bbox_dims') or None,
        })
        # ── تاريخ الجهة: الاقتراحُ البصريّ ونهائيُّ الكاتب ──────────────────
        # كان الحقل مستثنى بحجّة «فرق صيغة ISO/Date يعطي إيجابيّاتٍ كاذبة» —
        # وتلك علّةُ **مقارنةٍ** عولجت بمقارنة كائناتِ تاريخٍ لا نصوص، لا سبباً
        # لإهدار الذهب: كلُّ تصحيحٍ للتاريخ كان يضيع.
        sd = suggested.get('sender_date_suggestion') or {}
        if sd:
            add_data.update({
                'sender_date_suggested_raw': str(sd.get('raw') or '')[:32],
                'sender_date_suggested_iso': str(sd.get('iso') or '')[:10],
                'sender_date_parse': str(sd.get('parse') or '')[:16],
                'sender_date_confidence': _to_float(sd.get('confidence')),
                'sender_date_bbox': sd.get('bbox') or None,
                'sender_date_bbox_source': str(sd.get('source') or '')[:24],
                # وسمُ إصدار الهندسة: بدونه لا يُعرف مستقبلاً بأيّ قصٍّ جُمع هذا
                # الذهب حين تتبدّل الهندسة — فيختلط توزيعان في مجموعةٍ واحدة.
                'sender_date_geometry': str(sd.get('geometry') or '')[:8],
            })
        if sd or final.get('sender_date'):
            add_data.update({
                'sender_date_final': str(final.get('sender_date') or '')[:10],
                # تاريخُ القيد لحظةَ الحفظ: يمكّن ترشيحَ الفارق عند بناء مجموعة
                # التدريب التالية (قراءةُ ختمنا بدل حبر الجهة تعطي فارقاً صفراً).
                'sender_date_entry': str(final.get('date') or '')[:10],
                # مصدرُ القيمة: ما أكّده الكاتب بنقرةٍ ليس شاهدَ تقييمٍ مستقلّاً
                # (قد يختم بلا تدقيق)، وما كتبه بيده شاهدٌ نظيف. التدريب يأكل
                # الاثنين، والتقييم لا يثق إلّا بالثاني.
                'sender_date_provenance': normalize_provenance(
                    final.get('sender_date_provenance')),
            })

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
        # سجلّ العدد الكامل (للوارد فقط): المُقترَح + النهائي + حامل الموضع (فارغ
        # اليوم، يمتلئ حين يمرّر الأنبوب صندوق القصّ). يلتقط الإبقاء والتصحيح معاً —
        # ExtractionFeedback يسجّل التصحيح فقط. `sender_number` لا عمود له في
        # النموذج، فـ additional_data (JSONField) حامله الجاهز.
        additional_data=add_data,
    )

    # تصحيحات المستخدم: حيث اختلف المُقترَح عن النهائي → إشارة تعلّم
    _capture_date_feedback(extraction, suggested, final, user, is_incoming)
    for sug_key, final_key in _FIELD_MAP:
        if final_key == 'sender_number' and not is_incoming:
            continue   # الصادر: لا عدد جهةٍ يُستخرَج — لا إشارة تصحيح
        original = str(suggested.get(sug_key) or '').strip()
        corrected = str(final.get(final_key) or '').strip()
        differs = (not _same_number(original, corrected)
                   if final_key == 'sender_number' else original != corrected)
        if original and differs:
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
