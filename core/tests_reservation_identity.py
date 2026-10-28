import json
from datetime import timedelta

from django.contrib.auth.models import User
from django.conf import settings
from django.test import Client, TestCase, override_settings
from django.urls import path, reverse
from django.utils import timezone

from core.models import BookNumberReservation, BookSequence, Department
from core.reservation_service import reservation_client_key, reserve_number
from core import reservation_api
from core.reservation_identity import COOKIE_NAME, browser_key


KIND = 'incoming_internal'
urlpatterns = [
    path('reserve/', reservation_api.reserve_number, name='reservation-reserve'),
    path('status/', reservation_api.reservation_status, name='reservation-status'),
    path('heartbeat/', reservation_api.reservation_heartbeat, name='reservation-heartbeat'),
    path('void/', reservation_api.void_reservation, name='reservation-void'),
    path('reactivate/', reservation_api.reactivate_reservation, name='reservation-reactivate'),
]


@override_settings(ROOT_URLCONF=__name__)
class ReservationBrowserIdentityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('reservation-writer', password='p')
        self.client.force_login(self.user)

    def reserve(self, client=None):
        response = (client or self.client).post(
            reverse('reservation-reserve'),
            json.dumps({'kind': KIND}), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        return response.json()

    def rotate_session(self):
        session = self.client.session
        session.cycle_key()
        self.client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key

    def test_login_rotation_preserves_the_held_number(self):
        first = self.reserve()['reservation']
        old_session = self.client.session.session_key
        self.rotate_session()
        self.assertNotEqual(self.client.session.session_key, old_session)

        second = self.reserve()

        self.assertEqual(second['reservation']['id'], first['id'])
        self.assertEqual(second['outcome'], 'existing')
        self.assertEqual(BookSequence.get_next(KIND)['number'], 2)

    def test_logout_login_resumes_the_same_browser_cooldown(self):
        first = self.reserve()['reservation']
        reservation = BookNumberReservation.objects.get(pk=first['id'])
        reservation.enter_cooldown(15)
        # Client.logout clears all cookies, unlike an actual browser logout.
        identity = self.client.cookies[COOKIE_NAME].value
        self.client.logout()
        self.client.cookies[COOKIE_NAME] = identity
        self.client.force_login(self.user)

        second = self.reserve()

        self.assertEqual(second['reservation']['id'], first['id'])
        self.assertEqual(second['outcome'], 'resumed')
        self.assertEqual(BookSequence.get_next(KIND)['number'], 2)

    def test_first_request_preserves_session_scoped_legacy_hold(self):
        old, _ = reserve_number(
            self.user, KIND,
            client_key=reservation_client_key(self.client.session.session_key))
        self.assertEqual(self.reserve()['reservation']['id'], old.pk)

    def test_two_browsers_remain_isolated_after_relogin(self):
        other = Client()
        other.force_login(self.user)
        first = self.reserve()['reservation']
        second = self.reserve(other)['reservation']
        self.assertNotEqual(first['number'], second['number'])
        self.rotate_session()
        self.assertEqual(self.reserve()['reservation']['id'], first['id'])
        self.assertEqual(self.reserve(other)['reservation']['id'], second['id'])

    def test_cooldown_is_visible_as_resumable_not_a_different_preview(self):
        first = self.reserve()['reservation']
        BookNumberReservation.objects.get(pk=first['id']).enter_cooldown(15)

        data = self.client.get(
            reverse('reservation-status'), {'kind': KIND}).json()

        self.assertEqual(data['resumable_reservation']['id'], first['id'])
        self.assertNotIn('preview_number', data)
        self.assertFalse(data['has_reservation'])

    def test_heartbeat_resumes_own_cooldown_without_issuing_another_number(self):
        first = self.reserve()['reservation']
        BookNumberReservation.objects.get(pk=first['id']).enter_cooldown(15)

        response = self.client.post(
            reverse('reservation-heartbeat'),
            json.dumps({'reservation_id': first['id']}),
            content_type='application/json')

        self.assertTrue(response.json()['alive'])
        self.assertEqual(response.json()['reservation']['id'], first['id'])
        reservation = BookNumberReservation.objects.get(pk=first['id'])
        self.assertEqual(reservation.status, 'active')
        self.assertEqual(BookSequence.get_next(KIND)['number'], 2)

    def test_heartbeat_does_not_revive_a_recyclable_cooldown(self):
        first = self.reserve()['reservation']
        reservation = BookNumberReservation.objects.get(pk=first['id'])
        reservation.enter_cooldown(15)
        reservation.cooldown_until = timezone.now() - timedelta(seconds=1)
        reservation.save(update_fields=['cooldown_until'])

        response = self.client.post(
            reverse('reservation-heartbeat'),
            json.dumps({'reservation_id': first['id']}),
            content_type='application/json')

        self.assertFalse(response.json()['alive'])
        reservation.refresh_from_db()
        self.assertEqual(reservation.status, 'cooldown')

    def test_status_does_not_allocate_a_reservation(self):
        for _ in range(3):
            response = self.client.get(reverse('reservation-status'), {'kind': KIND})
            self.assertEqual(response.status_code, 200)
        self.assertFalse(BookNumberReservation.objects.exists())
        self.assertEqual(BookSequence.get_next(KIND)['number'], 1)

    def test_signed_cookie_matches_websocket_identity_and_hides_session_key(self):
        self.reserve()
        cookie = self.client.cookies[COOKIE_NAME]
        self.assertTrue(cookie['httponly'])
        self.assertEqual(cookie['samesite'], 'Lax')
        self.assertNotIn(self.client.session.session_key, cookie.value)
        self.assertEqual(
            browser_key({COOKIE_NAME: cookie.value}, 'rotated-session'),
            BookNumberReservation.objects.get().client_key)

    def test_forged_browser_cookie_does_not_claim_another_browsers_hold(self):
        first = self.reserve()['reservation']
        other = Client()
        other.force_login(self.user)
        other.cookies[COOKIE_NAME] = self.client.cookies[COOKIE_NAME].value + 'tampered'
        with self.assertLogs('lettersys', level='WARNING'):
            second = self.reserve(other)['reservation']
        self.assertNotEqual(first['id'], second['id'])

    def test_other_holds_explain_gaps_without_disclosing_owners_or_keys(self):
        first = self.reserve()['reservation']
        other = Client()
        other.force_login(self.user)
        second = self.reserve(other)
        self.assertEqual(second['other_holds'], {
            'count': 1, 'numbers': [first['formatted']],
        })
        data = self.client.get(reverse('reservation-status'), {'kind': KIND}).json()
        self.assertEqual(data['other_holds']['numbers'], [second['reservation']['formatted']])

    def test_same_browser_different_account_does_not_claim_original_users_hold(self):
        first = self.reserve()['reservation']
        another = User.objects.create_user('another-writer')
        self.client.force_login(another)
        second = self.reserve()['reservation']
        self.assertNotEqual(first['id'], second['id'])

    def test_other_department_holds_are_not_disclosed(self):
        department = Department.objects.create(name='Other register', code='other-register')
        reserve_number(self.user, KIND, department=department, client_key='other-browser')
        data = self.client.get(reverse('reservation-status'), {'kind': KIND}).json()
        self.assertEqual(data['other_holds'], {'count': 0, 'numbers': []})

    def test_other_browser_cannot_heartbeat_or_void_the_hold(self):
        first = self.reserve()['reservation']
        other = Client()
        other.force_login(self.user)
        for name in ['reservation-heartbeat', 'reservation-void']:
            response = other.post(
                reverse(name), json.dumps({'reservation_id': first['id']}),
                content_type='application/json')
            self.assertEqual(response.status_code, 404)
        self.assertEqual(BookNumberReservation.objects.get(pk=first['id']).status, 'active')

    def test_heartbeat_does_not_replace_a_newer_active_hold_with_an_old_cooldown(self):
        first = self.reserve()['reservation']
        old = BookNumberReservation.objects.get(pk=first['id'])
        old.enter_cooldown(15)
        # A pre-existing interrupted session can contain both records.
        newer = BookNumberReservation.objects.create(
            user=self.user, department=old.department, kind=KIND,
            number=2, formatted='2', year=old.year,
            client_key=old.client_key, status='active',
            expires_at=timezone.now() + timedelta(minutes=45))
        response = self.client.post(
            reverse('reservation-heartbeat'),
            json.dumps({'reservation_id': old.pk}), content_type='application/json')
        self.assertFalse(response.json()['alive'])
        newer.refresh_from_db()
        self.assertEqual(newer.status, 'active')
