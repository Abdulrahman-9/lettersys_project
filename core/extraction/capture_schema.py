# -*- coding: utf-8 -*-
"""مخطّطُ مفاتيح `additional_data` — عقدٌ واحدٌ يتشاركه الكاتبُ والقارئ.

`additional_data` قاموسٌ حرّ (JSONField)، وإعادةُ تسميةٍ صامتة لمفتاحٍ فيه **تقتل
الجرد بلا صوت**: الحاصدُ يقرأ مفتاحاً لم يعد يُكتب فيُخرج صفراً ويبدو سليماً. وهو
نظيرُ فخّ الملء التلقائيّ الذي عاش أسبوعاً بعد «إصلاحه» — لا اختبارَ يصرخ.

فالمفاتيح تُعلَن هنا مرّةً، ويستوردها `capture.py` (الكاتب) وكلُّ قارئ (الجرد،
الحصاد، الإحصاء)، ويحرسها اختبارٌ يقارن مفاتيحَ التقاطٍ **حقيقيّ** بهذا المخطّط.
"""
import hashlib

# ═══ الحقول الملتقَطة ═══
# تُلتقَط لكلّ كتابٍ مهما كان نوعه.
ALWAYS_CAPTURED_FIELDS = ('title', 'secret_level')
# لا تُلتقَط إلّا للوارد: الصادر لا عددَ جهةٍ فيه ولا تاريخَ جهة، والتقاطُهما له
# يفبرك عيّناتٍ سالبة («154→''») لأنّ الواجهة تُفرّغ الحقلين.
INCOMING_ONLY_FIELDS = ('sender_number', 'sender_date')
CAPTURED_FIELDS = ALWAYS_CAPTURED_FIELDS + INCOMING_ONLY_FIELDS

# ═══ مصدرُ القيمة (provenance) ═══
# ثلاثيٌّ لأنّ سكوتَ الكاتب ليس شهادة: قيمةٌ مُلئت تلقائيّاً وحُفظت بلا لمسٍ
# تحمل خطأ النموذج نفسَه، فتعزيزُها تسمّمٌ ذاتيّ (ضجيجٌ في اتّجاهٍ واحد لا يذوب).
PROV_TYPED = 'typed'            # كتبه الكاتب بيده — الشاهد الوحيد للتقييم
PROV_CONFIRMED = 'confirmed'    # لمسه/عدّله ثمّ أبقاه — للتدريب لا للتقييم
PROV_AUTOFILLED = 'autofilled'  # مُلئ تلقائيّاً وحُفظ بلا لمس — يُستبعَد كلّيّاً
PROVENANCE_VALUES = (PROV_TYPED, PROV_CONFIRMED, PROV_AUTOFILLED)
TRAINABLE_PROVENANCE = (PROV_TYPED, PROV_CONFIRMED)
EVAL_TRUSTED_PROVENANCE = (PROV_TYPED,)

# ═══ حجرُ التقييم ═══
EVAL_HOLD_KEY = 'eval_hold'
EVAL_HOLD_MODULUS = 10          # ~10% محجوزةٌ للانحدار، لا تدخل تدريباً أبداً

# ═══ رايةُ العرض ═══
DISPLAYED_SUFFIX = '_displayed'


def displayed_key(field):
    """اسمُ رايةِ العرض لحقلٍ ملتقَط — مشتقٌّ لا مكتوبٌ يدويّاً في موضعين."""
    return '%s%s' % (field, DISPLAYED_SUFFIX)


def eval_hold_for(book_id):
    """هل هذا الكتاب محجوزٌ للتقييم؟ — بالهاش، لا بالاختيار ولا بالزمن.

    الحجرُ بالزمن («كلّ ما بعد تاريخ س») أو بالانتقاء يسمح بترحيل صفٍّ من الحجز
    إلى التدريب **بعد** رؤية نتيجته، وذاك بابُ التسريب الوحيد الذي لا يُكشَف
    لاحقاً. الهاشُ يجعل الحكم حتميّاً ومُعاداً حسابُه في أيّ قارئ بلا حالة.
    """
    digest = hashlib.md5(str(book_id).encode('utf-8')).hexdigest()
    return int(digest, 16) % EVAL_HOLD_MODULUS == 0


