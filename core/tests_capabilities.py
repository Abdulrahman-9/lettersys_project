# -*- coding: utf-8 -*-
"""محلِّلُ الصلاحيّات: الافتراضُ خليّةً خليّة، وترتيبُ القرار، وقواعدُ من يعدّل، والأثر."""
import io
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.test import RequestFactory, SimpleTestCase, TestCase

from core import permission_service as svc
from core import scoping as s
from core.logging_models import UserActivityLog
from core.models import Book, Department, RoleCapabilityOverride, UserCapabilityOverride, UserProfile
from core.roles import (ARCHIVE_ALL_GROUP_NAME, ARCHIVIST_GROUP_NAME, CONTROLLER_GROUP_NAME, ENTRY_GROUP_NAME,
                        EXECUTOR_GROUP_NAME)

# المصفوفةُ المعتمدة نصّاً: أيُّ تغييرٍ في core/scoping.py يُسقط هذا الملفّ عمداً.
W = {'head', 'mail', 'archivist', 'entry'}
APPROVED = {
    'book.read': ({'head', 'mail', 'archivist', 'entry', 'unit', 'executor', 'reader'}, True),
    'book.comment': ({'head', 'mail', 'archivist', 'entry', 'unit', 'executor', 'reader'}, False),
    'book.enter': (W, False), 'book.edit': (W, False), 'number.reserve': (W, False), 'entity.add': (W, False),
    'book.trash': ({'head', 'mail'}, False), 'book.restore': ({'head', 'mail', 'archivist'}, False),
    'secret.own': ({'head', 'mail', 'archivist'}, True), 'secret.other': (set(), True),
    'referral.send': ({'head', 'mail', 'unit'}, False),
    'referral.receive': ({'head', 'mail', 'unit', 'executor'}, False),
    'custody.link': (W, False), 'book.sign': ({'head'}, True), 'archive.complete': ({'archivist'}, False),
    'desk.board': ({'head', 'mail', 'executor'}, False), 'desk.ledger': ({'head', 'mail'}, False),
    'desk.mine': ({'unit'}, False),
    'report.view': ({'head', 'unit'}, False), 'audit.view': ({'head', 'unit'}, False),
    'mail.operate': ({'mail'}, False), 'mail.send_book': ({'mail'}, False), 'mail.settings': (set(), True),
    'staff.manage': ({'head', 'unit'}, True), 'grant.office': ({'head'}, True),
    'grant.basic': ({'head', 'unit'}, True), 'unit.add': ({'head'}, True), 'account.manage': (set(), True),
}


class MatrixTests(SimpleTestCase):
    def test_the_registry_is_the_approved_matrix_cell_by_cell(self):
        self.assertEqual(set(s.CAPABILITIES), set(APPROVED))
        for key, (holders, locked) in APPROVED.items():
            with self.subTest(key=key):
                self.assertEqual(set(s.CAPABILITIES[key].holders), holders)
                self.assertEqual(s.CAPABILITIES[key].locked, locked)

    def test_writing_cells_are_frozen_for_reader_and_executor_only(self):
        for key in ('book.enter', 'book.edit', 'number.reserve', 'entity.add', 'book.trash', 'book.restore',
                    'custody.link', 'mail.send_book'):
            for role in ('reader', 'executor'):
                self.assertTrue(s.role_cell_frozen(key, role), (key, role))
            self.assertFalse(s.role_cell_frozen(key, 'entry'))
        self.assertFalse(s.role_cell_frozen('referral.receive', 'executor'))


class CapabilityCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dept = Department.objects.create(name='قسم محلِّل', code='ح1')
        cls.unit = Department.objects.create(name='وحدة محلِّل', code='ح1و', parent=cls.dept, holds_register=False)
        cls.other = Department.objects.create(name='قسم آخر للمحلِّل', code='ح2')
        cls.admin = User.objects.create_superuser('c_root', password='x')
        cls.head = cls.person('c_head', cls.dept, head=True)
        cls.unit_head = cls.person('c_unithead', cls.unit, head=True)
        cls.far_head = cls.person('c_farhead', cls.other, head=True)
        cls.mail = cls.person('c_mail', cls.dept, CONTROLLER_GROUP_NAME)
        cls.arch = cls.person('c_arch', cls.dept, ARCHIVIST_GROUP_NAME)
        cls.entry = cls.person('c_entry', cls.dept, ENTRY_GROUP_NAME)
        cls.executor = cls.person('c_exec', cls.unit, EXECUTOR_GROUP_NAME)
        cls.reader = cls.person('c_reader', cls.dept)

    @classmethod
    def person(cls, name, dept, group=None, head=False):
        user = User.objects.create_user(name, password='x')
        UserProfile.objects.update_or_create(user=user, defaults={'department': dept, 'is_department_head': head})
        if group:
            user.groups.add(Group.objects.get_or_create(name=group)[0])
        return user

    def fresh(self, user):
        return User.objects.get(pk=user.pk)

    def req(self, user):
        request = RequestFactory().post('/books/admin/')
        request.user = user
        return request


class RoleOfTests(CapabilityCase):
    def test_each_account_has_one_role(self):
        cases = ((self.head, 'head'), (self.unit_head, 'unit'), (self.mail, 'mail'), (self.arch, 'archivist'),
                 (self.entry, 'entry'), (self.executor, 'executor'), (self.reader, 'reader'))
        for user, role in cases:
            with self.subTest(role=role):
                self.assertEqual(s.role_of(user), role)

    def test_the_priority_when_groups_are_combined(self):
        combo = self.person('c_combo', self.dept, ENTRY_GROUP_NAME)
        combo.groups.add(Group.objects.get_or_create(name=ARCHIVIST_GROUP_NAME)[0])
        self.assertEqual(s.role_of(combo), 'archivist')
        combo.groups.add(Group.objects.get_or_create(name=CONTROLLER_GROUP_NAME)[0])
        self.assertEqual(s.role_of(combo), 'mail')
        combo.profile.is_department_head = True
        combo.profile.save(update_fields=['is_department_head'])
        self.assertEqual(s.role_of(self.fresh(combo)), 'head')

    def test_company_archive_is_an_archivist(self):
        self.assertEqual(s.role_of(self.person('c_comp', self.dept, ARCHIVE_ALL_GROUP_NAME)), 'archivist')

    def test_a_head_without_a_department_is_a_head(self):
        self.assertEqual(s.role_of(self.person('c_nodept', None, head=True)), 'head')

    def test_a_user_without_a_profile_is_a_reader(self):
        bare = User.objects.create_user('c_bare', password='x')
        UserProfile.objects.filter(user=bare).delete()
        self.assertEqual(s.role_of(self.fresh(bare)), 'reader')


