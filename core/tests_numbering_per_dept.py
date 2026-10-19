"""
الترقيم لكلّ قسم — المرحلة أ/3 (قرار المالك: لكلّ قسمٍ دفتر ختمه).

كان العدّاد واحداً لكلّ نوعٍ على مستوى النظام (`kind` فريد)، وقيدُ التفرّد
`(our_number, kind)` عالميّاً — فقسمان لا يستطيعان إصدار الرقم نفسه ولو كان
لكلٍّ منهما دفترُه الورقيّ المستقلّ.
"""

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse

from core.models import (
    Book, BookNumberReservation, BookSequence, Department, UserProfile,
)
from core.reservation_service import reservation_client_key, reserve_number


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

    def test_repeated_reservation_request_reuses_the_live_hold(self):
        first, outcome = reserve_number(self.licensing_user, 'incoming_internal')
        second, second_outcome = reserve_number(
            self.licensing_user, 'incoming_internal')

        self.assertEqual(outcome, 'new')
        self.assertEqual(second_outcome, 'existing')
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(
            BookNumberReservation.objects.filter(
                user=self.licensing_user,
                department=self.licensing,
                kind='incoming_internal',
                status__in=['active', 'reactivated'],
            ).count(),
            1,
        )

    def test_recycling_never_takes_another_departments_number(self):
        foreign, _ = reserve_number(self.licensing_user, 'incoming_internal')
        foreign.mark_voided()
        BookSequence.objects.update_or_create(
            department=self.followup, kind='incoming_internal',
            defaults={'next_number': 3920})

        own, outcome = reserve_number(self.followup_user, 'incoming_internal')

        self.assertEqual((own.number, outcome), (3920, 'new'))
        foreign.refresh_from_db()
        self.assertEqual(foreign.department, self.licensing)
        self.assertEqual(foreign.status, BookNumberReservation.STATUS_VOIDED)

    def test_reserve_ignores_client_supplied_department(self):
        self.client.force_login(self.followup_user)
        response = self.client.post(
            reverse('reservation-reserve'),
            data={'kind': 'incoming_internal', 'department_id': self.licensing.pk},
            content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['reservation']['department_id'], self.followup.pk)

    def test_same_login_on_two_browsers_gets_distinct_live_holds(self):
        first_client = Client()
        second_client = Client()
        first_client.force_login(self.followup_user)
        second_client.force_login(self.followup_user)

        first = first_client.post(
            reverse('reservation-reserve'),
            data='{"kind":"incoming_internal"}',
            content_type='application/json',
        ).json()['reservation']
        first_again = first_client.post(
            reverse('reservation-reserve'),
            data='{"kind":"incoming_internal"}',
            content_type='application/json',
        ).json()['reservation']
        second = second_client.post(
            reverse('reservation-reserve'),
            data='{"kind":"incoming_internal"}',
            content_type='application/json',
        ).json()['reservation']

        self.assertEqual(first['id'], first_again['id'])
        self.assertNotEqual(first['id'], second['id'])
        self.assertNotEqual(first['number'], second['number'])
        self.assertEqual(
            BookNumberReservation.objects.filter(
                user=self.followup_user,
                department=self.followup,
                kind='incoming_internal',
                status__in=['active', 'reactivated'],
            ).count(),
            2,
        )
        reservations = BookNumberReservation.objects.filter(
            user=self.followup_user, status='active').order_by('id')
        self.assertTrue(all(len(r.client_key) == 64 for r in reservations))

    def test_reservation_status_is_isolated_per_browser_session(self):
        first_client = Client()
        second_client = Client()
        first_client.force_login(self.followup_user)
        second_client.force_login(self.followup_user)
        reserve_response = first_client.post(
            reverse('reservation-reserve'),
            data='{"kind":"incoming_internal"}',
            content_type='application/json',
        )
        reserved = reserve_response.json()['reservation']

        own_status = first_client.get(
            reverse('reservation-status'), {'kind': 'incoming_internal'})
        other_status = second_client.get(
            reverse('reservation-status'), {'kind': 'incoming_internal'})

        self.assertEqual(own_status.json()['reservation']['id'], reserved['id'])
        self.assertFalse(other_status.json()['has_reservation'])
        self.assertEqual(other_status.json()['preview_number'], '2')

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
