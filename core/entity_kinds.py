# -*- coding: utf-8 -*-
"""تصنيفُ الجهات إلى ثلاثة أصنافٍ — **مصدرٌ وحيد**.

الأضابيرُ وصفحةُ الجهات تعرضان التصنيفَ نفسَه، فلو كُتبت القاعدةُ مرّتين
لانحرفتا (وهو عيبُ «نسخةٌ ثانية من الحقيقة» الذي لوحق في هذه الدفعة ثلاث
مرّات). القاعدةُ هنا، والصفحتان تستهلكانها.

**الأصنافُ الثلاثة بتسمية المالك:**

- ``INTERNAL`` — الجهاتُ الداخليّة: هيئاتُنا وأقسامُنا وَمكاتبُنا.
- ``EXTERNAL`` — الجهاتُ الخارجيّة: وزاراتٌ وشركاتٌ ومحافظاتٌ وسواها.
- ``UNIT`` — الشعبُ والوحداتُ والأفراد.

**والترتيبُ مقصود:** الشعبةُ شعبةٌ وإن كان لها توأمُ قسم — فحصُ الصنف الثالث
يسبق فحصَ التوأمة، وإلّا ابتلع التبويبُ الأوّلُ شعبَ التبويب الثالث.

**قواعدُ الصنف الثالث ثلاثٌ، وكلُّها مقيسةٌ على القاعدة الحيّة (413 جهةً نشطة):**

1. **صدرُ الاسم وحدةٌ فرعيّة** (شعبة · وحدة · فريق) — 50 جهة.
2. **صدرُ الاسم تشريفٌ أو منصبٌ شخصيّ** (السيد · رؤساء · مدير…) — والفردُ
   طرفُ مراسلةٍ حقيقيّ هنا: «السيد وسام حميد خالد» في الدليل فعلاً.
3. **«الأمّ / الفرع»** — 11 جهةً تكتب وحدةً داخليّةً بمسارٍ لا باسمٍ مفرد
   («هيئة العمليات / قسم حقول الانبار»). بلا هذه القاعدة تسقط في
   «الخارجيّة» — وهي وحداتُنا نحن. صدرُ المسار يُطابَق **بأسماء التوائم
   المبذورة** لا بقائمةٍ مكتوبةٍ باليد، فيكبر التصنيفُ مع الشجرة تلقائيّاً.

**المعجمُ هنا لا في العروض** ليراجعه المالكُ في موضعٍ واحد.
"""

from django.db.models import Q

INTERNAL = 'internal'
EXTERNAL = 'external'
UNIT = 'unit'

KINDS = (INTERNAL, EXTERNAL, UNIT)

KIND_LABELS = {
    INTERNAL: 'الجهات الداخلية',
    EXTERNAL: 'الجهات الخارجية',
    UNIT: 'الشعب والوحدات والأفراد',
}

#: صدرُ اسمِ وحدةٍ فرعيّةٍ داخل التنظيم.
SUB_UNIT_WORDS = ('شعبة', 'الشعبة', 'وحدة', 'الوحدة', 'فريق', 'فرق')

#: تشريفٌ أو منصبٌ يدلّ على شخصٍ لا على جهة.
PERSON_WORDS = (
    'السيد', 'السادة', 'الأستاذ', 'الاستاذ', 'المهندس', 'الدكتور',
    'رئيس', 'رؤساء', 'مدير', 'معاون', 'مسؤول',
)


def twin_names():
    """أسماءُ الجهات التي لها توأمُ قسمٍ مبذور — صدورُ المسارات تُطابَق بها."""
    from core.models import Department

    return {
        (d.entity.name or '').strip()
        for d in Department.objects.exclude(entity__isnull=True).select_related('entity')
        if (d.entity.name or '').strip()
    }


def _first_word(name):
    parts = (name or '').strip().split()
    return parts[0] if parts else ''


def _is_sub_path_of_internal(name, heads):
    """«الأمّ / الفرع» حيث الأمُّ وحدةٌ داخليّةٌ مُوأمة؟"""
    name = (name or '').strip()
    if '/' not in name:
        return False
    return name.split('/')[0].strip() in heads


def classify(entity, twin_ids=None, heads=None):
    """صنفُ الجهة — الصيغةُ البايثونيّة (للصفّ الواحد).

    ``twin_ids`` و``heads`` اختياريّتان: مرّرهما محسوبتين مرّةً واحدةً حين
    تُصنّف قائمةً، وإلّا استعلمت الدالّةُ لكلّ صفّ.
    """
    from core.models import Department

    name = (entity.name or '').strip()
    if heads is None:
        heads = twin_names()

    first = _first_word(name)
    if first in SUB_UNIT_WORDS or first in PERSON_WORDS:
        return UNIT
    if _is_sub_path_of_internal(name, heads):
        return UNIT

    if twin_ids is None:
        has_twin = Department.objects.filter(entity_id=entity.pk).exists()
    else:
        has_twin = entity.pk in twin_ids
    return INTERNAL if has_twin else EXTERNAL


def _unit_q(heads):
    """شرطُ الصنف الثالث — صالحٌ للاستعلام لا للذاكرة."""
    q = Q()
    for word in SUB_UNIT_WORDS + PERSON_WORDS:
        q |= Q(name__startswith=word + ' ')
    for head in heads:
        # الصدرُ يُتبَع بالشرطة مباشرةً — لا «فيه شرطةٌ في مكانٍ ما». الأخيرةُ
        # كانت تبتلع «لجنة… لحقلي (خشم الاحمر/انجانة)»: شرطةٌ داخل قوسين في
        # اسمِ وحدةٍ مُوأمةٍ نفسِها، فتُصنَّف شعبةً وهي هيئة. (كشفه اختبارُ
        # التوافق بين نسختَي القاعدة — وهو سببُ وجوده.)
        q |= Q(name__startswith=head + '/') | Q(name__startswith=head + ' /')
    return q


def kind_q(kind, heads=None):
    """شرطُ التصفية بالصنف — **في الاستعلام** لا بعد التجسيد.

    الصفحتان تُرقّمان النتائج، والتصفيةُ في بايثون تكسر العدّ والصفحات معاً.
    """
    if heads is None:
        heads = twin_names()

    unit = _unit_q(heads)
    if kind == UNIT:
        return unit
    if kind == INTERNAL:
        return ~unit & Q(department__isnull=False)
    if kind == EXTERNAL:
        return ~unit & Q(department__isnull=True)
    return Q()
