# -*- coding: utf-8 -*-
"""(ب)5 — البريدُ على مفاتيحه (2026‑11‑12).

قرارُ المالك: تشغيلُ البريد لمختصّه (``mail.operate``) وإرسالُ الكتاب كذلك (``mail.send_book``)،
وإعداداتُ بريد الشركة لمدير النظام وحده (``mail.settings`` المقفل — أُزيل ``is_staff``). وواجبُ أمن:
أمينُ السرّيّ يقرأ ``secret.own`` المقفل لا العضويّة، ونطاقُ كتب البريد لا يتجاوز نطاقَ الكتب.
"""
import json

from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from core import scoping as s
from core.messaging.scoping import mailable_book, scope_mail_books
from core.models import Book, Department, UserCapabilityOverride, UserProfile
from core.roles import CONTROLLER_GROUP_NAME, ENTRY_GROUP_NAME, ensure_role_groups


class MailCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_role_groups()
        cls.dept = Department.objects.create(name='قسم البريد', code='بر1')
        cls.unit = Department.objects.create(name='وحدة البريد', code='بر1و', parent=cls.dept, holds_register=False)
        cls.mail = cls.person('m_mail', cls.dept, CONTROLLER_GROUP_NAME)
        cls.entry = cls.person('m_entry', cls.dept, ENTRY_GROUP_NAME)
        cls.reader = cls.person('m_reader', cls.dept)
        cls.head = cls.person('m_head', cls.dept, head=True)
        cls.unit_head = cls.person('m_unithead', cls.unit, head=True)
        cls.staff = cls.person('m_staff', cls.dept)
        User.objects.filter(pk=cls.staff.pk).update(is_staff=True)
        cls.root = User.objects.create_superuser('m_root', password='pw-mail-1111')
        cls.book = Book.objects.create(kind='incoming_internal', title='كتاب البريد', created_by=cls.mail,
                                       department=cls.dept)
        cls.secret = Book.objects.create(kind='incoming_internal', title='سرّيّ البريد', created_by=cls.mail,
                                         department=cls.dept, secret_level='secret')
        # كتابٌ عاديٌّ في قسمٍ آخر: خارج نطاق مختصّ البريد — يكشف نطاقَ بريدٍ بلا حدّ
        far_dept = Department.objects.create(name='قسمٌ بعيد للبريد', code='بر2')
        cls.far = Book.objects.create(kind='incoming_internal', title='بعيد البريد',
                                      created_by=cls.person('m_far', far_dept), department=far_dept)
        cls.unit_secret = Book.objects.create(kind='incoming_internal', title='سرّيّ الوحدة', created_by=cls.mail,
                                              department=cls.unit, secret_level='secret')

    @classmethod
    def person(cls, name, dept, group=None, head=False):
        user = User.objects.create_user(name, password='pw-mail-1111')
        UserProfile.objects.update_or_create(user=user, defaults={'department': dept, 'is_department_head': head})
        if group:
            user.groups.add(Group.objects.get(name=group))
        return user

    def setUp(self):
        cache.clear()

    def fresh(self, user):
        return User.objects.get(pk=user.pk)

    def post_json(self, user, url, payload):
        self.client.force_login(user)
        return self.client.post(url, data=json.dumps(payload), content_type='application/json')


class KeysTests(MailCase):
    def test_operate_and_send_are_the_mail_officers(self):
        for user, expected in ((self.mail, True), (self.entry, False), (self.reader, False), (self.head, False),
                               (self.root, True)):
            with self.subTest(user=user.username):
                self.assertIs(s.can_operate_mail(self.fresh(user)), expected)
                self.assertIs(s.can_send_book_mail(self.fresh(user)), expected)

    def test_company_mail_settings_are_the_system_admins_alone(self):
        for user in (self.mail, self.staff, self.head):
            with self.subTest(user=user.username):
                self.assertFalse(s.can_manage_mail(self.fresh(user)))
                self.client.force_login(user)
                self.assertEqual(self.client.get(reverse('mail_settings')).status_code, 403)
                self.assertEqual(self.client.post(reverse('email-test-smtp')).status_code, 403)
        self.assertTrue(s.can_manage_mail(self.root))

    def test_a_person_exception_opens_operate_but_never_settings(self):
        UserCapabilityOverride.objects.create(user=self.entry, capability='mail.operate', allowed=True)
        UserCapabilityOverride.objects.create(user=self.entry, capability='mail.settings', allowed=True)
        self.assertTrue(s.can_operate_mail(self.fresh(self.entry)))
        self.assertFalse(s.can_manage_mail(self.fresh(self.entry)))


