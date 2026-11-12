# -*- coding: utf-8 -*-
"""(ب)6 — الطاولةُ والدفترُ والتقاريرُ وسجلُّ الحركات على مفاتيحها (2026‑11‑12).

قرارُ المالك: الطاولةُ (``desk.board``) لرئيس القسم ومختصّ البريد وموظّف التنفيذ — والمنفِّذ مقصورٌ
على وحدته؛ الدفترُ وكشفُ التسليم (``desk.ledger``) لرئيس القسم ومختصّ البريد؛ التقاريرُ وسجلُّ الحركات
(``report.view``/``audit.view``) لرئيس القسم ومسؤول الوحدة، والنطاقُ شجرةُ قسم حامل المفتاح.
"""
from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from core import scoping as s
from core.logging_models import UserActivityLog
from core.models import Book, BookReferral, Department, UserCapabilityOverride, UserProfile
from core.roles import (ARCHIVIST_GROUP_NAME, CONTROLLER_GROUP_NAME, ENTRY_GROUP_NAME, EXECUTOR_GROUP_NAME,
                        ensure_role_groups)


class DeskCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_role_groups()
        cls.dept = Department.objects.create(name='قسم الطاولة', code='طا1')
        cls.unit = Department.objects.create(name='وحدة الطاولة', code='طا1و', parent=cls.dept, holds_register=False)
        cls.sibling = Department.objects.create(name='وحدةٌ أخرى', code='طا1خ', parent=cls.dept, holds_register=False)
        cls.head = cls.person('d6_head', cls.dept, head=True)
        cls.mail = cls.person('d6_mail', cls.dept, CONTROLLER_GROUP_NAME)
        cls.arch = cls.person('d6_arch', cls.dept, ARCHIVIST_GROUP_NAME)
        cls.entry = cls.person('d6_entry', cls.dept, ENTRY_GROUP_NAME)
        cls.reader = cls.person('d6_reader', cls.dept)
        cls.executor = cls.person('d6_exec', cls.unit, EXECUTOR_GROUP_NAME)
        cls.unit_head = cls.person('d6_unithead', cls.unit, head=True)
        cls.mine = Book.objects.create(kind='incoming_internal', title='إلى وحدة المنفِّذ', created_by=cls.mail,
                                       department=cls.dept, our_number='61')
        cls.theirs = Book.objects.create(kind='incoming_internal', title='إلى الوحدة الأخرى', created_by=cls.mail,
                                         department=cls.dept, our_number='62')
        BookReferral.objects.create(book=cls.mine, from_department=cls.dept, to_department=cls.unit,
                                    status=BookReferral.SENT, created_by=cls.mail)
        BookReferral.objects.create(book=cls.theirs, from_department=cls.dept, to_department=cls.sibling,
                                    status=BookReferral.SENT, created_by=cls.mail)

    @classmethod
    def person(cls, name, dept, group=None, head=False):
        user = User.objects.create_user(name, password='pw-desk-1111')
        UserProfile.objects.update_or_create(user=user, defaults={'department': dept, 'is_department_head': head})
        if group:
            user.groups.add(Group.objects.get(name=group))
        return user

    def setUp(self):
        cache.clear()

    def fresh(self, user):
        return User.objects.get(pk=user.pk)


class KeysTests(DeskCase):
    def test_who_opens_the_board_the_ledger_reports_and_audit(self):
        table = ((self.head, True, True, True), (self.mail, True, True, False), (self.executor, True, False, False),
                 (self.unit_head, False, False, True), (self.arch, False, False, False),
                 (self.entry, False, False, False), (self.reader, False, False, False))
        for user, board, ledger, oversee in table:
            with self.subTest(user=user.username):
                u = self.fresh(user)
                self.assertIs(s.can_use_desk(u), board)
                self.assertIs(s.can_use_ledger(u), ledger)
                self.assertIs(s.can_view_reports(u), oversee)
                self.assertIs(s.can_view_audit(u), oversee)


