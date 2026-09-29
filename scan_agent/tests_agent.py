# -*- coding: utf-8 -*-
"""اختبارات وكيل المسح المحلي (مستقلة عن Django).

التشغيل:  python -m unittest scan_agent.tests_agent

يغطّي:
  - naps2: تحليل الأجهزة، نجاح/فشل المسح (returncode + حجم الملف)، القوائم
    البيضاء، قصّ DPI — عبر mock لـ subprocess (بلا ماسح حقيقي).
  - server: بوّابةُ Host (الارتباطُ المُعاد) وبوّابةُ Origin (مَن يُشغّل الماسح)
    والطلبُ الاستباقيّ وإسقاطُ التوكِن — عبر http.client كي تُضبَط ترويسةُ Host.
  - config: قائمةُ الأصول من agent.json على محطّة العمل + تقنينُ الأصل.
"""
import http.client
import io
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock

from . import config, naps2, server
from . import __version__ as VERSION


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


class ServerGateTests(unittest.TestCase):
    """بوّابتا الوكيل: Host (الارتباطُ المُعاد) و Origin (مَن يُشغّل الماسح).

    الطلباتُ تُبنى بـ``http.client`` منخفضِ المستوى لأنّ ترويسةَ Host هي موضعُ القياس:
    ``urllib`` يفرضها تلقائيّاً ولا يسمح بحذفها. ولا شيءَ هنا يُنفّذ CORS (لا متصفّح)،
    فكلُّ ما يُؤكَّد رمزٌ أو ترويسةٌ — سلوكُ المتصفّح نفسه يُقاس في المتصفّح.
    """

    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        # قائمةٌ صريحةٌ للقياس: أصلٌ باسمٍ على المنفذ الضمنيّ 80 وأصلٌ بـIP:منفذ.
        p = mock.patch.object(config, 'ALLOWED_ORIGINS',
                              {('http', '192.0.2.10', 8000), ('http', 'lettersys', 80)})
        p.start()
        self.addCleanup(p.stop)
        # سجلُّ الأصول المرفوضة إلى مجلّدٍ مؤقّت وstderr مُعلَّق — لا نكتب في بيانات المستخدم
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        for patcher in (mock.patch.dict(os.environ, {'LOCALAPPDATA': tmp}),
                        mock.patch('sys.stderr', io.StringIO())):
            patcher.start()
            self.addCleanup(patcher.stop)
        server._LOGGED_ORIGINS.clear()

    ALLOWED = 'http://192.0.2.10:8000'

    def _req(self, path, method='GET', headers=None, host=None, send_host=True, body=None):
        """(status, body, headers) — ``host=None`` يعني المضيفَ الصحيح، و``send_host=False``
        يحذف الترويسةَ تماماً."""
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        try:
            conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            if send_host:
                conn.putheader('Host', host or ('127.0.0.1:%d' % self.port))
            for k, v in (headers or {}).items():
                conn.putheader(k, v)
            data = body.encode('utf-8') if isinstance(body, str) else body
            if data is not None:
                conn.putheader('Content-Length', str(len(data)))
            conn.endheaders(data)
            r = conn.getresponse()
            return r.status, r.read().decode('utf-8', 'ignore'), dict(r.getheaders())
        finally:
            conn.close()

    # ═══════ بوّابةُ Host — الارتباطُ المُعاد ═══════
    def test_host_attacker_name_rejected_403(self):
        st, body, hdrs = self._req('/agent/health', host='evil.example:%d' % self.port,
                                   headers={'Origin': self.ALLOWED})
        self.assertEqual(st, 403)
        self.assertIn('bad_host', body)
        self.assertNotIn('Access-Control-Allow-Origin', hdrs)   # ولا حتى لأصلٍ مسموح

    def test_host_loopback_suffix_rejected_403(self):
        st, body, _ = self._req('/agent/health', host='127.0.0.1.evil.example:%d' % self.port)
        self.assertEqual(st, 403)
        self.assertIn('bad_host', body)

    def test_host_wrong_port_rejected_403(self):
        # المنفذُ الخطأ يُشتقّ من المنفذ الحقيقيّ: ثابتٌ مثل 9999 قد يكون هو المنفذَ
        # العابر الذي رُبِط في هذه الدورة، فيخضرّ الاختبارُ أو يحمرّ بالحظّ.
        wrong = self.port + 1 if self.port < 65535 else self.port - 1
        st, body, _ = self._req('/agent/health', host='127.0.0.1:%d' % wrong)
        self.assertEqual(st, 403)
        self.assertIn('bad_host', body)

    def test_host_missing_rejected_403(self):
        st, body, _ = self._req('/agent/health', send_host=False)
        self.assertEqual(st, 403)
        self.assertIn('bad_host', body)

    def test_host_localhost_accepted(self):
        st, body, _ = self._req('/agent/health', host='localhost:%d' % self.port)
        self.assertEqual(st, 200)
        self.assertIn('naps2_available', body)

    def test_host_gate_applies_to_options(self):
        st, _, hdrs = self._req('/agent/scan', method='OPTIONS',
                                host='evil.example:%d' % self.port,
                                headers={'Origin': self.ALLOWED,
                                         'Access-Control-Request-Method': 'POST'})
        self.assertEqual(st, 403)
        self.assertNotIn('Access-Control-Allow-Origin', hdrs)

    def test_host_gate_applies_to_devices(self):
        with mock.patch.object(naps2, 'list_devices', return_value=[]) as m:
            st, _, _ = self._req('/agent/devices', host='evil.example:%d' % self.port,
                                 headers={'Origin': self.ALLOWED})
        self.assertEqual(st, 403)
        m.assert_not_called()

    # ═══════ بوّابةُ Origin — مَن يُشغّل الماسح ═══════
    def test_devices_requires_origin_403_before_naps2(self):
        """بلا Origin (‎<img src>‎ · تنقّلٌ علويّ · no-cors GET): يُرفض قبل سردِ الأجهزة —
        فلا يُحجَز خيطٌ ستّين ثانيةً (هذا ما كان التوكِنُ يسدّه، بـ401)."""
        with mock.patch.object(naps2, 'list_devices', return_value=[]) as m:
            st, body, hdrs = self._req('/agent/devices')
        self.assertEqual(st, 403)
        self.assertIn('origin_not_allowed', body)
        self.assertNotIn('Access-Control-Allow-Origin', hdrs)
        m.assert_not_called()

    def test_scan_requires_origin_403(self):
        st, body, _ = self._req('/agent/scan', method='POST',
                                headers={'Content-Type': 'application/json'}, body='{}')
        self.assertEqual(st, 403)
        self.assertIn('origin_not_allowed', body)

    def test_origin_null_rejected_403(self):
        """‎iframe‎ معزولٌ أو file:// أو data: يرسل ``Origin: null`` — ليس في القائمة."""
        st, _, _ = self._req('/agent/devices', headers={'Origin': 'null'})
        self.assertEqual(st, 403)

    def test_bad_origin_rejected_403(self):
        st, _, hdrs = self._req('/agent/health', headers={'Origin': 'http://evil.example'})
        self.assertEqual(st, 403)
        self.assertNotIn('Access-Control-Allow-Origin', hdrs)

    def test_allowed_origin_ok(self):
        st, _, hdrs = self._req('/agent/health', headers={'Origin': self.ALLOWED})
        self.assertEqual(st, 200)
        self.assertEqual(hdrs.get('Access-Control-Allow-Origin'), self.ALLOWED)
        self.assertEqual(hdrs.get('Vary'), 'Origin')

    def test_origin_implicit_port_80_matches_named_entry(self):
        """المتصفّحُ يحذف ‎:80‎ من الأصل — ``http://lettersys`` = ``http://lettersys:80``."""
        st, _, hdrs = self._req('/agent/health', headers={'Origin': 'http://lettersys'})
        self.assertEqual(st, 200)
        self.assertEqual(hdrs.get('Access-Control-Allow-Origin'), 'http://lettersys')

    def test_origin_case_insensitive_host(self):
        st, _, hdrs = self._req('/agent/health', headers={'Origin': 'http://LETTERSYS'})
        self.assertEqual(st, 200)
        # ACAO هو **مدخلُ القائمة المُقنَّن**، لا نصُّ الترويسة الخامّ الذي أرسله العميل.
        self.assertEqual(hdrs.get('Access-Control-Allow-Origin'), 'http://lettersys')

    def test_acao_never_echoes_the_raw_request_header(self):
        """صيغةٌ مُقنَّنةٌ أخرى للأصل نفسِه (شرطةٌ ختاميّة): تُقبَل ويُعاد مدخلُ القائمة."""
        st, _, hdrs = self._req('/agent/health', headers={'Origin': 'http://LetterSys:80/'})
        self.assertEqual(st, 200)
        self.assertEqual(hdrs.get('Access-Control-Allow-Origin'), 'http://lettersys')

    def test_origin_suffix_attack_rejected(self):
        """مساواةُ tuple لا بادئةً: ``…:8000.evil.com`` مضيفٌ آخرُ تماماً."""
        st, _, _ = self._req('/agent/health',
                             headers={'Origin': 'http://192.0.2.10:8000.evil.com'})
        self.assertEqual(st, 403)

    def test_origin_other_port_rejected(self):
        st, _, _ = self._req('/agent/health', headers={'Origin': 'http://192.0.2.10:8001'})
        self.assertEqual(st, 403)

    def test_health_without_origin_ok(self):
        """curl والتشخيصُ ومسبارُ no-cors: بلا Origin ⟵ 200 (بلا آثارٍ غيرِ locate_exe)."""
        st, body, hdrs = self._req('/agent/health')
        self.assertEqual(st, 200)
        self.assertIn('naps2_available', body)
        self.assertNotIn('Access-Control-Allow-Origin', hdrs)

    def test_health_with_disallowed_origin_403(self):
        st, body, hdrs = self._req('/agent/health', headers={'Origin': 'http://evil.example'})
        self.assertEqual(st, 403)
        self.assertIn('origin_not_allowed', body)
        self.assertNotIn('Access-Control-Allow-Origin', hdrs)

    def test_devices_with_allowed_origin_and_no_token_ok(self):
        """بديلُ ``test_devices_without_token_401``: لا توكِنَ بعد اليوم — الأصلُ هو البوّابة."""
        with mock.patch.object(naps2, 'list_devices', return_value=[]):
            st, body, hdrs = self._req('/agent/devices', headers={'Origin': self.ALLOWED})
        self.assertEqual(st, 200)
        self.assertIn('devices', body)
        self.assertEqual(hdrs.get('Access-Control-Allow-Origin'), self.ALLOWED)

    def test_scan_error_json_carries_cors(self):
        """خطأُ الوكيل يجب أن يُقرأ في الصفحة (نصٌّ عربيٌّ مفيد) ⟵ ACAO على الخطأ أيضاً."""
        st, body, hdrs = self._req('/agent/scan', method='POST',
                                   headers={'Origin': self.ALLOWED,
                                            'Content-Type': 'application/json'}, body='{}')
        self.assertEqual(st, 400)
        self.assertIn('no_device', body)
        self.assertEqual(hdrs.get('Access-Control-Allow-Origin'), self.ALLOWED)

    # ═══════ الطلبُ الاستباقيّ (preflight) ═══════
    def test_options_preflight_204(self):
        st, _, hdrs = self._req('/agent/scan', method='OPTIONS',
                                headers={'Origin': self.ALLOWED,
                                         'Access-Control-Request-Method': 'POST',
                                         'Access-Control-Request-Headers': 'content-type'})
        self.assertEqual(st, 204)
        self.assertEqual(hdrs.get('Access-Control-Allow-Origin'), self.ALLOWED)
        self.assertEqual(hdrs.get('Access-Control-Allow-Private-Network'), 'true')
        self.assertEqual(hdrs.get('Access-Control-Allow-Headers'), 'Content-Type')
        self.assertNotIn('Token', hdrs.get('Access-Control-Allow-Headers', ''))

    def test_options_disallowed_origin_403(self):
        st, _, hdrs = self._req('/agent/scan', method='OPTIONS',
                                headers={'Origin': 'http://evil.example',
                                         'Access-Control-Request-Method': 'POST'})
        self.assertEqual(st, 403)
        self.assertNotIn('Access-Control-Allow-Origin', hdrs)

    def test_options_without_origin_403(self):
        st, _, _ = self._req('/agent/scan', method='OPTIONS',
                             headers={'Access-Control-Request-Method': 'POST'})
        self.assertEqual(st, 403)

    def test_unknown_path_404(self):
        st, _, _ = self._req('/agent/nope', headers={'Origin': self.ALLOWED})
        self.assertEqual(st, 404)

    # ═══════ أفعالٌ لا مسارَ لها — قبل التوجيه لا بعده ═══════
    def test_unrouted_methods_hit_the_host_gate_first(self):
        """‎PUT/DELETE/PATCH/TRACE‎ كانت تُجاب بـ501 من المكتبة **قبل** حارس Host:
        صفحةُ خطأٍ من عندها، وبترويسة ``Server``، ومن أيّ مضيف. الحارسُ أوّلاً الآن."""
        for method in ('PUT', 'DELETE', 'PATCH', 'TRACE', 'FOO'):
            st, body, hdrs = self._req('/agent/health', method=method,
                                       host='evil.example:%d' % self.port,
                                       headers={'Origin': self.ALLOWED})
            self.assertEqual(st, 403, method)
            self.assertIn('bad_host', body, method)
            self.assertNotIn('Access-Control-Allow-Origin', hdrs)

    def test_unrouted_method_with_good_host_is_405_not_501(self):
        st, body, hdrs = self._req('/agent/scan', method='PUT',
                                   headers={'Origin': self.ALLOWED})
        self.assertEqual(st, 405)
        self.assertIn('method_not_allowed', body)
        self.assertEqual(hdrs.get('Allow'), 'GET, POST, OPTIONS')

    def test_head_is_gated_and_carries_no_body(self):
        st, body, _ = self._req('/agent/health', method='HEAD',
                                host='evil.example:%d' % self.port)
        self.assertEqual(st, 403)
        self.assertEqual(body, '')          # HEAD بلا جسم، والحارسُ مع ذلك ردّ 403
        st, body, _ = self._req('/agent/health', method='HEAD')
        self.assertEqual(st, 405)
        self.assertEqual(body, '')

    def test_server_header_leaks_neither_python_nor_the_agent_version(self):
        """الترويسةُ تُبعَث قبل أيّ حارس، فلا يُقرأ منها إصدارُ مفسّرٍ ولا إصدارُ وكيل."""
        for method, host in (('GET', None), ('PUT', None),
                             ('GET', 'evil.example:%d' % self.port)):
            _, _, hdrs = self._req('/agent/health', method=method, host=host)
            banner = hdrs.get('Server', '')
            self.assertEqual(banner, 'LetterSysScanAgent', '%s %s' % (method, host))
            self.assertNotIn('Python', banner)
            self.assertNotIn(VERSION, banner)

    # ═══════ إسقاطُ التوكِن ═══════
    def test_token_machinery_removed(self):
        for name in ('AGENT_TOKEN', '_load_token'):
            self.assertFalse(hasattr(server, name), 'بقي %s في server' % name)
        self.assertFalse(hasattr(server.Handler, '_token_ok'))
        for name in ('TOKEN_FILE', 'TOKEN_DIR'):
            self.assertFalse(hasattr(config, name), 'بقي %s في config' % name)


