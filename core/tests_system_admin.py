# -*- coding: utf-8 -*-
"""إدارة النظام: البوّابة، والشريط، وتحويل الدخول، وأرقام المركز، والعدسة، وتشغيل النظام."""
import os
import re
import tempfile
import time
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core import system_centre, system_ops
from core.logging_models import UserActivityLog
from core.models import BackupSettings, Book, Department, Entity, UserProfile
from core.testing import as_writer

CENTRE, OPS = 'system_centre', 'system_ops'


class SystemAdminCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.today = timezone.localdate()
        cls.ent_q, cls.ent_s, cls.ent_x = (Entity.objects.create(name=n) for n in ('توأم القسم', 'توأم الشعبة', 'توأم الآخر'))
        cls.q = Department.objects.create(name='قسم تجربة المتابعة', code='ت13', entity=cls.ent_q)
        cls.s = Department.objects.create(name='شعبة تجربة التدقيق', code='ت.ش', parent=cls.q, entity=cls.ent_s, holds_register=False)
        cls.x = Department.objects.create(name='قسم تجربة التراخيص', code='ت4', entity=cls.ent_x)
        cls.idle = Department.objects.create(name='لجنة تجربة فارغة', code='ت9')
        cls.admin = User.objects.create_superuser('root', password='pw-root-1111')
        cls.head = as_writer(User.objects.create_user('head', password='pw-head-1111'))
        UserProfile.objects.update_or_create(user=cls.head, defaults={'department': cls.q, 'is_department_head': True})
        cls.clerk = as_writer(User.objects.create_user('clerk', password='pw-clerk-1111'))
        UserProfile.objects.update_or_create(user=cls.clerk, defaults={'department': cls.s})

        def book(num, dept, **kw):
            return Book.objects.create(kind='incoming_internal', title=kw.pop('title', 'كتاب'), our_number=num,
                                       created_by=cls.clerk, department=dept, date=cls.today, **kw)

        cls.new_q = book('101', cls.q, due_date=cls.today - timedelta(days=4), is_archived=False)
        cls.old_q = book('20250825', cls.q, source_ref='IIMAIL_2025#1', is_archived=True)
        cls.new_s = book('102', cls.s, is_archived=True)
        book('T1', cls.q, is_training=True)
        gone = book('103', cls.q)
        gone.is_deleted = True
        gone.save(update_fields=['is_deleted'])
        # كتابٌ يذكر القسمَ وشعبته معاً: يُعدّ في أضبارة القسم مرّةً واحدة.
        cls.new_q.issuing_entities.add(cls.ent_q)
        cls.new_q.receiving_entities.add(cls.ent_s)
        cls.old_q.receiving_entities.add(cls.ent_x)
        UserActivityLog.objects.create(user=cls.clerk, action='EDIT_SETTINGS', department=cls.s)
        UserActivityLog.objects.create(user=cls.admin, action='EDIT_SETTINGS', department=None)

    def rows(self):
        rows, orphan = system_centre.centre_rows()
        return {r['unit'].code: r for r in rows}, orphan


class GateTests(SystemAdminCase):
    def pages(self):
        return (reverse(CENTRE), reverse('system_department', args=[self.q.pk]), reverse(OPS))

    def test_only_the_system_admin_opens_them(self):
        for url in self.pages():
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 302)
                self.client.force_login(self.head)
                self.assertEqual(self.client.get(url).status_code, 403)
                self.client.force_login(self.admin)
                self.assertEqual(self.client.get(url).status_code, 200)
                self.client.logout()

    def test_writing_to_them_is_refused(self):
        self.client.force_login(self.admin)
        for url in self.pages():
            self.assertEqual(self.client.post(url).status_code, 405)


