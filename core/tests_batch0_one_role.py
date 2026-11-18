"""حرّاسُ الدفعة 0: دورٌ واحدٌ لكلّ شخص (قرارُ المالك 2026‑11‑16)، ومراجعةُ فيبل للخطّة.

١. **الحرّاسُ تقرأ الصلاحيّة لا العضويّة**، فيحمل الاستثناءُ ما يحمله الدور: قراءةُ بريد القسم بمفتاح
   «تشغيل البريد» وسرّيُّه بمفتاح «فتح سرّيّ قسمه» (لا يفتح حاملُ الاستثناء بريدَ سرّيٍّ لا يملكه)؛
   وطاولةُ الإحالات بمفتاح «الدفتر وكشف التسليم».
٢. **حاملُ الاستثناء الموجب حسّاس**، ورئيسُ القسم يمنح بدوره لا باستثناءاته.
٣. **الثابتُ في الخدمة**: لا يُسند دوران لشخصٍ واحد.
٤. **التحويل**: جافٌّ افتراضيّاً، والمنفَّذُ يُزيل الزائد ويكتب استثناءاتٍ باسمه ويُتراجع عنه من ملفّه؛
   وما يمنعه القسمُ لا يعود من باب الاستثناء، ودورٌ باقٍ لا يُسند في القسم يُترك للمالك.
"""
import csv
import os
import tempfile
from io import StringIO
from types import SimpleNamespace

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from core.admin_service import assign_user
from core.logging_models import UserActivityLog
from core.messaging.scoping import scope_mail_books
from core.models import Book, Department, UserCapabilityOverride, UserProfile
from core.permission_service import one_role_plan
from core.referral_service import _desk_of
from core.roles import (ARCHIVIST_GROUP_NAME, CONTROLLER_GROUP_NAME, ENTRY_GROUP_NAME, EXECUTOR_GROUP_NAME,
                        ensure_role_groups)
from core.scoping import (can_edit_exception, clear_capability_cache, extra_role_memberships,
                          is_sensitive_account, role_of)


class OneRoleBase(TestCase):

    @classmethod
    def setUpTestData(cls):
        ensure_role_groups()
        Group.objects.get_or_create(name=EXECUTOR_GROUP_NAME)
        cls.dept = Department.objects.create(name='قسم الدفعة', code='دف1')
        cls.unit = Department.objects.create(name='وحدة الدفعة', code='دف1و', parent=cls.dept, holds_register=False)
        cls.root = User.objects.create_superuser('b0_root', password='pw-b0-1111')

    def person(self, name, dept, *groups, head=False):
        user = User.objects.create_user(name, password='pw-b0-1111')
        UserProfile.objects.update_or_create(user=user, defaults={'department': dept, 'is_department_head': head})
        for group in groups:   # حالةُ اليوم القديمة تُبنى مباشرةً — الخدمةُ صارت ترفضها
            user.groups.add(Group.objects.get_or_create(name=group)[0])
        return User.objects.get(pk=user.pk)

    def grant(self, user, key):
        UserCapabilityOverride.objects.create(user=user, capability=key, allowed=True, changed_by=self.root)
        clear_capability_cache(user)
        return User.objects.get(pk=user.pk)


class GuardsReadCapabilitiesTests(OneRoleBase):

    def setUp(self):
        self.author = self.person('b0_author', self.dept, ENTRY_GROUP_NAME)
        self.normal = Book.objects.create(kind='incoming_internal', title='عاديّ', our_number='9101',
                                          department=self.dept, created_by=self.author)
        self.secret = Book.objects.create(kind='incoming_internal', title='سرّيّ', our_number='9102',
                                          department=self.dept, created_by=self.author, secret_level='secret')

    def _mail(self, user):
        return set(scope_mail_books(Book.objects.filter(pk__in=[self.normal.pk, self.secret.pk]), user))

    def test_the_mail_officer_still_reads_the_department_mail_and_its_secret(self):
        officer = self.person('b0_officer', self.dept, CONTROLLER_GROUP_NAME)
        self.assertEqual(self._mail(officer), {self.normal, self.secret})

    def test_an_operate_exception_reads_mail_but_not_secret_it_does_not_own(self):
        clerk = self.grant(self.person('b0_clerk', self.dept, ENTRY_GROUP_NAME), 'mail.operate')
        self.assertEqual(self._mail(clerk), {self.normal})

    def test_without_the_key_only_ones_own(self):
        reader = self.person('b0_reader', self.dept)
        self.assertEqual(self._mail(reader), set())

    def test_the_referral_desk_reads_the_ledger_key(self):
        referral = SimpleNamespace(book=SimpleNamespace(department_id=self.dept.pk))
        self.assertTrue(_desk_of(referral, self.person('b0_mail', self.dept, CONTROLLER_GROUP_NAME)))
        self.assertFalse(_desk_of(referral, self.person('b0_entry', self.dept, ENTRY_GROUP_NAME)))
        self.assertTrue(_desk_of(referral, self.grant(self.person('b0_entry2', self.dept, ENTRY_GROUP_NAME),
                                                      'desk.ledger')))


