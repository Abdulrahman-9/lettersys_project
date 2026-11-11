# -*- coding: utf-8 -*-
"""(ب)4 — الحذفُ والسلّة على مفتاحيهما (2026‑11‑11).

قرارُ المالك: الحذفُ إلى السلّة لرئيس القسم ومختصّ البريد · أبوابُ الاسترجاع الثلاثة (الكتاب
والمرفق والتراجعُ الفوريّ) لهما ولمسؤول الأرشفة · السلّةُ مغلقةٌ بالرابط أمام مَن لا يفعل فيها شيئاً
· حذفُ المرفق لمن يعدّل الكتاب. ولا زرَّ في صفوف القائمة يُعرض ليُرفض.
"""
import json

from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core import scoping as s
from core.models import (Attachment, Book, Department, RoleCapabilityOverride, UserCapabilityOverride,
                         UserProfile)
from core.roles import (ARCHIVIST_GROUP_NAME, CONTROLLER_GROUP_NAME, ENTRY_GROUP_NAME, EXECUTOR_GROUP_NAME,
                        ensure_role_groups)


class TrashCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_role_groups()
        cls.dept = Department.objects.create(name='قسم السلّة', code='سل1')
        cls.other = Department.objects.create(name='قسمٌ آخر للسلّة', code='سل2')
        cls.head = cls.person('t_head', cls.dept, head=True)
        cls.mail = cls.person('t_mail', cls.dept, CONTROLLER_GROUP_NAME)
        cls.arch = cls.person('t_arch', cls.dept, ARCHIVIST_GROUP_NAME)
        cls.entry = cls.person('t_entry', cls.dept, ENTRY_GROUP_NAME)
        cls.reader = cls.person('t_reader', cls.dept)
        cls.executor = cls.person('t_exec', cls.dept, EXECUTOR_GROUP_NAME)
        cls.far_mail = cls.person('t_farmail', cls.other, CONTROLLER_GROUP_NAME)

    @classmethod
    def person(cls, name, dept, group=None, head=False):
        user = User.objects.create_user(name, password='pw-trash-1111')
        UserProfile.objects.update_or_create(user=user, defaults={'department': dept, 'is_department_head': head})
        if group:
            user.groups.add(Group.objects.get(name=group))
        return user

    def setUp(self):
        cache.clear()
        self.book = Book.objects.create(kind='incoming_internal', title='كتاب السلّة', created_by=self.entry,
                                        department=self.dept, our_number='71')

    def fresh(self, user):
        return User.objects.get(pk=user.pk)

    def deleted(self, book=None):
        return Book.all_objects.get(pk=(book or self.book).pk).is_deleted

    def post(self, user, url, payload=None):
        self.client.force_login(user)
        if payload is None:
            return self.client.post(url)
        return self.client.post(url, data=json.dumps(payload), content_type='application/json')


class KeysTests(TrashCase):
    def test_who_trashes_and_who_restores(self):
        for user, trash, restore in ((self.head, True, True), (self.mail, True, True), (self.arch, False, True),
                                     (self.entry, False, False), (self.reader, False, False),
                                     (self.executor, False, False)):
            with self.subTest(user=user.username):
                u = self.fresh(user)
                self.assertIs(s.can_trash_book(self.book, u), trash)
                self.assertIs(s.can_restore_book(self.book, u), restore)
                self.assertIs(s.can_open_trash(u), trash or restore)

    def test_ownership_still_applies(self):
        u = self.fresh(self.far_mail)
        self.assertFalse(s.can_trash_book(self.book, u))
        self.assertFalse(s.can_restore_book(self.book, u))

    def test_a_frozen_role_row_does_not_open_the_trash(self):
        RoleCapabilityOverride.objects.create(role=s.ROLE_READER, capability='book.restore', allowed=True)
        self.assertFalse(s.can_open_trash(self.fresh(self.reader)))
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get(reverse('trash_list')).status_code, 403)