class SidebarTests(SystemAdminCase):
    def test_the_admin_gets_the_administration_sidebar_only(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse('book_unified')).content.decode('utf-8')
        self.assertIn('class="sa-nav"', html)
        for gone in ('app-sidebar-nav', 'الإدخال الذكي', 'ما يخصّني'):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, html)

    def test_everyone_else_keeps_the_staff_sidebar(self):
        self.client.force_login(self.head)
        html = self.client.get(reverse('book_unified')).content.decode('utf-8')
        self.assertNotIn('class="sa-nav"', html)
        self.assertIn('app-sidebar-nav', html)

    def test_a_forced_password_change_hides_it(self):
        profile, _ = UserProfile.objects.get_or_create(user=self.admin)
        profile.must_change_password = True
        profile.save(update_fields=['must_change_password'])
        self.client.force_login(self.admin)
        html = self.client.get(reverse('password_change')).content.decode('utf-8')
        self.assertNotIn('class="sa-nav"', html)

    def test_every_link_in_it_opens(self):
        """الرابطُ الظاهر صفحةٌ تُفتح."""
        self.client.force_login(self.admin)
        html = self.client.get(reverse(CENTRE)).content.decode('utf-8')
        nav = re.search(r'<nav class="sa-nav".*?</nav>', html, re.S).group(0)
        links = re.findall(r'href="([^"]+)"', nav)
        self.assertEqual(len(links), 15)
        for link in links:
            with self.subTest(link=link):
                self.assertEqual(self.client.get(link.replace('&amp;', '&')).status_code, 200)

    def test_one_entry_per_thing(self):
        """الأقسامُ مدخلٌ واحدٌ يضيء في المركز ومحرّر الهيكل، والشبكةُ في الإعدادات لا في الشريط (2026‑11‑08)."""
        self.client.force_login(self.admin)

        def lit(url):
            html = self.client.get(url).content.decode('utf-8')
            nav = re.search(r'<nav class="sa-nav".*?</nav>', html, re.S).group(0)
            self.assertNotIn(reverse('network_settings'), nav)
            return re.findall(r'class="on"[^>]*>.*?<span>([^<]+)</span>', nav, re.S)

        self.assertEqual(lit(reverse(CENTRE)), ['الأقسام'])
        self.assertEqual(lit(reverse('admin_panel') + '?tab=departments'), ['الأقسام'])
        self.assertEqual(lit(reverse('network_settings')), ['الإعدادات'])
        self.assertEqual(lit(reverse('workstation_board')), ['المحطّات'])

    def test_the_panel_uses_the_same_sidebar(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse('admin_panel')).content.decode('utf-8')
        self.assertIn('class="sa-nav"', html)
        self.assertNotIn('class="admbox"', html)
        self.client.force_login(self.head)
        self.assertIn('class="admbox"', self.client.get(reverse('admin_panel')).content.decode('utf-8'))


class LoginRedirectTests(SystemAdminCase):
    def login(self, username, password, **query):
        url = reverse('login') + ('?' + '&'.join(f'{k}={v}' for k, v in query.items()) if query else '')
        return self.client.post(url, {'username': username, 'password': password})

    def test_the_admin_lands_on_the_centre(self):
        self.assertRedirects(self.login('root', 'pw-root-1111'), reverse(CENTRE), fetch_redirect_response=False)

    def test_next_wins(self):
        target = reverse('book_unified')
        self.assertRedirects(self.login('root', 'pw-root-1111', next=target), target, fetch_redirect_response=False)

    def test_staff_land_where_they_did(self):
        self.assertEqual(self.login('clerk', 'pw-clerk-1111').url, '/')

    def test_the_home_page_is_not_redirected(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get('/').status_code, 200)