class SensitivityAndGrantingTests(OneRoleBase):

    def test_a_positive_exception_makes_an_account_sensitive(self):
        clerk = self.person('b0_s1', self.dept, ENTRY_GROUP_NAME)
        self.assertFalse(is_sensitive_account(clerk))
        clerk = self.grant(clerk, 'mail.operate')
        self.assertTrue(is_sensitive_account(clerk))
        self.assertTrue(is_sensitive_account(clerk, {ENTRY_GROUP_NAME}, {clerk.pk}))
        self.assertFalse(is_sensitive_account(clerk, {ENTRY_GROUP_NAME}, set()))

    def test_a_head_grants_by_his_role_not_by_his_exceptions(self):
        head = self.grant(self.person('b0_head', self.dept, head=True), 'mail.operate')
        staff = self.person('b0_staff', self.dept, ENTRY_GROUP_NAME)
        self.assertTrue(can_edit_exception(head, staff, 'book.enter'))
        self.assertFalse(can_edit_exception(head, staff, 'mail.operate'))

    def test_a_head_blocked_from_a_key_cannot_grant_it(self):
        """فيبل 11-16: بالدور **وبما لم يُحجب عنه** — كان المحجوبُ عنه باستثناءٍ سالب يمنحه."""
        head = self.person('b0_head2', self.dept, head=True)
        UserCapabilityOverride.objects.create(user=head, capability='book.enter', allowed=False, changed_by=self.root)
        clear_capability_cache(head)
        staff = self.person('b0_staff2', self.dept, ENTRY_GROUP_NAME)
        self.assertFalse(can_edit_exception(User.objects.get(pk=head.pk), staff, 'book.enter'))

    def test_the_mail_and_ledger_keys_are_frozen_for_reader_and_executor(self):
        from core.models import RoleCapabilityOverride
        from core.scoping import role_capability
        for role in ('reader', 'executor'):
            for key in ('mail.operate', 'desk.ledger'):
                RoleCapabilityOverride.objects.create(role=role, capability=key, allowed=True)
                with self.subTest(role=role, key=key):
                    self.assertFalse(role_capability(role, key))


class DormantExceptionTests(OneRoleBase):
    """الاستثناءُ الخامد (مفتاحٌ لم يُربط): لا يُعدّ «يستطيع»، ويُحذف من المحرّر (فيبل 11-16)."""

    def test_the_editor_names_it_dormant_and_removes_it(self):
        from django.urls import reverse
        person = self.person('b0_dormant', self.dept, CONTROLLER_GROUP_NAME)
        UserCapabilityOverride.objects.create(user=person, capability='archive.complete', allowed=True,
                                              changed_by=self.root)
        self.client.force_login(self.root)
        html = self.client.get(reverse('system_account', args=[person.pk])).content.decode('utf-8')
        self.assertIn('استثناءٌ خامد — لم يُربط بعد', html)
        self.client.post(reverse('system_account', args=[person.pk]),
                         {'action': 'override', 'key': 'archive.complete', 'value': 'reset'})
        self.assertFalse(UserCapabilityOverride.objects.filter(user=person, capability='archive.complete').exists())

    def test_an_unwired_key_still_cannot_be_granted_from_the_editor(self):
        from django.urls import reverse
        person = self.person('b0_unwired', self.dept, CONTROLLER_GROUP_NAME)
        self.client.force_login(self.root)
        self.client.post(reverse('system_account', args=[person.pk]),
                         {'action': 'override', 'key': 'archive.complete', 'value': 'allow'})
        self.assertFalse(UserCapabilityOverride.objects.filter(user=person).exists())


