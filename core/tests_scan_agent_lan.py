# -*- coding: utf-8 -*-
"""
جسرُ المسح على الشبكة المحلّيّة — عقدُ نقطتَي الوكيل في Django.

الوكيلُ يعمل على **جهاز المستخدم** (يشغّل ماسحَه) ويستمع على حلقته المحلّيّة وحدَها،
فالخادمُ لا يعرف عنه شيئاً. وهذا يفرض ثلاثة أشياء تُقاس هنا:

1. ``agent-info`` لا يقرأ قرصاً ولا يفحص منفذاً ولا يُعيد توكِناً ولا ``available`` —
   لا يدّعي ما لا يستطيع رؤيتَه (وكيلُ الخادم هو الجهازُ الخطأ لكلّ صفحةٍ بعيدة).
2. ``agent-start`` يُرفض إلّا من حلقة الخادم المحلّيّة — كان ``login_required`` وحدَه،
   فكانت أيُّ كاتبةٍ على الشبكة تُولِّد عمليّةً على الخادم (بلا نفعٍ لها أصلاً).
3. المسارُ القديم ``agent-token/`` انتهى إلى 404: نقطةٌ اسمُها «توكِن» ولا تُعيد توكِناً
   مصيدةٌ لمن يقرأ الشيفرة بعدنا.
"""
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

# عنوانٌ محجوزٌ للتوثيق (RFC 5737) — والمستودعُ عامّ فلا عنوانَ شركةٍ فيه. وهو
# يخدم القياسَ كما هو: ``ipaddress`` يَعُدّ 192.0.2.0/24 شبكةً خاصّةً، فبقي
# ``is_lan_peer`` صادقاً عليه كما على عنوان كاتبةٍ حقيقيّ.
REMOTE = '192.0.2.50'           # كاتبةٌ على الشبكة المحلّيّة
LOOPBACK = '127.0.0.1'          # كونسولُ الخادم
_PROXY = ('HTTP_X_FORWARDED_PROTO', 'https')

# مصيدةٌ مقيسة: ``settings_test`` يستورد ``settings`` **قبل** أن يرفع ``DEBUG``، فكتلةُ
# الإنتاج تعمل و``SECURE_PROXY_SSL_HEADER`` يبقى مضبوطاً في كلّ اختبار. وضعُ الأسبوع
# الأوّل (كشفٌ مباشرٌ بلا بروكسي) يُصرَّح به هنا، ومرحلةُ Caddy تُقاس باختبارها الخاصّ —
# فلا يخضرّ حارسُ الحلقة المحلّيّة لسببٍ عارضٍ بدل سببه.
@override_settings(SECURE_PROXY_SSL_HEADER=None)
class ScanAgentInfoTests(TestCase):
    def setUp(self):
        self.client = Client()
        User.objects.create_user('u', password='p')
        self.client.login(username='u', password='p')
        self.url = reverse('scan_agent_info')

    def test_remote_gets_agent_url_without_token_or_availability(self):
        r = self.client.get(self.url, REMOTE_ADDR=REMOTE)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(set(data.keys()), {'agent_url', 'port', 'server_can_start'})
        self.assertNotIn('token', data)          # لا سرَّ خادمٍ إلى متصفّحٍ بعيد
        self.assertNotIn('available', data)      # التوفّرُ سؤالُ المتصفّح لا الخادم
        self.assertTrue(data['agent_url'].startswith('http://127.0.0.1:'))
        self.assertEqual(data['agent_url'], 'http://127.0.0.1:%d' % data['port'])
        self.assertFalse(data['server_can_start'])

    def test_loopback_can_start(self):
        r = self.client.get(self.url, REMOTE_ADDR=LOOPBACK)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['server_can_start'])

    @override_settings(SECURE_PROXY_SSL_HEADER=_PROXY)
    def test_behind_proxy_loopback_proves_nothing(self):
        """خلف Caddy يكون REMOTE_ADDR هو البروكسي — فالحلقةُ المحلّيّة لا تُثبت شيئاً."""
        r = self.client.get(self.url, REMOTE_ADDR=LOOPBACK)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()['server_can_start'])

    def test_does_not_read_any_file(self):
        """المسبارُ الحاسم: لو بقيت قراءةُ ملفِّ التوكِن لانفجرت النقطةُ هنا."""
        with mock.patch('builtins.open', side_effect=OSError('no disk reads here')):
            r = self.client.get(self.url, REMOTE_ADDR=REMOTE)
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('token', r.json())

    def test_does_not_probe_the_servers_own_port(self):
        """ولا يفتح مقبساً: مسبارُ الخادم كان يُنتج «جاهز» كاذبةً للكاتبة (جهازٌ آخر)."""
        import socket
        with mock.patch.object(socket, 'create_connection',
                               side_effect=AssertionError('no socket probe')) as m:
            r = self.client.get(self.url, REMOTE_ADDR=REMOTE)
        self.assertEqual(r.status_code, 200)
        m.assert_not_called()

    def test_requires_login(self):
        c = Client()
        r = c.get(self.url, REMOTE_ADDR=LOOPBACK)
        self.assertEqual(r.status_code, 302)

    def test_old_token_endpoint_is_gone(self):
        r = self.client.get('/books/api/scan/agent-token/', REMOTE_ADDR=LOOPBACK)
        self.assertEqual(r.status_code, 404)