class DoorsTests(MailCase):
    def test_operating_doors_refuse_without_the_key(self):
        cases = (('/books/mail/api/compose/', {'to': 'a@b.example', 'subject': 's', 'body': 'b'}),
                 ('/books/mail/api/bulk-send/', {'book_ids': [self.book.pk], 'subject': 's'}),
                 (reverse('mail-api-inbox-sync'), {}))
        for url, payload in cases:
            with self.subTest(url=url):
                self.assertEqual(self.post_json(self.entry, url, payload).status_code, 403)
                self.assertNotEqual(self.post_json(self.mail, url, payload).status_code, 403)
        self.client.force_login(self.entry)
        for name in ('mail_compose', 'mail_templates'):
            self.assertEqual(self.client.get(reverse(name)).status_code, 403)
        self.client.force_login(self.mail)
        self.assertEqual(self.client.get(reverse('mail_templates')).status_code, 200)

    def test_sending_the_book_needs_its_key(self):
        response = self.post_json(self.entry, '/books/api/email/send/', {'book_id': self.book.pk, 'to': 'a@b.example'})
        self.assertEqual((response.status_code, response.json()['error_code']), (403, 'FORBIDDEN'))
        response = self.post_json(self.entry, f'/books/api/email/book/{self.book.pk}/send/', {})
        self.assertEqual(response.status_code, 403)


class SurfacesTests(MailCase):
    def page(self, user, url):
        self.client.force_login(user)
        return self.client.get(url, follow=True).content.decode()

    def test_compose_and_send_buttons_follow_operate(self):
        compose = reverse('mail_compose_book', args=[self.book.pk])
        self.assertIn(compose, self.page(self.mail, reverse('book_detail', args=[self.book.pk])))
        self.assertNotIn(compose, self.page(self.entry, reverse('book_detail', args=[self.book.pk])))
        self.assertIn(f'href="{reverse("mail_compose")}"', self.page(self.mail, reverse('mail_hub')))
        self.assertNotIn(f'href="{reverse("mail_compose")}"', self.page(self.entry, reverse('mail_hub')))

    def test_save_and_send_follows_send_book(self):
        self.assertIn('id="saveAndSendButton"', self.page(self.mail, '/books/extract/smart-desktop/'))
        self.assertNotIn('id="saveAndSendButton"', self.page(self.entry, '/books/extract/smart-desktop/'))


class SecretDutyTests(MailCase):
    def test_the_custodian_reads_the_locked_key(self):
        self.assertTrue(s._department_custodian(self.fresh(self.mail)))
        self.assertTrue(s._department_custodian(self.fresh(self.head)))
        self.assertFalse(s._department_custodian(self.fresh(self.unit_head)))   # الوحدةُ تستلم ولا تفتح
        self.assertFalse(s.can_open_content(self.unit_secret, self.fresh(self.unit_head)))
        UserCapabilityOverride.objects.create(user=self.reader, capability='secret.own', allowed=True)
        self.assertFalse(s._department_custodian(self.fresh(self.reader)))       # مقفلٌ: لا استثناء

    def test_mail_scope_never_exceeds_book_scope(self):
        everything = Book.objects.all()
        for user in (self.mail, self.entry, self.reader, self.head, self.unit_head):
            with self.subTest(user=user.username):
                u = self.fresh(user)
                self.assertLessEqual(set(scope_mail_books(everything, u).values_list('pk', flat=True)),
                                     set(s.scope_books_for(u, everything).values_list('pk', flat=True)))

    def test_granting_operate_does_not_open_secret_mail(self):
        UserCapabilityOverride.objects.create(user=self.reader, capability='mail.operate', allowed=True)
        reader = self.fresh(self.reader)
        self.assertNotIn(self.secret.pk, scope_mail_books(Book.objects.all(), reader).values_list('pk', flat=True))
        self.assertIsNone(mailable_book(reader, self.secret.pk))
        self.assertEqual(mailable_book(self.fresh(self.mail), self.secret.pk), self.secret)