class DecisionOrderTests(CapabilityCase):
    def test_every_cell_follows_the_matrix_on_empty_tables(self):
        people = {'head': self.head, 'unit': self.unit_head, 'mail': self.mail, 'archivist': self.arch,
                  'entry': self.entry, 'executor': self.executor, 'reader': self.reader}
        for key, (holders, _locked) in APPROVED.items():
            for role, user in people.items():
                with self.subTest(key=key, role=role):
                    self.assertEqual(s.has_capability(self.fresh(user), key), role in holders)

    def test_inactive_has_nothing_even_when_superuser(self):
        self.admin.is_active = False
        self.assertFalse(s.has_capability(self.admin, 'book.read'))
        self.reader.is_active = False
        self.assertFalse(s.has_capability(self.reader, 'book.comment'))

    def test_anonymous_has_nothing(self):
        from django.contrib.auth.models import AnonymousUser
        self.assertFalse(s.has_capability(AnonymousUser(), 'book.read'))

    def test_the_superuser_has_everything_even_locked(self):
        for key in s.CAPABILITIES:
            self.assertTrue(s.has_capability(self.admin, key), key)

    def test_an_unknown_key_is_a_bug_not_a_no(self):
        with self.assertRaises(KeyError):
            s.has_capability(self.reader, 'book.nonsense')

    def test_a_row_planted_on_a_locked_key_is_ignored(self):
        RoleCapabilityOverride.objects.create(role='reader', capability='secret.other', allowed=True)
        UserCapabilityOverride.objects.create(user=self.reader, capability='secret.other', allowed=True)
        self.assertFalse(s.has_capability(self.fresh(self.reader), 'secret.other'))
        RoleCapabilityOverride.objects.create(role='head', capability='book.sign', allowed=False)
        self.assertTrue(s.has_capability(self.fresh(self.head), 'book.sign'))

    def test_a_row_planted_on_a_frozen_cell_is_ignored(self):
        RoleCapabilityOverride.objects.create(role='reader', capability='book.edit', allowed=True)
        self.assertFalse(s.has_capability(self.fresh(self.reader), 'book.edit'))
        self.assertFalse(s.role_capability('reader', 'book.edit'))

    def test_a_role_override_flips_the_role(self):
        RoleCapabilityOverride.objects.create(role='entry', capability='book.restore', allowed=True)
        self.assertTrue(s.has_capability(self.fresh(self.entry), 'book.restore'))
        self.assertFalse(s.has_capability(self.fresh(self.reader), 'book.restore'))
        self.assertTrue(s.role_capability('entry', 'book.restore'))

    def test_a_personal_exception_beats_the_role_override(self):
        RoleCapabilityOverride.objects.create(role='entry', capability='book.restore', allowed=True)
        UserCapabilityOverride.objects.create(user=self.entry, capability='book.restore', allowed=False)
        self.assertFalse(s.has_capability(self.fresh(self.entry), 'book.restore'))

    def test_a_personal_exception_reaches_a_frozen_cell(self):
        """المجمَّدُ على مستوى الدور يبقى ممكناً لشخصٍ بعينه."""
        UserCapabilityOverride.objects.create(user=self.executor, capability='book.edit', allowed=True)
        self.assertTrue(s.has_capability(self.fresh(self.executor), 'book.edit'))

    def test_an_exception_belongs_to_one_person(self):
        UserCapabilityOverride.objects.create(user=self.entry, capability='book.trash', allowed=True)
        other = self.person('c_entry2', self.dept, ENTRY_GROUP_NAME)
        self.assertFalse(s.has_capability(other, 'book.trash'))

    def test_a_grant_widens_no_scope(self):
        """المنحُ لا يخرج عن النطاق: الكتابُ في قسمٍ آخر والسرّيُّ يبقيان مغلقين."""
        far = Book.objects.create(kind='incoming_internal', title='بعيد', our_number='9001',
                                  created_by=self.far_head, department=self.other)
        secret = Book.objects.create(kind='incoming_internal', title='سرّ', our_number='9002', secret_level='secret',
                                     created_by=self.head, department=self.dept)
        for key in s.CAPABILITIES:
            if not s.CAPABILITIES[key].locked:
                UserCapabilityOverride.objects.update_or_create(user=self.reader, capability=key, defaults={'allowed': True})
        user = self.fresh(self.reader)
        self.assertFalse(s.can_view_book(far, user))
        self.assertFalse(s.can_open_content(secret, user))
        self.assertNotIn(far, s.scope_books_for(user, Book.objects.all()))


class CacheTests(CapabilityCase):
    def test_one_object_asks_the_database_once(self):
        user = self.fresh(self.entry)
        s.has_capability(user, 'book.edit')
        with self.assertNumQueries(0):
            s.has_capability(user, 'book.trash')
            s.has_capability(user, 'audit.view')

    def test_the_next_request_sees_a_withdrawal(self):
        UserCapabilityOverride.objects.create(user=self.entry, capability='book.trash', allowed=True)
        self.assertTrue(s.has_capability(self.fresh(self.entry), 'book.trash'))
        UserCapabilityOverride.objects.all().delete()
        self.assertFalse(s.has_capability(self.fresh(self.entry), 'book.trash'))

    def test_clearing_refreshes_the_same_object(self):
        user = self.fresh(self.entry)
        self.assertFalse(s.has_capability(user, 'book.trash'))
        UserCapabilityOverride.objects.create(user=self.entry, capability='book.trash', allowed=True)
        s.clear_capability_cache(user)
        self.assertTrue(s.has_capability(user, 'book.trash'))

    def test_the_service_clears_the_target_it_holds(self):
        target = self.fresh(self.entry)
        self.assertFalse(s.has_capability(target, 'book.trash'))
        svc.set_user_override(self.req(self.admin), target, 'book.trash', True)
        self.assertTrue(s.has_capability(target, 'book.trash'))


