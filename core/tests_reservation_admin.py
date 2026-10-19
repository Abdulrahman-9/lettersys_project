from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import BookNumberReservation


class ReservationAdminReportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser('reservation-admin', password='test-only')
        cls.writer = User.objects.create_user('reservation-writer')

    def _reservation(self, number, *, status, assigned_at, expires_at=None,
                     cooldown_until=None, is_recycled=False, reserved_days_ago=0):
        now = timezone.now()
        reservation = BookNumberReservation.objects.create(
            user=self.writer,
            kind='incoming_internal',
            number=number,
            year=now.year,
            formatted=str(number),
            status=status,
            assigned_at=assigned_at,
            expires_at=expires_at or now + timedelta(hours=1),
            cooldown_until=cooldown_until,
            is_recycled=is_recycled,
            last_heartbeat=assigned_at,
        )
        if reserved_days_ago:
            BookNumberReservation.objects.filter(pk=reservation.pk).update(
                reserved_at=now - timedelta(days=reserved_days_ago))
        return reservation

    def test_report_is_read_only_and_shows_current_assignment_age(self):
        now = timezone.now()
        active = self._reservation(
            1, status=BookNumberReservation.STATUS_ACTIVE,
            assigned_at=now - timedelta(hours=2))
        stale = self._reservation(
            2, status=BookNumberReservation.STATUS_ACTIVE,
            assigned_at=now - timedelta(days=1),
            expires_at=now - timedelta(minutes=1))
        cooldown = self._reservation(
            3, status=BookNumberReservation.STATUS_COOLDOWN,
            assigned_at=now - timedelta(days=10),
            cooldown_until=now + timedelta(minutes=5),
            is_recycled=True, reserved_days_ago=10)
        old_assignment_unknown = self._reservation(
            4, status=BookNumberReservation.STATUS_USED,
            assigned_at=None, reserved_days_ago=2)

        self.client.force_login(self.admin)
        response = self.client.get(reverse('admin_panel'), {
            'tab': 'reservations',
            'days': '7',
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['reservation_summary']['active'], 1)
        self.assertEqual(response.context['reservation_summary']['overdue_active'], 1)
        self.assertEqual(response.context['reservation_summary']['cooldown'], 1)
        self.assertEqual(response.context['reservation_summary']['recycled'], 1)
        self.assertContains(response, '2 ساعة')
        self.assertContains(response, 'انتهت المهلة — بانتظار التنظيف')
        self.assertContains(response, 'غير متاح — حجز سابق لإضافة تتبّع الإسناد')
        self.assertContains(response, cooldown.formatted)
        self.assertNotContains(response, 'client_key')
        self.assertNotContains(response, 'session_key')
        self.assertNotContains(response, 'تشكيلُ العناقيد')
        self.assertIn('no-store', response['Cache-Control'])

        for reservation, status, assignment in (
            (active, BookNumberReservation.STATUS_ACTIVE, active.assigned_at),
            (stale, BookNumberReservation.STATUS_ACTIVE, stale.assigned_at),
            (cooldown, BookNumberReservation.STATUS_COOLDOWN, cooldown.assigned_at),
            (old_assignment_unknown, BookNumberReservation.STATUS_USED, None),
        ):
            reservation.refresh_from_db()
            self.assertEqual(reservation.status, status)
            self.assertEqual(reservation.assigned_at, assignment)

    def test_only_superusers_can_open_reservation_report(self):
        self.client.force_login(self.writer)
        response = self.client.get(reverse('admin_panel'), {'tab': 'reservations'})
        self.assertEqual(response.status_code, 403)

    def test_days_are_allowlisted_and_recent_history_is_paged(self):
        now = timezone.now()
        for number in range(1, 52):
            self._reservation(
                number,
                status=BookNumberReservation.STATUS_USED,
                assigned_at=now - timedelta(days=number % 5),
            )
        self.client.force_login(self.admin)

        first = self.client.get(reverse('admin_panel'), {
            'tab': 'reservations', 'days': '999',
        })
        second = self.client.get(reverse('admin_panel'), {
            'tab': 'reservations', 'days': '30', 'page': '2',
        })

        self.assertEqual(first.context['reservation_days'], 7)
        self.assertEqual(first.context['reservation_page'].paginator.count, 51)
        self.assertEqual(first.context['reservation_page'].number, 1)
        self.assertEqual(second.context['reservation_days'], 30)
        self.assertEqual(second.context['reservation_page'].number, 2)
        self.assertEqual(len(second.context['reservation_rows']), 1)