@override_settings(SECURE_PROXY_SSL_HEADER=None)
class ScanAgentStartTests(TestCase):
    def setUp(self):
        self.client = Client()
        User.objects.create_user('u', password='p')
        self.client.login(username='u', password='p')
        self.url = reverse('scan_agent_start')

    def test_remote_refused_and_nothing_spawned(self):
        """رمزُ الحالة وحدَه لا يُثبت شيئاً — المُثبِتُ أنّ ``Popen`` لم يُنادَ."""
        with mock.patch('core.views.scan_settings.subprocess.Popen') as popen, \
             mock.patch('core.views.scan_settings._agent_is_alive', return_value=False):
            r = self.client.post(self.url, REMOTE_ADDR=REMOTE)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()['status'], 'remote')
        self.assertFalse(r.json()['ok'])
        popen.assert_not_called()

    def test_remote_refused_before_alive_probe(self):
        """الرفضُ أوّلُ سطر: لا مقبسَ ولا قرصَ قبله."""
        with mock.patch('core.views.scan_settings._agent_is_alive',
                        side_effect=AssertionError('probed before refusing')) as alive:
            r = self.client.post(self.url, REMOTE_ADDR=REMOTE)
        self.assertEqual(r.status_code, 403)
        alive.assert_not_called()

    def test_loopback_launches(self):
        with mock.patch('core.views.scan_settings.subprocess.Popen') as popen, \
             mock.patch('core.views.scan_settings._agent_is_alive', return_value=False):
            r = self.client.post(self.url, REMOTE_ADDR=LOOPBACK)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['status'], 'launching')
        self.assertEqual(popen.call_count, 1)

    def test_loopback_already_running(self):
        with mock.patch('core.views.scan_settings.subprocess.Popen') as popen, \
             mock.patch('core.views.scan_settings._agent_is_alive', return_value=True):
            r = self.client.post(self.url, REMOTE_ADDR=LOOPBACK)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['status'], 'already_running')
        popen.assert_not_called()

    @override_settings(SECURE_PROXY_SSL_HEADER=_PROXY)
    def test_behind_proxy_refused_even_from_loopback(self):
        with mock.patch('core.views.scan_settings.subprocess.Popen') as popen:
            r = self.client.post(self.url, REMOTE_ADDR=LOOPBACK)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()['status'], 'remote')
        popen.assert_not_called()

    def test_requires_login(self):
        c = Client()
        r = c.post(self.url, REMOTE_ADDR=LOOPBACK)
        self.assertEqual(r.status_code, 302)