class RoleOverrideServiceTests(CapabilityCase):
    def test_only_the_system_admin_edits_the_matrix(self):
        for user in (self.head, self.unit_head, self.mail, self.reader):
            with self.subTest(user=user.username), self.assertRaises(PermissionDenied):
                svc.set_role_override(self.req(user), 'entry', 'book.restore', True)
        self.assertFalse(RoleCapabilityOverride.objects.exists())

    def test_locked_and_frozen_cells_are_refused(self):
        for role, key in (('head', 'book.sign'), ('reader', 'secret.other'), ('reader', 'book.edit'), ('executor', 'book.enter')):
            with self.subTest(role=role, key=key), self.assertRaises(PermissionDenied):
                svc.set_role_override(self.req(self.admin), role, key, True)

    def test_unknown_role_and_key_are_errors(self):
        with self.assertRaises(ValueError):
            svc.set_role_override(self.req(self.admin), 'ghost', 'book.restore', True)
        with self.assertRaises(KeyError):
            svc.set_role_override(self.req(self.admin), 'entry', 'ghost', True)

    def test_a_change_writes_a_row_and_its_trace(self):
        self.assertTrue(svc.set_role_override(self.req(self.admin), 'entry', 'book.restore', True))
        row = RoleCapabilityOverride.objects.get()
        self.assertEqual((row.role, row.capability, row.allowed, row.changed_by), ('entry', 'book.restore', True, self.admin))
        log = UserActivityLog.objects.get(action='EDIT_PERMISSIONS')
        self.assertEqual(log.user, self.admin)
        self.assertEqual((log.metadata['scope'], log.metadata['role'], log.metadata['from'], log.metadata['to']),
                         ('role', 'entry', False, True))
        self.assertIn('الاسترجاع من السلّة', log.metadata['summary'])

    def test_no_change_leaves_no_trace(self):
        self.assertFalse(svc.set_role_override(self.req(self.admin), 'entry', 'book.edit', True))
        self.assertFalse(UserActivityLog.objects.filter(action='EDIT_PERMISSIONS').exists())
        self.assertFalse(RoleCapabilityOverride.objects.exists())

    def test_returning_to_the_default_deletes_the_row(self):
        svc.set_role_override(self.req(self.admin), 'entry', 'book.restore', True)
        self.assertTrue(svc.set_role_override(self.req(self.admin), 'entry', 'book.restore', False))
        self.assertFalse(RoleCapabilityOverride.objects.exists())
        self.assertEqual(UserActivityLog.objects.filter(action='EDIT_PERMISSIONS').count(), 2)

    def test_a_failed_trace_cancels_the_change(self):
        with patch('core.permission_service._audit', side_effect=RuntimeError('boom')), self.assertRaises(RuntimeError):
            svc.set_role_override(self.req(self.admin), 'entry', 'book.restore', True)
        self.assertFalse(RoleCapabilityOverride.objects.exists())