class CentreNumbersTests(SystemAdminCase):
    def test_books_roll_up_the_tree_without_training_or_deleted(self):
        rows, _ = self.rows()
        self.assertEqual((rows['ت13']['books'], rows['ت13']['paper'], rows['ت13']['live']), (3, 1, 2))
        self.assertEqual((rows['ت.ش']['books'], rows['ت.ش']['paper']), (1, 0))

    def test_paper_rolls_up_with_the_books(self):
        Book.objects.create(kind='incoming_internal', title='ورق الشعبة', our_number='20250900', created_by=self.clerk,
                            department=self.s, date=self.today, source_ref='IIMAIL_2025#9', is_archived=True)
        row = self.rows()[0]['ت13']
        self.assertEqual((row['books'], row['paper'], row['live']), (4, 2, 2))

    def test_a_book_naming_parent_and_child_counts_once(self):
        rows, _ = self.rows()
        self.assertEqual(rows['ت13']['dossier'], 1)
        self.assertEqual(rows['ت.ش']['dossier'], 1)
        self.assertEqual(rows['ت4']['dossier'], 1)

    def test_a_deleted_book_is_not_in_a_dossier(self):
        self.new_q.is_deleted = True
        self.new_q.save(update_fields=['is_deleted'])
        self.assertEqual(self.rows()[0]['ت13']['dossier'], 0)

    def test_late_rolls_up_and_stays_home(self):
        rows, _ = self.rows()
        self.assertEqual((rows['ت13']['late'], rows['ت.ش']['late'], rows['ت4']['late']), (1, 0, 0))

    def test_a_late_book_in_a_child_counts_for_its_parent(self):
        Book.objects.create(kind='incoming_internal', title='متأخّر الشعبة', our_number='104', created_by=self.clerk,
                            department=self.s, date=self.today, is_archived=False,
                            due_date=self.today - timedelta(days=2))
        rows, _ = self.rows()
        self.assertEqual((rows['ت13']['late'], rows['ت.ش']['late']), (2, 1))

    def test_activity_belongs_to_the_actors_department(self):
        rows, orphan = self.rows()
        self.assertEqual((rows['ت.ش']['act7'], rows['ت13']['act7'], rows['ت13']['tree_activity']), (1, 0, 1))
        self.assertEqual(orphan['act7'], 1)
        self.assertEqual(orphan['staff_active'], 1)

    def test_children_follow_their_parent(self):
        rows, _ = system_centre.centre_rows()
        codes = [r['unit'].code for r in rows]
        self.assertEqual(codes[:2], ['ت13', 'ت.ش'])
        self.assertEqual([r['depth'] for r in rows[:2]], [0, 1])

    def test_the_default_filter_shows_units_named_in_books(self):
        rows, _ = system_centre.centre_rows()
        picked = system_centre.filter_rows(rows)
        self.assertEqual(picked['show'], system_centre.SHOW_NAMED)
        self.assertNotIn('ت9', [r['unit'].code for r in picked['rows']])
        self.assertIn('ت9', [r['unit'].code for r in system_centre.filter_rows(rows, show='all')['rows']])
        self.assertEqual(system_centre.filter_rows(rows, show='nonsense')['show'], system_centre.SHOW_NAMED)

    def test_the_other_filters_and_search(self):
        rows, _ = system_centre.centre_rows()
        codes = lambda **kw: [r['unit'].code for r in system_centre.filter_rows(rows, **kw)['rows']]
        self.assertEqual(codes(show='late'), ['ت13'])
        self.assertEqual(sorted(codes(show='active')), ['ت.ش', 'ت13'])
        self.assertEqual(codes(show='all', query='لجنة تجربة'), ['ت9'])
        self.assertEqual(codes(show='all', query='ت4'), ['ت4'])

    def test_more_lifts_the_cap(self):
        rows = [{'unit': self.q, 'books': 1, 'dossier': 1, 'late': 0, 'tree_activity': 0} for _ in range(20)]
        self.assertEqual(len(system_centre.filter_rows(rows)['rows']), system_centre.DEFAULT_ROWS)
        self.assertEqual(len(system_centre.filter_rows(rows, expanded=True)['rows']), 20)
        self.assertEqual(system_centre.filter_rows(rows)['matched'], 20)

    def test_the_page_links_to_lens_dossier_and_department(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse(CENTRE)).content.decode('utf-8')
        self.assertIn(f'dept={self.q.pk}', html)
        self.assertIn(reverse('dossier_detail', args=[self.ent_q.pk]), html)
        self.assertIn(reverse('system_department', args=[self.q.pk]), html)

    def test_jump_goes_to_the_department_and_ignores_garbage(self):
        self.client.force_login(self.admin)
        self.assertRedirects(self.client.get(reverse(CENTRE), {'go': self.x.pk}),
                             reverse('system_department', args=[self.x.pk]), fetch_redirect_response=False)
        for bad in ('999999', 'x'):
            self.assertEqual(self.client.get(reverse(CENTRE), {'go': bad}).status_code, 200)


