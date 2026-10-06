# -*- coding: utf-8 -*-
"""اختبارات وكيل المسح المحلي (مستقلة عن Django).

التشغيل:  python -m unittest scan_agent.tests_agent

يغطّي:
  - naps2: تحليل الأجهزة، نجاح/فشل المسح (returncode + حجم الملف)، القوائم
    البيضاء، قصّ DPI — عبر mock لـ subprocess (بلا ماسح حقيقي).
  - server: فحص Origin (403)، التوكِن (401)، health بلا توكِن (200)، OPTIONS (204).
"""
import os
import subprocess
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

from . import config, naps2, server


def _fake_run_writes_pdf(cmd, *a, **k):
    """side_effect لـ subprocess.run: يكتب محتوى لملف -o ويُعيد نجاحاً."""
    if '-o' in cmd:
        out = cmd[cmd.index('-o') + 1]
        with open(out, 'wb') as f:
            f.write(b'%PDF-1.4 fake scan')
    return mock.Mock(returncode=0, stdout='', stderr='')


class Naps2Tests(unittest.TestCase):
    def setUp(self):
        # إن لم يكن NAPS2 مثبّتاً على جهاز الاختبار، زيّف موقعه (نُموّه subprocess أصلاً)
        if not naps2.locate_exe():
            p = mock.patch.object(naps2, 'locate_exe', return_value=r'C:\fake\NAPS2.Console.exe')
            p.start()
            self.addCleanup(p.stop)

    def test_list_devices_parses_nonblank_lines(self):
        res = mock.Mock(returncode=0, stdout='Canon A\nCanon B\n\n', stderr='')
        with mock.patch('subprocess.run', return_value=res):
            self.assertEqual(naps2.list_devices('twain'), ['Canon A', 'Canon B'])

    def test_list_devices_empty_ok(self):
        res = mock.Mock(returncode=0, stdout='', stderr='')
        with mock.patch('subprocess.run', return_value=res):
            self.assertEqual(naps2.list_devices('wia'), [])

    def test_list_devices_rejects_bad_driver(self):
        with self.assertRaises(ValueError):
            naps2.list_devices('evil')

    def test_scan_success_returns_nonempty_path(self):
        with mock.patch('subprocess.run', side_effect=_fake_run_writes_pdf):
            path = naps2.scan_to_pdf('Dev', source='feeder', dpi=300, color='color', driver='twain')
        try:
            self.assertTrue(os.path.isfile(path))
            self.assertGreater(os.path.getsize(path), 0)
        finally:
            naps2.safe_remove(path)

    def test_scan_fails_on_nonzero_returncode(self):
        res = mock.Mock(returncode=1, stdout='', stderr='driver failure')
        with mock.patch('subprocess.run', return_value=res):
            with self.assertRaises(RuntimeError):
                naps2.scan_to_pdf('Dev')

    def test_scan_fails_on_empty_output(self):
        # rc=0 لكن لا ملف يُكتب → الحجم 0 → فشل (يلتقط فخّ NAPS2)
        res = mock.Mock(returncode=0, stdout='', stderr='')
        with mock.patch('subprocess.run', return_value=res):
            with self.assertRaises(RuntimeError):
                naps2.scan_to_pdf('Dev')

    def test_scan_rejects_whitelist_violations(self):
        for bad in ({'driver': 'x'}, {'source': 'x'}, {'color': 'x'}):
            with self.assertRaises(ValueError):
                naps2.scan_to_pdf('Dev', **bad)

    def test_scan_requires_device(self):
        with self.assertRaises(ValueError):
            naps2.scan_to_pdf('')

    def test_dpi_clamped_to_range(self):
        self.assertEqual(naps2._clamp_dpi(99999), config.DPI_MAX)
        self.assertEqual(naps2._clamp_dpi(1), config.DPI_MIN)
        with self.assertRaises(ValueError):
            naps2._clamp_dpi('not-a-number')


def _make_fake_run(behavior):
    """side_effect لـ subprocess.run يحاكي سلوكاً لكل مصدر.

    behavior: dict مصدر→('success'|'nopages'|'error'). الافتراضي 'nopages'.
    """
    def fake_run(cmd, *a, **k):
        source = cmd[cmd.index('--source') + 1] if '--source' in cmd else '?'
        out = cmd[cmd.index('-o') + 1] if '-o' in cmd else None
        kind = behavior.get(source, 'nopages')
        if kind == 'success':
            if out:
                with open(out, 'wb') as f:
                    f.write(b'%PDF-1.4 fake scan ' + source.encode())
            return mock.Mock(returncode=0, stdout='scanned 1 page', stderr='')
        if kind == 'nopages':
            # فخّ NAPS2: rc=0 لكن لا ملف + رسالة "No scanned pages to export"
            return mock.Mock(returncode=0, stdout='Beginning scan...',
                             stderr='0 page(s) scanned. No scanned pages to export.')
        return mock.Mock(returncode=1, stdout='', stderr='device error')
    return fake_run


