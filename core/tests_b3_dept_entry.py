# -*- coding: utf-8 -*-
"""(ب)3‑3 — الإدخالُ في دفتر قسمٍ من صفحته (2026‑11‑11).

مواصفةُ المالك: «لوحدةٍ تمسك سجلّاً، وللسوبر فقط، بقسمٍ يتحقّق منه الخادم، وتأكيدٍ يسمّي القسمَ
والرقمَ التالي ويذكر أنّ الرقم لا يعود، ويُسجَّل القسمُ الهدف في السجلّ». شريطُ مدير النظام إدارةٌ
فقط؛ والعملُ يُفتح من صفحة القسم.
"""
from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from core import scoping as s
from core.models import Book, BookHistory, BookSequence, Department, Entity, UserProfile
from core.roles import ENTRY_GROUP_NAME, ensure_role_groups

DESK = '/books/extract/smart-desktop/'
KIND = 'incoming_external'


class DeptEntryCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_role_groups()
        cls.dept = Department.objects.create(name='قسم الهدف', code='هد1')
        cls.unit = Department.objects.create(name='شعبة الهدف', code='هد1ش', parent=cls.dept, holds_register=False)
        cls.off = Department.objects.create(name='قسمٌ معطَّل', code='هد2', is_active=False)
        cls.home = Department.objects.create(name='قسم المدير', code='هد3')
        cls.root = User.objects.create_superuser('d_root', password='pw-dept-1111')
        UserProfile.objects.update_or_create(user=cls.root, defaults={'department': cls.home})
        cls.entry = User.objects.create_user('d_entry', password='pw-dept-1111')
        UserProfile.objects.update_or_create(user=cls.entry, defaults={'department': cls.dept})
        cls.entry.groups.add(Group.objects.get(name=ENTRY_GROUP_NAME))
        cls.entity = Entity.objects.create(name='جهة الهدف')

    def setUp(self):
        cache.clear()

    def payload(self, title, **extra):
        return {'title': title, 'date': '2026-11-11', 'kind': KIND, 'document_type': 'كتاب',
                'issuing_entity_id': str(self.entity.id), 'auto_number': 'true', 'our_number': 'تلقائي', **extra}


class CanEnterForTests(DeptEntryCase):
    def test_the_system_admin_into_an_active_register_holder_only(self):
        self.assertTrue(s.can_enter_for(self.root, self.dept))
        for department in (self.unit, self.off, None):
            with self.subTest(department=getattr(department, 'code', None)):
                self.assertFalse(s.can_enter_for(self.root, department))
        self.assertFalse(s.can_enter_for(self.entry, self.dept))


class DepartmentPageButtonTests(DeptEntryCase):
    def test_the_button_is_on_a_register_holders_page_only(self):
        self.client.force_login(self.root)
        target = f'href="{DESK}?department={self.dept.pk}"'
        self.assertIn(target, self.client.get(reverse('system_department', args=[self.dept.pk])).content.decode())
        body = self.client.get(reverse('system_department', args=[self.unit.pk])).content.decode()
        self.assertNotIn(f'?department={self.unit.pk}"', body)


class DeskTargetModeTests(DeptEntryCase):
    def test_the_desk_names_the_target_and_hides_reservation(self):
        self.client.force_login(self.root)
        response = self.client.get(f'{DESK}?department={self.dept.pk}')
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn(f'data-target-department-id="{self.dept.pk}"', body)
        self.assertIn('قسم الهدف', body)
        self.assertNotIn('id="reservationRing"', body)

    def test_the_server_checks_the_department(self):
        self.client.force_login(self.root)
        for raw in (self.unit.pk, self.off.pk, 'x', 999999):
            with self.subTest(raw=raw):
                self.assertEqual(self.client.get(f'{DESK}?department={raw}').status_code, 403)
        self.client.force_login(self.entry)
        self.assertEqual(self.client.get(f'{DESK}?department={self.dept.pk}').status_code, 403)


