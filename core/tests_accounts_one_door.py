# -*- coding: utf-8 -*-
"""مراجعةُ صفحات السوبر أدمن 2026-11-02 — حرّاسُ ما أُغلق.

١. **بابٌ واحدٌ للحسابات**: تبويبُ لوحة الإدارة. والحسابُ الجديد يُختار قسمُه صراحةً،
   ويُجبَر على تغيير كلمته، ويترك أثراً.
٢. **الحذفُ انتقل إلى اللوحة بأثرٍ يبقى بعد ذهاب الحساب**، والرفضُ لا يترك أثراً كاذباً.
٣. **كلُّ تغيير إعدادٍ يُكتب في سجلّ الحركات**: ما تغيّر وقيمتاه — والسرُّ اسمُه وحدَه،
   ولا صفَّ إن لم يتغيّر شيء.
٤. **وضعُ التشغيل ظاهرٌ** في مركز الإعدادات بعد أن كان مخفيّاً.
"""
import json

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import NoReverseMatch, reverse

from core import roles
from core.logging_models import UserActivityLog
from core.models import (AIIntegrationSettings, BackupSettings, Book, BookSequence, Department,
                         EmailSettings, NetworkSettings, NotificationSettings, SecuritySettings,
                         SystemSettings, UserProfile)

PANEL = '/books/admin/'


def _settings_rows():
    return UserActivityLog.objects.filter(action='EDIT_SETTINGS')


class OneDoorTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.first = Department.objects.create(name='القسم الأوّل', code='أ-1102')
        cls.second = Department.objects.create(name='القسم الثاني', code='ب-1102')
        cls.boss = User.objects.create_superuser('door_boss', 'b@x.co', 'pw-door-boss-1')

    def setUp(self):
        self.client.force_login(self.boss)

    def create(self, **fields):
        return self.client.post(PANEL, {'action': 'create_department_user', 'tab': 'users',
                                        'role': 'viewer', **fields})

    def test_the_old_page_has_no_name_left_to_link_to(self):
        with self.assertRaises(NoReverseMatch):
            reverse('user_roles')

    def test_the_sidebar_leads_to_the_panel_and_the_hub_has_no_second_door(self):
        self.assertContains(self.client.get(reverse('book_unified')), PANEL + '?tab=users')
        hub = self.client.get(reverse('settings_hub'))
        self.assertNotContains(hub, 'data-tab="users"')
        self.assertNotContains(hub, '/books/users/')

    def test_an_account_without_a_department_is_refused_and_keeps_the_form(self):
        response = self.create(username='nodept', department='', job_title='كاتب')
        self.assertFalse(User.objects.filter(username='nodept').exists())
        self.assertContains(response, 'اختر قسمَ الحساب الجديد')
        self.assertContains(response, 'value="كاتب"')

    def test_the_chosen_department_is_kept_and_nothing_is_guessed(self):
        """في وضع «قسم واحد» كان الحسابُ يقع صامتاً في أوّل قسم."""
        self.assertEqual(SystemSettings.get().deployment_profile, SystemSettings.PROFILE_SINGLE)
        self.create(username='chosen', department=self.second.pk)
        self.assertEqual(UserProfile.objects.get(user__username='chosen').department, self.second)

    def test_a_new_account_must_rotate_its_password_and_leaves_a_trace(self):
        self.create(username='traced', department=self.first.pk)
        self.assertTrue(UserProfile.objects.get(user__username='traced').must_change_password)
        log = UserActivityLog.objects.get(action='CREATE_USER')
        self.assertEqual(log.metadata['user'], 'traced')


class DeleteAccountTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.dept = Department.objects.create(name='قسم الحذف', code='ح-1102')
        cls.boss = User.objects.create_superuser('del_boss', 'b@x.co', 'pw-del-boss-111')
        cls.plain = User.objects.create_user('del_plain', password='pw-del-plain-11')
        UserProfile.objects.update_or_create(user=cls.plain, defaults={'department': cls.dept})

    def delete(self, who, target):
        self.client.force_login(who)
        return self.client.post(PANEL, {'action': 'delete_user', 'tab': 'users',
                                        'user_id': target.pk}, follow=True)

    def test_deleting_leaves_a_trace_that_outlives_the_account(self):
        self.delete(self.boss, self.plain)
        self.assertFalse(User.objects.filter(username='del_plain').exists())
        log = UserActivityLog.objects.get(action='DELETE_USER')
        self.assertEqual(log.metadata['user'], 'del_plain')
        self.assertEqual(log.user, self.boss)

    def test_a_book_author_is_refused_with_the_way_out_and_no_false_trace(self):
        Book.objects.create(kind='incoming_internal', title='له', our_number='8302',
                            created_by=self.plain, department=self.dept)
        response = self.delete(self.boss, self.plain)
        self.assertTrue(User.objects.filter(pk=self.plain.pk).exists())
        self.assertContains(response, 'عطِّله بدل ذلك')
        self.assertFalse(UserActivityLog.objects.filter(action='DELETE_USER').exists())

    def test_the_account_in_use_is_kept_and_has_no_button(self):
        self.delete(self.boss, self.boss)
        self.assertTrue(User.objects.filter(pk=self.boss.pk).exists())
        html = self.client.get(PANEL + '?tab=users').content.decode('utf-8')
        self.assertIn('حذف حساب «del_plain»', html)
        self.assertNotIn('حذف حساب «del_boss»', html)

    def test_a_department_head_neither_deletes_nor_sees_the_button(self):
        head = User.objects.create_user('del_head', password='pw-del-head-111')
        UserProfile.objects.create(user=head, department=self.dept, is_department_head=True)
        self.delete(head, self.plain)
        self.assertTrue(User.objects.filter(pk=self.plain.pk).exists())
        html = self.client.get(PANEL + '?tab=users').content.decode('utf-8')
        self.assertNotIn('حذف حساب «', html)


class SettingsAuditTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        roles.ensure_role_groups()
        cls.boss = User.objects.create_superuser('set_boss', 'b@x.co', 'pw-set-boss-111')
        cls.dept = Department.objects.create(name='قسم الإعدادات', code='ع-1102')

    def setUp(self):
        self.client.force_login(self.boss)

    def row_after(self, call):
        before = _settings_rows().count()
        response = call()
        self.assertLess(response.status_code, 400, response.content[:200])
        rows = _settings_rows().order_by('-pk')
        self.assertEqual(rows.count(), before + 1, 'لم يُسجَّل التغيير')
        return rows.first()

    def test_every_settings_form_writes_the_log(self):
        post = self.client.post
        forms = {
            'هوية النظام': lambda: post(reverse('settings_general_save'),
                                        {'app_name': 'نظام الاختبار', 'brand_subtitle': 'وصف'}),
            'سياسة الإشعارات': lambda: post(reverse('settings_notifications_save'),
                                            {'overdue_enabled': 'on'}),
            'الأمان': lambda: post(reverse('settings_security_save'), {'password_min_length': '11'}),
            'النسخ الاحتياطي': lambda: post(reverse('settings_backup_save'),
                                            {'enabled': 'on', 'frequency': 'daily', 'hour': '4',
                                             'retention_days': '9'}),
            'الاستخراج الخارجيّ': lambda: post(reverse('settings_ai_save'),
                                               {'provider': 'azure', 'azure_endpoint': 'https://e.test'}),
            'البريد الإلكتروني': lambda: post(reverse('mail_settings'), {'smtp_host': 'smtp.new.test'}),
            'الربط الشبكي': lambda: post(reverse('network-save-config'),
                                         data=json.dumps({'role': 'standalone', 'this_host': '10.9.8.7',
                                                          'app_port': 1312}),
                                         content_type='application/json'),
        }
        for section, call in forms.items():
            with self.subTest(section):
                row = self.row_after(call)
                self.assertEqual(row.metadata['section'], section)
                self.assertEqual(row.user, self.boss)
                self.assertTrue(row.metadata['changes'])

    def test_the_counters_and_the_hold_time_are_settings_too(self):
        BookSequence.get_next('incoming_internal')   # يُنشئ صفَّ القسم الافتراضيّ
        row = self.row_after(lambda: self.client.post(reverse('sequence_settings'),
                                                      {'next_number_incoming_internal': '777'}))
        self.assertIn('العدّادات', row.metadata['section'])
        self.assertIn('777', row.metadata['summary'])
        minutes = SystemSettings.RESERVATION_TTL_MIN + 1
        row = self.row_after(lambda: self.client.post(reverse('sequence_settings'),
                                                      {'reservation_expire_minutes': str(minutes)}))
        self.assertEqual(row.metadata['section'], 'مدّة حجز الرقم')

    def test_the_log_says_what_changed_with_both_values(self):
        cfg = SecuritySettings.get()
        old = cfg.password_min_length
        row = self.row_after(lambda: self.client.post(reverse('settings_security_save'),
                                                      {'password_min_length': str(old + 2)}))
        change = next(iter(row.metadata['changes'].values()))
        self.assertEqual(change, {'from': old, 'to': old + 2})
        self.assertIn(str(old + 2), row.metadata['summary'])

    def test_the_summary_reads_in_arabic(self):
        cfg = NotificationSettings.get()
        cfg.overdue_enabled = False
        cfg.save()
        row = self.row_after(lambda: self.client.post(reverse('settings_notifications_save'),
                                                      {'overdue_enabled': 'on'}))
        self.assertIn('لا ⟵ نعم', row.metadata['summary'])
        self.assertNotIn('True', row.metadata['summary'])
        self.assertIn({'from': False, 'to': True}, row.metadata['changes'].values())
        row = self.row_after(lambda: self.client.post(reverse('settings_general_save'),
                                                      {'app_name': 'نظام', 'brand_subtitle': ''}))
        SystemSettings.objects.update(brand_subtitle='وصف')
        row = self.row_after(lambda: self.client.post(reverse('settings_general_save'),
                                                      {'app_name': 'نظام', 'brand_subtitle': ''}))
        self.assertIn('(فارغ)', row.metadata['summary'])

    def test_saving_without_a_change_writes_nothing(self):
        cfg = SecuritySettings.get()
        before = _settings_rows().count()
        self.client.post(reverse('settings_security_save'),
                         {'password_min_length': str(cfg.password_min_length)})
        self.assertEqual(_settings_rows().count(), before)

    def test_secrets_are_named_never_written(self):
        secrets = {
            'mail': lambda: self.client.post(reverse('mail_settings'), {
                'smtp_password': 'SMTP-SECRET-VALUE', 'imap_password': 'IMAP-SECRET-VALUE'}),
            'ai': lambda: self.client.post(reverse('settings_ai_save'), {
                'provider': 'azure', 'azure_key': 'AZURE-SECRET-VALUE'}),
        }
        for label, call in secrets.items():
            with self.subTest(label):
                row = self.row_after(call)
                self.assertNotIn('SECRET-VALUE', json.dumps(row.metadata, ensure_ascii=False))
                self.assertIn('changed', row.metadata['changes'].values())

    def test_the_audit_page_shows_the_label_and_what_changed(self):
        self.client.post(reverse('settings_security_save'), {'password_min_length': '13'})
        page = self.client.get(reverse('audit_log'), {'tab': 'users'})
        self.assertContains(page, 'تعديل إعدادات')
        self.assertContains(page, 'الأمان —')

    def test_the_password_reset_row_has_a_label_not_a_code(self):
        UserActivityLog.objects.create(user=self.boss, action='PASSWORD_RESET')
        page = self.client.get(reverse('audit_log'), {'tab': 'users'})
        self.assertContains(page, 'إعادة تعيين كلمة مرور')
        self.assertNotContains(page, '>PASSWORD_RESET<')

    def test_the_panels_recent_activity_includes_settings_and_deletions(self):
        UserActivityLog.objects.create(user=self.boss, action='EDIT_SETTINGS', metadata={})
        UserActivityLog.objects.create(user=self.boss, action='DELETE_USER', metadata={})
        page = self.client.get(PANEL + '?tab=overview')
        actions = [entry.action for entry in page.context['admin_activity']]
        self.assertIn('EDIT_SETTINGS', actions)
        self.assertIn('DELETE_USER', actions)

    def test_the_old_settings_api_is_gone(self):
        response = self.client.post('/books/api/email/settings/',
                                    data='{"smtp_host":"evil.test"}', content_type='application/json')
        self.assertEqual(response.status_code, 404)
        self.assertNotEqual(EmailSettings.get().smtp_host, 'evil.test')


class OperatingModeIsVisibleTests(TestCase):

    def test_the_hub_names_the_mode_and_the_default_department(self):
        Department.objects.create(name='قسم افتراضيّ', code='ف-1102')
        boss = User.objects.create_superuser('mode_boss', 'b@x.co', 'pw-mode-boss-11')
        self.client.force_login(boss)
        hub = self.client.get(reverse('settings_hub'))
        self.assertContains(hub, 'وضع التشغيل:')
        self.assertContains(hub, 'قسم واحد')
        self.assertContains(hub, BookSequence.resolve_department().name)

    def test_only_who_can_open_the_panel_sees_it(self):
        staff = User.objects.create_user('mode_staff', password='pw-mode-staff-1', is_staff=True)
        self.client.force_login(staff)
        self.assertNotContains(self.client.get(reverse('settings_hub')), 'وضع التشغيل:')