class ServiceInvariantTests(OneRoleBase):

    def test_two_roles_in_one_save_are_refused(self):
        worker = self.person('b0_w1', self.dept)
        with self.assertRaisesMessage(ValidationError, 'للشخص دورٌ واحد'):
            assign_user(worker, by=self.root, is_controller=True, is_archivist=True)
        self.assertEqual(extra_role_memberships(User.objects.get(pk=worker.pk)), [])

    def test_a_system_admin_row_with_old_boxes_still_saves(self):
        """لقطةُ المالك 11-16: صفُّ admin في الإنتاج بأربع خانات — مديرُ النظام بلا أثرٍ لعضويّاته."""
        other = User.objects.create_superuser('b0_root2', password='pw-b0-1111')
        UserProfile.objects.update_or_create(user=other, defaults={'department': self.dept, 'is_department_head': True})
        for group in (CONTROLLER_GROUP_NAME, ARCHIVIST_GROUP_NAME, ENTRY_GROUP_NAME):
            other.groups.add(Group.objects.get_or_create(name=group)[0])
        assign_user(other, by=self.root, is_entry=False)   # تغييرُ خانةٍ في صفّه لا يُرفض
        self.assertFalse(other.groups.filter(name=ENTRY_GROUP_NAME).exists())

    def test_moving_from_one_role_to_another_is_one_save(self):
        worker = self.person('b0_w2', self.dept, CONTROLLER_GROUP_NAME)
        assign_user(worker, by=self.root, is_controller=False, is_archivist=True)
        fresh = User.objects.get(pk=worker.pk)
        self.assertEqual(role_of(fresh), 'archivist')
        self.assertEqual(extra_role_memberships(fresh), [])


class ConversionPlanTests(OneRoleBase):

    def test_head_and_mail_keeps_head_and_gains_the_mail_keys_by_name(self):
        plan = one_role_plan(self.person('b0_hm', self.dept, CONTROLLER_GROUP_NAME, head=True))
        self.assertEqual(plan['kept'], 'head')
        self.assertEqual(plan['remove'], [CONTROLLER_GROUP_NAME])
        self.assertEqual(set(plan['grant']), {'mail.operate', 'mail.send_book'})

    def test_an_unwired_key_becomes_a_dormant_exception(self):
        plan = one_role_plan(self.person('b0_ma', self.dept, CONTROLLER_GROUP_NAME, ARCHIVIST_GROUP_NAME))
        self.assertEqual(plan['kept'], 'mail')
        self.assertIn('archive.complete', plan['dormant'])
        self.assertNotIn('archive.complete', plan['grant'])

    def test_what_the_department_forbids_is_dropped_not_granted(self):
        plan = one_role_plan(self.person('b0_ue', self.unit, ENTRY_GROUP_NAME, head=True))
        self.assertEqual(plan['kept'], 'unit')
        self.assertEqual(plan['grant'], [])
        self.assertIn('book.enter', plan['dropped'])

    def test_a_kept_role_the_department_cannot_hold_waits_for_the_owner(self):
        plan = one_role_plan(self.person('b0_ea', self.unit, EXECUTOR_GROUP_NAME, ARCHIVIST_GROUP_NAME))
        self.assertFalse(plan['kept_assignable'])

    def test_one_role_has_no_plan(self):
        self.assertIsNone(one_role_plan(self.person('b0_one', self.dept, CONTROLLER_GROUP_NAME)))


