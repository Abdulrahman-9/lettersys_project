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
from core.models import SecuritySettings
from core.scoping import can_manage_accounts
from core.views.users import PASSWORD_RESET_ACTION


class AccountsGateTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_user('gstaff', password='pw-gstaff-1111111', is_staff=True)
        cls.boss = User.objects.create_superuser('gboss', 'b@x.invalid', 'pw-gboss-1111111')

    def test_staff_cannot_open_or_post_to_the_accounts_page(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse('user_roles')).status_code, 403)
        resp = self.client.post(reverse('user_roles'), {
            'action': 'create', 'username': 'intruder', 'password': 'x' * 12, 'password2': 'x' * 12})
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(User.objects.filter(username='intruder').exists())

    def test_staff_pages_show_no_link_that_would_403(self):
        self.client.force_login(self.staff)
        for url in (reverse('settings_hub'), reverse('entity_list'), reverse('entity_list') + '?view=groups',
                    reverse('book_unified')):
            body = self.client.get(url).content.decode('utf-8')
            with self.subTest(url=url):
                self.assertNotIn(reverse('user_roles'), body)
                self.assertNotIn(reverse('admin_panel'), body)
                # رابطٌ لا حقلٌ مخفيّ: نموذجُ الإجراءات الجماعيّة يحمل الاستعلامَ الحاليّ في «back»
                self.assertNotRegex(body, r'href="[^"]*view=groups')

    def test_the_boss_sees_all_three(self):
        self.client.force_login(self.boss)
        hub = self.client.get(reverse('settings_hub')).content.decode('utf-8')
        entities = self.client.get(reverse('entity_list')).content.decode('utf-8')
        self.assertIn(reverse('user_roles'), hub)
        self.assertRegex(entities, r'href="[^"]*view=groups')
        self.assertEqual(self.client.get(reverse('user_roles')).status_code, 200)

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
        self.min_len = SecuritySettings.get().password_min_length
        self.new = 'New-Pass-' + '7' * self.min_len

    def _reset(self, who, target, pw, pw2=None):
        self.client.force_login(who)
        return self.client.post(reverse('user_roles'), {
            'action': 'reset_password', 'user_id': target.pk, 'password': pw,
            'password2': pw if pw2 is None else pw2}, follow=True)

    def test_a_non_superuser_cannot_reset(self):
        staff = User.objects.create_user('rstaff', password='pw-rstaff-1111111', is_staff=True)
        self.client.force_login(staff)
        resp = self.client.post(reverse('user_roles'), {
            'action': 'reset_password', 'user_id': self.clerk.pk, 'password': self.new, 'password2': self.new})
        self.assertEqual(resp.status_code, 403)
        self.clerk.refresh_from_db()
        self.assertTrue(self.clerk.check_password('old-pass-1234567'))

    def test_short_or_mismatched_changes_nothing_and_never_echoes_the_password(self):
        for pw, pw2 in (('x' * (self.min_len - 1), None), (self.new, self.new + 'X')):
            resp = self._reset(self.boss, self.clerk, pw, pw2)
            texts = ' '.join(m.message for m in resp.context['messages'])
            with self.subTest(pw=pw):
                self.assertNotIn(pw, texts)
                self.clerk.refresh_from_db()
                self.assertTrue(self.clerk.check_password('old-pass-1234567'))

    def test_success_sets_the_password_logs_it_and_ends_the_targets_sessions(self):
        other = self.client_class()
        other.force_login(self.clerk)
        self.assertEqual(other.get(reverse('dashboard')).status_code, 200)

        resp = self._reset(self.boss, self.clerk, self.new)

        self.clerk.refresh_from_db()
        self.assertTrue(self.clerk.check_password(self.new))
        texts = ' '.join(m.message for m in resp.context['messages'])
        self.assertNotIn(self.new, texts)
        log = UserActivityLog.objects.get(action=PASSWORD_RESET_ACTION)
        self.assertEqual(log.metadata.get('user'), 'rclerk')
        self.assertNotIn(self.new, str(log.metadata))
        self.assertEqual(other.get(reverse('dashboard')).status_code, 302)

    def test_your_own_account_goes_to_the_change_page(self):
        self.client.force_login(self.boss)
        resp = self.client.post(reverse('user_roles'), {
            'action': 'reset_password', 'user_id': self.boss.pk, 'password': self.new, 'password2': self.new})
        self.assertRedirects(resp, reverse('password_change'), fetch_redirect_response=False)
        self.boss.refresh_from_db()
        self.assertTrue(self.boss.check_password('pw-rboss-1111111'))