class DoorsTests(TrashCase):
    def test_entry_cannot_trash_alone_or_in_bulk(self):
        self.assertEqual(self.post(self.entry, reverse('api_delete_book', args=[self.book.pk])).status_code, 403)
        self.post(self.entry, reverse('api_bulk_delete_books'), {'book_ids': [self.book.pk]})
        self.assertFalse(self.deleted())

    def test_mail_trashes_and_undoes(self):
        response = self.post(self.mail, reverse('api_delete_book', args=[self.book.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['can_undo'])
        self.assertTrue(self.deleted())
        self.assertEqual(self.post(self.mail, reverse('api_undo_delete_book', args=[self.book.pk])).status_code, 200)
        self.assertFalse(self.deleted())

    def test_trash_without_restore_gets_no_undo(self):
        UserCapabilityOverride.objects.create(user=self.entry, capability='book.trash', allowed=True)
        response = self.post(self.entry, reverse('api_delete_book', args=[self.book.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['can_undo'])
        self.assertEqual(self.post(self.entry, reverse('api_undo_delete_book', args=[self.book.pk])).status_code, 403)
        self.assertTrue(self.deleted())

    def test_the_archivist_restores_but_does_not_trash(self):
        self.assertEqual(self.post(self.arch, reverse('api_delete_book', args=[self.book.pk])).status_code, 403)
        Book.all_objects.filter(pk=self.book.pk).update(is_deleted=True, deleted_at=timezone.now())
        self.post(self.arch, reverse('restore_book', args=[self.book.pk]))
        self.assertFalse(self.deleted())

    def test_the_entry_clerk_loses_the_trash_page_and_link(self):
        self.client.force_login(self.entry)
        self.assertEqual(self.client.get(reverse('trash_list')).status_code, 403)
        body = self.client.get(reverse('book_unified')).content.decode()
        self.assertNotIn('href="%s"' % reverse('trash_list'), body)
        self.client.force_login(self.arch)
        self.assertEqual(self.client.get(reverse('trash_list')).status_code, 200)

    def test_attachment_deletion_stays_with_whoever_edits(self):
        att = Attachment.objects.create(book=self.book, file=SimpleUploadedFile(
            'b4.pdf', b'%PDF-1.4 b4 test', content_type='application/pdf'))
        self.client.force_login(self.entry)
        self.client.post(reverse('attachment_delete', args=[att.pk]))
        self.assertTrue(Attachment.all_objects.get(pk=att.pk).is_deleted)


class RowButtonsTests(TrashCase):
    def test_the_bulk_marker_agrees_with_the_guards(self):
        secret = Book.objects.create(kind='incoming_internal', title='سرّيّ السلّة', created_by=self.mail,
                                     department=self.dept, secret_level='secret')
        far = Book.objects.create(kind='incoming_internal', title='بعيد السلّة', created_by=self.far_mail,
                                  department=self.other)
        for user in (self.head, self.mail, self.arch, self.entry, self.reader, self.far_mail):
            u = self.fresh(user)
            books = list(Book.objects.filter(pk__in=[self.book.pk, secret.pk, far.pk])
                         .annotate(restricted=s.restricted_flag_sql(u)))
            s.mark_row_actions(books, u)
            for book in books:
                with self.subTest(user=user.username, book=book.title):
                    self.assertIs(book.can_trash_row, s.can_trash_book(book, u))
                    self.assertIs(book.can_edit_row, s.can_edit_book(book, u))

    def rows(self, user):
        self.client.force_login(user)
        page = self.client.get(reverse('book_unified') + '?tab=all').content.decode()
        ajax = self.client.get(reverse('api_unified_data') + '?tab=all').json()
        return page, json.dumps(ajax, ensure_ascii=False)

    def test_rows_show_only_what_the_server_accepts(self):
        delete_url = reverse('api_delete_book', args=[self.book.pk])
        edit_url = reverse('book_edit', args=[self.book.pk])
        for user, can_edit, can_trash in ((self.mail, True, True), (self.entry, True, False),
                                          (self.reader, False, False)):
            for where, body in zip(('page', 'ajax'), self.rows(user)):
                with self.subTest(user=user.username, where=where):
                    self.assertIs(delete_url in body, can_trash)
                    self.assertIs(edit_url in body, can_edit)

    def test_bulk_buttons_follow_their_keys(self):
        self.client.force_login(self.entry)
        body = self.client.get(reverse('book_unified')).content.decode()
        self.assertNotIn('id="bulkDeleteBtn"', body)
        self.assertIn('id="bulkUpdateStatusBtn"', body)
        self.client.force_login(self.mail)
        self.assertIn('id="bulkDeleteBtn"', self.client.get(reverse('book_unified')).content.decode())
