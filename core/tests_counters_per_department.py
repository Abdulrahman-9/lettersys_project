# -*- coding: utf-8 -*-
"""عدّاداتُ كلّ دفترٍ على حدة — صفحةُ العدّادات وصفحةُ القسم والقائمة (2026-11-12).

كانت صفحةُ العدّادات على أوّل ماسكٍ وحدَه، وتقيس «آخر رقمٍ صدر» على كتب الأقسام كلّها:
فبدايةٌ صحيحةٌ لعدّاد قسمٍ تُرفض لأنّ قسماً آخر بلغ رقماً أعلى («فكان سيكرّر أرقاماً» ولا
تكرار — التفرّدُ داخل القسم)، ولا يُضبط عدّادُ قسمٍ ثانٍ من أيّ واجهة. والقائمةُ لا تقول
لأيّ دفترٍ رقمُ الصفّ، و«125» في دفترين كتابان.
"""
from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse

from core import roles
from core.models import Book, BookSequence, Department, UserProfile

PAGE = 'sequence_settings'


def _book(department, number, kind='incoming_internal', by=None):
    return Book.objects.create(kind=kind, title='كتاب %s' % number, our_number=str(number),
                               department=department, created_by=by)


class CountersPageTests(TestCase):
    """الافتراضيُّ (أوّلُ ماسكٍ من الهجرات) بلا كتب، والقسم «ب» أصدر حتّى 500."""

    @classmethod
    def setUpTestData(cls):
        roles.ensure_role_groups()
        cls.boss = User.objects.create_superuser('ctr_boss', 'c@x.co', 'pw-ctr-boss-111')
        cls.default = BookSequence.resolve_department()
        cls.b = Department.objects.create(name='قسم ب للعدّاد', code='عب-1112')
        _book(cls.b, 500, by=cls.boss)
        BookSequence.objects.create(kind='incoming_internal', department=cls.b, next_number=501)

    def setUp(self):
        self.client.force_login(self.boss)

    def _post(self, number, department=None, user=None):
        if user is not None:
            self.client.force_login(user)
        data = {'next_number_incoming_internal': str(number)}
        if department is not None:
            data['department'] = str(department.pk)
        return self.client.post(reverse(PAGE), data)

    def _next(self, department):
        return BookSequence.objects.get(kind='incoming_internal', department=department).next_number

    def test_the_admin_sees_every_register_and_picks_one(self):
        response = self.client.get(reverse(PAGE))
        names = [d.name for d in response.context['departments']]
        self.assertIn(self.default.name, names)
        self.assertIn(self.b.name, names)
        self.assertContains(response, 'id="counterDepartment"')
        picked = self.client.get(reverse(PAGE), {'department': self.b.pk})
        self.assertEqual(picked.context['department'], self.b)
        self.assertContains(picked, f'name="department" value="{self.b.pk}"')   # الحفظُ يحمل دفترَه
        self.assertEqual({s['obj'].department_id for s in picked.context['sequences']}, {self.b.pk})

    def test_a_start_is_measured_within_its_own_register(self):
        # «ب» بلغ 500، والافتراضيُّ لم يُصدر شيئاً: 20 بدايةٌ صحيحةٌ له لا تكرارَ فيها
        self._post(20, self.default)
        self.assertEqual(self._next(self.default), 20)

    def test_a_real_duplicate_is_still_refused_and_named(self):
        response = self._post(500, self.b)
        self.assertEqual(self._next(self.b), 501)
        texts = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertTrue(any('آخر رقمٍ صدر (500)' in t and self.b.name in t for t in texts), texts)

    def test_books_without_a_department_count_for_the_default(self):
        _book(None, 3917, by=self.boss)
        self._post(3917, self.default)
        self.assertNotEqual(self._next(self.default), 3917)
        self._post(600, self.b)   # كتابٌ بلا قسمٍ لا يحسب على دفتر «ب»
        self.assertEqual(self._next(self.b), 600)

    def test_a_unit_without_a_register_spends_its_holders(self):
        unit = Department.objects.create(name='وحدة تحت ب', code='عب-1112-و', parent=self.b,
                                         holds_register=False)
        _book(unit, 700, by=self.boss)
        self._post(650, self.b)
        self.assertEqual(self._next(self.b), 501)

    def test_saving_returns_to_the_chosen_register(self):
        response = self._post(900, self.b)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], f"{reverse(PAGE)}?department={self.b.pk}")
        self.assertEqual(self._next(self.b), 900)

    def test_an_unknown_register_is_404(self):
        self.assertEqual(self.client.get(reverse(PAGE), {'department': 999999}).status_code, 404)
        self.assertEqual(self._post(950, Department(pk=999999)).status_code, 404)

    def test_a_staff_member_edits_his_own_register_only(self):
        staffer = User.objects.create_user('ctr_staff', password='pw-ctr-staff-111', is_staff=True)
        UserProfile.objects.update_or_create(user=staffer, defaults={'department': self.b})
        self.client.force_login(staffer)
        page = self.client.get(reverse(PAGE))
        self.assertEqual([d.pk for d in page.context['departments']], [self.b.pk])
        self.assertNotContains(page, 'id="counterDepartment"')
        self.assertEqual(self.client.get(reverse(PAGE), {'department': self.default.pk}).status_code, 404)
        self._post(800)
        self.assertEqual(self._next(self.b), 800)

    def test_one_register_keeps_the_page_as_it_was(self):
        Department.objects.filter(pk=self.b.pk).update(holds_register=False)
        page = self.client.get(reverse(PAGE))
        self.assertNotContains(page, 'id="counterDepartment"')
        self.assertNotContains(page, 'name="department"')
        response = self._post(30)
        self.assertEqual(response['Location'], reverse(PAGE))
        self.assertEqual(self._next(self.default), 30)


class DepartmentPageCountersLinkTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        roles.ensure_role_groups()
        cls.boss = User.objects.create_superuser('ctr_link', 'l@x.co', 'pw-ctr-link-111')
        cls.holder = Department.objects.create(name='قسم برابط', code='رب-1112')
        cls.unit = Department.objects.create(name='وحدة بلا سجل', code='رب-1112-و', parent=cls.holder,
                                             holds_register=False)

    def setUp(self):
        self.client.force_login(self.boss)

    def test_a_register_links_to_its_own_counters(self):
        page = self.client.get(reverse('system_department', args=[self.holder.pk]))
        self.assertContains(page, f'{reverse(PAGE)}?department={self.holder.pk}')

    def test_a_unit_without_a_register_has_no_link(self):
        page = self.client.get(reverse('system_department', args=[self.unit.pk]))
        self.assertNotContains(page, f'{reverse(PAGE)}?department=')


class ListRegisterTagTests(TestCase):
    """«125» في دفترين كتابان: الصفُّ يحمل رمزَ سجلّه حين تجمع النتيجةُ أكثر من دفتر."""

    @classmethod
    def setUpTestData(cls):
        roles.ensure_role_groups()
        cls.boss = User.objects.create_superuser('ctr_list', 'r@x.co', 'pw-ctr-list-111')
        cls.a = Department.objects.create(name='قسم أ للقائمة', code='قأ-1112')
        cls.b = Department.objects.create(name='قسم ب للقائمة', code='قب-1112')
        _book(cls.a, 125, by=cls.boss)

    def setUp(self):
        self.client.force_login(self.boss)

    def _page(self):
        return self.client.get(reverse('book_unified'), {'tab': 'all'})

    def _ajax_rows(self):
        return self.client.get(reverse('api_unified_data'), {'tab': 'all'}).json()['rows_html']

    def test_one_register_shows_no_tag(self):
        self.assertNotContains(self._page(), 'class="num-register"')
        self.assertNotIn('num-register', self._ajax_rows())

    def test_two_registers_tag_every_row_on_both_paths(self):
        _book(self.b, 125, by=self.boss)
        page = self._page()
        self.assertContains(page, '>قأ-1112</span>')
        self.assertContains(page, '>قب-1112</span>')
        rows = self._ajax_rows()
        self.assertIn('>قأ-1112</span>', rows)
        self.assertIn('>قب-1112</span>', rows)

    def test_the_tag_survives_every_sort_and_a_search(self):
        # الفرزُ يضيف تعليقاتٍ (مفتاحُ الرقم، العنوانُ كما يُرى) والبحثُ صلةً — والقرارُ يبقى صحيحاً
        _book(self.b, 125, by=self.boss)
        from core.views.filter_helpers import BookSortEngine
        for sort in list(BookSortEngine.VALID_SORTS) + ['relevance']:
            for q in ('', '125'):
                with self.subTest(sort=sort, q=q):
                    params = {'tab': 'all', 'sort': sort, 'q': q}
                    rows = self.client.get(reverse('api_unified_data'), params).json()['rows_html']
                    self.assertIn('>قأ-1112</span>', rows)
                    self.assertIn('>قب-1112</span>', rows)
                    self.assertContains(self.client.get(reverse('book_unified'), params), '>قب-1112</span>')
