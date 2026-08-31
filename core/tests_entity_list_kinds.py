# -*- coding: utf-8 -*-
"""حرّاسُ مرشِّح الصنف في صفحة الجهات."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.entity_kinds import EXTERNAL, INTERNAL, UNIT
from core.models import Department, Entity


class EntityListKindFilterTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user('clerk', 'c@x.co', 'pw', is_staff=True)
        self.client.force_login(self.staff)

        self.body = Entity.objects.create(name='هيئة العمليات', code='ع',
                                          kind=INTERNAL)
        Department.objects.create(name='هيئة العمليات', code='ع', entity=self.body)
        Entity.objects.create(name='شعبة المتابعة الفنية', kind=UNIT)
        Entity.objects.create(name='وزارة النفط', kind=EXTERNAL)

    def _names(self, **params):
        res = self.client.get(reverse('entity_list'), params)
        self.assertEqual(res.status_code, 200)
        return sorted(e.name for e in res.context['entities'].object_list)

    def test_filter_by_each_kind(self):
        self.assertEqual(self._names(kind=INTERNAL), ['هيئة العمليات'])
        self.assertEqual(self._names(kind=EXTERNAL), ['وزارة النفط'])
        self.assertEqual(self._names(kind=UNIT), ['شعبة المتابعة الفنية'])

    def test_no_kind_shows_everything(self):
        """الصفحةُ بلا مرشِّحٍ تبقى كما كانت — إضافةٌ لا تضييق."""
        self.assertEqual(len(self._names()), 3)

    def test_unknown_kind_is_ignored_not_empty(self):
        res = self.client.get(reverse('entity_list'), {'kind': 'ملفّق'})

        self.assertEqual(res.context['kind_filter'], '')
        self.assertEqual(len(res.context['entities'].object_list), 3)

    def test_kind_and_language_filters_compose(self):
        """المرشِّحان مستقلّان ويعملان معاً — لا يُلغي أحدهما الآخر."""
        Entity.objects.create(name='Baker Hughes', kind=EXTERNAL)

        self.assertEqual(self._names(kind=EXTERNAL, lang='en'), ['Baker Hughes'])
        self.assertEqual(self._names(kind=EXTERNAL, lang='ar'), ['وزارة النفط'])

    def test_counts_cover_all_three_kinds(self):
        res = self.client.get(reverse('entity_list'))
        counts = {t['key']: t['count'] for t in res.context['kind_tabs']}

        self.assertEqual(counts, {INTERNAL: 1, EXTERNAL: 1, UNIT: 1})
