# -*- coding: utf-8 -*-
"""تدقيقُ نيلسن F (مركز الإعدادات · المستخدمون · لوحة الإدارة) — حرّاسُ الخادم.

S3 الخروجُ POST وحدَه · F#1 «عرض كلمة المرور» الميّت أُزيل · F#2 تغييرُ كلمة المرور صار له مسار ·
F#7 الحدُّ الأدنى من الإعدادات · F#4 بطاقةُ الأدوار لمن يقبله حارسُها · F#9 الرفضُ لا يقول «حُفظ» ·
F#11 صفحةُ «غير متّصل» تُخدَم · F#5 «تعديل» العنقود يذهب إلى ورشته.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import NoReverseMatch, reverse

from core.models import Book, BookSequence, SecuritySettings


class LogoutTests(TestCase):

    def test_logout_refuses_get_and_accepts_post(self):
        user = User.objects.create_user('lgo', password='pw-lgo-11111111')
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('logout')).status_code, 405)
        self.assertIn('_auth_user_id', self.client.session)
        resp = self.client.post(reverse('logout'))
        self.assertRedirects(resp, reverse('login'), fetch_redirect_response=False)
        self.assertNotIn('_auth_user_id', self.client.session)


class PasswordChangeTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('pwc', password='old-pass-123456')
        self.min_len = SecuritySettings.get().password_min_length

    def test_anonymous_is_sent_to_login(self):
        resp = self.client.get(reverse('password_change'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse('login'), resp['Location'])

    def test_a_short_password_is_refused_with_the_settings_minimum(self):
        self.client.force_login(self.user)
        short = 'x' * (self.min_len - 1)
        resp = self.client.post(reverse('password_change'), {
            'old_password': 'old-pass-123456', 'new_password1': short, 'new_password2': short})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '%d أحرف على الأقل' % self.min_len)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('old-pass-123456'))

    def test_a_valid_change_keeps_the_user_signed_in(self):
        self.client.force_login(self.user)
        new = 'Nw-Pass-%s' % ('9' * self.min_len)
        resp = self.client.post(reverse('password_change'), {
            'old_password': 'old-pass-123456', 'new_password1': new, 'new_password2': new})
        self.assertRedirects(resp, reverse('dashboard'), fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(new))
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 200)

    def test_the_topbar_links_to_it(self):
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse('dashboard')), reverse('password_change'))


class UsersPageTests(TestCase):

    def setUp(self):
        self.admin = User.objects.create_superuser('uadm', 'u@x.co', 'pw-uadm-11111111')
        self.client.force_login(self.admin)

    def test_the_dead_show_password_feature_is_gone(self):
        with self.assertRaises(NoReverseMatch):
            reverse('get_user_password', args=[1])
        self.assertNotContains(self.client.get(reverse('user_roles')), 'عرض كلمة المرور')

    def test_the_form_asks_for_the_servers_minimum(self):
        min_len = SecuritySettings.get().password_min_length
        self.assertContains(self.client.get(reverse('user_roles')), 'minlength="%d"' % min_len)


class RolesGateTests(TestCase):

    def test_the_roles_card_is_shown_only_to_who_can_open_it(self):
        staff = User.objects.create_user('rstaff', password='pw-rstaff-1111111', is_staff=True)
        self.client.force_login(staff)
        self.assertNotContains(self.client.get(reverse('settings_hub')), 'الأقسام والأدوار')
        boss = User.objects.create_superuser('rboss', 'b@x.co', 'pw-rboss-11111111')
        self.client.force_login(boss)
        self.assertContains(self.client.get(reverse('settings_hub')), 'الأقسام والأدوار')


class CounterRejectionTests(TestCase):

    def test_a_rejected_number_does_not_also_say_saved(self):
        admin = User.objects.create_superuser('sqadm', 's@x.co', 'pw-sqadm-1111111')
        self.client.force_login(admin)
        Book.objects.create(kind='incoming_internal', title='صدر', our_number='3917', created_by=admin)
        BookSequence.objects.update_or_create(kind='incoming_internal', defaults={'next_number': 3918})
        resp = self.client.post(reverse('sequence_settings'),
                                {'next_number_incoming_internal': 3000}, follow=True)
        texts = [m.message for m in resp.context['messages']]
        self.assertTrue(any('لا يأتي بعد آخر رقمٍ' in t for t in texts), texts)
        self.assertFalse(any('حُفظ' in t or 'بنجاح' in t for t in texts), texts)


class OfflinePageTests(TestCase):

    def test_the_service_workers_offline_page_is_served(self):
        self.assertEqual(self.client.get('/offline.html').status_code, 200)