class BoardTests(DeskCase):
    def board(self, user):
        self.client.force_login(user)
        return self.client.get(reverse('desk_board') + '?queue=unreceived')

    def test_the_executor_sees_his_unit_only(self):
        response = self.board(self.executor)
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn('إلى وحدة المنفِّذ', body)
        self.assertNotIn('إلى الوحدة الأخرى', body)
        self.assertNotIn(reverse('desk_ledger'), body)

    def test_the_mail_officer_sees_the_department_and_the_ledger(self):
        body = self.board(self.mail).content.decode()
        self.assertIn('إلى وحدة المنفِّذ', body)
        self.assertIn('إلى الوحدة الأخرى', body)
        self.assertIn(reverse('desk_ledger'), body)

    def test_closed_to_whoever_lacks_the_key(self):
        for user in (self.entry, self.reader, self.arch, self.unit_head):
            with self.subTest(user=user.username):
                self.assertEqual(self.board(user).status_code, 403)

    def test_the_ledger_and_handover_follow_their_own_key(self):
        self.client.force_login(self.executor)
        for name in ('desk_ledger', 'desk_handover'):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 403)
        self.client.force_login(self.mail)
        self.assertEqual(self.client.get(reverse('desk_ledger')).status_code, 200)


class OversightScopeTests(DeskCase):
    def test_a_report_grant_opens_the_holders_tree_not_an_empty_page(self):
        self.assertFalse(s.report_departments(self.fresh(self.mail)).exists())
        UserCapabilityOverride.objects.create(user=self.mail, capability='report.view', allowed=True)
        departments = set(s.report_departments(self.fresh(self.mail)).values_list('pk', flat=True))
        self.assertEqual(departments, {self.dept.pk, self.unit.pk, self.sibling.pk})

    def test_the_unit_head_oversees_his_unit_only(self):
        departments = set(s.report_departments(self.fresh(self.unit_head)).values_list('pk', flat=True))
        self.assertEqual(departments, {self.unit.pk})

    def test_audit_follows_its_key(self):
        UserActivityLog.objects.create(user=self.executor, action='view', department=self.unit)
        self.assertTrue(s.scope_activity_for(self.fresh(self.unit_head)).exists())
        self.assertFalse(s.scope_activity_for(self.fresh(self.mail)).exists())
        UserCapabilityOverride.objects.create(user=self.mail, capability='audit.view', allowed=True)
        self.assertTrue(s.scope_activity_for(self.fresh(self.mail)).exists())


class RecentRowFlagsTests(DeskCase):
    """مراجعةُ فيبل: أعلامُ «آخر القيود» من حرّاس الخدمة — لا زرَّ يُعرض للمنفِّذ ثمّ يُرفض."""

    def test_the_executor_is_offered_only_what_the_service_accepts(self):
        from core.referral_service import mark_received
        from core.views.queues import _recent_desk_books

        book = Book.objects.create(kind='outgoing_internal', title='صادر الوحدة', created_by=self.mail,
                                   department=self.unit, our_number='63')
        out = BookReferral.objects.create(book=book, from_department=self.unit, to_department=self.sibling,
                                          status=BookReferral.SENT, purpose=BookReferral.ACTION, created_by=self.mail)
        inn = BookReferral.objects.create(book=book, from_department=self.dept, to_department=self.unit,
                                          status=BookReferral.SENT, purpose=BookReferral.ACTION, created_by=self.mail)
        executor = self.fresh(self.executor)
        books = _recent_desk_books(executor, self.unit.pk, s.subtree_ids(self.unit.pk))
        rows = {row.pk: row for listed in books for row in listed.desk_referrals}
        for flag in ('desk_can_receive', 'desk_can_cancel', 'desk_can_update_followup'):
            with self.subTest(flag=flag):
                self.assertFalse(getattr(rows[out.pk], flag))
        self.assertFalse(rows[inn.pk].desk_can_cancel)
        self.assertTrue(rows[inn.pk].desk_can_receive)
        mark_received(inn, by=executor)   # ما يُعرض يقبله الخادم

    def test_the_mail_officer_keeps_cancel_and_followup(self):
        from core.views.queues import _recent_desk_books

        ref = BookReferral.objects.filter(book=self.mine).get()
        Book.objects.filter(pk=self.mine.pk).update(department=self.dept)
        BookReferral.objects.filter(pk=ref.pk).update(purpose=BookReferral.ACTION)
        mail = self.fresh(self.mail)
        books = _recent_desk_books(mail, self.dept.pk, s.subtree_ids(self.dept.pk))
        row = next(r for listed in books for r in listed.desk_referrals if r.pk == ref.pk)
        self.assertTrue(row.desk_can_cancel)
        self.assertTrue(row.desk_can_update_followup)