class UserOverrideServiceTests(CapabilityCase):
    def test_the_head_grants_what_he_holds_to_his_staff(self):
        self.assertTrue(svc.set_user_override(self.req(self.head), self.entry, 'book.trash', True))
        self.assertTrue(s.has_capability(self.fresh(self.entry), 'book.trash'))

    def test_the_head_cannot_grant_what_he_does_not_hold(self):
        with self.assertRaises(PermissionDenied):
            svc.set_user_override(self.req(self.head), self.entry, 'mail.operate', True)
        with self.assertRaises(PermissionDenied):
            svc.set_user_override(self.req(self.head), self.entry, 'archive.complete', True)

    def test_the_head_cannot_reach_another_department(self):
        with self.assertRaises(PermissionDenied):
            svc.set_user_override(self.req(self.far_head), self.entry, 'book.trash', True)

    def test_the_head_reaches_his_tree(self):
        self.assertTrue(svc.set_user_override(self.req(self.head), self.executor, 'book.edit', True))

    def test_nobody_edits_himself(self):
        for user in (self.head, self.admin):
            with self.subTest(user=user.username), self.assertRaises(PermissionDenied):
                svc.set_user_override(self.req(user), user, 'book.trash', True)

    def test_locked_is_refused_even_for_the_admin(self):
        with self.assertRaises(PermissionDenied):
            svc.set_user_override(self.req(self.admin), self.entry, 'book.sign', True)

    def test_unit_managers_and_staff_cannot_edit_exceptions(self):
        """مسؤولُ الشعبة والوحدة مغلقٌ بقرار المالك 2026‑11‑03."""
        with self.assertRaises(PermissionDenied):
            svc.set_user_override(self.req(self.unit_head), self.executor, 'book.comment', False)
        with self.assertRaises(PermissionDenied):
            svc.set_user_override(self.req(self.mail), self.entry, 'book.trash', True)

    def test_the_admin_can_grant_anything_unlocked(self):
        self.assertTrue(svc.set_user_override(self.req(self.admin), self.entry, 'mail.operate', True))

    def test_equal_to_the_role_stores_nothing(self):
        self.assertFalse(svc.set_user_override(self.req(self.admin), self.entry, 'book.edit', True))
        self.assertFalse(UserCapabilityOverride.objects.exists())
        self.assertFalse(UserActivityLog.objects.filter(action='EDIT_PERMISSIONS').exists())

    def test_back_to_the_role_deletes_and_traces(self):
        svc.set_user_override(self.req(self.admin), self.entry, 'book.trash', True)
        self.assertTrue(svc.set_user_override(self.req(self.admin), self.entry, 'book.trash', None))
        self.assertFalse(UserCapabilityOverride.objects.exists())
        last = UserActivityLog.objects.filter(action='EDIT_PERMISSIONS').order_by('-id').first()
        self.assertEqual((last.metadata['from'], last.metadata['to']), (True, None))
        self.assertEqual(last.metadata['target_id'], self.entry.pk)

    def test_back_to_the_role_with_nothing_set_changes_nothing(self):
        self.assertFalse(svc.set_user_override(self.req(self.admin), self.entry, 'book.trash', None))

    def test_the_exception_compares_against_the_role_as_edited(self):
        svc.set_role_override(self.req(self.admin), 'entry', 'book.restore', True)
        self.assertFalse(svc.set_user_override(self.req(self.admin), self.entry, 'book.restore', True))
        self.assertTrue(svc.set_user_override(self.req(self.admin), self.entry, 'book.restore', False))

    def test_a_failed_trace_cancels_the_change(self):
        with patch('core.permission_service._audit', side_effect=RuntimeError('boom')), self.assertRaises(RuntimeError):
            svc.set_user_override(self.req(self.admin), self.entry, 'book.trash', True)
        self.assertFalse(UserCapabilityOverride.objects.exists())

    def test_who_and_when_are_kept_on_the_row(self):
        svc.set_user_override(self.req(self.head), self.entry, 'book.trash', True)
        row = UserCapabilityOverride.objects.get()
        self.assertEqual(row.changed_by, self.head)
        self.assertIsNotNone(row.changed_at)


class OrphanTests(CapabilityCase):
    def test_a_retired_key_is_found_and_ignored(self):
        RoleCapabilityOverride.objects.create(role='entry', capability='retired.key', allowed=True)
        UserCapabilityOverride.objects.create(user=self.entry, capability='retired.key', allowed=True)
        self.assertEqual(len(svc.orphan_rows()), 2)
        self.assertTrue(s.has_capability(self.fresh(self.entry), 'book.edit'))

    def test_live_keys_are_not_orphans(self):
        RoleCapabilityOverride.objects.create(role='entry', capability='book.restore', allowed=True)
        self.assertEqual(svc.orphan_rows(), [])


class ConversionReportTests(CapabilityCase):
    def report(self):
        out = io.StringIO()
        call_command('role_conversion_report', stdout=out)
        return out.getvalue()

    def test_it_names_each_role_and_writes_nothing(self):
        combo = self.person('c_both', self.unit, ENTRY_GROUP_NAME)
        combo.groups.add(Group.objects.get_or_create(name=ARCHIVIST_GROUP_NAME)[0])
        groups_before = combo.groups.count()
        text = self.report()
        self.assertIn('c_exec\tنشط\tموظّف تنفيذ', text)
        self.assertIn('c_root\tنشط\tمدير النظام', text)
        self.assertIn('يجمع أدواراً', text)
        self.assertIn('مدخل في وحدة لا تمسك سجلّاً', text)
        self.assertEqual(combo.groups.count(), groups_before)
