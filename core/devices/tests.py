"""«الشبكة والأجهزة»: الكودُ والخادمُ والمحاولاتُ والبوّابةُ والشريط — حارسٌ لكلّ قاعدة."""
import hashlib
import re
import shutil
import tempfile
from datetime import timedelta
from pathlib import Path

from django.contrib.auth.models import User
from django.core.management import call_command
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.base import SessionBase
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import resolve, reverse
from django.utils import timezone

from . import service
from .models import BrowserDevice, DeviceAttempt, DevicePolicy, PairingCode


class DevicesTestBase(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.code_file = self.tmp / 'declare.txt'
        patcher = override_settings(DEVICES_DECLARE_CODE_FILE=str(self.code_file))
        patcher.enable()
        self.addCleanup(patcher.disable)
        self.admin = User.objects.create_superuser('boss', password='p')
        self.server = Client()
        self.server.force_login(self.admin)

    def user_client(self, name='clerk'):
        user = User.objects.create_user(name, password='p')
        client = Client()
        client.force_login(user)
        return user, client

    def declare(self, client=None, name='الخادم'):
        client = client or self.server
        self.assertEqual(client.post(reverse('device_declare_start')).status_code, 200)
        code = re.search(r'server code: (\d{8})', self.code_file.read_text(encoding='utf-8')).group(1)
        res = client.post(reverse('device_declare_finish'), {'code': code, 'name': name},
                          content_type='application/json')
        self.assertEqual(res.status_code, 200, res.content)
        return res

    def issue(self, client=None, device=None):
        body = {'device': str(device.pk)} if device else {}
        res = (client or self.server).post(reverse('device_issue_code'), body, content_type='application/json')
        return res

    def device_of(self, client):
        token = client.cookies[service.COOKIE_NAME].value
        return BrowserDevice.objects.get(token_hash=service.hash_token(token))

    def join(self, client, code, name='استقبال-3', has_scanner=True):
        return client.post(reverse('device_join_finish'),
                           {'code': code, 'name': name, 'has_scanner': has_scanner},
                           content_type='application/json')


class ServerDeclarationTests(DevicesTestBase):
    def test_the_code_is_written_on_the_server_disk_never_in_the_reply(self):
        res = self.server.post(reverse('device_declare_start'))
        self.assertEqual(res.status_code, 200)
        code = re.search(r'(\d{8})', self.code_file.read_text(encoding='utf-8')).group(1)
        self.assertNotIn(code, res.content.decode())
        self.assertNotEqual(DevicePolicy.get().declare_code_hash, code)

    def test_declaring_makes_this_browser_the_server_and_clears_the_file(self):
        self.declare()
        pol = DevicePolicy.get()
        device = self.device_of(self.server)
        self.assertEqual(pol.server_id, device.pk)
        self.assertTrue(device.is_active)
        self.assertEqual(self.code_file.read_text(encoding='utf-8'), '')
        self.assertEqual(pol.declare_code_hash, '')

    def test_a_wrong_or_expired_declare_code_is_refused_and_counted(self):
        self.server.post(reverse('device_declare_start'))
        res = self.server.post(reverse('device_declare_finish'), {'code': '00000000'},
                               content_type='application/json')
        if res.status_code == 200:                       # احتمالُ 1/10⁸ أن يكون الكودُ أصفاراً
            return
        self.assertEqual(res.status_code, 400)
        self.assertIsNone(DevicePolicy.get().server_id)
        self.assertTrue(DeviceAttempt.objects.filter(kind='declare', ok=False).exists())
        pol = DevicePolicy.get()
        pol.declare_code_expires = timezone.now() - timedelta(seconds=1)
        pol.save()
        code = re.search(r'(\d{8})', self.code_file.read_text(encoding='utf-8')).group(1)
        res = self.server.post(reverse('device_declare_finish'), {'code': code}, content_type='application/json')
        self.assertEqual(res.status_code, 400)

    def test_an_unwritable_disk_answers_with_the_console_route(self):
        blocker = self.tmp / 'not-a-dir'
        blocker.write_text('x', encoding='utf-8')
        with override_settings(DEVICES_DECLARE_CODE_FILE=str(blocker / 'code.txt')):
            res = self.server.post(reverse('device_declare_start'))
        self.assertEqual(res.status_code, 503)
        self.assertIn('devices_gate --declare-code', res.json()['message'])
        self.assertEqual(DevicePolicy.get().declare_code_hash, '')

    def test_only_a_superuser_declares(self):
        _, clerk = self.user_client()
        self.assertEqual(clerk.post(reverse('device_declare_start')).status_code, 403)
        self.assertFalse(self.code_file.exists())

    def test_redeclaring_moves_the_server(self):
        self.declare()
        other = Client()
        other.force_login(self.admin)
        self.declare(other, name='الخادم الجديد')
        self.assertEqual(DevicePolicy.get().server_id, self.device_of(other).pk)

    def test_the_console_code_works_too(self):
        from io import StringIO
        out = StringIO()
        call_command('devices_gate', '--declare-code', stdout=out)
        code = re.search(r'server code: (\d{8})', out.getvalue()).group(1)
        res = self.server.post(reverse('device_declare_finish'), {'code': code}, content_type='application/json')
        self.assertEqual(res.status_code, 200)


class CodeIssueTests(DevicesTestBase):
    def test_codes_come_from_the_server_device_only(self):
        self.assertEqual(self.issue().status_code, 403)             # لا خادمَ بعد
        self.declare()
        self.assertEqual(self.issue().status_code, 200)
        elsewhere = Client()
        elsewhere.force_login(self.admin)
        elsewhere.get(reverse('dashboard'))
        self.assertEqual(self.issue(elsewhere).status_code, 403)    # مديرٌ عامّ لكن ليس على الخادم

    def test_a_clerk_on_the_server_browser_still_cannot_issue(self):
        """حاسوبُ الخادم قد يُستعمل بحساب موظّف: الكوكي للخادم لكنّ الإصدارَ للمدير العامّ وحده."""
        self.declare()
        clerk = User.objects.create_user('on-server', password='p')
        self.server.force_login(clerk)                                # الكوكي باقٍ، والحسابُ تغيّر
        self.assertEqual(self.issue().status_code, 403)

    def test_a_clerk_never_issues(self):
        self.declare()
        _, clerk = self.user_client()
        self.assertEqual(self.issue(clerk).status_code, 403)

    def test_codes_are_five_digits_stored_as_keyed_hash(self):
        self.declare()
        code = self.issue().json()['code']
        self.assertRegex(code, r'^\d{5}$')
        row = PairingCode.objects.get()
        self.assertNotEqual(row.code_hash, code)
        self.assertNotEqual(row.code_hash, hashlib.sha256(code.encode()).hexdigest())
        self.assertEqual(row.code_hash, service.code_digest(code))

    def test_at_most_three_open_codes(self):
        self.declare()
        for _ in range(3):
            self.assertEqual(self.issue().status_code, 200)
        self.assertEqual(self.issue().status_code, 400)
        PairingCode.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.issue().status_code, 200)              # المنتهي يُغلق قبل الإصدار


