# -*- coding: utf-8 -*-
"""تبويبُ الجهة — **قرارٌ مخزَّنٌ يملكه المالك**، لا استنتاجٌ من الاسم.

الأضابيرُ وصفحةُ الجهات تعرضان التبويبَ نفسَه، والمصدرُ الوحيد هو الحقل
``Entity.kind``. هذه الوحدةُ تُسمّي الأصنافَ وتبني شروطَ الاستعلام وتقترح
قيمةً للجهة الجديدة — **ولا تُقرّر لجهةٍ قائمة**.

**لماذا مخزَّنٌ لا محسوب:** الاستنتاجُ من صدر الاسم تقريبٌ يخطئ بطبيعته، ولا
توجد قاعدةٌ لغويّةٌ تفصل «قسمٌ من شركتنا» عن «قسمٌ من وزارة». والمالكُ يشكّل
المجموعات بالأسماء والأقسام التي يريد — فالقرارُ بشريٌّ والحقلُ يحفظه.

**الاقتراحُ لا يكتب فوق قرار:** ``suggest_kind`` تُستدعى عند إنشاء جهةٍ جديدة
وفي بذر الهجرة 0074 مرّةً واحدة. أيُّ مسارٍ يُعيد تشغيلها على القاعدة كلِّها
يمحو عملَ المالك — وهذا ممنوع.
"""

from django.db.models import Q

from core.models import Entity

INTERNAL = Entity.KIND_INTERNAL
EXTERNAL = Entity.KIND_EXTERNAL
UNIT = Entity.KIND_UNIT

#: ترتيبُ العرض — كما سمّاها المالك.
KINDS = (EXTERNAL, INTERNAL, UNIT)

KIND_LABELS = {
    EXTERNAL: 'جهات خارجية',
    INTERNAL: 'أقسام الشركة',
    UNIT: 'الشعب والوحدات',
}

#: شرحٌ تحت التبويب — الفرقُ بين الثلاثة ليس بديهيّاً لمن يفتح الصفحة أوّل مرّة.
KIND_HINTS = {
    EXTERNAL: 'جهات من خارج الشركة',
    INTERNAL: 'أقسام شركة نفط الوسط',
    UNIT: 'الشعب والوحدات التابعة للقسم',
}

#: صدرُ اسمِ وحدةٍ فرعيّة — للاقتراح وحده.
SUB_UNIT_WORDS = ('شعبة', 'الشعبة', 'وحدة', 'الوحدة', 'فريق', 'فرق')

#: تشريفٌ أو منصبٌ يدلّ على شخصٍ لا على جهة — للاقتراح وحده.
PERSON_WORDS = (
    'السيد', 'السادة', 'الأستاذ', 'الاستاذ', 'المهندس', 'الدكتور',
    'رئيس', 'رؤساء', 'مدير', 'معاون', 'مسؤول',
)


def kind_of(entity):
    """تبويبُ الجهة كما قرّره المالك."""
    return entity.kind


def kind_q(kind):
    """شرطُ التصفية بالتبويب — **في الاستعلام** لا بعد التجسيد.

    الصفحتان مُرقَّمتان، وتصفيةٌ في بايثون تكسر العدَّ والصفحات معاً.
    """
    return Q(kind=kind) if kind in KINDS else Q()


def suggest_kind(entity_or_name, *, twin_ids=None, heads=None):
    """اقتراحُ تبويبٍ لجهةٍ **جديدة** — قابلٌ للتغيير قبل الحفظ وبعده.

    يُستدعى في نموذج الإنشاء ليضع قيمةً أوّليّةً معقولة. لا يُستدعى أبداً على
    جهةٍ قائمة: قرارُ المالك أثقلُ من أيّ قاعدة.
    """
    from core.models import Department

    entity = None if isinstance(entity_or_name, str) else entity_or_name
    name = (entity_or_name if entity is None else (entity.name or '')).strip()

    words = name.split()
    first = words[0] if words else ''
    if first in SUB_UNIT_WORDS or first in PERSON_WORDS:
        return UNIT

    if heads is None:
        heads = {(d.entity.name or '').strip()
                 for d in Department.objects.exclude(entity__isnull=True)
                                            .select_related('entity')
                 if (d.entity.name or '').strip()}
    if '/' in name and name.split('/')[0].strip() in heads:
        return UNIT

    if entity is not None and entity.pk:
        has_twin = (entity.pk in twin_ids if twin_ids is not None
                    else Department.objects.filter(entity_id=entity.pk).exists())
        if has_twin:
            return INTERNAL
    return EXTERNAL
