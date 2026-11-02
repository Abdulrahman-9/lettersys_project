# -*- coding: utf-8 -*-
"""الهويّةُ والسلطة لمدير النظام وحدَه (قرارُ المالك 2026‑10‑07، البندان 1 و4).

الحساباتُ ولوحةُ الإدارة وورشةُ العناقيد بوّابةٌ واحدة (``can_manage_accounts``)، ولا
رابطَ يُظهَر لمن يلقى 403 بعده؛ وإعادةُ تعيين كلمة المرور فعلُ المدير على حسابِ غيره.
"""
from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase
from django.urls import reverse

from core.context_processors import nav_gates
from core.logging_models import UserActivityLog
from core.scoping import can_manage_accounts


class AccountsGateTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_user('gstaff', password='pw-gstaff-1111111', is_staff=True)
        cls.boss = User.objects.create_superuser('gboss', 'b@x.invalid', 'pw-gboss-1111111')

    def test_staff_cannot_open_or_post_to_the_accounts_page(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse('admin_panel') + '?tab=users').status_code, 403)
        resp = self.client.post(reverse('admin_panel'), {
            'action': 'create_department_user', 'tab': 'users', 'username': 'intruder'})
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(User.objects.filter(username='intruder').exists())

    def test_staff_pages_show_no_link_that_would_403(self):
        self.client.force_login(self.staff)
        for url in (reverse('settings_hub'), reverse('entity_list'), reverse('entity_list') + '?view=groups',
                    reverse('book_unified')):
            body = self.client.get(url).content.decode('utf-8')
            with self.subTest(url=url):
                self.assertNotIn(reverse('admin_panel'), body)
                # رابطٌ لا حقلٌ مخفيّ: نموذجُ الإجراءات الجماعيّة يحمل الاستعلامَ الحاليّ في «back»
                self.assertNotRegex(body, r'href="[^"]*view=groups')

    def test_the_boss_sees_all_three(self):
        self.client.force_login(self.boss)
        hub = self.client.get(reverse('settings_hub')).content.decode('utf-8')
        entities = self.client.get(reverse('entity_list')).content.decode('utf-8')
        self.assertIn(reverse('admin_panel'), hub)
        self.assertRegex(entities, r'href="[^"]*view=groups')
        self.assertEqual(self.client.get(reverse('admin_panel') + '?tab=users').status_code, 200)

    def test_the_nav_gate_is_the_page_gate(self):
        plain = User.objects.create_user('gplain', password='pw-gplain-1111111')
        rf = RequestFactory()
        for user in (plain, self.staff, self.boss):
            req = rf.get('/')
            req.user = user
            with self.subTest(user=user.username):
                self.assertEqual(nav_gates(req)['nav']['roles'], can_manage_accounts(user))


class PasswordResetTests(TestCase):

    def setUp(self):
        self.boss = User.objects.create_superuser('rboss', 'r@x.invalid', 'pw-rboss-1111111')
        self.clerk = User.objects.create_user('rclerk', password='old-pass-1234567')

    def _reset(self, who, target):
        self.client.force_login(who)
        return self.client.post(reverse('admin_panel'), {
            'action': 'reset_user_password', 'tab': 'users', 'user_id': target.pk})

    def test_a_non_superuser_cannot_reset(self):
        staff = User.objects.create_user('rstaff', password='pw-rstaff-1111111', is_staff=True)
        self.assertEqual(self._reset(staff, self.clerk).status_code, 403)
        self.clerk.refresh_from_db()
        self.assertTrue(self.clerk.check_password('old-pass-1234567'))

    def test_success_rotates_the_password_logs_it_and_ends_the_targets_sessions(self):
        other = self.client_class()
        other.force_login(self.clerk)
        self.assertEqual(other.get(reverse('dashboard')).status_code, 200)

        self._reset(self.boss, self.clerk)

        self.clerk.refresh_from_db()
        self.assertFalse(self.clerk.check_password('old-pass-1234567'))
        self.assertTrue(self.clerk.profile.must_change_password)
        log = UserActivityLog.objects.get(action='PASSWORD_RESET')
        self.assertEqual(log.metadata.get('user'), 'rclerk')
        self.assertEqual(other.get(reverse('dashboard')).status_code, 302)

    def test_another_admins_password_can_be_reset(self):
        """المديرُ الذي نسي كلمته يُنقذه مديرٌ آخر — كانت الصفحةُ القديمة تتيحه."""
        second = User.objects.create_superuser('rboss2', 'r2@x.invalid', 'pw-rboss2-111111')
        self._reset(self.boss, second)
        second.refresh_from_db()
        self.assertFalse(second.check_password('pw-rboss2-111111'))

    def test_your_own_account_is_not_reset_from_here(self):
        self._reset(self.boss, self.boss)
        self.boss.refresh_from_db()
        self.assertTrue(self.boss.check_password('pw-rboss-1111111'))