class JoinTests(DevicesTestBase):
    def setUp(self):
        super().setUp()
        self.declare()
        self.clerk, self.client_ = self.user_client()
        self.client_.get(reverse('dashboard'))                       # الوسيطُ يُنشئ صفَّه وكوكيه

    def test_a_free_code_joins_once(self):
        code = self.issue().json()['code']
        self.assertEqual(self.client_.post(reverse('device_join_check'), {'code': code},
                                           content_type='application/json').status_code, 200)
        res = self.join(self.client_, code)
        self.assertEqual(res.status_code, 200, res.content)
        device = self.device_of(self.client_)
        self.assertTrue(device.is_active)
        self.assertEqual(device.name, 'استقبال-3')
        self.assertEqual(device.approved_by, self.admin)
        _, again = self.user_client('second')
        again.get(reverse('dashboard'))
        self.assertEqual(self.join(again, code, name='آخر').status_code, 400)

    def test_arabic_digits_are_accepted(self):
        code = self.issue().json()['code']
        arabic = code.translate(str.maketrans('0123456789', '٠١٢٣٤٥٦٧٨٩'))
        self.assertEqual(self.join(self.client_, arabic).status_code, 200)

    def test_a_request_bound_code_works_only_on_its_device(self):
        device = self.device_of(self.client_)
        self.client_.post(reverse('device_join_request'))
        code = self.issue(device=device).json()['code']
        _, thief = self.user_client('thief')
        thief.get(reverse('dashboard'))
        self.assertEqual(self.join(thief, code, name='سرقة').status_code, 400)
        self.assertEqual(self.join(self.client_, code).status_code, 200)

    def test_a_code_used_between_check_and_join_is_refused(self):
        """سباقُ جهازين على الكود نفسه: الاستهلاكُ تحديثٌ مشروط، فالثاني يُرفض."""
        from unittest import mock
        code = self.issue().json()['code']
        real = service.check_code

        def check_then_lose_the_race(request, raw, device):
            found = real(request, raw, device)
            PairingCode.objects.filter(pk=found.pk).update(used_at=timezone.now())
            return found

        with mock.patch.object(service, 'check_code', side_effect=check_then_lose_the_race):
            self.assertEqual(self.join(self.client_, code).status_code, 400)
        self.assertFalse(self.device_of(self.client_).is_active)

    def test_an_expired_code_is_refused(self):
        code = self.issue().json()['code']
        PairingCode.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.join(self.client_, code).status_code, 400)
        self.assertFalse(self.device_of(self.client_).is_active)

    def test_a_cancelled_code_is_refused(self):
        data = self.issue().json()
        self.server.post(reverse('device_cancel_code', args=[data['id']]))
        self.assertEqual(self.join(self.client_, data['code']).status_code, 400)

    def test_five_wrong_codes_lock_the_account(self):
        real = self.issue().json()['code']
        wrong = '00000' if real != '00000' else '11111'
        for i in range(4):
            res = self.join(self.client_, wrong)
            self.assertEqual(res.status_code, 400)
            self.assertEqual(res.json()['left'], 4 - i)
        self.assertEqual(self.join(self.client_, wrong).status_code, 429)
        self.assertEqual(self.join(self.client_, real).status_code, 429)  # حتّى الصحيح أثناء الإيقاف

    def test_thirty_wrong_codes_from_anyone_pause_everyone(self):
        now = timezone.now()
        DeviceAttempt.objects.bulk_create([
            DeviceAttempt(kind='join', user=self.admin, ok=False, at=now) for _ in range(service.GLOBAL_FAIL_LIMIT)])
        code = self.issue().json()['code']
        self.assertEqual(self.join(self.client_, code).status_code, 429)

    def test_a_taken_name_does_not_consume_the_code(self):
        first = self.issue().json()['code']
        self.assertEqual(self.join(self.client_, first, name='استقبال-1').status_code, 200)
        _, other = self.user_client('other')
        other.get(reverse('dashboard'))
        code = self.issue().json()['code']
        res = self.join(other, code, name='استقبال-1')
        self.assertEqual(res.json()['error'], 'name_taken')
        self.assertEqual(self.join(other, code, name='استقبال-2').status_code, 200)

    def test_the_cookie_token_is_stored_hashed(self):
        token = self.client_.cookies[service.COOKIE_NAME].value
        self.assertFalse(BrowserDevice.objects.filter(token_hash=token).exists())
        self.assertTrue(BrowserDevice.objects.filter(token_hash=service.hash_token(token)).exists())