class OriginConfigTests(unittest.TestCase):
    """قائمةُ الأصول تأتي من ملفٍّ على محطّة العمل، لا من ثابتٍ في مستودعٍ عامّ."""

    def setUp(self):
        p = mock.patch('sys.stderr', io.StringIO())     # سطرُ الرفض لا يُشوّش مخرَجَ الاختبار
        p.start()
        self.addCleanup(p.stop)
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        p = mock.patch.dict(os.environ, {'LOCALAPPDATA': self.tmp})
        p.start()
        self.addCleanup(p.stop)
        self.cfg = os.path.join(self.tmp, 'LetterSys', 'agent.json')
        os.makedirs(os.path.dirname(self.cfg), exist_ok=True)

    def _write(self, text):
        with open(self.cfg, 'w', encoding='utf-8') as f:
            f.write(text)

    def test_file_with_two_origins_parsed(self):
        self._write('{"allowed_origins": ["http://lettersys", "http://192.0.2.10:8000"]}')
        got = config.load_allowed_origins()
        self.assertEqual(got, {('http', 'lettersys', 80), ('http', '192.0.2.10', 8000)})

    def test_missing_file_falls_back_to_loopback_defaults(self):
        """حالةُ الجهاز الواحد (كونسولُ الخادم/استنساخٌ جديد): تعمل بصفر إعداد كما اليوم."""
        warns = []
        got = config.load_allowed_origins(warnings=warns)
        self.assertEqual(got, {('http', '127.0.0.1', 8000), ('http', 'localhost', 8000)})
        self.assertTrue(warns)

    def test_malformed_json_falls_back_to_defaults(self):
        self._write('{ this is not json')
        warns = []
        got = config.load_allowed_origins(warnings=warns)
        self.assertIn(('http', '127.0.0.1', 8000), got)
        self.assertTrue(warns)

    def test_key_of_wrong_type_falls_back(self):
        self._write('{"allowed_origins": "http://lettersys"}')
        got = config.load_allowed_origins()
        self.assertIn(('http', 'localhost', 8000), got)

    def test_invalid_entries_rejected(self):
        self._write('{"allowed_origins": ["http://*", "lettersys", "http://x/path",'
                    ' "ftp://x", "", "http://good:8000"]}')
        warns = []
        got = config.load_allowed_origins(warnings=warns)
        self.assertEqual(got, {('http', 'good', 8000)})
        self.assertEqual(len(warns), 5)

    def test_trailing_slash_normalised(self):
        self._write('{"allowed_origins": ["http://lettersys/"]}')
        self.assertEqual(config.load_allowed_origins(), {('http', 'lettersys', 80)})

    def test_all_entries_invalid_falls_back_to_defaults(self):
        self._write('{"allowed_origins": ["http://*"]}')
        got = config.load_allowed_origins()
        self.assertIn(('http', '127.0.0.1', 8000), got)

    def test_shipped_defaults_cover_the_single_machine_case(self):
        """الاختبارُ يقرأ المصدرَ الذي تقرأه الشيفرةُ المُشحونة (لا ثابتاً مكرَّراً في
        الاختبار)، فلا تخضرّ الاختباراتُ فوق افتراضٍ فارغٍ — نمطُ «النسخة بلا أوزان»."""
        got = {config.normalize_origin(o) for o in config.DEFAULT_ORIGINS}
        self.assertIn(('http', '127.0.0.1', 8000), got)
        self.assertIn(('http', 'localhost', 8000), got)

    def test_normalize_rejects_control_characters(self):
        self.assertIsNone(config.normalize_origin('http://a\r\nX-Evil: 1'))
        self.assertIsNone(config.normalize_origin('http://a b'))

    def test_rejected_origin_logged_once(self):
        server._LOGGED_ORIGINS.clear()
        server._log_rejected_origin('http://evil.example')
        server._log_rejected_origin('http://evil.example')
        with open(config.log_file(), encoding='utf-8') as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
        self.assertEqual(len(lines), 1)
        self.assertIn('http://evil.example', lines[0])
        self.assertIn('agent.json', lines[0])


