"""
الترقيم لكلّ قسم — المرحلة أ/3 (قرار المالك: لكلّ قسمٍ دفتر ختمه).

كان العدّاد واحداً لكلّ نوعٍ على مستوى النظام (`kind` فريد)، وقيدُ التفرّد
`(our_number, kind)` عالميّاً — فقسمان لا يستطيعان إصدار الرقم نفسه ولو كان
لكلٍّ منهما دفترُه الورقيّ المستقلّ.
"""

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from core.models import Book, BookSequence, Department, UserProfile
from core.reservation_service import reserve_number


class SequencePerDepartmentTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.d1 = Department.objects.create(name='المتابعة', code='ن-ش13')
        cls.d2 = Department.objects.create(name='العقود', code='ن-ش5')

    def test_each_department_has_its_own_counter(self):
        a = BookSequence.consume_next('incoming_internal', department=self.d1)
        b = BookSequence.consume_next('incoming_internal', department=self.d2)
        self.assertEqual(a['number'], b['number'], 'العدّادان تشاركا الرقم بدل أن يستقلّا')

    def test_counters_advance_independently(self):
        for _ in range(3):
            BookSequence.consume_next('incoming_internal', department=self.d1)
        self.assertEqual(BookSequence.get_next('incoming_internal', self.d1)['number'], 4)
        self.assertEqual(BookSequence.get_next('incoming_internal', self.d2)['number'], 1)

    def test_missing_department_falls_back_to_default(self):
        """المسارات القديمة لا تعرف القسم — تسقط إلى الافتراضيّ لا إلى خطأ."""
        info = BookSequence.get_next('incoming_internal')
        self.assertIsNotNone(info['number'])

    def test_numberless_still_consumes_nothing(self):
        before = BookSequence.get_next('incoming_internal', self.d1)['number']
        BookSequence.consume_next('incoming_internal', numberless=True, department=self.d1)
        self.assertEqual(BookSequence.get_next('incoming_internal', self.d1)['number'], before)


class ReservationPerDepartmentTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.followup, _ = Department.objects.get_or_create(
            code='ش13', defaults={'name': 'المتابعة'})
        cls.licensing, _ = Department.objects.get_or_create(
            code='ش4', defaults={'name': 'التراخيص'})
        cls.followup_user = User.objects.create_user('followup-clerk', password='pw-test-111')
        cls.licensing_user = User.objects.create_user('licensing-clerk', password='pw-test-222')
        UserProfile.objects.update_or_create(
            user=cls.followup_user, defaults={'department': cls.followup})
        UserProfile.objects.update_or_create(
            user=cls.licensing_user, defaults={'department': cls.licensing})

    def test_reservations_consume_the_users_department_counter(self):
        BookSequence.objects.update_or_create(
            department=self.followup, kind='incoming_internal',
            defaults={'next_number': 3917})
        first, _ = reserve_number(self.followup_user, 'incoming_internal')
        second, _ = reserve_number(self.licensing_user, 'incoming_internal')

        self.assertEqual(first.department, self.followup)
        self.assertEqual(first.number, 3917)
        self.assertEqual(second.department, self.licensing)
        self.assertEqual(second.number, 1)

    def test_status_preview_uses_the_users_department_counter(self):
        BookSequence.objects.update_or_create(
            department=self.followup, kind='incoming_internal',
            defaults={'next_number': 3917})
        BookSequence.objects.update_or_create(
            department=self.licensing, kind='incoming_internal',
            defaults={'next_number': 4})
        self.client.force_login(self.licensing_user)

        response = self.client.get(
            reverse('reservation-status'), {'kind': 'incoming_internal'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['preview_number'], '4')

    def test_next_number_api_uses_the_users_department_counter(self):
        BookSequence.objects.update_or_create(
            department=self.followup, kind='incoming_internal',
            defaults={'next_number': 3917})
        BookSequence.objects.update_or_create(
            department=self.licensing, kind='incoming_internal',
            defaults={'next_number': 7})
        self.client.force_login(self.licensing_user)

        response = self.client.get(
            reverse('next-number-api'), {'kind': 'incoming_internal'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['formatted'], '7')

    def test_manual_register_has_no_preview_or_reservation(self):
        self.client.force_login(self.licensing_user)

        preview = self.client.get(
            reverse('reservation-status'), {'kind': 'outgoing_external'})
        reserve = self.client.post(
            reverse('reservation-reserve'),
            data='{"kind":"outgoing_external"}',
            content_type='application/json',
        )

        self.assertEqual(preview.status_code, 200)
        self.assertTrue(preview.json()['manual_number'])
        self.assertEqual(preview.json()['preview_number'], '')
        self.assertEqual(reserve.status_code, 400)
        self.assertEqual(reserve.json()['error_code'], 'MANUAL_REGISTER')


class UniquenessIsScopedToDepartmentTests(TestCase):
    """جوهرُ القرار: الرقم نفسه في قسمين مشروع، وتكراره داخل القسم ممنوع."""

    @classmethod
    def setUpTestData(cls):
        cls.d1 = Department.objects.create(name='المتابعة', code='ق-ش13')
        cls.d2 = Department.objects.create(name='العقود', code='ق-ش5')
        cls.user = User.objects.create_user('clerk', password='pw-clerk-111')

    def _book(self, dept, number='2433'):
        return Book.objects.create(kind='incoming_internal', title='كتاب',
                                   created_by=self.user, department=dept, our_number=number)

    def test_same_number_in_two_departments_is_allowed(self):
        self._book(self.d1)
        self._book(self.d2)   # لا يجوز أن يرمي
        self.assertEqual(Book.objects.filter(our_number='2433').count(), 2)

    def test_duplicate_inside_one_department_is_refused(self):
        self._book(self.d1)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._book(self.d1)

    def test_deleted_book_frees_its_number(self):
        """القيد ما زال يستثني المحذوف: موظّفٌ يصحّح خطأه بإعادة الرقم."""
        first = self._book(self.d1)
        first.is_deleted = True
        first.save(update_fields=['is_deleted'])
        self._book(self.d1)   # لا يجوز أن يرمي
        self.assertEqual(Book.all_objects.filter(our_number='2433').count(), 2)
