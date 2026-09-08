# -*- coding: utf-8 -*-
"""حرّاسُ دور «مسؤول الأرشفة» — التسميةُ والبوّابةُ والسرّيُّ ومسارُ المنح.

**الدرسُ الذي يحرسه هذا الملفّ**: التسميةُ الواحدة (`get_user_role`) لا تحتمل
رجلاً يجمع البريدَ والأرشفة، والشهادةُ الميدانيّة تقول إنّه يجمعهما. فالبوّابةُ
عضويّةُ مجموعةٍ لا تسمية — وحارسُ العضويّة أدناه يسقط لحظةَ يُبنى أحدُهما على
الآخر، مهما بدا ذلك أنظف.
"""

from django.contrib.auth.models import Group, User
from django.test import TestCase

from core.admin_service import assign_user
from core.logging_models import UserActivityLog
from core.models import Book, Department, UserProfile
from core.roles import (ARCHIVIST_GROUP_NAME, CONTROLLER_GROUP_NAME,
                        ROLE_DEFINITIONS, get_user_role, role_capabilities)
from core.scoping import (ACCESS_FULL, ACCESS_STUB, can_archive,
                          can_open_content, can_use_desk, can_view_audit,
                          guard_secret_text_search, is_archivist,
                          is_mail_officer, secret_access)


def _member(name, department, *, head=False, controller=False,
            archivist=False, admin=False):
    if admin:
        user = User.objects.create_superuser(name, name + '@x.co', 'pw')
    else:
        user = User.objects.create_user(name, name + '@x.co', 'pw')
    UserProfile.objects.update_or_create(
        user=user, defaults={'department': department, 'is_department_head': head})
    for wanted, group_name in ((controller, CONTROLLER_GROUP_NAME),
                               (archivist, ARCHIVIST_GROUP_NAME)):
        if wanted:
            user.groups.add(Group.objects.get_or_create(name=group_name)[0])
    return user


