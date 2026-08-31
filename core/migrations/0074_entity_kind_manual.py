# -*- coding: utf-8 -*-
"""تبويبُ الجهة يصير حقلاً مخزَّناً يملكه المالك.

كان التبويبُ يُستنتج من صدر الاسم — تقريبٌ يخطئ بطبيعته. صار حقلاً، والاستنتاجُ
يُشغَّل هنا **مرّةً واحدة** ليضع نقطةَ بدءٍ بدل صفحةٍ فارغة، ثمّ لا يعود.
"""

from django.db import migrations, models

#: صدرُ اسمِ وحدةٍ فرعيّة، وتشريفٌ شخصيّ — لبذر القيمة الابتدائيّة لا غير.
_SUB_UNIT = ('شعبة', 'الشعبة', 'وحدة', 'الوحدة', 'فريق', 'فرق')
_PERSON = ('السيد', 'السادة', 'الأستاذ', 'الاستاذ', 'المهندس', 'الدكتور',
           'رئيس', 'رؤساء', 'مدير', 'معاون', 'مسؤول')


def seed_initial_kind(apps, schema_editor):
    """بذرُ تبويبٍ ابتدائيّ — نقطةُ بدءٍ يُصحّحها المالكُ بيده لا حقيقةٌ نهائيّة.

    أربعُ قواعدَ مقيسةٍ على القاعدة الحيّة (413 جهةً نشطة): صدرُ الاسم وحدةٌ
    فرعيّةٌ أو تشريفٌ شخصيّ ⟵ شعبة/وحدة · «الأمّ / الفرع» حيث الأمُّ وحدةٌ
    مُوأمة ⟵ شعبة/وحدة (11 جهةً كانت ستُقرأ خارجيّةً وهي وحداتُنا) · توأمُ
    قسمٍ ⟵ داخليّة · وما عداه خارجيّة.
    """
    Entity = apps.get_model('core', 'Entity')
    Department = apps.get_model('core', 'Department')

    twin_ids = set(Department.objects.exclude(entity__isnull=True)
                   .values_list('entity_id', flat=True))
    heads = {(e.name or '').strip()
             for e in Entity.objects.filter(pk__in=twin_ids).only('id', 'name')
             if (e.name or '').strip()}

    buckets = {'unit': [], 'internal': [], 'external': []}
    for entity in Entity.objects.all().only('id', 'name'):
        name = (entity.name or '').strip()
        words = name.split()
        first = words[0] if words else ''
        if first in _SUB_UNIT or first in _PERSON:
            kind = 'unit'
        elif '/' in name and name.split('/')[0].strip() in heads:
            kind = 'unit'
        elif entity.id in twin_ids:
            kind = 'internal'
        else:
            kind = 'external'
        buckets[kind].append(entity.id)

    for kind, ids in buckets.items():
        if ids:
            Entity.objects.filter(pk__in=ids).update(kind=kind)


def unseed(apps, schema_editor):
    """عكسُ AddField يُسقط العمودَ كلَّه — فلا شيء يُستعاد هنا."""


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0073_admin_actions'),
    ]

    operations = [
        migrations.AddField(
            model_name='entity',
            name='kind',
            field=models.CharField(
                choices=[('external', 'جهة خارجية'), ('internal', 'قسم داخلي'),
                         ('unit', 'شعبة/وحدة/فرد')],
                db_index=True, default='external', max_length=10,
                verbose_name='التبويب'),
        ),
        migrations.RunPython(seed_initial_kind, unseed),
    ]
