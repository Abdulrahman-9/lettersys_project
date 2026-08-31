# -*- coding: utf-8 -*-
"""حرّاسُ تصنيف الجهات — أخطرُ ما فيه انحرافُ نسختَي القاعدة عن بعضهما."""

from django.test import TestCase

from core.entity_kinds import (
    EXTERNAL, INTERNAL, KINDS, UNIT, classify, kind_q, twin_names,
)
from core.models import Department, Entity


class EntityKindTests(TestCase):
    def setUp(self):
        self.body = Entity.objects.create(name='هيئة العمليات', code='ع')
        self.dept = Department.objects.create(name='هيئة العمليات', code='ع',
                                              entity=self.body)
        self.branch = Entity.objects.create(name='هيئة العمليات / قسم حقول الانبار')
        self.section = Entity.objects.create(name='شعبة المتابعة الفنية')
        self.person = Entity.objects.create(name='السيد وسام حميد خالد')
        self.outside = Entity.objects.create(name='وزارة النفط')
        # اسمٌ مُوأمٌ فيه شرطةٌ داخل قوسين — الفخُّ الذي كشفه اختبارُ التوافق.
        self.tricky = Entity.objects.create(
            name='لجنة الادارة المشتركة لحقلي (خشم الاحمر/انجانة)', code='ل خ')
        Department.objects.create(name=self.tricky.name, code='ل خ',
                                  entity=self.tricky)

    def test_kinds_partition_every_active_entity(self):
        """الأصنافُ الثلاثة تقسم النشطةَ قسمةً تامّة — لا صفَّ بلا تبويبٍ ولا في تبويبين."""
        heads = twin_names()
        seen = []
        for kind in KINDS:
            seen += list(
                Entity.objects.filter(is_active=True).filter(kind_q(kind, heads))
                .distinct().values_list('pk', flat=True)
            )

        active = set(Entity.objects.filter(is_active=True).values_list('pk', flat=True))
        self.assertEqual(sorted(seen), sorted(active))
        self.assertEqual(len(seen), len(set(seen)))

    def test_python_and_queryset_rules_agree(self):
        """نسختا القاعدة تتّفقان على كلّ صفّ.

        هذا الاختبارُ كشف عيباً فعليّاً: `startswith(head) & contains('/')`
        كانت تبتلع الجهةَ التي في اسمها شرطةٌ داخل قوسين.
        """
        heads = twin_names()
        twins = set(Department.objects.exclude(entity__isnull=True)
                    .values_list('entity_id', flat=True))

        by_query = {}
        for kind in KINDS:
            for pk in (Entity.objects.filter(is_active=True)
                       .filter(kind_q(kind, heads)).values_list('pk', flat=True)):
                by_query[pk] = kind

        for entity in Entity.objects.filter(is_active=True):
            self.assertEqual(by_query.get(entity.pk),
                             classify(entity, twins, heads),
                             msg=entity.name)

    def test_sub_unit_beats_twin(self):
        """الشعبةُ شعبةٌ وإن كان لها توأمُ قسم — الترتيبُ مقصود."""
        section = Entity.objects.create(name='شعبة ادارة الجودة', code='ش.ج')
        Department.objects.create(name=section.name, code='ش.ج', entity=section)

        self.assertEqual(classify(section), UNIT)

    def test_branch_path_is_a_unit_not_external(self):
        """«الأمّ / الفرع» وحدةٌ داخليّة لا جهةٌ خارجيّة."""
        self.assertEqual(classify(self.branch), UNIT)

    def test_tricky_parenthesised_slash_stays_internal(self):
        """شرطةٌ داخل قوسين لا تجعل الهيئةَ شعبة."""
        self.assertEqual(classify(self.tricky), INTERNAL)

    def test_person_and_body_and_outsider(self):
        self.assertEqual(classify(self.person), UNIT)
        self.assertEqual(classify(self.section), UNIT)
        self.assertEqual(classify(self.body), INTERNAL)
        self.assertEqual(classify(self.outside), EXTERNAL)
