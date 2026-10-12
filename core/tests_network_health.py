from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from core.models import NetworkNode, NetworkSettings


class NetworkHealthViewTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(
            username='network-staff',
            password='test-password',
            is_staff=True,
        )
        self.client.force_login(self.staff)
        self.config = NetworkSettings.get()
        self.config.app_port = 8765
        self.config.save(update_fields=['app_port'])

    def test_devices_endpoint_requires_staff_access(self):
        regular_user = User.objects.create_user(
            username='regular-user',
            password='test-password',
        )
        self.client.force_login(regular_user)

        response = self.client.get('/books/api/network/devices/')

        self.assertEqual(response.status_code, 403)

    @patch('core.network_views._get_local_ip', return_value='192.168.1.16')
    def test_delete_protects_current_device_using_live_identity(self, _get_ip):
        current = NetworkNode.objects.create(
            name='Current device',
            ip_address='192.168.1.16',
            app_port=1312,
            is_current=False,
        )

        response = self.client.post(
            f'/books/api/network/device/{current.pk}/delete/',
            SERVER_PORT='1312',
        )

        self.assertEqual(response.status_code, 400)
        self.assertTrue(NetworkNode.objects.filter(pk=current.pk).exists())
        _get_ip.assert_called_once_with()

    @patch('core.network_views._get_local_ip', return_value='192.168.1.16')
    def test_delete_allows_removing_node_with_stale_current_flag(self, _get_ip):
        stale_current = NetworkNode.objects.create(
            name='Previous device identity',
            ip_address='192.168.1.20',
            app_port=1312,
            is_current=True,
        )

        response = self.client.post(
            f'/books/api/network/device/{stale_current.pk}/delete/',
            SERVER_PORT='1312',
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(NetworkNode.objects.filter(pk=stale_current.pk).exists())
        _get_ip.assert_called_once_with()

    @patch('core.network_views._get_local_ip', return_value='192.168.1.16')
    def test_devices_reports_local_request_and_stale_nodes_accurately(self, _get_ip):
        old_seen = timezone.now() - timedelta(hours=70)
        current = NetworkNode.objects.create(
            name='Current device',
            ip_address='192.168.1.16',
            app_port=1312,
            is_online=False,
            last_seen=old_seen,
        )
        stale = NetworkNode.objects.create(
            name='Stale device',
            ip_address='192.168.1.20',
            app_port=8000,
            is_online=True,
            last_seen=old_seen,
        )
        page_response = self.client.get(
            '/books/settings/network/',
            SERVER_PORT='1312',
        )
        self.assertEqual(page_response.status_code, 200)
        self.assertContains(page_response, 'غير محدّث')
        self.assertContains(page_response, 'أنا')

        recent = NetworkNode.objects.create(
            name='Recent device',
            ip_address='192.168.1.21',
            app_port=8000,
            is_online=True,
            last_seen=timezone.now(),
        )

        response = self.client.get(
            '/books/api/network/devices/',
            SERVER_PORT='1312',
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        devices = {device['id']: device for device in data['devices']}
        self.assertTrue(data['database']['is_online'])
        self.assertTrue(devices[current.pk]['is_current'])
        self.assertTrue(devices[current.pk]['is_online'])
        self.assertFalse(devices[current.pk]['is_stale'])
        self.assertFalse(devices[stale.pk]['is_online'])
        self.assertTrue(devices[stale.pk]['is_stale'])
        self.assertFalse(NetworkNode.objects.get(pk=stale.pk).is_online)
        self.assertTrue(devices[recent.pk]['is_online'])
        self.assertFalse(devices[recent.pk]['is_stale'])
        self.assertIsInstance(data['active_sessions'], int)
        self.assertEqual(_get_ip.call_count, 2)

    @patch('core.network_views._get_local_ip', return_value='192.168.1.16')
    def test_ping_all_checks_other_devices_and_returns_live_results(
        self,
        _get_ip,
    ):
        current = NetworkNode.objects.create(
            name='Current device',
            ip_address='192.168.1.16',
            app_port=1312,
            is_online=False,
        )
        remote = NetworkNode.objects.create(
            name='Remote device',
            ip_address='192.168.1.20',
            app_port=8000,
        )

        def update_status(node, is_online, ping_ms):
            node.is_online = is_online
            node.last_ping_ms = ping_ms

        with patch(
            'core.network_views._ping_node',
            return_value={'ping_ms': 12},
        ), patch(
            'core.models.NetworkNode.update_status',
            new=update_status,
        ):
            response = self.client.post(
                '/books/api/network/ping-all/',
                SERVER_PORT='1312',
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['checked'], 1)
        self.assertEqual(data['online'], 1)
        self.assertEqual(data['results'][0]['id'], remote.pk)
        self.assertEqual(data['results'][0]['status'], 'online')
        self.assertTrue(data['results'][0]['is_online'])
        self.assertFalse(NetworkNode.objects.get(pk=current.pk).is_online)
        _get_ip.assert_called_once_with()

    @patch('core.network_views._get_local_ip', return_value='192.168.1.16')
    @patch('core.network_views._ping_node', side_effect=RuntimeError('probe failed'))
    def test_ping_all_reports_probe_errors_separately_from_offline_devices(
        self,
        _ping_node,
        _get_ip,
    ):
        NetworkNode.objects.create(
            name='Remote device',
            ip_address='192.168.1.20',
            app_port=8000,
        )

        response = self.client.post(
            '/books/api/network/ping-all/',
            SERVER_PORT='1312',
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['online'], 0)
        self.assertEqual(data['offline'], 0)
        self.assertEqual(data['errors'], 1)
        self.assertEqual(data['results'][0]['status'], 'error')
        _ping_node.assert_called_once()
        _get_ip.assert_called_once_with()