class ArchivistRoleTests(TestCase):
    """الفاعلون التسعة — ومن بينهم الجامعُ للدورين والغريبُ عن القسم."""

    @classmethod
    def setUpTestData(cls):
        cls.dept = Department.objects.create(name='قسم الأرشفة', code='ر.ق')
        cls.other = Department.objects.create(name='قسمٌ آخر', code='ر.خ')

        cls.plain = _member('plain', cls.dept)
        cls.entry = _member('entryman', cls.dept)
        cls.officer = _member('officer', cls.dept, controller=True)
        cls.head = _member('head', cls.dept, head=True)
        cls.archivist = _member('archivist', cls.dept, archivist=True)
        cls.both = _member('both', cls.dept, controller=True, archivist=True)
        cls.head_archivist = _member('headarch', cls.dept, head=True, archivist=True)
        cls.stranger = _member('stranger', cls.other, archivist=True)
        cls.root = _member('root', cls.dept, admin=True)

        cls.secret = Book.objects.create(
            kind='incoming_external', title='مناقصةٌ سرّيّة', our_number='9700',
            secret_level='secret', department=cls.dept, created_by=cls.head)

    # ── التسمية ────────────────────────────────────────────────────────
    def test_the_archivist_has_a_role_label_of_its_own(self):
        self.assertEqual(get_user_role(self.archivist), 'archivist')
        self.assertIn('archivist', ROLE_DEFINITIONS)
        self.assertEqual(ROLE_DEFINITIONS['archivist']['label'], ARCHIVIST_GROUP_NAME)

    def test_the_archivist_capabilities_match_the_entry_clerk(self):
        caps = role_capabilities('archivist')

        self.assertTrue(caps['can_manage_books'])
        self.assertFalse(caps['can_manage_users'])

    # ── العضويّةُ لا التسمية — الحارسُ الأهمّ ───────────────────────────
    def test_one_person_may_hold_both_the_mail_desk_and_the_archive(self):
        """صيغةُ الشهادة «مسؤول إدارة البريد والأرشفة» — رجلٌ واحدٌ ببابين.

        لو بُنيت `is_archivist` على التسمية الواحدة لسقط أحدُ البابين هنا.
        """
        self.assertEqual(get_user_role(self.both), 'controller')
        self.assertTrue(is_archivist(self.both))
        self.assertTrue(is_mail_officer(self.both))

    def test_a_department_head_may_also_keep_the_archive(self):
        self.assertEqual(get_user_role(self.head_archivist), 'dept_head')
        self.assertTrue(is_archivist(self.head_archivist))

    def test_membership_alone_answers_the_gate(self):
        self.assertTrue(is_archivist(self.archivist))
        for outsider in (self.plain, self.entry, self.officer, self.head):
            self.assertFalse(is_archivist(outsider), outsider.username)

    # ── مصفوفةُ «تمامُ الأرشفة» ─────────────────────────────────────────
    def test_only_the_archivist_and_the_root_may_close_the_file(self):
        for allowed in (self.archivist, self.both, self.root, self.head_archivist):
            self.assertTrue(can_archive(allowed), allowed.username)
        for refused in (self.plain, self.entry, self.officer, self.head):
            self.assertFalse(can_archive(refused), refused.username)

    # ── لا يتّسع الدورُ إلى ما ليس له ───────────────────────────────────
    def test_the_archive_role_does_not_open_the_mail_desk_or_the_audit(self):
        """يحفظ الورقَ ولا يُفرّقه ولا يراقب مَن قرأ — وإلّا فهو دورٌ رابع."""
        self.assertFalse(can_use_desk(self.archivist))
        self.assertFalse(can_view_audit(self.archivist))

    def test_the_desk_page_refuses_the_archivist(self):
        self.client.force_login(self.archivist)

        self.assertEqual(self.client.get('/books/desk/').status_code, 403)

    # ── السرّيّ — أمينُ الورق يفتح ورقَ قسمه وحده ───────────────────────
    def test_the_archivist_opens_the_secret_of_his_own_department(self):
        self.assertEqual(secret_access(self.archivist, self.secret), ACCESS_FULL)
        self.assertTrue(can_open_content(self.secret, self.archivist))

    def test_an_archivist_of_another_department_gets_the_stub(self):
        self.assertEqual(secret_access(self.stranger, self.secret), ACCESS_STUB)
        self.assertFalse(can_open_content(self.secret, self.stranger))

    # ── حارسُ التطابق البنيويّ — توأمُ `tests_scope_parity` ─────────────
    def test_the_text_search_guard_never_diverges_from_secret_access(self):
        """فتحُ المحتوى وحارسُ البحث قاعدةٌ واحدةٌ في موضعين.

        لو مُنح دورٌ في أحدهما دون الآخر لصار البحثُ إمّا أداةَ استنطاقٍ
        (يُعيد ما لا يُفتح) وإمّا حاجباً عن صاحب الحقّ. هذا الحارسُ يقارنهما
        فاعلاً فاعلاً — وأيُّ دورٍ يُضاف لأحدهما وحدَه يُسقطه.
        """
        for user in (self.plain, self.entry, self.officer, self.head,
                     self.archivist, self.both, self.head_archivist,
                     self.stranger, self.root):
            opens = secret_access(user, self.secret) == ACCESS_FULL
            found = guard_secret_text_search(
                Book.objects.filter(pk=self.secret.pk), user, 'مناقصة').exists()

            self.assertEqual(opens, found, 'انفرجا على %s' % user.username)


class ArchivistGrantTests(TestCase):
    """مسارُ المنح — مجموعةٌ خاملةٌ لا يدخلها أحدٌ دورٌ لا وجودَ له."""

    def setUp(self):
        self.dept = Department.objects.create(name='قسم المنح', code='ن.ق')
        self.root = _member('root', self.dept, admin=True)
        self.worker = _member('worker', self.dept)

    def test_granting_the_role_adds_the_group_and_leaves_a_trace(self):
        assign_user(self.worker, by=self.root, is_archivist=True)

        self.assertTrue(is_archivist(self.worker))
        log = UserActivityLog.objects.filter(action='ASSIGN_USER').latest('id')
        self.assertTrue(log.metadata.get('is_archivist'))

    def test_revoking_the_role_removes_the_group(self):
        assign_user(self.worker, by=self.root, is_archivist=True)
        assign_user(self.worker, by=self.root, is_archivist=False)

        self.assertFalse(is_archivist(User.objects.get(pk=self.worker.pk)))

    def test_the_two_roles_are_granted_independently(self):
        """كتلتان لا سلسلةٌ واحدة — ومنحُ أحدهما لا يمسّ الآخر."""
        assign_user(self.worker, by=self.root, is_controller=True, is_archivist=True)
        assign_user(self.worker, by=self.root, is_controller=False, is_archivist=True)

        fresh = User.objects.get(pk=self.worker.pk)
        self.assertTrue(is_archivist(fresh))
        self.assertFalse(is_mail_officer(fresh))

    def test_the_admin_panel_offers_the_checkbox(self):
        self.client.force_login(self.root)

        res = self.client.get('/books/admin/?tab=users')

        self.assertContains(res, 'name="is_archivist"')
