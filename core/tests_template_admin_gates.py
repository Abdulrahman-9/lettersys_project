"""ق12 في 7.4‑هـ: مواضعُ `is_staff`/`is_superuser` الأربعةُ في القوالب صارت بوّاباتٍ
مسمّاةً تُحسَب في بايثون (`nav.admin` · `can_sync_mail` · `comment.can_edit`).
هذه الاختباراتُ تُثبت أنّ **ما يراه المستخدم لم يتغيّر** قبل البوّابة وبعدها.
"""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.context_processors import nav_gates
from core.models import Book, BookComment


class _Req:
    def __init__(self, user):
        self.user = user


class SidebarAdminGateTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.plain = User.objects.create_user('nplain', password='pw-nplain-11')
        cls.staff = User.objects.create_user('nstaff', password='pw-nstaff-11', is_staff=True)

    def test_nav_admin_mirrors_is_staff(self):
        self.assertFalse(nav_gates(_Req(self.plain))['nav']['admin'])
        self.assertTrue(nav_gates(_Req(self.staff))['nav']['admin'])

    def test_plain_user_does_not_see_admin_links(self):
        self.client.force_login(self.plain)
        resp = self.client.get(reverse('book_unified'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, reverse('user_roles'))

    def test_staff_sees_admin_links(self):
        self.client.force_login(self.staff)
        resp = self.client.get(reverse('book_unified'))
        self.assertContains(resp, reverse('user_roles'))


class MailSyncButtonGateTests(TestCase):

    def test_sync_button_is_a_view_decision(self):
        plain = User.objects.create_user('mplain', password='pw-mplain-11')
        staff = User.objects.create_user('mstaff', password='pw-mstaff-11', is_staff=True)
        self.client.force_login(plain)
        r1 = self.client.get(reverse('mail_inbox'))
        self.client.force_login(staff)
        r2 = self.client.get(reverse('mail_inbox'))
        if r1.status_code == 200:
            self.assertNotContains(r1, 'id="syncBtn"')
        self.assertEqual(r2.status_code, 200)
        self.assertContains(r2, 'id="syncBtn"')


class CommentCanEditTests(TestCase):

    def test_can_edit_is_computed_in_the_view(self):
        from core.models import Department, UserProfile
        dept = Department.objects.create(name='قسمُ التعليق', code='ق-ت')
        owner = User.objects.create_user('cowner', password='pw-cowner-11', is_staff=True)
        other = User.objects.create_user('cother', password='pw-cother-11', is_staff=True)
        UserProfile.objects.create(user=owner, department=dept)
        UserProfile.objects.create(user=other, department=dept)   # زميلٌ يرى الكتابَ ولا يملك التعليق
        boss = User.objects.create_superuser('cboss', 'b@x.com', 'pw-cboss-11')
        book = Book.objects.create(kind='incoming_internal', title='تعليق', created_by=owner,
                                   department=dept)
        BookComment.objects.create(book=book, created_by=owner, content='ملاحظة')
        url = reverse('book_detail', args=[book.pk])
        for user, expected in ((owner, 'data-can-edit="true"'), (other, 'data-can-edit="false"'),
                               (boss, 'data-can-edit="true"')):
            self.client.force_login(user)
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, user.username)
            self.assertContains(resp, expected, msg_prefix=user.username)