class DepartmentPageTests(SystemAdminCase):
    def page(self, dept):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('system_department', args=[dept.pk]))
        self.assertEqual(resp.status_code, 200)
        return resp

    def test_numbers_cover_its_tree(self):
        ctx = self.page(self.q).context
        self.assertEqual((ctx['late_count'], ctx['tree_size']), (1, 1))
        self.assertEqual(ctx['row']['books'], 3)
        self.assertEqual({c['unit'].code for c in ctx['children']}, {'ت.ش'})

    def test_no_training_or_deleted_in_recent(self):
        numbers = {b.our_number for b in self.page(self.q).context['recent']}
        self.assertNotIn('T1', numbers)
        self.assertNotIn('103', numbers)

    def test_it_says_whether_the_unit_holds_a_register(self):
        self.assertContains(self.page(self.s), 'لا تمسك سجلّاً')
        self.assertNotContains(self.page(self.s), reverse('desk_board') + '"><i class="bi bi-inbox"')

    def test_a_missing_department_is_404(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('system_department', args=[999999])).status_code, 404)


class LensTests(SystemAdminCase):
    def listing(self, user, **params):
        self.client.force_login(user)
        return self.client.get(reverse('book_unified'), {'tab': 'all', **params}).context

    def test_the_admin_sees_one_tree(self):
        self.assertEqual(self.listing(self.admin, dept=self.s.pk)['total_count'], 1)
        self.assertEqual(self.listing(self.admin, dept=self.q.pk)['total_count'], 3)
        self.assertEqual(self.listing(self.admin)['total_count'], 3)

    def test_the_bar_offers_the_way_back(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse('book_unified'), {'tab': 'all', 'dept': self.q.pk}).content.decode('utf-8')
        self.assertIn('رجوع إلى القسم', html)
        self.assertIn(reverse('system_department', args=[self.q.pk]), html)

    def test_the_refresh_and_export_follow_it(self):
        self.client.force_login(self.admin)
        api = self.client.get(reverse('api_unified_data'), {'tab': 'all', 'dept': self.s.pk}).json()
        self.assertEqual(len(api['books']), 1)
        resp = self.client.get(reverse('api_export_csv'), {'tab': 'all', 'dept': self.s.pk})
        body = (b''.join(resp.streaming_content) if resp.streaming else resp.content).decode('utf-8-sig')
        self.assertIn('102', body)
        self.assertNotIn('20250825', body)

    def test_nobody_else_can_use_it(self):
        ctx = self.listing(self.clerk, dept=self.x.pk)
        self.assertIsNone(ctx['lens_department'])
        self.assertNotEqual(ctx['total_count'], 0)

    def test_garbage_is_ignored(self):
        for bad in ('999999', 'abc', ''):
            with self.subTest(bad=bad):
                self.assertIsNone(self.listing(self.admin, dept=bad)['lens_department'])

    def test_clearing_filters_keeps_the_lens(self):
        src = Path('static/js/book_unified_ajax_manager.js').read_text(encoding='utf-8')
        self.assertIn('dept: this.currentState.dept, page: 1', src)
        self.assertIn('params.dept       = this.currentState.dept', src)
        self.assertIn("this.currentState.dept       = p.get('dept')", src)