@override_settings(SECURE_PROXY_SSL_HEADER=None)
class NetAddrHelperTests(TestCase):
    """مصدرٌ وحيدٌ للقاعدة: ``REMOTE_ADDR`` وحدَه، ولا ``X-Forwarded-For`` أبداً."""

    def _req(self, addr, **extra):
        from django.test import RequestFactory
        return RequestFactory().get('/', REMOTE_ADDR=addr, **extra)

    def test_loopback_only_not_whole_lan(self):
        from core.netaddr import is_lan_peer, request_is_loopback
        self.assertTrue(request_is_loopback(self._req('127.0.0.1')))
        self.assertFalse(request_is_loopback(self._req(REMOTE)))
        # الفرقُ عن ``is_lan_peer`` هو بيتُ القصيد: هذا يقبل كلَّ الشبكة الخاصّة
        self.assertTrue(is_lan_peer(self._req(REMOTE)))

    def test_forwarded_header_is_ignored(self):
        from core.netaddr import request_is_loopback
        r = self._req(REMOTE, HTTP_X_FORWARDED_FOR='127.0.0.1')
        self.assertFalse(request_is_loopback(r))

    def test_garbage_address_is_not_loopback(self):
        from core.netaddr import is_lan_peer, request_is_loopback
        self.assertFalse(request_is_loopback(self._req('not-an-ip')))
        self.assertFalse(is_lan_peer(self._req('')))

    def test_network_views_alias_still_points_at_the_same_rule(self):
        from core import network_views
        from core.netaddr import is_lan_peer
        self.assertIs(network_views._is_lan_peer, is_lan_peer)


# ════════════ النصفُ الآخر: ما يفعله المتصفّح ════════════
# النقطةُ الخلفيّة وحدَها لا تُثبت أنّ الميزةَ حيّة: الواجهةُ كانت لا تزال تنادي
# ``agent-token/`` المحذوفة (404) وتُرسل ``X-LetterSys-Token`` التي لم يعد الوكيلُ
# يعلنها في ``Access-Control-Allow-Headers`` — فالطلبُ الاستباقيّ يسقط. هذان الصفّان
# يحرسان الطرفَ الذي لا يراه اختبارُ Django.

class ScanFrontendContractTests(SimpleTestCase):
    """عقدُ مصدرٍ: لا نقطةَ ميّتةً ولا ترويسةَ توكِن في الشيفرة المُشحونة."""

    def _read(self, rel):
        with io.open(str(settings.BASE_DIR / rel), encoding='utf-8') as f:
            return f.read()

    def test_frontend_calls_agent_info_not_the_deleted_endpoint(self):
        for rel in ('static/extraction_smart.js', 'templates/core/scan_settings.html'):
            src = self._read(rel)
            self.assertFalse('agent-token' in src, '%s ما يزال ينادي النقطةَ المحذوفة (404)' % rel)
            self.assertTrue('/books/api/scan/agent-info/' in src, '%s لا يسأل agent-info' % rel)

    def test_frontend_sends_no_token_header(self):
        """الوكيلُ لا يعلن إلّا ``Content-Type``؛ أيُّ ترويسةٍ أخرى تُفشل الطلبَ الاستباقيّ."""
        for rel in ('static/extraction_smart.js', 'templates/core/scan_settings.html'):
            self.assertFalse('X-LetterSys-Token' in self._read(rel), rel)

    def test_browser_probes_the_local_agent_itself(self):
        """المسبارُ على حلقة المتصفّح — لا على منفذ الخادم (وهو الجهازُ الخطأ للكاتبة)."""
        src = self._read('static/extraction_smart.js')
        self.assertTrue("`http://127.0.0.1:${port}`" in src, 'المسبار لا يبني عنوان الحلقة المحلّيّة')
        self.assertTrue("'/agent/health'" in src, 'لا نداءَ /agent/health في الواجهة')