class ConversionCommandTests(OneRoleBase):

    def setUp(self):
        self.hm = self.person('b0_cmd_hm', self.dept, CONTROLLER_GROUP_NAME, head=True)
        self.ea = self.person('b0_cmd_ea', self.unit, EXECUTOR_GROUP_NAME, ARCHIVIST_GROUP_NAME)
        self.db = settings.DATABASES['default']['NAME']
        self.tmp = tempfile.mkdtemp()

    def _run(self, *args):
        out = StringIO()
        call_command('convert_multi_role_accounts', *args, stdout=out)
        return out.getvalue()

    def test_the_default_run_writes_nothing(self):
        text = self._run()
        self.assertIn('لم يُكتب شيء', text)
        self.assertIn(CONTROLLER_GROUP_NAME, extra_role_memberships(User.objects.get(pk=self.hm.pk)))
        self.assertFalse(UserCapabilityOverride.objects.exists())

    def test_apply_refuses_an_existing_undo_file_before_writing_anything(self):
        """ذرّيّ (فيبل 11-16): ملفُّ التراجع يُفتح أوّلاً — فلا تحويلَ بلا ملفّ."""
        path = os.path.join(self.tmp, 'taken.csv')
        open(path, 'w').close()
        with self.assertRaises(FileExistsError):
            self._run('--apply', '--expect-db', self.db, '--out', path)
        self.assertIn(CONTROLLER_GROUP_NAME, extra_role_memberships(User.objects.get(pk=self.hm.pk)))
        self.assertFalse(UserCapabilityOverride.objects.exists())

    def test_a_failure_midway_converts_nobody_and_leaves_no_file(self):
        from unittest.mock import patch
        path = os.path.join(self.tmp, 'mid.csv')
        with patch('core.management.commands.convert_multi_role_accounts.apply_one_role_plan',
                   side_effect=RuntimeError('سقوطٌ في المنتصف')):
            with self.assertRaises(RuntimeError):
                self._run('--apply', '--expect-db', self.db, '--out', path)
        self.assertFalse(os.path.exists(path))
        self.assertIn(CONTROLLER_GROUP_NAME, extra_role_memberships(User.objects.get(pk=self.hm.pk)))

    def test_a_failure_on_the_second_account_undoes_the_first(self):
        """معاملةٌ واحدة: حسابٌ حُوِّل ثمّ سقط ما بعده ⟵ لا يبقى الأوّلُ محوَّلاً بلا ملفّ."""
        from unittest.mock import patch
        from core.permission_service import apply_one_role_plan as real
        second = self.person('b0_cmd_hm2', self.dept, CONTROLLER_GROUP_NAME, head=True)
        calls = []

        def first_then_fail(user, plan, *, by):
            calls.append(user.get_username())
            if len(calls) == 2:
                raise RuntimeError('سقوطٌ عند الحساب الثاني')
            return real(user, plan, by=by)

        path = os.path.join(self.tmp, 'second.csv')
        with patch('core.management.commands.convert_multi_role_accounts.apply_one_role_plan',
                   side_effect=first_then_fail):
            with self.assertRaises(RuntimeError):
                self._run('--apply', '--expect-db', self.db, '--out', path)
        self.assertEqual(len(calls), 2)
        for user in (self.hm, second):
            with self.subTest(user=user.get_username()):
                self.assertIn(CONTROLLER_GROUP_NAME, extra_role_memberships(User.objects.get(pk=user.pk)))
        self.assertFalse(UserCapabilityOverride.objects.exists())
        self.assertFalse(os.path.exists(path))

    def test_apply_needs_the_named_database(self):
        path = os.path.join(self.tmp, 'wrong-db.csv')   # لا يترك ملفّاً في جذر المشروع ولو كُسر الحارس
        with self.assertRaises(CommandError):
            self._run('--apply', '--expect-db', 'not-this-one', '--out', path)
        self.assertFalse(UserCapabilityOverride.objects.exists())

    def test_apply_converts_logs_and_undo_restores(self):
        path = os.path.join(self.tmp, 'conv.csv')
        self._run('--apply', '--expect-db', self.db, '--out', path)
        fresh = User.objects.get(pk=self.hm.pk)
        self.assertEqual(extra_role_memberships(fresh), [])
        self.assertEqual(set(UserCapabilityOverride.objects.filter(user=fresh).values_list('capability', flat=True)),
                         {'mail.operate', 'mail.send_book'})
        self.assertTrue(UserActivityLog.objects.filter(metadata__scope='role_conversion').exists())
        # الدورُ الباقي لا يُسند في الوحدة ⟵ يُترك كما هو لقرار المالك
        self.assertTrue(extra_role_memberships(User.objects.get(pk=self.ea.pk)))
        with open(path, encoding='utf-8-sig') as fh:
            self.assertEqual([r['username'] for r in csv.DictReader(fh)], ['b0_cmd_hm'])

        self._run('--undo', path, '--expect-db', self.db)
        back = User.objects.get(pk=self.hm.pk)
        self.assertEqual(extra_role_memberships(back), [CONTROLLER_GROUP_NAME])
        self.assertFalse(UserCapabilityOverride.objects.filter(user=back).exists())
