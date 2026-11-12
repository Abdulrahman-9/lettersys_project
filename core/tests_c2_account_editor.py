# -*- coding: utf-8 -*-
"""(ج‑2) محرّرُ الحساب — دورٌ واحد، واستثناءاتٌ بأثر، وتغييرُ الدور أو القسم يُلغيها بتأكيد (2026‑11‑12).

التصميمُ المعتمد shots_v2/v2_account*.png. مراجعةُ فيبل: الأعلامُ الستّة تُضبط كلُّها صراحةً (علمٌ باقٍ
سلطةٌ خفيّة)، والمنفِّذُ يُمنح، ولا تعديلَ للنفس ولا لمدير نظام، ونقلُ القسم يُلغي الاستثناءاتِ ويرفض دوراً
لا يناسبه، وإلغاءُ استثناءٍ مقفلٍ أو يتيمٍ لا يُفشل التغيير.
"""
import itertools

from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import RequestFactory, TestCase
from django.urls import reverse

from core import scoping as s
from core.admin_service import assign_user
from core.logging_models import UserActivityLog
from core.models import Department, UserCapabilityOverride, UserProfile
from core.permission_service import role_change_preview, set_user_role
from core.roles import (ARCHIVE_ALL_GROUP_NAME, ARCHIVIST_GROUP_NAME, CONTROLLER_GROUP_NAME, ENTRY_GROUP_NAME,
                        EXECUTOR_GROUP_NAME, ensure_role_groups)

ROLE_GROUPS = {ENTRY_GROUP_NAME, CONTROLLER_GROUP_NAME, ARCHIVIST_GROUP_NAME, ARCHIVE_ALL_GROUP_NAME,
               EXECUTOR_GROUP_NAME}
EXPECTED = {   # الدور ⟵ (مجموعاتُ الدور، علمُ الرئاسة)
    'head': (set(), True), 'unit': (set(), True), 'mail': ({CONTROLLER_GROUP_NAME}, False),
    'archivist': ({ARCHIVIST_GROUP_NAME}, False), 'entry': ({ENTRY_GROUP_NAME}, False),
    'executor': ({EXECUTOR_GROUP_NAME}, False), 'reader': (set(), False),
}


class EditorCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_role_groups()
        Group.objects.get_or_create(name=EXECUTOR_GROUP_NAME)
        Group.objects.get_or_create(name=ARCHIVE_ALL_GROUP_NAME)
        cls.dept = Department.objects.create(name='قسم المحرّر', code='مح1')
        cls.unit = Department.objects.create(name='وحدة المحرّر', code='مح1و', parent=cls.dept, holds_register=False)
        cls.root = User.objects.create_superuser('c2_root', password='pw-c2-1111')
        cls.other_root = User.objects.create_superuser('c2_root2', password='pw-c2-1111')

    def setUp(self):
        cache.clear()
        self.request = RequestFactory().post('/books/system/account/')
        self.request.user = self.root

    def person(self, name, dept, role):
        user = User.objects.create_user(name, password='pw-c2-1111')
        UserProfile.objects.update_or_create(user=user, defaults={'department': dept,
                                                                   'is_department_head': role in ('head', 'unit')})
        groups, _head = EXPECTED[role]
        for group in groups:
            user.groups.add(Group.objects.get(name=group))
        return user

    def state(self, user):
        user = User.objects.get(pk=user.pk)
        return set(user.groups.values_list('name', flat=True)) & ROLE_GROUPS, user.profile.is_department_head


class RoleFlagsTests(EditorCase):
    def test_every_pair_leaves_exactly_the_new_roles_flags(self):
        for dept, roles in ((self.dept, ('head', 'mail', 'archivist', 'entry', 'reader')),
                            (self.unit, ('unit', 'executor', 'reader'))):
            for n, (before, after) in enumerate(itertools.permutations(roles, 2)):
                with self.subTest(dept=dept.code, before=before, after=after):
                    user = self.person(f'c2_{dept.code}_{n}', dept, before)
                    self.assertTrue(set_user_role(self.request, user, after))
                    self.assertEqual(self.state(user), EXPECTED[after])
                    self.assertEqual(s.role_of(User.objects.get(pk=user.pk)), after)

    def test_the_archivist_keeps_company_archive_only_while_archivist(self):
        user = self.person('c2_company', self.dept, 'archivist')
        user.groups.add(Group.objects.get(name=ARCHIVE_ALL_GROUP_NAME))
        set_user_role(self.request, user, 'entry')
        self.assertEqual(self.state(user), ({ENTRY_GROUP_NAME}, False))


class GuardsTests(EditorCase):
    def test_only_the_system_admin_and_never_on_self_or_another_admin(self):
        user = self.person('c2_guard', self.dept, 'entry')
        self.request.user = self.person('c2_head', self.dept, 'head')
        with self.assertRaisesMessage(PermissionDenied, 'أدوارُ الحسابات يغيّرها مدير النظام وحده.'):
            set_user_role(self.request, user, 'mail')
        self.request.user = self.root
        with self.assertRaises(PermissionDenied):
            set_user_role(self.request, self.root, 'reader')
        with self.assertRaises(PermissionDenied):
            set_user_role(self.request, self.other_root, 'reader')

    def test_the_role_must_fit_the_department(self):
        user = self.person('c2_fit', self.unit, 'executor')
        with self.assertRaisesMessage(ValidationError, 'هذا الدورُ لا يُسند في هذا القسم.'):
            set_user_role(self.request, user, 'mail')
        self.assertEqual(self.state(user), EXPECTED['executor'])


