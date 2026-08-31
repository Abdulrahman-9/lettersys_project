# -*- coding: utf-8 -*-
"""حرّاسُ تبويبات صفحة الأضابير الثلاثة."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.entity_kinds import EXTERNAL, INTERNAL, UNIT
from core.models import Book, Department, Entity


class DossierKindTabTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('boss', 'b@x.co', 'pw')
        self.client.force_login(self.user)

        self.body = Entity.objects.create(name='هيئة العمليات', code='ع')
        Department.objects.create(name='هيئة العمليات', code='ع', entity=self.body)
        self.section = Entity.objects.create(name='شعبة المتابعة الفنية')
        self.outside = Entity.objects.create(name='وزارة النفط')

        # الأضبارةُ لا تظهر إلّا لجهةٍ لها كتب.
        for ent in (self.body, self.section, self.outside):
            book = Book.objects.create(kind='incoming_external', title='ك',
                                       created_by=self.user)
            book.receiving_entities.add(ent)

    def _names(self, kind):
        res = self.client.get(reverse('dossier_list'), {'kind': kind})
        self.assertEqual(res.status_code, 200)
        return [e.name for e in res.context['page_obj'].object_list]

    def test_each_tab_shows_only_its_kind(self):
        self.assertEqual(self._names(INTERNAL), ['هيئة العمليات'])
        self.assertEqual(self._names(EXTERNAL), ['وزارة النفط'])
        self.assertEqual(self._names(UNIT), ['شعبة المتابعة الفنية'])

    def test_tab_counts_are_rendered(self):
        res = self.client.get(reverse('dossier_list'))
        counts = {t['key']: t['count'] for t in res.context['tabs']}

        self.assertEqual(counts, {INTERNAL: 1, EXTERNAL: 1, UNIT: 1})
        self.assertEqual(len(res.context['tabs']), 3)

    def test_unknown_kind_falls_back_to_internal(self):
        """قيمةٌ ملفّقةٌ في الرابط لا تُفرغ الصفحة ولا ترفع خطأً."""
        res = self.client.get(reverse('dossier_list'), {'kind': 'nonsense'})

        self.assertEqual(res.context['kind'], INTERNAL)

    def test_search_keeps_the_active_tab(self):
        """البحثُ داخل التبويب لا يقذف المستخدمَ إلى تبويبٍ آخر."""
        res = self.client.get(reverse('dossier_list'),
                              {'kind': UNIT, 'q': 'شعبة'})

        self.assertEqual(res.context['kind'], UNIT)
        self.assertEqual([e.name for e in res.context['page_obj'].object_list],
                         ['شعبة المتابعة الفنية'])
