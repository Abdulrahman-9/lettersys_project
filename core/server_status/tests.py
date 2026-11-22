"""«حالة الخادم»: الأحكامُ وعتباتُها، والصلاحيّات، والصفحة والواجهة، والدليل ونسخته، وشريطُ اللوحة.

الاختباراتُ تعمل على حاسوب الخادم نفسه، فكلُّ ما يقرأ ويندوز (السجلّ و``sc.exe`` ووقتُ التشغيل والأقراص)
يُستبدل بقيمٍ ثابتة: لا اختبارَ يتغيّر بحال الخادم الحقيقيّ.
"""
import io
import os
import re
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.devices.models import DevicePolicy
from core.logging_models import UserActivityLog
from core.models import BackupSettings
from core.scoping import can_view_server_status

from . import checks

GB = 1024 ** 3
DiskUsage = __import__('collections').namedtuple('DiskUsage', 'total used free')   # شكلُ shutil.disk_usage


def fake_service(name):
    return {'LetterSys': {'start': 2, 'delayed': False, 'image': 'nssm.exe', 'depends': ['pg']},
            'pg': {'start': 2, 'delayed': False, 'image': '"pg_ctl.exe" runservice -D "C:\\pg\\data" -w',
                   'depends': []}}.get(name)


class WindowsFaked(TestCase):
    """ويندوزُ مزيّف: خدماتٌ تلقائيّة، رابطٌ آمن يعمل، قرصٌ واحد مريح، ونسخةٌ أُخذت بعد التشغيل."""

    def setUp(self):
        cache.clear()
        booted = timezone.localtime() - timedelta(hours=5)
        backups_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, backups_dir, True)
        backup = backups_dir / 'pg_backup_test.dump.enc'
        backup.write_bytes(b'x')
        stamp = (booted + timedelta(hours=1)).timestamp()
        os.utime(backup, (stamp, stamp))
        BackupSettings.objects.update_or_create(singleton=1, defaults={'enabled': True})
        # حفظُ جهة التبليغ يكتب نسخةَ الدليل على القرص: إلى مجلّدٍ مؤقّت لا إلى var/ المستودع
        guide_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, guide_dir, True)
        guide_path = override_settings(SERVER_GUIDE_EXPORT_PATH=str(guide_dir / 'guide' / 'index.html'))
        guide_path.enable()
        self.addCleanup(guide_path.disable)
        for target, value in (('windows_service', fake_service), ('service_state', lambda name: 'RUNNING'),
                              ('disk_drives', lambda db_drive='': ['C:\\'])):
            patcher = mock.patch.object(checks, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for target, value in (('shutil.disk_usage', lambda root: DiskUsage(100 * GB, 40 * GB, 60 * GB)),
                              ('core.backup_service.configured_backup_dir', lambda: backups_dir),
                              ('core.system_ops.system_booted_at', lambda: booted)):
            patcher = mock.patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.boss = User.objects.create_superuser('boss', password='p')
        self.clerk = User.objects.create_user('clerk', password='p')
        self.admin = Client()
        self.admin.force_login(self.boss)
        self.staff = Client()
        self.staff.force_login(self.clerk)


class ScopingTests(TestCase):
    def test_only_the_super_admin_sees_the_server_status(self):
        boss = User.objects.create_superuser('boss', password='p')
        staff = User.objects.create_user('staff', password='p', is_staff=True)
        clerk = User.objects.create_user('clerk', password='p')
        self.assertTrue(can_view_server_status(boss))
        self.assertFalse(can_view_server_status(staff))
        self.assertFalse(can_view_server_status(clerk))


class DiskTests(TestCase):
    def cards(self, free_gb, total_gb=237, db_drive='C:\\'):
        with mock.patch.object(checks, 'disk_drives', lambda db_drive='': ['C:\\']):
            return checks.disk_cards(db_drive, usage=lambda root: (total_gb * GB, 0, free_gb * GB))

    def test_the_measured_server_is_a_problem(self):
        card = self.cards(10.2)[0]                      # 4.3% حرّة — مقيسٌ 11-19
        self.assertEqual((card.state, card.label), (checks.BAD, 'ممتلئ تقريباً'))
        self.assertIn('قاعدةُ البيانات على هذا القرص', card.text)
        self.assertEqual(card.guide, 'disk')

    def test_thresholds(self):
        self.assertEqual(self.cards(20)[0].state, checks.WARN)      # 8.4%
        self.assertEqual(self.cards(120)[0].state, checks.OK)       # 50%
        self.assertEqual(self.cards(1.5, total_gb=20)[0].state, checks.BAD)   # 7.5% لكن أقلّ من 2 GB

    def test_the_database_note_only_on_its_drive(self):
        self.assertNotIn('قاعدةُ البيانات', self.cards(120, db_drive='D:\\')[0].text)

    def test_a_missing_drive_is_a_problem_not_unknown(self):
        def gone(root):
            raise OSError('not ready')
        with mock.patch.object(checks, 'disk_drives', lambda db_drive='': ['G:\\']):
            card = checks.disk_cards('', usage=gone)[0]
        self.assertEqual((card.state, card.label), (checks.BAD, 'غير موجود'))

    def test_a_database_on_a_fourth_drive_is_watched(self):
        # قرصُ القاعدة غيرُ قرص ويندوز والتطبيق والنسخ — كان لا يُراقَب (فيبل 11-22)
        with mock.patch.object(checks, 'backup_dir', lambda: Path('D:\\trackbackup')):
            roots = checks.disk_drives('Q:\\')
            cards = checks.disk_cards('Q:\\', usage=lambda root: (100 * GB, 0, 60 * GB))
        self.assertEqual(roots.count('Q:\\'), 1)
        self.assertEqual(len(roots), len(set(roots)))
        q = next(c for c in cards if c.key == 'disk-q')
        self.assertIn('قاعدةُ البيانات على هذا القرص', q.text)

    def test_the_shown_numbers_never_round_past_a_threshold(self):
        # 4.98% كانت تُعرض «5.0%» بجوار «ممتلئ تقريباً» (الحدُّ أقلُّ من 5)، و9.6 GB «10 GB» بجوار «يكاد يمتلئ»:
        # المعروضُ يُقطع ولا يُقرَّب، فلا يناقض الرقمُ حكمَ بطاقته (لقطة 11-22)
        card = self.cards(11.82)[0]                      # من 237: ‎4.987%‎
        self.assertEqual(card.state, checks.BAD)
        self.assertIn('⁦4.9%⁩', card.text)
        self.assertIn('⁦11 GB⁩', card.text)
        warn = self.cards(9.6, total_gb=60)[0]           # 16% لكن أقلّ من 10 GB
        self.assertEqual(warn.state, checks.WARN)
        self.assertIn('⁦9 GB⁩', warn.text)


class AutostartTests(TestCase):
    def card(self, app_start, db_start=2):
        services = {'LetterSys': {'start': app_start, 'depends': ['pg']}, 'pg': {'start': db_start}}
        return checks.autostart_card(lookup=services.get)

    def test_automatic_app_and_database(self):
        self.assertEqual(self.card(2).state, checks.OK)

    def test_manual_app_is_a_warning_with_a_guide(self):
        card = self.card(3)
        self.assertEqual((card.state, card.guide), (checks.WARN, 'autostart'))

    def test_disabled_app_is_a_problem(self):
        self.assertEqual(self.card(4).state, checks.BAD)

    def test_a_manual_database_breaks_the_autostart(self):
        card = self.card(2, db_start=3)
        self.assertEqual(card.state, checks.BAD)
        self.assertIn('pg', card.text)

    def test_no_service_is_unknown(self):
        self.assertEqual(checks.autostart_card(lookup=lambda name: None).state, checks.UNKNOWN)

    def test_boot_and_system_start_types_start_by_themselves(self):
        # 0 إقلاع · 1 نظام: تبدأ وحدها قبل التلقائيّ — ليست «يدويّة» (فيبل 11-22)
        for db_start in (0, 1):
            self.assertEqual(self.card(2, db_start=db_start).state, checks.OK, db_start)

    def test_the_label_names_the_database_only_when_it_is_one(self):
        def label(dep):
            return checks.autostart_card(lookup={'LetterSys': {'start': 2, 'depends': [dep]},
                                                 dep: {'start': 3}}.get).label
        self.assertEqual(label('postgresql-x64-16'), 'قاعدةُ البيانات لا تبدأ')
        self.assertEqual(label('Tcpip'), 'خدمةٌ لازمة لا تبدأ')

    def test_no_dependency_claims_no_database(self):
        card = checks.autostart_card(lookup={'LetterSys': {'start': 2, 'depends': []}}.get)
        self.assertEqual(card.state, checks.OK)
        self.assertIn('يبدأ النظامُ وحده', card.text)
        self.assertNotIn('قاعدة', card.text)


class AppCardTests(TestCase):
    def test_a_non_text_deploy_time_does_not_break_the_card(self):
        # ‎null‎ أو رقمٌ في release.json كانا يُسقطان صفحةَ هبوط المدير العامّ كلَّها (فيبل 11-22)
        for stamp in (12345, None):
            with mock.patch.object(checks, 'read_release', lambda: {'head': 'abcdef1234', 'deployed_at': stamp}):
                card = checks.app_card()
            self.assertEqual(card.state, checks.OK)
            self.assertIn('النسخة abcdef1', card.text)
            self.assertNotIn('نُشرت', card.text)

    def test_a_valid_deploy_time_is_shown(self):
        release = {'head': 'abcdef1234', 'deployed_at': '2026-11-22T08:00:00+03:00'}
        with mock.patch.object(checks, 'read_release', lambda: release):
            self.assertIn('نُشرت', checks.app_card().text)


def at(day, hour, minute=0):
    return timezone.make_aware(datetime(2026, 11, day, hour, minute))


class BackupTests(TestCase):
    """الحكمُ من ``core.system_ops.backup_is_late`` — المصدرُ الوحيد؛ البطاقةُ تعرضه."""
    booted = at(19, 8)

    def card(self, latest, now, booted=booted, enabled=True):
        return checks.backup_card(now=now, latest=latest, booted=booted, enabled=enabled)

    def test_none_is_a_problem(self):
        self.assertEqual(self.card(None, at(19, 12)).state, checks.BAD)

    def test_a_backup_after_boot_is_fresh(self):
        self.assertEqual(self.card(at(19, 9), at(19, 12)).state, checks.OK)

    def test_two_hours_grace_after_boot(self):
        # 47 ساعة بعد عطلة (مقيسٌ) — ليست تأخّراً ما دامت الساعتان الأوليان بعد التشغيل
        self.assertEqual(self.card(at(17, 9), at(19, 9, 30)).state, checks.OK)

    def test_late_when_none_since_boot(self):
        card = self.card(at(17, 9), at(19, 10, 30))
        self.assertEqual((card.state, card.guide), (checks.WARN, 'backup'))

    def test_a_backup_from_before_the_boot_is_late_after_the_grace(self):
        # نسخةُ السابعة وأُقلع في الثامنة: عمرُها ساعاتٌ لا يوم، لكنّ نسخةَ ما بعد التشغيل لم تأتِ — وحده
        # «لا نسخةَ منذ التشغيل» يكشفها (قاعدةُ 26 ساعة تصمت هنا)
        self.assertEqual(self.card(at(19, 7), at(19, 9, 30)).state, checks.OK)      # الساعتان لم تمضيا
        card = self.card(at(19, 7), at(19, 10, 30))
        self.assertEqual((card.state, card.label), (checks.WARN, 'متأخّرة'))
        self.assertIn('لم تُؤخذ نسخةٌ منذ تشغيل الحاسوب', card.text)

    def test_the_grace_does_not_excuse_a_week_old_backup(self):
        # مركزُ النظام يسأل ``backup_is_late`` وحدها: بعد التشغيل بدقائق تبقى نسخةُ تسعة أيّامٍ متأخّرة
        from core import system_ops
        self.assertTrue(system_ops.backup_is_late(at(10, 9), at(19, 8, 30), booted=self.booted))

    def test_a_week_old_backup_is_a_problem(self):
        self.assertEqual(self.card(at(10, 9), at(19, 9, 30)).state, checks.BAD)

    def test_disabled_backup_is_a_warning(self):
        card = self.card(at(19, 9), at(19, 12), enabled=False)
        self.assertEqual((card.state, card.label), (checks.WARN, 'معطَّل'))

    def test_the_rule_is_shared_with_the_system_centre(self):
        from core import system_ops
        self.assertFalse(system_ops.backup_is_late(at(17, 9), at(19, 9, 30), booted=self.booted))
        self.assertTrue(system_ops.backup_is_late(at(17, 9), at(19, 10, 30), booted=self.booted))

    def test_a_missing_folder_is_a_problem_and_is_not_created(self):
        missing = Path(tempfile.mkdtemp())
        missing.rmdir()                                  # اسمٌ جديدٌ مضمون الغياب (طفرةُ الإنشاء تترك مجلّداً)
        self.addCleanup(shutil.rmtree, missing, True)
        with mock.patch.object(checks, 'backup_dir', lambda: missing):
            card = checks.backup_card(now=at(19, 12), booted=None, enabled=True)
        self.assertEqual((card.state, card.label), (checks.BAD, 'المجلّد غير موجود'))
        self.assertFalse(missing.exists())               # الفحصُ يقرأ ولا يكتب

    def test_the_checks_never_create_the_backup_folder(self):
        """النسخُ مفعّلٌ هنا كي يصل الفحصُ إلى ``system_ops.newest_backup`` فعلاً (طفرةٌ نجت حين كان معطّلاً)."""
        from core import system_ops

        def forbidden(*a, **k):
            raise AssertionError('default_backup_dir creates folders; a status read must not call it')
        BackupSettings.objects.update_or_create(singleton=1, defaults={'enabled': True})
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        (folder / 'pg_backup_x.dump.enc').write_bytes(b'x')
        with mock.patch('core.backup_service.default_backup_dir', forbidden), \
                mock.patch('core.backup_service.configured_backup_dir', lambda: folder), \
                mock.patch.object(checks, 'service_state', lambda name: None):
            self.assertEqual(system_ops.newest_backup().path.name, 'pg_backup_x.dump.enc')
            self.assertIsNotNone(system_ops.disk_percent())
            report = checks.collect()
        self.assertEqual(next(c for c in report['cards'] if c.key == 'backup').label, 'حديثة')

    def test_unknown_boot_falls_back_to_a_day(self):
        now = at(19, 12)
        self.assertEqual(self.card(now - timedelta(hours=30), now, booted=None).state, checks.WARN)
        self.assertEqual(self.card(now - timedelta(hours=20), now, booted=None).state, checks.OK)

    def test_running_for_days_with_an_old_backup_is_late(self):
        # حاسوبٌ شغّالٌ منذ 16 نوفمبر (أو عائدٌ من «الإقلاع السريع» فلم يتصفّر عدّاده) أخذ نسخةً بعد تشغيله
        # ثمّ توقّف النسخ: كان الحكمُ يصمت حتّى يمضي أسبوع (فيبل 11-22)
        from core import system_ops
        booted, latest, now = at(16, 8), at(16, 9), at(19, 12)
        self.assertTrue(system_ops.backup_is_late(latest, now, booted=booted))
        card = self.card(latest, now, booted=booted)
        self.assertEqual((card.state, card.label), (checks.WARN, 'متأخّرة'))
        self.assertIn('أقدمُ من يوم', card.text)
        self.assertNotIn('منذ تشغيل الحاسوب', card.text)      # أُخذت نسخةٌ بعد التشغيل: لا يُقال غيرُ ذلك
        self.assertEqual(self.card(now - timedelta(hours=20), now, booted=booted).state, checks.OK)

    def test_a_backup_that_vanishes_is_skipped(self):
        # التدويرُ يحذف نسخةً بين سرد المجلّد وقراءة وقتها: تُتخطّى ولا تُسقط الصفحة (فيبل 11-22)
        from core import system_ops
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        kept = folder / 'pg_backup_kept.dump.enc'
        kept.write_bytes(b'x')
        gone = folder / 'pg_backup_gone.dump.enc'          # سُرد ولم يعد موجوداً

        class Listing:
            def glob(self, pattern):
                return [gone, kept]
        with mock.patch('core.backup_service.configured_backup_dir', Listing):
            newest = system_ops.newest_backup()
        self.assertEqual((newest.path, newest.mtime), (kept, kept.stat().st_mtime))


class HttpsAndLinkTests(TestCase):
    def test_https_states(self):
        self.assertEqual(checks.https_card('RUNNING', probe=False).state, checks.OK)
        paused = checks.https_card('PAUSED', probe=False)
        self.assertEqual((paused.state, paused.label), (checks.BAD, 'موقوفٌ مؤقّتاً'))
        self.assertEqual(checks.https_card('STOPPED', probe=False).state, checks.BAD)
        self.assertEqual(checks.https_card('MISSING', probe=False).state, checks.INFO)
        self.assertIsNone(checks.https_card(None, probe=False))

    @override_settings(ALLOWED_HOSTS=['172.16.2.16', '172.20.2.5', 'follow2', 'follow2.mdoc'], LETTERSYS_OFFICIAL_URL='')
    def test_the_official_link_is_the_first_name(self):
        request = RequestFactory().get('/', HTTP_HOST='172.20.2.5:1312')
        self.assertEqual(checks.official_url(request), 'http://follow2:1312')
        card = checks.link_card(request, addresses=['172.20.2.5'])
        self.assertEqual(card.state, checks.OK)
        self.assertIn('follow2', card.text)
        self.assertIn('الرابطُ الآمن غيرُ مفعّل', card.text)

    @override_settings(ALLOWED_HOSTS=['172.20.2.5'], LETTERSYS_OFFICIAL_URL='')
    def test_numbers_only_is_a_warning(self):
        request = RequestFactory().get('/', HTTP_HOST='172.20.2.5:1312')
        self.assertEqual(checks.link_card(request, addresses=[]).state, checks.WARN)

    @override_settings(LETTERSYS_OFFICIAL_URL='https://follow2/')
    def test_an_explicit_link_wins(self):
        self.assertEqual(checks.official_url(RequestFactory().get('/')), 'https://follow2')


class DevicesCardTests(TestCase):
    def test_undeclared_server_is_information(self):
        card = checks.devices_card()
        self.assertEqual((card.state, card.label), (checks.INFO, 'الخادم لم يُعلَن'))

    def test_a_declared_server_counts_active_devices(self):
        from core.devices.models import BrowserDevice
        server = BrowserDevice.objects.create(token_hash='s' * 64, status=BrowserDevice.Status.ACTIVE, name='الخادم')
        BrowserDevice.objects.create(token_hash='a' * 64, status=BrowserDevice.Status.ACTIVE, name='استقبال-3')
        BrowserDevice.objects.create(token_hash='p' * 64)                           # غيرُ مسجّل: لا يُعدّ
        pol = DevicePolicy.get()
        pol.server = server
        pol.save()
        card = checks.devices_card()
        self.assertEqual((card.state, card.label), (checks.OK, 'جهازان مسجّلان'))


class SummaryAndOrderTests(TestCase):
    def test_headline_counts_in_arabic(self):
        def card(state):
            return checks.Card('k', 't', state, 'l', 'x', 'server')
        self.assertEqual(checks.summarize([card(checks.OK)])['headline'], 'الخادم يعمل بلا ملاحظات')
        warn = checks.summarize([card(checks.WARN), card(checks.OK)])
        self.assertIn('تنبيهٌ واحد', warn['headline'])
        self.assertEqual(warn['state'], checks.WARN)
        bad = checks.summarize([card(checks.BAD), card(checks.BAD), card(checks.WARN)])
        self.assertIn('مشكلتان', bad['headline'])
        self.assertEqual(bad['state'], checks.BAD)


class CollectTests(WindowsFaked):
    def test_attention_comes_first(self):
        with mock.patch.object(checks, 'service_state', lambda name: 'PAUSED'), \
                mock.patch('shutil.disk_usage', lambda root: DiskUsage(100 * GB, 93 * GB, 7 * GB)):
            report = checks.collect(RequestFactory().get('/'))
        states = [c.state for c in report['cards']]
        self.assertEqual(states[0], checks.BAD)
        ranks = [checks._RANK[s] for s in states]
        self.assertEqual(ranks, sorted(ranks))

    def test_the_strip_is_cached_and_asks_windows_once_a_minute(self):
        calls = []
        with mock.patch.object(checks, 'service_state', lambda name: calls.append(name) or 'RUNNING'):
            first = checks.strip_summary()
            second = checks.strip_summary()
        self.assertEqual(first, second)
        self.assertEqual(len(calls), 1)                  # مرّةً واحدة ثمّ من الحفظ

    def test_the_strip_and_the_page_count_the_same_problems(self):
        with mock.patch.object(checks, 'service_state', lambda name: 'PAUSED'):
            page = checks.collect(RequestFactory().get('/'))['summary']
            cache.clear()
            strip = checks.strip_summary()
        self.assertEqual((strip['bad'], strip['warn']), (page['bad'], page['warn']))

    @override_settings(ALLOWED_HOSTS=['172.20.2.5'], LETTERSYS_OFFICIAL_URL='')
    def test_the_strip_counts_a_numbers_only_link(self):
        # الشريطُ يُحسب بلا طلب: بطاقةُ الرابط كانت تغيب عنه فيقول «بلا ملاحظات» والصفحةُ تنبّه (فيبل 11-22)
        strip = checks.strip_summary()
        self.assertEqual((strip['bad'], strip['warn']), (0, 1))
        self.assertEqual((strip['first']['key'], strip['first']['label']), ('link', 'بالأرقام'))


class PageTests(WindowsFaked):
    def test_anonymous_is_sent_to_login(self):
        res = Client().get(reverse('server_status'))
        self.assertEqual(res.status_code, 302)

    def test_a_clerk_is_refused_everywhere(self):
        self.assertEqual(self.staff.get(reverse('server_status')).status_code, 403)
        api = self.staff.get(reverse('server_status_api'))
        self.assertEqual(api.status_code, 403)
        self.assertEqual(api.json()['error'], 'forbidden')
        res = self.staff.post(reverse('server_contact_api'), {'name': 'x'}, content_type='application/json')
        self.assertEqual(res.status_code, 403)

    def test_the_super_admin_sees_the_cards(self):
        res = self.admin.get(reverse('server_status'))
        self.assertEqual(res.status_code, 200)
        body = res.content.decode()
        self.assertIn('حالة الخادم', body)
        self.assertIn('id="card-disk-c"', body)
        self.assertIn('الخادم يعمل بلا ملاحظات', body)
        self.assertNotIn('النظام لا يبدأ وحده مع الحاسوب', body)

    def test_first_run_steps_when_autostart_is_off(self):
        manual = {'LetterSys': {'start': 3, 'depends': []}}
        with mock.patch.object(checks, 'windows_service', manual.get):
            body = self.admin.get(reverse('server_status')).content.decode()
        self.assertIn('النظام لا يبدأ وحده مع الحاسوب', body)
        self.assertIn('sc.exe config LetterSys start= auto', body)

    def test_the_api_returns_rendered_cards(self):
        data = self.admin.get(reverse('server_status_api')).json()
        self.assertTrue(data['ok'])
        self.assertIn('ss-card', data['cards_html'])
        self.assertEqual(data['summary']['state'], checks.OK)
        self.assertEqual(data['autostart_state'], checks.OK)

    def test_the_contact_is_saved_and_audited(self):
        res = self.admin.post(reverse('server_contact_api'), {'name': 'المدير العامّ', 'phone': '1023'},
                              content_type='application/json')
        self.assertEqual(res.status_code, 200, res.content)
        pol = DevicePolicy.get()
        self.assertEqual((pol.notify_name, pol.notify_phone), ('المدير العامّ', '1023'))
        self.assertTrue(UserActivityLog.objects.filter(action='EDIT_SETTINGS',
                                                       metadata__section='حالة الخادم').exists())

    def test_reading_the_pages_creates_no_device_policy(self):
        # فتحُ صفحةٍ لا يكتب صفّاً: الشريطُ يُسأل مع كلّ صفحة، والدليلُ لكلّ موظّف (فيبل 11-22)
        for client, name in ((self.admin, 'server_status'), (self.admin, 'server_status_api'),
                             (self.admin, 'server_guide'), (self.staff, 'server_guide')):
            self.assertEqual(client.get(reverse(name)).status_code, 200, name)
        self.assertFalse(DevicePolicy.objects.exists())

    def test_saving_the_contact_rewrites_the_offline_guide(self):
        res = self.admin.post(reverse('server_contact_api'), {'name': 'أبو علي', 'phone': '1023'},
                              content_type='application/json')
        self.assertEqual(res.status_code, 200, res.content)
        self.assertTrue(res.json()['guide_written'])
        html = Path(settings.SERVER_GUIDE_EXPORT_PATH).read_text(encoding='utf-8')
        self.assertIn('أبو علي', html)
        self.assertIn('href="http://testserver/books/', html)     # الروابطُ من الطلب، لا ‎file:///‎ ميّتة

    @override_settings(ALLOWED_HOSTS=['172.20.2.5'], LETTERSYS_OFFICIAL_URL='')
    def test_without_a_name_the_guide_links_to_the_typed_address(self):
        # لا اسمَ في الإعدادات: الروابطُ بالعنوان الذي كتبه المتصفّح، لا ‎file:///D:/books/…‎
        res = self.admin.post(reverse('server_contact_api'), {'name': 'أبو علي'},
                              content_type='application/json', HTTP_HOST='172.20.2.5:1312')
        self.assertEqual(res.status_code, 200, res.content)
        html = Path(settings.SERVER_GUIDE_EXPORT_PATH).read_text(encoding='utf-8')
        self.assertIn('href="http://172.20.2.5:1312/books/', html)

    def test_a_guide_that_cannot_be_written_is_said_and_the_contact_stays_saved(self):
        blocker = Path(settings.SERVER_GUIDE_EXPORT_PATH).parent.parent / 'blocker'
        blocker.write_bytes(b'x')                        # ملفٌّ حيث يجب أن يكون مجلّد: كتابةٌ تفشل حقّاً
        with override_settings(SERVER_GUIDE_EXPORT_PATH=str(blocker / 'guide' / 'index.html')):
            res = self.admin.post(reverse('server_contact_api'), {'name': 'أبو علي'},
                                  content_type='application/json')
        self.assertEqual(res.status_code, 200, res.content)
        data = res.json()
        self.assertEqual((data['ok'], data['guide_written']), (True, False))
        self.assertEqual(data['message'], 'حُفظ، ولم تُحدَّث نسخةُ الدليل على القرص.')
        self.assertEqual(DevicePolicy.get().notify_name, 'أبو علي')

    def test_a_long_contact_is_a_message(self):
        res = self.admin.post(reverse('server_contact_api'), {'name': 'x' * 81}, content_type='application/json')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json()['error'], 'too_long')

    def test_the_contact_needs_the_csrf_token(self):
        strict = Client(enforce_csrf_checks=True)
        strict.force_login(self.boss)
        res = strict.post(reverse('server_contact_api'), {'name': 'x'}, content_type='application/json')
        self.assertEqual(res.status_code, 403)

    def test_the_guide_is_for_everyone_with_anchors(self):
        body = self.staff.get(reverse('server_guide')).content.decode()
        for anchor in ('unreachable', 'bad-request', 'slow', 'disk', 'power-cut', 'db', 'https', 'backup',
                       'scanner', 'autostart', 'report'):
            self.assertIn(f'id="{anchor}"', body, anchor)
        self.assertNotIn(reverse('server_status') + '"', body.split('ss-guide-grid')[0])

    def test_every_card_guide_has_an_anchor(self):
        body = self.staff.get(reverse('server_guide')).content.decode()
        anchors = set(re.findall(r'id="([a-z-]+)"', body))
        guides = set(re.findall(r"guide='([a-z-]+)'", Path(checks.__file__).read_text(encoding='utf-8')))
        self.assertTrue(guides)
        self.assertEqual(guides - anchors, set())

    def test_the_dashboard_strip_is_for_the_super_admin_only(self):
        self.assertIn('class="ss-strip"', self.admin.get(reverse('dashboard')).content.decode())
        self.assertNotIn('class="ss-strip"', self.staff.get(reverse('dashboard')).content.decode())

    def test_the_strip_greets_the_super_admin_where_login_lands(self):
        # المدير العامّ يهبط بعد الدخول على مركز النظام لا اللوحة (مقيسٌ في المتصفّح 11-19)
        body = self.admin.get(reverse('system_centre')).content.decode()
        self.assertIn('class="ss-strip"', body)
        self.assertIn('css/server_status.css', body)

    def test_the_account_menu_link_follows_the_rule(self):
        link = f'href="{reverse("server_status")}"'
        self.assertIn(link, self.admin.get(reverse('dashboard')).content.decode())
        self.assertNotIn(link, self.staff.get(reverse('dashboard')).content.decode())