class ExceptionsTests(EditorCase):
    def test_a_role_change_cancels_every_exception_with_a_trace(self):
        user = self.person('c2_ex', self.dept, 'mail')
        UserCapabilityOverride.objects.create(user=user, capability='book.trash', allowed=False)
        UserCapabilityOverride.objects.create(user=user, capability='secret.own', allowed=False)   # مقفل
        UserCapabilityOverride.objects.create(user=user, capability='ghost.key', allowed=True)     # يتيم
        before = UserActivityLog.objects.count()
        set_user_role(self.request, user, 'entry')
        self.assertFalse(UserCapabilityOverride.objects.filter(user=user).exists())
        self.assertGreaterEqual(UserActivityLog.objects.count() - before, 4)   # ثلاثة إلغاءات + تغييرُ الدور

    def test_moving_department_cancels_exceptions_and_refuses_an_unfit_role(self):
        user = self.person('c2_move', self.dept, 'entry')
        UserCapabilityOverride.objects.create(user=user, capability='book.trash', allowed=True)
        with self.assertRaises(ValidationError):
            assign_user(user, by=self.root, department=self.unit)   # مدخلٌ في وحدةٍ لا تمسك سجلّاً
        self.assertTrue(UserCapabilityOverride.objects.filter(user=user).exists())   # التراجعُ ذرّيّ
        user = User.objects.get(pk=user.pk)   # كما يقرؤه الطلبُ التالي بعد إعادة التوجيه
        self.assertEqual(user.profile.department, self.dept)
        set_user_role(self.request, user, 'reader')
        user = User.objects.get(pk=user.pk)
        UserCapabilityOverride.objects.create(user=user, capability='book.comment', allowed=False)
        assign_user(user, by=self.root, department=self.unit)
        self.assertFalse(UserCapabilityOverride.objects.filter(user=user).exists())

    def test_the_preview_names_what_is_lost_kept_and_cancelled(self):
        user = self.person('c2_prev', self.dept, 'mail')
        UserCapabilityOverride.objects.create(user=user, capability='archive.complete', allowed=True)
        preview = role_change_preview(User.objects.get(pk=user.pk), 'entry')
        self.assertIn('تشغيل البريد', preview['lose'])
        self.assertIn('الإدخال', preview['keep'])
        self.assertEqual(preview['cancel'], ['تمام الأرشفة'])


class PageTests(EditorCase):
    def url(self, user):
        return reverse('system_account', args=[user.pk])

    def test_the_page_is_the_system_admins(self):
        user = self.person('c2_page', self.dept, 'entry')
        self.client.force_login(self.person('c2_pagehead', self.dept, 'head'))
        self.assertEqual(self.client.get(self.url(user)).status_code, 403)
        self.client.force_login(self.root)
        body = self.client.get(self.url(user)).content.decode()
        self.assertIn('id="aeRole"', body)
        for label in ('رئيس قسم', 'مختصّ البريد', 'مسؤول الأرشفة', 'مدخل', 'قارئ'):
            self.assertIn(f'>{label}</option>', body)
        self.assertNotIn('>موظّف تنفيذ</option>', body)

    def test_role_change_needs_the_dialogs_confirmation(self):
        user = self.person('c2_confirm', self.dept, 'entry')
        self.client.force_login(self.root)
        self.client.post(self.url(user), {'action': 'role', 'role': 'mail', 'confirm': '0'})
        self.assertEqual(s.role_of(User.objects.get(pk=user.pk)), 'entry')
        self.client.post(self.url(user), {'action': 'role', 'role': 'mail', 'confirm': '1'})
        self.assertEqual(s.role_of(User.objects.get(pk=user.pk)), 'mail')

    def test_exceptions_are_added_and_returned_to_the_role(self):
        user = self.person('c2_over', self.dept, 'entry')
        self.client.force_login(self.root)
        self.client.post(self.url(user), {'action': 'override', 'key': 'book.trash', 'value': 'allow'})
        self.assertTrue(UserCapabilityOverride.objects.get(user=user, capability='book.trash').allowed)
        self.client.post(self.url(user), {'action': 'override', 'key': 'book.trash', 'value': 'reset'})
        self.assertFalse(UserCapabilityOverride.objects.filter(user=user).exists())
        self.client.post(self.url(user), {'action': 'override', 'key': 'archive.complete', 'value': 'allow'})
        self.assertFalse(UserCapabilityOverride.objects.filter(user=user).exists())   # غيرُ موصول

    def test_a_department_change_needs_confirmation(self):
        user = self.person('c2_dept', self.dept, 'reader')
        other = Department.objects.create(name='قسمٌ ثانٍ', code='مح2')
        self.client.force_login(self.root)
        data = {'action': 'save', 'name': 'اسم جديد', 'department': str(other.pk), 'job_title': '', 'is_active': '1'}
        self.client.post(self.url(user), {**data, 'confirm_department': '0'})
        self.assertEqual(User.objects.get(pk=user.pk).profile.department, self.dept)
        self.client.post(self.url(user), {**data, 'confirm_department': '1'})
        moved = User.objects.get(pk=user.pk)
        self.assertEqual((moved.profile.department, moved.first_name), (other, 'اسم'))

    def test_a_temporary_password_shows_once_and_is_not_cached(self):
        user = self.person('c2_pw', self.dept, 'reader')
        self.client.force_login(self.root)
        response = self.client.post(self.url(user), {'action': 'password'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('ae-secret', response.content.decode())
        self.assertIn('no-store', response['Cache-Control'])

    def test_the_accounts_list_links_to_the_editor(self):
        user = self.person('c2_list', self.dept, 'reader')
        self.client.force_login(self.root)
        self.assertIn(self.url(user), self.client.get(reverse('admin_panel') + '?tab=users').content.decode())