class Naps2AutoScanTests(unittest.TestCase):
    """المسح الأوتوماتيكي: cascade المصادر + حلّ خطأ 0 صفحات."""

    def setUp(self):
        if not naps2.locate_exe():
            p = mock.patch.object(naps2, 'locate_exe', return_value=r'C:\fake\NAPS2.Console.exe')
            p.start()
            self.addCleanup(p.stop)

    def test_auto_falls_back_to_glass_when_feeder_empty(self):
        # وجهان فشل، وجه فارغ، الزجاج ينجح — يحاكي مستنداً على الزجاج
        fake = _make_fake_run({'duplex': 'nopages', 'feeder': 'nopages', 'glass': 'success'})
        with mock.patch('subprocess.run', side_effect=fake):
            path = naps2.scan_to_pdf_auto('Dev', driver='twain')
        try:
            self.assertTrue(os.path.isfile(path))
            with open(path, 'rb') as f:
                self.assertIn(b'glass', f.read())   # نجح عبر الزجاج
        finally:
            naps2.safe_remove(path)

    def test_auto_uses_duplex_first_when_available(self):
        fake = _make_fake_run({'duplex': 'success', 'feeder': 'success', 'glass': 'success'})
        with mock.patch('subprocess.run', side_effect=fake):
            path = naps2.scan_to_pdf_auto('Dev', driver='twain')
        try:
            with open(path, 'rb') as f:
                self.assertIn(b'duplex', f.read())  # المصدر الأغنى أولاً
        finally:
            naps2.safe_remove(path)

    def test_auto_raises_helpful_error_when_all_sources_empty(self):
        fake = _make_fake_run({})  # الكل nopages
        with mock.patch('subprocess.run', side_effect=fake):
            with self.assertRaises(RuntimeError) as cm:
                naps2.scan_to_pdf_auto('Dev', driver='twain')
        self.assertNotIsInstance(cm.exception, naps2.ScanNoPagesError)
        self.assertIn('الماسح', str(cm.exception))

    def test_auto_fails_fast_on_device_error_no_retry(self):
        """خطأ تعريف/عتاد صلب (-4400/-4539) يفشل فوراً بلا تجريب بقيّة المصادر — يمنع تكرار الحواريّات."""
        res = mock.Mock(returncode=1, stdout='', stderr='Scanner is not ready. (Power may have been cycled.) (-4400)')
        with mock.patch('subprocess.run', return_value=res) as m:
            with self.assertRaises(naps2.ScanDeviceError):
                naps2.scan_to_pdf_auto('Dev', driver='twain')
        self.assertEqual(m.call_count, 1)   # محاولة واحدة فقط — لا cascade على المصادر الثلاثة

    def test_auto_requires_device(self):
        with self.assertRaises(ValueError):
            naps2.scan_to_pdf_auto('')

    def test_auto_rejects_bad_color(self):
        with self.assertRaises(ValueError):
            naps2.scan_to_pdf_auto('Dev', color='evil')

    def test_no_pages_marker_detection(self):
        self.assertTrue(naps2._is_no_pages('0 page(s) scanned. No scanned pages to export.'))
        self.assertTrue(naps2._is_no_pages('No pages'))
        self.assertFalse(naps2._is_no_pages('scanned 3 pages ok'))

    def test_no_pages_no_false_positive_on_multi_digit(self):
        # تراجع #10: «0 page» يجب ألا يطابق «10 pages»/«100 pages»
        self.assertFalse(naps2._is_no_pages('10 page(s) scanned. ok'))
        self.assertFalse(naps2._is_no_pages('100 pages exported'))
        self.assertTrue(naps2._is_no_pages('Scanned 0 pages'))

    def test_timeout_fails_fast_not_cascaded(self):
        # تراجع #4: مهلة المسح تُفشِل فوراً (ScanTimeoutError) بلا تكرار على المصادر
        calls = []

        def fake_run(cmd, *a, **k):
            calls.append(cmd[cmd.index('--source') + 1] if '--source' in cmd else '?')
            raise subprocess.TimeoutExpired(cmd, k.get('timeout', 1))

        with mock.patch('subprocess.run', side_effect=fake_run):
            with self.assertRaises(naps2.ScanTimeoutError):
                naps2.scan_to_pdf_auto('Dev', driver='twain')
        self.assertEqual(len(calls), 1)   # مصدر واحد فقط — لا cascade على المهلة


class ServerAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.AGENT_TOKEN = 'testtok'
        cls.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.base = 'http://127.0.0.1:%d' % cls.port
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def _open(self, path, method='GET', headers=None):
        req = urllib.request.Request(self.base + path, method=method, headers=headers or {})
        try:
            r = urllib.request.urlopen(req, timeout=5)
            return r.status, r.read().decode('utf-8', 'ignore')
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode('utf-8', 'ignore')

    def test_health_no_token_ok(self):
        status, _ = self._open('/agent/health')
        self.assertEqual(status, 200)

    def test_devices_without_token_401(self):
        status, _ = self._open('/agent/devices')
        self.assertEqual(status, 401)

    def test_devices_with_token_ok(self):
        with mock.patch.object(naps2, 'list_devices', return_value=[]):
            status, body = self._open('/agent/devices', headers={'X-LetterSys-Token': 'testtok'})
        self.assertEqual(status, 200)
        self.assertIn('devices', body)

    def test_scan_without_token_401(self):
        status, _ = self._open('/agent/scan', method='POST', headers={'Content-Type': 'application/json'})
        self.assertEqual(status, 401)

    def test_bad_origin_rejected_403(self):
        status, _ = self._open('/agent/health', headers={'Origin': 'http://evil.example'})
        self.assertEqual(status, 403)

    def test_allowed_origin_ok(self):
        status, _ = self._open('/agent/health', headers={'Origin': 'http://127.0.0.1:8000'})
        self.assertEqual(status, 200)

    def test_options_preflight_204(self):
        status, _ = self._open('/agent/scan', method='OPTIONS', headers={'Origin': 'http://127.0.0.1:8000'})
        self.assertEqual(status, 204)

    def test_unknown_path_404(self):
        status, _ = self._open('/agent/nope', headers={'X-LetterSys-Token': 'testtok'})
        self.assertEqual(status, 404)


if __name__ == '__main__':
    unittest.main()