class MiddlewareTests(DevicesTestBase):
    def test_nothing_happens_before_a_server_is_declared(self):
        _, clerk = self.user_client()
        clerk.get(reverse('dashboard'))
        self.assertNotIn(service.COOKIE_NAME, clerk.cookies)
        self.assertFalse(BrowserDevice.objects.exists())

    def test_discovery_on_top_level_html_only(self):
        self.declare()
        _, clerk = self.user_client()
        clerk.get(reverse('device_me'))                                # JSON
        clerk.get(reverse('dashboard'), headers={'sec-fetch-dest': 'iframe'})
        self.assertEqual(BrowserDevice.objects.exclude(pk=DevicePolicy.get().server_id).count(), 0)
        clerk.get(reverse('dashboard'))
        self.assertEqual(BrowserDevice.objects.exclude(pk=DevicePolicy.get().server_id).count(), 1)
        clerk.get(reverse('dashboard'))
        self.assertEqual(BrowserDevice.objects.exclude(pk=DevicePolicy.get().server_id).count(), 1)

    def test_concurrent_first_requests_share_one_row(self):
        """على HTTP لا يرسل المتصفّح Sec-Fetch-Dest، فالصفحةُ وإطارُها أو جزءُ HTML معاً بلا كوكي:
        التوكِنُ الأوّل من مفتاح الجلسة فيصلان إلى الصفّ نفسه (فيبل)."""
        self.declare()
        _, clerk = self.user_client()
        clerk.get(reverse('dashboard'))
        first = clerk.cookies[service.COOKIE_NAME].value
        del clerk.cookies[service.COOKIE_NAME]                       # الطلبُ الثاني بلا كوكيٍّ بعد
        clerk.get(reverse('dashboard'))
        self.assertEqual(clerk.cookies[service.COOKIE_NAME].value, first)
        self.assertEqual(BrowserDevice.objects.exclude(pk=DevicePolicy.get().server_id).count(), 1)

    # مقيسٌ في Chromium 11-18 على أصلٍ آمن (probe_nav.py): بعد أن يتحكّم عاملُ الخدمة بالصفحة — أي
    # من أوّل صفحةٍ بعد الدخول — يصل كلُّ تنقّلٍ بـ Sec-Fetch-Dest: empty مع Sec-Fetch-Mode: navigate.
    SW_NAVIGATION = {'sec-fetch-dest': 'empty', 'sec-fetch-mode': 'navigate'}
    SCRIPT_FETCH = {'sec-fetch-dest': 'empty', 'sec-fetch-mode': 'cors'}

    def test_a_navigation_through_the_service_worker_is_discovered(self):
        self.declare()
        _, clerk = self.user_client()
        for not_a_page in (self.SCRIPT_FETCH, {'sec-fetch-dest': 'empty', 'sec-fetch-mode': 'no-cors'},
                           {'sec-fetch-dest': 'iframe', 'sec-fetch-mode': 'navigate'}):
            clerk.get(reverse('dashboard'), headers=not_a_page)
        self.assertEqual(BrowserDevice.objects.exclude(pk=DevicePolicy.get().server_id).count(), 0)
        clerk.get(reverse('dashboard'), headers=self.SW_NAVIGATION)
        self.assertEqual(BrowserDevice.objects.exclude(pk=DevicePolicy.get().server_id).count(), 1)

    def test_only_mode_sends_a_navigation_through_the_service_worker_to_join(self):
        """كانت الموظّفةُ ترى JSON خاماً بدل صفحة الانضمام (مشيُ المتصفّح 11-18)."""
        self.declare()
        self.server.post(reverse('device_mode'), {'mode': 'only'}, content_type='application/json')
        _, clerk = self.user_client()
        res = clerk.get(reverse('dashboard'), headers=self.SW_NAVIGATION)
        self.assertRedirects(res, reverse('device_join'), fetch_redirect_response=False)
        res = clerk.get(reverse('device_board'), headers=self.SW_NAVIGATION)  # تنقّلٌ إلى /api/ لإنسان
        self.assertRedirects(res, reverse('device_join'), fetch_redirect_response=False)
        res = clerk.get(reverse('dashboard'), headers=self.SCRIPT_FETCH)
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json()['error'], 'device_not_registered')

    def test_only_mode_answers_scripts_with_json_anywhere(self):
        self.declare()
        self.server.post(reverse('device_mode'), {'mode': 'only'}, content_type='application/json')
        _, clerk = self.user_client()
        res = clerk.get(reverse('dashboard'), headers={'x-requested-with': 'XMLHttpRequest'})
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json()['error'], 'device_not_registered')

    def test_anonymous_requests_are_untouched(self):
        self.declare()
        Client().get(reverse('login'))
        self.assertEqual(BrowserDevice.objects.count(), 1)

    def test_touch_records_the_user_once_a_minute(self):
        self.declare()
        clerk, client = self.user_client()
        client.get(reverse('dashboard'))
        device = self.device_of(client)
        BrowserDevice.objects.filter(pk=device.pk).update(last_seen=timezone.now() - timedelta(minutes=5))
        client.get(reverse('dashboard'))
        device.refresh_from_db()
        self.assertGreater(device.last_seen, timezone.now() - timedelta(minutes=1))
        self.assertEqual(list(device.users.all()), [clerk])

    def test_remind_mode_shows_the_banner_to_unregistered_only(self):
        _, clerk = self.user_client()
        self.assertNotIn('id="dvsBanner"', clerk.get(reverse('dashboard')).content.decode())  # لا خادم
        self.declare()
        self.assertIn('id="dvsBanner"', clerk.get(reverse('dashboard')).content.decode())
        self.assertNotIn('id="dvsBanner"', self.server.get(reverse('dashboard')).content.decode())

    def test_open_mode_shows_no_banner(self):
        self.declare()
        self.server.post(reverse('device_mode'), {'mode': 'open'}, content_type='application/json')
        _, clerk = self.user_client()
        self.assertNotIn('id="dvsBanner"', clerk.get(reverse('dashboard')).content.decode())

    def test_only_mode_gates_the_unregistered(self):
        self.declare()
        self.server.post(reverse('device_mode'), {'mode': 'only'}, content_type='application/json')
        self.assertEqual(DevicePolicy.get().mode, 'only')
        _, clerk = self.user_client()
        res = clerk.get(reverse('dashboard'))
        self.assertRedirects(res, reverse('device_join'), fetch_redirect_response=False)
        api = clerk.get(reverse('device_board'), headers={'accept': 'application/json'})
        self.assertEqual(api.status_code, 403)
        self.assertEqual(clerk.get(reverse('device_join')).status_code, 200)
        self.assertEqual(clerk.get(reverse('device_me')).status_code, 200)
        self.assertEqual(self.server.get(reverse('dashboard')).status_code, 200)
        # تسجيلُ الخروج مفتوح
        self.assertIn(clerk.post(reverse('logout')).status_code, (200, 302))

    def test_only_mode_lets_a_superuser_redeclare_after_losing_the_cookie(self):
        self.declare()
        self.server.post(reverse('device_mode'), {'mode': 'only'}, content_type='application/json')
        lost = Client()
        lost.force_login(self.admin)
        self.assertEqual(lost.get(reverse('dashboard')).status_code, 302)
        self.declare(lost)
        self.assertEqual(lost.get(reverse('dashboard')).status_code, 200)

    def test_the_mode_changes_from_the_server_only(self):
        self.declare()
        _, clerk = self.user_client()
        self.assertEqual(clerk.post(reverse('device_mode'), {'mode': 'open'},
                                    content_type='application/json').status_code, 403)
        self.assertEqual(DevicePolicy.get().mode, 'remind')


