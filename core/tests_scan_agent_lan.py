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
from unittest import mock

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

REMOTE = '172.16.2.50'          # كاتبةٌ على الشبكة المحلّيّة
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
        self.assertFalse(request_is_loopback(self._req('172.16.2.50')))
        # الفرقُ عن ``is_lan_peer`` هو بيتُ القصيد: هذا يقبل كلَّ الشبكة الخاصّة
        self.assertTrue(is_lan_peer(self._req('172.16.2.50')))

    def test_forwarded_header_is_ignored(self):
        from core.netaddr import request_is_loopback
        r = self._req('172.16.2.50', HTTP_X_FORWARDED_FOR='127.0.0.1')
        self.assertFalse(request_is_loopback(r))

    def test_garbage_address_is_not_loopback(self):
        from core.netaddr import is_lan_peer, request_is_loopback
        self.assertFalse(request_is_loopback(self._req('not-an-ip')))
        self.assertFalse(is_lan_peer(self._req('')))

    def test_network_views_alias_still_points_at_the_same_rule(self):
        from core import network_views
        from core.netaddr import is_lan_peer
        self.assertIs(network_views._is_lan_peer, is_lan_peer)