class SaveIntoTargetTests(DeptEntryCase):
    def test_only_the_system_admin_names_a_department(self):
        before = Book.all_objects.count()
        self.client.force_login(self.entry)
        response = self.client.post(reverse('save-book-api'), self.payload('من مدخل', department_id=str(self.dept.pk)))
        self.assertEqual((response.status_code, response.json()['error_code']), (403, 'DEPARTMENT_FORBIDDEN'))
        self.client.force_login(self.root)
        response = self.client.post(reverse('save-book-api'), self.payload('إلى شعبة', department_id=str(self.unit.pk)))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Book.all_objects.count(), before)

    def test_a_confirmation_names_the_department_and_the_number_before_anything_is_spent(self):
        nxt = BookSequence.get_next(KIND, department=self.dept)['formatted']
        self.client.force_login(self.root)
        response = self.client.post(reverse('save-book-api'), self.payload('قبل التأكيد', department_id=str(self.dept.pk)))
        self.assertEqual(response.status_code, 409)
        data = response.json()
        self.assertEqual(data['error_code'], 'CONFIRM_DEPARTMENT')
        for part in ('قسم الهدف', nxt, 'لا يعود'):
            self.assertIn(part, data['message'])
        self.assertFalse(Book.all_objects.filter(title='قبل التأكيد').exists())
        self.assertEqual(BookSequence.get_next(KIND, department=self.dept)['formatted'], nxt)

    def test_confirmed_it_enters_the_targets_register_and_records_it(self):
        nxt = BookSequence.get_next(KIND, department=self.dept)['formatted']
        self.client.force_login(self.root)
        response = self.client.post(reverse('save-book-api'),
                                    self.payload('بعد التأكيد', department_id=str(self.dept.pk), confirm_department='true'))
        self.assertEqual(response.status_code, 201, response.content[:300])
        book = Book.objects.get(title='بعد التأكيد')
        self.assertEqual((book.department, book.our_number), (self.dept, nxt))
        note = BookHistory.objects.get(book=book, action='create').notes
        self.assertIn('قسم الهدف', note)

    def test_without_a_department_nothing_changes(self):
        self.client.force_login(self.root)
        response = self.client.post(reverse('save-book-api'), self.payload('بلا هدف'))
        self.assertEqual(response.status_code, 201, response.content[:300])
        self.assertEqual(Book.objects.get(title='بلا هدف').department, self.home)


class SaveIntoTargetEdgesTests(DeptEntryCase):
    """حدودٌ سمّاها فيبل: لا عدّادَ أعمى، ولا حجزَ من دفترٍ آخر، ولا قسمَ معطَّل، والدفترُ الأوّل ثابت."""

    def test_a_system_admin_without_a_department_must_name_one(self):
        root = User.objects.create_superuser('d_root_nodept', password='pw-dept-1111')
        counters = list(BookSequence.objects.values_list('pk', 'next_number'))
        self.client.force_login(root)
        response = self.client.post(reverse('save-book-api'), self.payload('بلا قسم ولا هدف'))
        self.assertEqual((response.status_code, response.json()['error_code']), (400, 'DEPARTMENT_REQUIRED'))
        self.assertEqual(list(BookSequence.objects.values_list('pk', 'next_number')), counters)

    def test_a_reservation_with_a_target_is_refused(self):
        self.client.force_login(self.root)
        response = self.client.post(reverse('save-book-api'),
                                    self.payload('حجزٌ وهدف', department_id=str(self.dept.pk), reservation_id='7',
                                                 auto_number='false', confirm_department='true'))
        self.assertEqual((response.status_code, response.json()['error_code']), (400, 'RESERVATION_WITH_DEPARTMENT'))

    def test_an_inactive_target_is_refused_and_nothing_moves(self):
        counters = list(BookSequence.objects.values_list('pk', 'next_number'))
        self.client.force_login(self.root)
        response = self.client.post(reverse('save-book-api'),
                                    self.payload('إلى معطَّل', department_id=str(self.off.pk), confirm_department='true'))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(list(BookSequence.objects.values_list('pk', 'next_number')), counters)

    def test_the_home_register_stays_put(self):
        home_next = BookSequence.get_next(KIND, department=self.home)['formatted']
        self.client.force_login(self.root)
        self.client.post(reverse('save-book-api'),
                         self.payload('في دفتر الهدف', department_id=str(self.dept.pk), confirm_department='true'))
        self.assertTrue(Book.objects.filter(title='في دفتر الهدف', department=self.dept).exists())
        self.assertEqual(BookSequence.get_next(KIND, department=self.home)['formatted'], home_next)
