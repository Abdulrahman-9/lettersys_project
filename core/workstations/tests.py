import hashlib
import json
import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Workstation


class WorkstationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model()
        cls.user = users.objects.create_user(username='workstation-owner')
        cls.other = users.objects.create_user(username='another-owner')
        cls.staff = users.objects.create_user(username='data-admin', is_staff=True)
        cls.admin = users.objects.create_superuser(username='device-admin', password='test-only')

    def setUp(self):
        self.client.force_login(self.user)
        self.client_uuid = str(uuid.uuid4())

    def enroll(self, **overrides):
        payload = dict(client_uuid=self.client_uuid, name='Mail Desk', machine_name='PC-TEST')
        payload.update(overrides)
        return self.client.post(
            reverse('workstation_enroll'), json.dumps(payload),
            content_type='application/json', secure=True,
        )

    def beat(self, token, **overrides):
        payload = dict(
            client_uuid=self.client_uuid, agent_version='1.1.0', naps2_available=True,
            scanner_state='ready', scanner_names=['Test Scanner'], scanner_age_seconds=0,
        )
        payload.update(overrides)
        return self.client.post(
            reverse('workstation_heartbeat'), json.dumps(payload),
            content_type='application/json', secure=True, HTTP_AUTHORIZATION='Bearer ' + token,
        )

    def test_enrollment_is_immediate_but_not_online_until_agent_confirms(self):
        response = self.enroll()
        self.assertEqual(response.status_code, 200)
        data = response.json()
        device = Workstation.objects.get()
        self.assertEqual(device.owner, self.user)
        self.assertEqual(device.connection_state, 'pairing')
        self.assertEqual(device.token_hash, hashlib.sha256(data['token'].encode()).hexdigest())
        self.assertNotIn(data['token'], repr(device.__dict__))
        self.assertEqual(self.beat(data['token']).status_code, 200)
        device.refresh_from_db()
        self.assertEqual(device.connection_state, 'online')
        self.assertEqual(device.current_scanner_state, 'ready')

    def test_anonymous_and_http_cannot_register(self):
        self.client.logout()
        self.assertEqual(self.enroll().status_code, 302)
        self.client.force_login(self.user)
        with self.assertLogs('lettersys', level='WARNING'):
            response = self.client.post(
                reverse('workstation_enroll'), '{}', content_type='application/json'
            )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Workstation.objects.exists())

    def test_csrf_guard_cannot_be_bypassed_with_a_device_token(self):
        token = self.enroll().json()['token']
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.user)
        response = browser.post(reverse('workstation_enroll'), '{}',
                                content_type='application/json', secure=True,
                                HTTP_AUTHORIZATION='Bearer ' + token)
        self.assertEqual(response.status_code, 403)

    def test_names_and_status_have_strict_shapes(self):
        for overrides in (
            {'name': ''}, {'name': 'x' * 81}, {'name': 'bad\nname'},
            {'client_uuid': 'not-a-uuid'}, {'replace': 'yes'}, {'owner': self.other.pk},
        ):
            with self.subTest(overrides=overrides), self.assertLogs('lettersys', level='WARNING'):
                self.assertEqual(self.enroll(**overrides).status_code, 400)
        token = self.enroll().json()['token']
        for overrides in (
            {'naps2_available': 'true'}, {'scanner_names': 'scanner'},
            {'scanner_names': []}, {'scanner_age_seconds': None},
            {'client_uuid': str(uuid.uuid4())}, {'scanner_state': 'scanned_and_uploaded'},
        ):
            with self.subTest(overrides=overrides), self.assertLogs('lettersys', level='WARNING'):
                self.assertEqual(self.beat(token, **overrides).status_code, 400)
        self.assertIsNone(Workstation.objects.get().last_seen)

    def test_other_owner_cannot_take_uuid_and_name_collision_is_explicit(self):
        self.enroll()
        self.client.force_login(self.other)
        with self.assertLogs('lettersys', level='WARNING'):
            self.assertEqual(self.enroll(replace=True).status_code, 409)
            self.assertEqual(self.enroll(client_uuid=str(uuid.uuid4()), name='mail desk').status_code, 409)
        self.assertEqual(Workstation.objects.get().owner, self.user)

    def test_repair_requires_explicit_replacement_and_rotates_token(self):
        old = self.enroll().json()['token']
        with self.assertLogs('lettersys', level='WARNING'):
            self.assertEqual(self.enroll().status_code, 409)
        new = self.enroll(replace=True).json()['token']
        self.assertNotEqual(old, new)
        with self.assertLogs('lettersys', level='WARNING'):
            self.assertEqual(self.beat(old).status_code, 401)
        self.assertEqual(self.beat(new).status_code, 200)
        self.assertEqual(Workstation.objects.count(), 1)

    def test_admin_revocation_cannot_be_bypassed_by_owner(self):
        token = self.enroll().json()['token']
        device = Workstation.objects.get()
        self.client.force_login(self.admin)
        response = self.client.post(reverse('workstation_revoke', args=[device.pk]), secure=True)
        self.assertEqual(response.status_code, 200)
        self.client.force_login(self.user)
        response = self.client.post(reverse('workstation_revoke', args=[device.pk]), secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Workstation.objects.get(pk=device.pk).blocked_by_admin)
        with self.assertLogs('lettersys', level='WARNING'):
            self.assertEqual(self.beat(token).status_code, 401)
            self.assertEqual(self.enroll(replace=True).status_code, 403)
        self.client.force_login(self.admin)
        self.client.post(reverse('workstation_unblock', args=[device.pk]), secure=True)
        with self.assertLogs('lettersys', level='WARNING'):
            self.assertEqual(self.beat(token).status_code, 401)
        self.client.force_login(self.user)
        self.assertEqual(self.enroll(replace=True).status_code, 200)

    def test_inactive_user_and_expired_tokens_cannot_heartbeat(self):
        token = self.enroll().json()['token']
        get_user_model().objects.filter(pk=self.user.pk).update(is_active=False)
        with self.assertLogs('lettersys', level='WARNING'):
            self.assertEqual(self.beat(token).status_code, 401)
        get_user_model().objects.filter(pk=self.user.pk).update(is_active=True)
        Workstation.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        with self.assertLogs('lettersys', level='WARNING'):
            self.assertEqual(self.beat(token).status_code, 401)

    def test_pairing_expiry_online_ttl_and_scanner_staleness(self):
        token = self.enroll().json()['token']
        Workstation.objects.update(token_issued_at=timezone.now() - timedelta(minutes=11))
        with self.assertLogs('lettersys', level='WARNING'):
            self.assertEqual(self.beat(token).status_code, 401)
        Workstation.objects.update(token_issued_at=timezone.now())
        self.beat(token)
        Workstation.objects.update(scanner_checked_at=timezone.now() - timedelta(minutes=11))
        self.assertEqual(Workstation.objects.select_related('owner').get().current_scanner_state, 'unknown')
        Workstation.objects.update(last_seen=timezone.now() - timedelta(seconds=91))
        device = Workstation.objects.select_related('owner').get()
        self.assertEqual(device.connection_state, 'offline')
        self.assertEqual(device.current_scanner_state, 'unknown')

    def test_tokens_never_create_browser_sessions_or_document_access(self):
        token = self.enroll().json()['token']
        self.client.logout()
        for name in ('workstation_mine', 'workstation_status', 'device_setup_download'):
            self.assertEqual(self.client.get(reverse(name), secure=True,
                                            HTTP_AUTHORIZATION='Bearer ' + token).status_code, 302)
        with self.assertLogs('lettersys', level='WARNING'):
            self.assertEqual(self.client.post(reverse('workstation_heartbeat'), '{}',
                                             content_type='application/json',
                                             HTTP_AUTHORIZATION='Bearer ' + token).status_code, 403)

    def test_board_is_system_admin_only_and_mine_is_owner_scoped(self):
        self.enroll()
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse('workstation_mine')).json()['devices'], [])
        device = Workstation.objects.get()
        self.assertEqual(self.client.post(reverse('workstation_revoke', args=[device.pk]),
                                          secure=True).status_code, 403)
        for user in (self.user, self.staff):
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse('workstation_board')).status_code, 403)
            self.assertEqual(self.client.get(reverse('workstation_status')).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('workstation_board')).status_code, 200)
        response = self.client.get(reverse('workstation_status'))
        self.assertEqual(len(response.json()['devices']), 1)
        self.assertNotIn('token', response.content.decode())
        self.assertIn('no-store', response.headers['Cache-Control'])