@unittest.skipUnless(os.name == 'nt', 'المُثبِّت سكربتُ ويندوز')
class InstallerTests(unittest.TestCase):
    """``install_agent.bat``: لا يُكتَب أصلٌ بلا تحقُّقٍ من شكله وبلا موافقةٍ صريحة.

    كلُّ سطرٍ هنا يشغّل السكربتَ فعلاً بـ``LOCALAPPDATA``/``APPDATA`` مؤقّتَين — فلا
    شيءَ يُكتب في بيانات المستخدم. والسببُ أنّ عقدَ هذا الملفّ لا يُقاس بالقراءة:
    النسخةُ السابقة كانت تكتب ``[\\"http://…\\"]`` (شرطاتٌ خلفيّةٌ حرفيّة) فيسقط
    ``json.load`` ويعود الوكيلُ إلى الحلقة المحلّيّة — قائمةٌ مكتوبةٌ ولا تعمل.
    """

    BAT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'install_agent.bat')
    ORIGIN = 'http://192.0.2.10:8000'

    def _sandbox(self, prefix='ls_inst_'):
        tmp = tempfile.mkdtemp(prefix=prefix)
        self.addCleanup(shutil.rmtree, tmp, True)
        startup = os.path.join(tmp, 'app', 'Microsoft', 'Windows',
                               'Start Menu', 'Programs', 'Startup')
        os.makedirs(startup)
        os.makedirs(os.path.join(tmp, 'local'))
        return tmp, startup

    def _run(self, args, answer, tmp, bat=None):
        env = dict(os.environ)
        env['LOCALAPPDATA'] = os.path.join(tmp, 'local')
        env['APPDATA'] = os.path.join(tmp, 'app')
        env['LETTERSYS_INSTALL_NO_START'] = '1'      # لا وكيلَ حقيقيّاً من الاختبار
        proc = subprocess.run(['cmd', '/c', bat or self.BAT] + list(args), input=answer,
                              capture_output=True, text=True, encoding='utf-8',
                              errors='replace', env=env, timeout=180)
        return proc

    def _json_path(self, tmp):
        return os.path.join(tmp, 'local', 'LetterSys', 'agent.json')

    # ═══════ التحقُّق من شكل الوسيط ═══════
    def test_origin_with_path_is_refused_and_nothing_written(self):
        """«install_agent.bat http://evil.example/x» أُرسل إلى الكاتبة ⟵ لا يُكتَب."""
        tmp, _ = self._sandbox()
        p = self._run(['http://evil.example/x'], 'y\n', tmp)
        self.assertEqual(p.returncode, 2, p.stdout)
        self.assertFalse(os.path.exists(self._json_path(tmp)), 'كُتب agent.json لوسيطٍ غيرِ صالح')

    def test_non_http_scheme_refused(self):
        tmp, _ = self._sandbox()
        for bad in ('file://x', 'ftp://192.0.2.10', 'http://a b'):
            p = self._run([bad], 'y\n', tmp)
            self.assertEqual(p.returncode, 2, '%s قُبل: %s' % (bad, p.stdout))
            self.assertFalse(os.path.exists(self._json_path(tmp)))

    # ═══════ الموافقةُ الصريحة ═══════
    def test_refusal_writes_nothing(self):
        tmp, startup = self._sandbox()
        p = self._run([self.ORIGIN], 'n\n', tmp)
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertFalse(os.path.exists(self._json_path(tmp)), 'كُتب agent.json بعد رفضٍ صريح')
        self.assertEqual(os.listdir(startup), [], 'وُضع اختصارٌ بعد الرفض')

    def test_no_answer_writes_nothing(self):
        """مدخلٌ خالٍ (أنبوبٌ مغلق) ⟵ فشلٌ مغلق: لا كتابةَ بلا «y»."""
        tmp, _ = self._sandbox()
        p = self._run([self.ORIGIN], '', tmp)
        self.assertNotEqual(p.returncode, 0, p.stdout)
        self.assertFalse(os.path.exists(self._json_path(tmp)))

    # ═══════ الناتجُ يعمل فعلاً ═══════
    def test_accepted_file_is_parsed_by_the_agent_itself(self):
        """المقياسُ ليس «كُتب ملفّ» بل «الوكيلُ قرأه»: ``load_allowed_origins`` بلا تحذير."""
        tmp, startup = self._sandbox()
        p = self._run([self.ORIGIN, 'https://SERVER-NAME'], 'y\n', tmp)
        self.assertEqual(p.returncode, 0, p.stdout)
        path = self._json_path(tmp)
        self.assertTrue(os.path.exists(path), p.stdout)
        warns = []
        got = config.load_allowed_origins(path=path, warnings=warns)
        self.assertEqual(got, {('http', '192.0.2.10', 8000), ('https', 'server-name', 443)})
        self.assertEqual(warns, [], 'الوكيلُ لم يقرأ ما كتبه المُثبِّت')
        self.assertIn('LetterSys Scan Agent.lnk', os.listdir(startup))

    def test_shortcut_target_survives_an_apostrophe_in_the_path(self):
        """اسمُ مستخدمٍ فيه فاصلةٌ عليا كان يكسر سطرَ PowerShell فيبقى الهدفُ فارغاً."""
        tmp, startup = self._sandbox(prefix="ls_o'brien_")
        p = self._run([self.ORIGIN], 'y\n', tmp)
        self.assertEqual(p.returncode, 0, p.stdout)
        lnk = os.path.join(startup, 'LetterSys Scan Agent.lnk')
        self.assertTrue(os.path.exists(lnk), p.stdout)
        with open(lnk, 'rb') as f:
            blob = f.read()
        self.assertIn(b'run_agent.bat', blob, 'الاختصارُ أُنشئ بهدفٍ فارغ')

    # ═══════ الاسمُ المفردُ على http يُنبَّه عليه ═══════
    def test_single_label_http_origin_warns_about_spoofing(self):
        tmp, _ = self._sandbox()
        p = self._run(['http://lettersys'], 'n\n', tmp)
        self.assertIn('LLMNR', p.stdout, 'لا تنبيهَ على اسمٍ مفردٍ قابلٍ للانتحال')
        self.assertFalse(os.path.exists(self._json_path(tmp)))

    # ═══════ حزمةُ التوزيع: حاسبةٌ بلا Python ═══════
    def test_distribution_copies_runtime_and_targets_embedded_pythonw(self):
        """من حزمة التوزيع (python\\ بجوار scan_agent\\) ينسخ المُثبِّتُ الاثنين إلى
        LOCALAPPDATA ويوجّه الاختصارَ إلى pythonw المنسوخ بـ«-m scan_agent» — لا إلى
        run_agent.bat الذي يطلب Python مثبَّتاً («Python was not found» على الحاسبة الثانية)."""
        tmp, startup = self._sandbox()
        dist = os.path.join(tmp, 'dist')
        os.makedirs(os.path.join(dist, 'python'))
        with open(os.path.join(dist, 'python', 'pythonw.exe'), 'wb') as f:
            f.write(b'MZ fake runtime')
        pkg = os.path.join(dist, 'scan_agent')
        shutil.copytree(os.path.dirname(self.BAT), pkg, ignore=shutil.ignore_patterns('__pycache__'))
        p = self._run([self.ORIGIN], 'y\n', tmp, bat=os.path.join(pkg, 'install_agent.bat'))
        self.assertEqual(p.returncode, 0, p.stdout)
        agent = os.path.join(tmp, 'local', 'LetterSys', 'agent')
        self.assertTrue(os.path.isfile(os.path.join(agent, 'python', 'pythonw.exe')), p.stdout)
        self.assertTrue(os.path.isfile(os.path.join(agent, 'scan_agent', 'server.py')), p.stdout)
        self.assertFalse(os.path.exists(os.path.join(agent, 'scan_agent', 'tests_agent.py')))
        with open(os.path.join(startup, 'LetterSys Scan Agent.lnk'), 'rb') as f:
            blob = f.read()
        self.assertIn(b'pythonw.exe', blob, 'الاختصارُ لا يشير إلى pythonw المنسوخ')
        self.assertNotIn(b'run_agent.bat', blob)
        self.assertIn('-m scan_agent'.encode('utf-16-le'), blob, 'الاختصارُ بلا «-m scan_agent»')