class OpsCase(TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.logs = Path(tmp.name) / 'logs'
        self.backups = Path(tmp.name) / 'backups'
        self.logs.mkdir()
        self.backups.mkdir()
        patcher = patch('core.backup_service.default_backup_dir', return_value=self.backups)
        patcher.start()
        self.addCleanup(patcher.stop)
        settings_patch = override_settings(OPS_LOG_DIR=self.logs)
        settings_patch.enable()
        self.addCleanup(settings_patch.disable)
        BackupSettings.objects.update_or_create(singleton=1, defaults={'enabled': True})

    def touch(self, path, hours_ago, text='x'):
        path.write_text(text, encoding='utf-8')
        when = time.time() - hours_ago * 3600
        os.utime(path, (when, when))
        return path

    def jobs(self):
        return {j['key']: j for j in system_ops.job_statuses()}


class JobStateTests(OpsCase):
    def test_backup_state_comes_from_the_age_of_the_newest_file(self):
        self.touch(self.backups / 'pg_backup_old.dump.enc', 100)
        self.assertEqual(self.jobs()['backup']['state'], system_ops.STALE)
        self.touch(self.backups / 'pg_backup_new.dump.enc', 25)
        self.assertEqual(self.jobs()['backup']['state'], system_ops.OK)

    def test_the_limit_is_26_hours(self):
        self.touch(self.backups / 'pg_backup_a.dump.enc', 27)
        self.assertEqual(self.jobs()['backup']['state'], system_ops.STALE)

    def test_no_backup_at_all_is_a_failure_when_enabled(self):
        self.assertEqual(self.jobs()['backup']['state'], system_ops.STALE)
        self.assertEqual(self.jobs()['backup']['next_step'], 'settings_backup')

    def test_disabled_backup_is_not_a_failure(self):
        BackupSettings.objects.update(enabled=False)
        self.assertEqual(self.jobs()['backup']['state'], system_ops.UNKNOWN)

    def test_a_log_saying_rc_zero_does_not_make_a_stale_job_healthy(self):
        self.touch(self.logs / 'task_disk.log', 100, 'backup_hourly rc=0')
        self.assertEqual(self.jobs()['disk']['state'], system_ops.STALE)

    def test_a_missing_log_is_unknown_not_failed(self):
        self.assertEqual(self.jobs()['overdue']['state'], system_ops.UNKNOWN)

    def test_a_weekly_job_has_a_week(self):
        self.touch(self.logs / 'task_verify.log', 6 * 24)
        self.touch(self.backups / 'pg_backup_a.dump.enc', 1)
        self.assertEqual(self.jobs()['verify']['state'], system_ops.OK)
        self.touch(self.logs / 'task_verify.log', 9 * 24)
        self.assertEqual(self.jobs()['verify']['state'], system_ops.STALE)

    def test_an_alert_older_than_the_newest_backup_has_been_answered(self):
        self.touch(self.logs / 'task_verify.log', 1)
        self.touch(self.logs / 'ALERT_VERIFY.txt', 48)
        self.touch(self.backups / 'pg_backup_a.dump.enc', 1)
        self.assertEqual(self.jobs()['verify']['state'], system_ops.OK)

    def test_an_alert_newer_than_the_newest_backup_is_a_failure(self):
        self.touch(self.logs / 'task_verify.log', 1)
        self.touch(self.backups / 'pg_backup_a.dump.enc', 48)
        self.touch(self.logs / 'ALERT_VERIFY.txt', 1)
        self.assertEqual(self.jobs()['verify']['state'], system_ops.STALE)

    def test_the_badge_counts_failures_only(self):
        self.touch(self.backups / 'pg_backup_a.dump.enc', 1)
        self.touch(self.logs / 'task_disk.log', 1)
        self.touch(self.logs / 'task_overdue.log', 100)
        self.assertEqual(system_ops.failing_job_count(), 1)


class LogReadingTests(OpsCase):
    def write(self, text, name='task_backup.log'):
        (self.logs / name).write_text(text, encoding='utf-8')

    def test_newest_first_and_errors_only(self):
        self.write('[2026-11-03 08:00:00] INFO a\n[2026-11-03 08:01:00] ERROR b\n[2026-11-03 08:02:00] WARNING c\n')
        lines, err = system_ops.read_log('tasks', errors_only=True)
        self.assertEqual(err, '')
        self.assertEqual([l['level'] for l in lines], ['w', 'e'])
        self.assertEqual(len(system_ops.read_log('tasks')[0]), 3)

    def test_secrets_are_masked(self):
        self.write('GET /share/attachment/abc123/ 200\nGET /x?token=s3cret&a=1\nto admin@example.test\nGET /api/scan/serve/tok9/\n')
        text = '\n'.join(l['text'] for l in system_ops.read_log('tasks')[0])
        for secret in ('abc123', 's3cret', 'admin@example.test', 'tok9'):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, text)

    def test_an_unknown_key_cannot_name_a_file(self):
        self.write('secret line', name='other.log')
        with patch.dict(system_ops.LOG_SOURCES, {'system': ('النظام', lambda: self.logs / 'task_backup.log')}):
            self.write('system line')
            lines, _ = system_ops.read_log('../other.log')
        self.assertEqual([l['text'] for l in lines], ['system line'])

    def test_a_missing_file_says_so(self):
        lines, err = system_ops.read_log('server')
        self.assertEqual(lines, [])
        self.assertIn('لا يوجد', err)

    def test_a_big_file_reads_the_tail_without_the_cut_line(self):
        self.write('A' * 300 + '\n' + ('line\n' * 60000))
        lines, _ = system_ops.read_log('tasks')
        self.assertEqual(len(lines), system_ops.LOG_MAX_LINES)
        self.assertFalse(any(l['text'].startswith('AAA') for l in lines))

    def test_the_line_cut_by_the_tail_is_dropped(self):
        self.write('X' * (system_ops.LOG_TAIL_BYTES + 100) + '\nlast\n')
        self.assertEqual(len(system_ops.read_log('tasks')[0]), 1)  # لا فرقَ نصّيّ بربع ميغا عند الإخفاق

    def test_a_very_long_line_is_cut_for_display(self):
        self.write('a' * (system_ops.LOG_MAX_LINE_CHARS + 500) + '\n')
        self.assertEqual(len(system_ops.read_log('tasks')[0][0]['text']), system_ops.LOG_MAX_LINE_CHARS)

    def test_masking_a_long_word_stays_fast(self):
        """كان التعبيرُ تربيعيّاً فيعلّق الصفحة؛ كشفته طفرةٌ لا قارئ."""
        started = time.perf_counter()
        system_ops.mask('a' * 30000)
        self.assertLess(time.perf_counter() - started, 2)

    def test_a_bom_is_stripped(self):
        (self.logs / 'task_backup.log').write_bytes('﻿hello\n'.encode('utf-8'))
        self.assertEqual(system_ops.read_log('tasks')[0][0]['text'], 'hello')

    def test_service_errors_count_the_last_day(self):
        now = timezone.localtime()
        fresh = (now - timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
        old = (now - timedelta(hours=30)).strftime('%Y-%m-%d %H:%M:%S')
        path = self.logs / 'lettersys.log'
        path.write_text(f'[{fresh},1] ERROR core.messaging.engines.imap x\n[{old},1] ERROR core.extraction.pipeline y\n'
                        f'[{fresh},1] INFO core.extraction.pipeline z\n', encoding='utf-8')
        with patch.dict(system_ops.LOG_SOURCES, {'system': ('النظام', lambda: path)}):
            self.assertEqual(system_ops.service_errors(now), [{'label': 'مزامنة البريد', 'count': 1}])


class OpsPageTests(OpsCase):
    def test_the_page_escapes_and_masks(self):
        admin = User.objects.create_superuser('root2', password='pw-root-2222')
        (self.logs / 'task_backup.log').write_text('ERROR <script>alert(1)</script> /share/attachment/zzz/\n', encoding='utf-8')
        self.client.force_login(admin)
        html = self.client.get(reverse(OPS), {'log': 'tasks'}).content.decode('utf-8')
        self.assertNotIn('<script>alert(1)', html)
        self.assertNotIn('zzz', html)
        self.assertIn('dir="auto"', html)


class AgeTextTests(SimpleTestCase):
    def test_arabic_counting(self):
        cases = [(None, 'لا سجلّ'), (0.2, 'قبل أقلّ من ساعة'), (1, 'قبل ساعة'), (2, 'قبل ساعتين'), (3, 'قبل 3 ساعات'),
                 (20, 'قبل 20 ساعة'), (48, 'قبل يومين'), (72, 'قبل 3 أيام'), (24 * 12, 'قبل 12 يوماً')]
        for hours, text in cases:
            with self.subTest(hours=hours):
                self.assertEqual(system_ops.age_text(hours), text)


class CountingTests(SimpleTestCase):
    def test_arabic_counting_of_people(self):
        from core.views.system_admin import count_ar
        forms = ('موظّف واحد', 'موظّفان', 'موظّفين', 'موظّفاً')
        for n, text in ((1, 'موظّف واحد'), (2, 'موظّفان'), (3, '3 موظّفين'), (10, '10 موظّفين'), (11, '11 موظّفاً')):
            with self.subTest(n=n):
                self.assertEqual(count_ar(n, *forms), text)

    def test_numbers_are_grouped_whatever_the_language(self):
        from core.templatetags.ar_counts import grouped
        self.assertEqual((grouped(15703), grouped(0), grouped(None)), ('15,703', '0', '0'))