def normalize_provenance(value):
    """قيمةٌ خارج الثلاثيّ تُفرَّغ: مصدرٌ مجهولٌ أصدقُ من مصدرٍ مُختلَق."""
    value = str(value or '').strip()
    return value if value in PROVENANCE_VALUES else ''


# ═══ المفاتيح ═══
# تُكتب لكلّ التقاطٍ مهما كان نوع الكتاب.
BASE_KEYS = frozenset({
    'book_kind',                    # نوعُ الكتاب — يميّز «غيرُ منطبق» عن «القارئ أخفق»
    EVAL_HOLD_KEY,                  # حجرُ التقييم بالهاش (أعلاه)
    displayed_key('title'),         # هل عُرض اقتراحُ الموضوع فعلاً
    displayed_key('secret_level'),  # هل عُرض اقتراحُ السرّيّة فعلاً
    # مصدرُ قيمة الموضوع — **حقيقةُ تدريب الموضوع هي `Book.title` نفسُه**، فعنوانٌ
    # مُلئ آليّاً وحُفظ بلا لمسٍ يعود وسماً يدرّب المُنتقي على مخرجه هو (حلقةُ
    # تسميمٍ ذاتيّ لا تُكشَف لاحقاً بلا هذا الوسم — الحصادُ يقرأ العمود مجرّداً).
    'title_provenance',
    'title_suggestion_source',   # marker | fallback | bracket_* | '' — أيُّ مسارٍ أنتج ما عُرض
})

# كتلةُ العدد + رايةُ عرض التاريخ — تُكتب لكلّ واردٍ بلا شرط.
INCOMING_KEYS = frozenset({
    'sender_number_suggested',      # ما قرأه النظام (خامّاً)
    'sender_number_confidence',     # ثقةُ القراءة
    'sender_number_final',          # ما حُفظ فعلاً = حقيقةُ التدريب
    'sender_number_bbox',           # موضعُ القصاصة (نسبيّ)
    'sender_number_bbox_source',    # كاشفٌ أم قراءةٌ واثقة — عيّنتان مختلفتا القيمة
    'sender_number_bbox_dims',      # المقاسُ المرجعيّ — بدونه لا تُعاد البكسلات
    'sender_number_provenance',     # مكتوبٌ بيد / مؤكَّد / مُلئ تلقائيّاً
    displayed_key('sender_number'),
    displayed_key('sender_date'),
})

# اقتراحُ تاريخ الجهة — يُكتب حين ينطق الأنبوب باقتراحٍ فقط.
DATE_SUGGESTION_KEYS = frozenset({
    'sender_date_suggested_raw',    # السلسلةُ كما رُسمت
    'sender_date_suggested_iso',    # ما حلّه المحلّل (فارغٌ عند الامتناع)
    'sender_date_parse',            # ok / ambiguous / invalid
    'sender_date_confidence',
    'sender_date_bbox',
    'sender_date_bbox_source',
    'sender_date_geometry',         # إصدارُ هندسة القصّ — وإلّا اختلط توزيعان
})

# نهائيُّ التاريخ — يُكتب حين وُجد اقتراحٌ أو قيمةٌ نهائيّة.
DATE_FINAL_KEYS = frozenset({
    'sender_date_final',            # حبرُ الجهة كما أقرّه الكاتب
    'sender_date_entry',            # تاريخُ القيد — فارقٌ صفر = قراءةُ ختمنا مُحتمَلة
    'sender_date_provenance',
})

# كلُّ ما يجوز أن يظهر في `additional_data` — لا مفتاحَ خارجها.
CAPTURE_KEYS = BASE_KEYS | INCOMING_KEYS | DATE_SUGGESTION_KEYS | DATE_FINAL_KEYS