# ملفُّ ``node`` صغيرٌ يحمّل السكربت المُشحون بمُجسَّمات DOM ثمّ يستدعي
# ``_renderAgentHelp`` مرّتين: مرّةً كاتبةً على الشبكة ومرّةً كونسولَ الخادم.
_HELP_HARNESS = r"""
const fs = require('fs');
const vm = require('vm');
const els = {
  scanAgentHelp: { innerHTML: '', hidden: true, addEventListener() {}, setAttribute() {},
                   querySelector: () => null, contains: () => false },
  scanAgentStatus: { dataset: { state: 'unavailable' }, addEventListener() {},
                     setAttribute() {}, textContent: '', title: '' },
};
global.document = {
  readyState: 'loading', cookie: '', addEventListener() {},
  getElementById: (id) => els[id] || null,
  querySelector: () => null, querySelectorAll: () => [],
  createElement: () => ({ style: {}, dataset: {}, appendChild() {}, setAttribute() {} }),
  body: { appendChild() {} },
};
global.window = global;
global.location = { origin: 'http://192.0.2.10:8000', search: '', pathname: '/' };
global.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
global.sessionStorage = global.localStorage;
global.navigator = { userAgent: 'node' };
global.fetch = () => Promise.reject(new Error('no network in this probe'));
global.AbortController = class { constructor() { this.signal = {}; } abort() {} };

const src = fs.readFileSync(process.argv[2], 'utf8');
vm.runInThisContext(src + '\n;globalThis.__ESS = ExtractionSmartSystem;',
                    { filename: 'extraction_smart.js' });

function render(canStart) {
  const self = { _scanDevices: [], _agentServerCanStart: canStart, _positionAgentHelp() {} };
  els.scanAgentHelp.innerHTML = '';
  globalThis.__ESS.prototype._renderAgentHelp.call(self, 'unavailable');
  return els.scanAgentHelp.innerHTML;
}
const remote = render(false), consoleSide = render(true);
console.log(JSON.stringify({
  remote_has_start: remote.includes('data-action="start"'),
  console_has_start: consoleSide.includes('data-action="start"'),
  remote_has_recheck: remote.includes('data-action="recheck"'),
  remote_tells_her_own_pc: remote.includes('هذا الجهاز'),
}));
"""


@unittest.skipUnless(shutil.which('node'), 'node غير متوفّر — اختبارُ سلوكِ الواجهة يُتجاوَز')
class ScanHelpPanelButtonTests(SimpleTestCase):
    """سلوكٌ حقيقيّ (لا عقدُ نصٍّ): زرُّ «شغّل الوكيل الآن» لكونسول الخادم وحدَه.

    الكاتبةُ على الشبكة لو ضغطته لولّدت عمليّةً على **الخادم** — بلا ماسحٍ لها هناك،
    والخادمُ يرفضها بـ403 أصلاً. فالزرُّ وعدٌ كاذب، ووجودُه هو العطب.
    """

    def test_start_button_only_on_the_server_console(self):
        js = str(settings.BASE_DIR / 'static' / 'extraction_smart.js')
        tmp = tempfile.mkdtemp()
        try:
            harness = os.path.join(tmp, 'help_harness.js')
            with io.open(harness, 'w', encoding='utf-8') as f:
                f.write(_HELP_HARNESS)
            out = subprocess.run([shutil.which('node'), harness, js],
                                 capture_output=True, text=True, encoding='utf-8', timeout=120)
            self.assertEqual(out.returncode, 0, out.stderr)
            got = json.loads(out.stdout.strip().splitlines()[-1])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertFalse(got['remote_has_start'],
                         'زرُّ تشغيل الوكيل ظهر لكاتبةٍ على الشبكة (server_can_start=false)')
        self.assertTrue(got['console_has_start'], 'الزرُّ غاب عن كونسول الخادم')
        self.assertTrue(got['remote_has_recheck'], 'لا زرَّ «إعادة الفحص» للكاتبة')
        self.assertTrue(got['remote_tells_her_own_pc'],
                        'رسالةُ الكاتبة لا تقول لها إنّ الوكيلَ يُشغَّل على حاسبتها')