class WindowlessEntrypointTests(unittest.TestCase):
    """اختصارُ بدء التشغيل يشغّل pythonw: ‏sys.stdout وsys.stderr ‏None."""

    def _localappdata(self):
        tmp = tempfile.mkdtemp(prefix='ls_log_')
        self.addCleanup(shutil.rmtree, tmp, True)
        p = mock.patch.dict(os.environ, {'LOCALAPPDATA': tmp})
        p.start()
        self.addCleanup(p.stop)
        return tmp

    def test_streams_go_to_agent_log_when_windowless(self):
        """بلا التوجيه يرمي ``sys.stderr.write`` (سطرُ الأصل المرفوض) AttributeError فيسقط
        المعالجُ قبل الاستجابة، ويضيع كلُّ print الإقلاع."""
        from . import __main__ as entry
        tmp = self._localappdata()
        with mock.patch.object(sys, 'stdout', None), mock.patch.object(sys, 'stderr', None):
            log = entry.attach_log_when_windowless()
            try:
                sys.stderr.write('rejected-origin-line\n')
                print('startup-line')
            finally:
                log.close()
        with open(os.path.join(tmp, 'LetterSys', 'agent.log'), encoding='utf-8') as f:
            text = f.read()
        self.assertIn('rejected-origin-line', text)
        self.assertIn('startup-line', text)

    def test_console_run_is_left_alone(self):
        from . import __main__ as entry
        tmp = self._localappdata()
        self.assertIsNone(entry.attach_log_when_windowless())
        self.assertFalse(os.path.exists(os.path.join(tmp, 'LetterSys', 'agent.log')))


class StdlibOnlyTests(unittest.TestCase):
    """حزمةُ التوزيع = Python المضمَّن، و``._pth`` يعزل site-packages: أيُّ استيرادٍ من
    خارج المكتبة القياسيّة عند الإقلاع يُسقط الوكيلَ على حاسبة الكاتبة بصمت
    (``fitz`` اختياريٌّ داخل دالّة، فلا يُحسب)."""

    def test_agent_imports_without_site_packages(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        code = ('import sys; sys.path.insert(0, %r); import scan_agent.__main__, '
                'scan_agent.server, scan_agent.naps2, scan_agent.config' % root)
        p = subprocess.run([sys.executable, '-E', '-S', '-c', code],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)


if __name__ == '__main__':
    unittest.main()