class ManagementAndBoardTests(DevicesTestBase):
    def test_the_console_reopens_the_gate(self):
        self.declare()
        self.server.post(reverse('device_mode'), {'mode': 'only'}, content_type='application/json')
        call_command('devices_gate', '--mode', 'remind', stdout=open(self.tmp / 'out.txt', 'w', encoding='utf-8'))
        self.assertEqual(DevicePolicy.get().mode, 'remind')

    def test_the_board_is_for_superusers(self):
        _, clerk = self.user_client()
        self.assertEqual(clerk.get(reverse('device_board')).status_code, 403)
        self.declare()
        data = self.server.get(reverse('device_board')).json()
        self.assertTrue(data['can_approve'])
        self.assertEqual(data['counts']['registered'], 1)

    def test_requests_show_and_dismiss(self):
        self.declare()
        _, clerk = self.user_client()
        clerk.get(reverse('dashboard'))
        clerk.post(reverse('device_join_request'))
        board = self.server.get(reverse('device_board')).json()
        self.assertEqual(len(board['requests']), 1)
        rid = board['requests'][0]['id']
        self.server.post(reverse('device_action', args=[rid, 'dismiss']))
        self.assertEqual(self.server.get(reverse('device_board')).json()['requests'], [])

    def test_the_server_device_cannot_be_revoked(self):
        self.declare()
        sid = DevicePolicy.get().server_id
        self.assertEqual(self.server.post(reverse('device_action', args=[sid, 'revoke'])).status_code, 400)

    def test_report_keeps_only_clean_values(self):
        self.declare()
        res = self.server.post(reverse('device_report'),
                               {'agent_version': '1.2.0<script>', 'scanner_state': 'ok', 'scanner_label': 'Canon\x00X'},
                               content_type='application/json')
        self.assertEqual(res.status_code, 200)
        device = self.device_of(self.server)
        self.assertEqual(device.agent_version, '')
        self.assertEqual(device.scanner_label, 'CanonX')

    def test_outdated_is_measured_against_the_kit_not_the_repo(self):
        self.assertFalse(service.agent_outdated('1.1.0', ''))
        self.assertTrue(service.agent_outdated('1.1.0', '1.2.0'))
        self.assertFalse(service.agent_outdated('1.10.0', '1.9.0'))

    def test_pages_render_for_admin_and_clerk(self):
        admin_page = self.server.get(reverse('network_settings')).content.decode()
        self.assertIn('لم يُعلَن خادمٌ بعد', admin_page)
        self.declare()
        admin_page = self.server.get(reverse('network_settings')).content.decode()
        self.assertIn('id="dvsBoardData"', admin_page)
        self.assertIn('id="dvsAddDevice"', admin_page)
        _, clerk = self.user_client()
        page = clerk.get(reverse('network_settings')).content.decode()
        self.assertIn('id="dvsMe"', page)
        self.assertNotIn('dvsBoardData', page)
        self.assertNotIn('dvsDeclareModal', page)

    def test_the_only_file_written_is_the_declare_code(self):
        """حارسُ «لا كتابةَ في مسار الطلب» (tests_env_no_runtime_write) يراقب العروض؛ والكتابةُ
        الوحيدةُ هنا في الخدمة، وهدفُها ملفُّ كود الإعلان وحده (فيبل)."""
        import ast
        from django.conf import settings as dj
        from core.tests_env_no_runtime_write import find_file_writes
        base = Path(dj.BASE_DIR) / 'core' / 'devices'
        for f in sorted(base.rglob('*.py')):
            if f.name == 'tests.py' or f.name == 'service.py' or 'migrations' in f.parts:
                continue
            self.assertEqual(find_file_writes(f.read_text(encoding='utf-8')), [], f.name)
        src = (base / 'service.py').read_text(encoding='utf-8')
        self.assertEqual(len(find_file_writes(src)), 2, find_file_writes(src))
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'write_text':
                target = node.func.value
                ok = (isinstance(target, ast.Name) and target.id == 'path') or (
                    isinstance(target, ast.Call) and getattr(target.func, 'id', '') == 'declare_code_path')
                self.assertTrue(ok, ast.dump(target))
        self.assertIn('    path = declare_code_path()\n', src)

    def test_report_updates_only_what_it_was_sent(self):
        self.declare()
        self.server.post(reverse('device_report'), {'agent_version': '1.2.0', 'scanner_state': 'ok',
                                                    'scanner_label': 'Canon DR-M160'}, content_type='application/json')
        self.server.post(reverse('device_report'), {'agent_version': '1.2.1'}, content_type='application/json')
        device = self.device_of(self.server)
        self.assertEqual((device.agent_version, device.scanner_state, device.scanner_label),
                         ('1.2.1', 'ok', 'Canon DR-M160'))

    def test_a_bad_device_id_is_a_message_not_a_crash(self):
        self.declare()
        res = self.server.post(reverse('device_issue_code'), {'device': 'not-a-uuid'}, content_type='application/json')
        self.assertEqual(res.status_code, 400)

    def test_a_rename_race_is_a_message_not_a_crash(self):
        from unittest import mock
        from django.db import IntegrityError
        self.declare()
        sid = DevicePolicy.get().server_id
        with mock.patch.object(BrowserDevice, 'save', side_effect=IntegrityError('race')):
            res = self.server.post(reverse('device_action', args=[sid, 'rename']), {'name': 'خادم'},
                                   content_type='application/json')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()['error'], 'name_taken')

    def test_the_address_is_the_default_route_interface_only(self):
        from unittest import mock
        fake = mock.MagicMock()
        fake.getsockname.return_value = ('172.20.2.5', 50000)
        with mock.patch('core.devices.service.socket.socket', return_value=fake):
            self.assertEqual(service.server_addresses(), ['172.20.2.5'])
        fake.connect.side_effect = OSError('no route')
        with mock.patch('core.devices.service.socket.socket', return_value=fake):
            self.assertEqual(service.server_addresses(), [])

    def test_the_admin_page_prunes_old_rows(self):
        self.declare()
        _, clerk = self.user_client()
        clerk.get(reverse('dashboard'))
        BrowserDevice.objects.filter(status='pending').update(last_seen=timezone.now() - timedelta(days=31))
        DeviceAttempt.objects.create(kind='join', user=self.admin, ok=False, at=timezone.now() - timedelta(days=91))
        self.server.get(reverse('network_settings'))
        self.assertFalse(BrowserDevice.objects.filter(status='pending').exists())
        self.assertFalse(DeviceAttempt.objects.filter(at__lt=timezone.now() - timedelta(days=90)).exists())

    def test_prune_drops_stale_unregistered_rows(self):
        self.declare()
        _, clerk = self.user_client()
        clerk.get(reverse('dashboard'))
        BrowserDevice.objects.filter(status='pending').update(last_seen=timezone.now() - timedelta(days=31))
        self.assertEqual(service.prune(), 1)
        self.assertEqual(BrowserDevice.objects.count(), 1)


class RenderWithoutMiddlewareTests(DevicesTestBase):
    """حارسُ صفحات النشر (D:/migration/identity_tools/verify_release_pages.py) يستدعي العروضَ بلا وسيط،
    ويُرجع النشرَ كلَّه إن انكسرت صفحةٌ كانت تعمل. كانت صفحةُ الشبكة تقرأ request.lx_device مباشرة."""

    def render_like_the_deploy_guard(self, user, name):
        request = RequestFactory().get(reverse(name), secure=True)
        request.user = user
        request.session = SessionBase()
        request._messages = FallbackStorage(request)
        match = resolve(request.path_info)
        response = match.func(request, *match.args, **match.kwargs)
        if getattr(response, 'is_rendered', True) is False:
            response.render()
        return response.status_code

    def test_the_pages_render_without_the_middleware_before_and_after_a_declaration(self):
        clerk, _ = self.user_client()
        for declared in (False, True):
            if declared:
                self.declare()
            for user in (self.admin, clerk):
                for name in ('network_settings', 'device_join', 'dashboard'):
                    with self.subTest(declared=declared, user=user.username, page=name):
                        self.assertEqual(self.render_like_the_deploy_guard(user, name), 200)
