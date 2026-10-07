# -*- coding: utf-8 -*-
"""الدفعةُ الثانية من تدقيق نيلسن (2026‑10‑07): حرّاسُ الخادم وحدَهم.

E#3 حذفُ الذات/آخرِ مدير/صاحبِ الكتب · E#4 خفضُ العدّاد تحت آخر رقمٍ صدر · E#1 الدخولُ الخاطئ يقول.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import Book, BookSequence


class UserDeleteGuardTests(TestCase):

    def setUp(self):
        self.admin = User.objects.create_superuser('gadmin', 'g@x.co', 'pw-gadmin-1111')
        self.client.force_login(self.admin)

    def _delete(self, user):
        return self.client.post(reverse('user_roles'), {'action': 'delete', 'user_id': user.pk})

    def test_an_admin_cannot_delete_the_account_in_use(self):
        User.objects.create_superuser('gadmin2', 'g2@x.co', 'pw-gadmin2-1111')
        self._delete(self.admin)
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())

    def test_the_last_active_admin_is_kept(self):
        staff = User.objects.create_user('gstaff', password='pw-gstaff-1111', is_staff=True)
        self.client.force_login(staff)
        self._delete(self.admin)
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())

    def test_a_book_author_is_refused_not_a_500(self):
        author = User.objects.create_user('gauthor', password='pw-gauthor-1111')
        Book.objects.create(kind='incoming_internal', title='له', our_number='8301', created_by=author)
        resp = self._delete(author)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(User.objects.filter(pk=author.pk).exists())

    def test_a_plain_user_is_still_deleted(self):
        plain = User.objects.create_user('gplain', password='pw-gplain-1111')
        self._delete(plain)
        self.assertFalse(User.objects.filter(pk=plain.pk).exists())


class SequenceLoweringGuardTests(TestCase):

    def setUp(self):
        self.admin = User.objects.create_superuser('sadmin', 's@x.co', 'pw-sadmin-1111')
        self.client.force_login(self.admin)
        Book.objects.create(kind='incoming_internal', title='صدر', our_number='3917', created_by=self.admin)
        BookSequence.objects.update_or_create(kind='incoming_internal', defaults={'next_number': 3918})

    def _save(self, number):
        return self.client.post(reverse('sequence_settings'), {'next_number_incoming_internal': number})

    def test_a_number_already_issued_is_refused(self):
        self._save(3917)
        self.assertEqual(BookSequence.objects.get(kind='incoming_internal').next_number, 3918)

    def test_moving_forward_is_saved(self):
        self._save(4000)
        self.assertEqual(BookSequence.objects.get(kind='incoming_internal').next_number, 4000)


class LoginErrorTests(TestCase):

    def test_a_wrong_password_says_so(self):
        User.objects.create_user('lclerk', password='pw-lclerk-1111')
        resp = self.client.post(reverse('login'), {'username': 'lclerk', 'password': 'wrong'})
        self.assertContains(resp, 'كلمةُ المرور غيرُ صحيحة')
        self.assertContains(resp, 'value="lclerk"')
