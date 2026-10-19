import http.client
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from . import config, server, workstation

ORIGIN = 'https://lettersys.test'


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.env = mock.patch.dict(os.environ, LOCALAPPDATA=self.folder.name)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.origins = mock.patch.object(config, 'ALLOWED_ORIGINS', {config.normalize_origin(ORIGIN)})
        self.origins.start()
        self.addCleanup(self.origins.stop)
        self.monitor = workstation.DeviceMonitor()

    def payload(self):
        return dict(
            client_uuid=self.monitor.data['client_uuid'], server_origin=ORIGIN,
            name='Test Desk', token='a' * 43, pair_nonce=self.monitor.nonce,
        )

    @unittest.skipUnless(os.name == 'nt', 'Windows DPAPI')
    def test_real_dpapi_roundtrip_and_no_plaintext_token(self):
        value = b'test-device-credential'
        protected = workstation._protect(value)
        self.assertNotIn(value, protected)
        self.assertEqual(workstation._protect(protected, decrypt=True), value)
        with mock.patch.object(self.monitor, 'check_server', return_value=True):
            self.monitor.pair(self.payload(), ORIGIN)
        contents = self.monitor.path.read_text(encoding='utf-8')
        self.assertNotIn('a' * 43, contents)
        self.assertNotIn('protected_token', self.monitor.public_status())

    def test_identity_is_stable_and_invalid_identity_is_not_silently_replaced(self):
        self.assertEqual(workstation.DeviceMonitor().data['client_uuid'], self.monitor.data['client_uuid'])
        self.monitor.path.write_text('{"bad":true}', encoding='utf-8')
        with self.assertLogs(workstation.logger, level='ERROR'), self.assertRaises(OSError):
            workstation.DeviceMonitor()

    def test_pairing_rejects_origin_server_identity_and_nonce_before_storage(self):
        for field, value in (
            ('server_origin', 'https://evil.test'), ('client_uuid', 'another-device'),
            ('pair_nonce', 'incorrect'), ('token', 'short'),
        ):
            payload = self.payload()
            payload[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.monitor.pair(payload, ORIGIN)
        with self.assertRaises(ValueError):
            self.monitor.pair(self.payload(), 'http://lettersys.test')
        self.assertNotIn('protected_token', self.monitor.data)

    def test_legacy_unpaired_behavior_and_paired_network_failure_are_distinct(self):
        self.assertTrue(self.monitor.check_server())
        self.monitor.data.update(server_origin=ORIGIN, protected_token='YQ==')
        with mock.patch.object(workstation, '_protect', return_value=b'a' * 43):
            with mock.patch('urllib.request.build_opener') as opener:
                opener.return_value.open.side_effect = OSError('offline')
                with self.assertLogs(workstation.logger, level='ERROR'):
                    self.assertFalse(self.monitor.check_server())
        self.assertTrue(self.monitor.public_status()['error'])
        self.assertIsNone(self.monitor.last_contact)

    def test_redirects_do_not_forward_credentials(self):
        self.assertIsNone(workstation._NoRedirect().redirect_request(
            None, None, 302, '', {}, 'https://another.test'
        ))

    def test_managed_clients_cannot_pull_paper_before_pairing(self):
        Path(config.config_file()).write_text(json.dumps({'require_pairing': True}), encoding='utf-8')
        managed = workstation.DeviceMonitor()
        self.assertFalse(managed.check_server())
        self.assertTrue(managed.public_status()['registration_required'])
        self.assertTrue(managed.public_status()['error'])

    def test_managed_naps2_ignores_old_environment_override_without_legacy_regression(self):
        old = r'C:\old-naps2\NAPS2.Console.exe'
        with mock.patch.dict(os.environ, NAPS2_CONSOLE=old):
            self.assertEqual(config.naps2_candidates()[0], old)
            Path(config.config_file()).write_text('{"require_pairing":true}', encoding='utf-8')
            expected = str(Path(config.__file__).parent / 'naps2_portable' / 'NAPS2.Console.exe')
            self.assertEqual(config.naps2_candidates(), [expected])

    def test_invalid_managed_flag_is_not_treated_as_legacy(self):
        Path(config.config_file()).write_text('{"require_pairing":"true"}', encoding='utf-8')
        with self.assertRaises(ValueError):
            config.naps2_candidates()
        with self.assertLogs(workstation.logger, level='ERROR'), self.assertRaises(OSError):
            workstation.DeviceMonitor()


class PairingEndpointTests(unittest.TestCase):
    def setUp(self):
        self.origins = mock.patch.object(config, 'ALLOWED_ORIGINS', {config.normalize_origin(ORIGIN)})
        self.origins.start()
        self.addCleanup(self.origins.stop)
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        self.httpd.device_monitor = mock.Mock()
        self.httpd.device_monitor.public_status.return_value = {'ok': True, 'client_uuid': 'example'}
        self.httpd.device_monitor.pair.return_value = {'ok': True, 'paired': True}
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join()

    def request(self, method, path, headers=None, body=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.httpd.server_port)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response.status, json.loads(data) if data else {}

    def test_pairing_requires_host_origin_json_and_non_simple_header(self):
        good = {'Origin': ORIGIN, 'Content-Type': 'application/json', 'X-LetterSys-Pairing': '1'}
        for headers, expected in (
            ({}, 403), ({**good, 'Origin': 'https://evil.test'}, 403),
            ({**good, 'Host': 'evil.test'}, 403),
            ({'Origin': ORIGIN, 'Content-Type': 'application/json'}, 400),
            ({**good, 'Content-Type': 'application/x-www-form-urlencoded'}, 400),
        ):
            with self.subTest(headers=headers):
                self.assertEqual(self.request('POST', '/agent/workstation/pair', headers, '{}')[0], expected)
        self.httpd.device_monitor.pair.assert_not_called()
        self.assertEqual(self.request('POST', '/agent/workstation/pair', good, '{}')[0], 200)
        self.httpd.device_monitor.pair.assert_called_once()

    def test_identity_is_not_readable_without_an_allowed_origin(self):
        self.assertEqual(self.request('GET', '/agent/workstation')[0], 403)
        self.assertEqual(self.request('GET', '/agent/workstation', {'Origin': ORIGIN})[0], 200)

    def test_server_outage_prevents_paper_scan_on_paired_devices(self):
        self.httpd.device_monitor.check_server.return_value = False
        with mock.patch.object(server.naps2, 'scan_to_pdf_auto') as scan:
            status, body = self.request('POST', '/agent/scan', {'Origin': ORIGIN}, '{}')
        self.assertEqual(status, 503)
        self.assertEqual(body['code'], 'server_unavailable')
        scan.assert_not_called()