class GuideExportTests(TestCase):
    def test_the_offline_copy_is_written_whole(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'guide' / 'index.html'
            stdout = io.StringIO()
            call_command('export_server_guide', out=str(out), official_url='http://follow2:1312', stdout=stdout)
            html = out.read_text(encoding='utf-8')
            self.assertEqual([p.name for p in out.parent.iterdir()], ['index.html'])   # لا مؤقّتَ يتيم
        self.assertIn('GUIDE_EXPORTED', stdout.getvalue())
        self.assertIn('دليل التشغيل والمشكلات', html)
        self.assertIn('http://follow2:1312', html)
        self.assertIn('id="disk"', html)
        self.assertNotIn('{%', html)
        self.assertNotIn('<link', html)                  # لا ملفّاتٍ خارجيّة: يُفتح من القرص بلا خادم

    def test_a_failed_write_leaves_no_temp_file(self):
        from core.server_status.offline_guide import write_offline_guide
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'index.html'
            out.mkdir()                                  # مجلّدٌ باسم الدليل: يفشل الاستبدالُ بعد كتابة المؤقّت
            with self.assertRaises(OSError):
                write_offline_guide('http://follow2:1312', out)
            self.assertEqual([p.name for p in Path(tmp).iterdir()], ['index.html'])

    @override_settings(LETTERSYS_OFFICIAL_URL='')
    def test_the_export_needs_the_official_link(self):
        # بلا رابطٍ تصير روابطُ النسخة المفتوحة من القرص ‎file:///D:/books/…‎ ميّتة (فيبل 11-22)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'index.html'
            with self.assertRaises(CommandError):
                call_command('export_server_guide', out=str(out), stdout=io.StringIO())
            self.assertFalse(out.exists())

    @override_settings(LETTERSYS_OFFICIAL_URL='https://follow2/')
    def test_the_export_takes_the_configured_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'index.html'
            call_command('export_server_guide', out=str(out), stdout=io.StringIO())
            html = out.read_text(encoding='utf-8')
        self.assertIn('href="https://follow2/books/', html)
        self.assertFalse(DevicePolicy.objects.exists())   # التصديرُ يقرأ جهةَ التبليغ ولا يُنشئ صفّاً


class TemplateRuleTests(TestCase):
    def test_no_role_condition_in_the_templates(self):
        folder = Path(__file__).resolve().parents[2] / 'templates' / 'core' / 'server_status'
        for path in folder.glob('*.html'):
            text = path.read_text(encoding='utf-8')
            self.assertNotRegex(text, r'is_superuser|is_staff|\.groups', path.name)
