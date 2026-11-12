# -*- coding: utf-8 -*-
"""(ج‑4) مفاتيحُ الإدارة — المنحُ بمستوى الرئيس، والهيكلُ لرئيس القسم، والشجرةُ تقف عند الوحدة (2026‑11‑12).

قراراتُ المالك (11‑02، المستويان 2 و3): رئيسُ القسم يمنح مختصَّ البريد والأرشفة والمدخل وموظّفَ التنفيذ
والقارئ؛ ومسؤولُ الشعبة أو الوحدة يمنح التنفيذَ والقارئَ وحدهما ويدير موظّفيه لا هيكلَه؛ وإضافةُ الوحدات
للمدير ولرئيس القسم وتقف الشجرةُ عند الوحدة.
"""
from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse

from core import scoping as s
from core.admin_service import assign_user, create_department, create_department_user, update_department
from core.models import Department, UserProfile
from core.roles import EXECUTOR_GROUP_NAME, ensure_role_groups

SHAPER_ONLY = 'هيكلُ الأقسام لرئيس القسم ومدير النظام؛ مسؤولُ الشعبة أو الوحدة يدير موظّفيه.'
TREE_STOPS = 'الوحدةُ آخرُ الشجرة: لا يتبعها قسم.'
BECOMES_UNIT = 'بهذا تصير وحدةٌ ولها أقسامٌ تتبعها'


class AdminKeysCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_role_groups()
        Group.objects.get_or_create(name=EXECUTOR_GROUP_NAME)
        cls.dept = Department.objects.create(name='قسم المفاتيح', code='مف1')
        cls.section = Department.objects.create(name='شعبة المفاتيح', code='مف1ش', parent=cls.dept,
                                                holds_register=False)
        cls.unit = Department.objects.create(name='وحدة المفاتيح', code='مف1و', parent=cls.section,
                                             holds_register=False)
        cls.root = User.objects.create_superuser('c4_root', password='pw-c4-1111')
        cls.head = cls.person('c4_head', cls.dept, head=True)
        cls.unit_head = cls.person('c4_unithead', cls.section, head=True)
        cls.clerk = cls.person('c4_clerk', cls.section)

    @staticmethod
    def person(name, dept, head=False):
        user = User.objects.create_user(name, password='pw-c4-1111')
        UserProfile.objects.update_or_create(user=user, defaults={'department': dept, 'is_department_head': head})
        return user

    def setUp(self):
        cache.clear()

    def fresh(self, user):
        return User.objects.get(pk=user.pk)


class GrantTests(AdminKeysCase):
    def test_each_level_grants_its_own_roles(self):
        self.assertEqual(s.grantable_roles(self.root), s.HEAD_GRANTABLE_ROLES | s.ADMIN_ONLY_ROLES)
        self.assertEqual(s.grantable_roles(self.head),
                         {'viewer', 'executor', 'entry', 'archivist', 'controller'})
        self.assertEqual(s.grantable_roles(self.unit_head), {'viewer', 'executor'})
        self.assertEqual(s.grantable_roles(self.clerk), frozenset())
        self.assertNotIn('executor', s.ADMIN_ONLY_ROLES)

    def test_the_unit_head_creates_an_executor_but_not_an_office_role(self):
        user, _password = create_department_user(by=self.unit_head, department=self.unit,
                                                  username='c4_exec', role='executor')
        self.assertEqual(s.role_of(self.fresh(user)), 'executor')
        with self.assertRaises(PermissionDenied):
            create_department_user(by=self.unit_head, department=self.section, username='c4_entry', role='entry')
        self.assertFalse(User.objects.filter(username='c4_entry').exists())

    def test_the_head_grants_execution_in_a_unit_below(self):
        assign_user(self.clerk, by=self.head, is_executor=True)
        self.assertEqual(s.role_of(self.fresh(self.clerk)), 'executor')

    def test_the_panel_offers_execution_to_both_heads(self):
        for user, columns in ((self.head, {'entry', 'archivist', 'controller', 'executor'}),
                              (self.unit_head, {'executor'})):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                context = self.client.get(reverse('admin_panel') + '?tab=users').context
                self.assertEqual({col['role'] for col in context['role_columns']}, columns)
                row = next(r for r in context['people'] if r['user'] == self.clerk)
                self.assertIn('is_executor', row)


class TreeTests(AdminKeysCase):
    def test_the_unit_head_manages_staff_not_the_tree(self):
        self.assertTrue(s.can_manage_departments(self.unit_head))
        with self.assertRaisesMessage(PermissionDenied, SHAPER_ONLY):
            create_department(by=self.unit_head, name='وحدة ثانية', code='مف1و2', parent=self.section)
        for change in ({'name': 'شعبة باسمٍ آخر'}, {'code': 'مف9'}, {'parent': self.dept}, {'is_active': False}):
            with self.subTest(change=change), self.assertRaisesMessage(PermissionDenied, SHAPER_ONLY):
                update_department(self.section, by=self.unit_head, **change)
        self.assertEqual(Department.objects.get(pk=self.section.pk).name, 'شعبة المفاتيح')

    def test_the_head_shapes_his_tree(self):
        added = create_department(by=self.head, name='وحدة ثانية', code='مف1و2', parent=self.section)
        update_department(added, by=self.head, name='وحدة الأرشيف')
        self.assertEqual(Department.objects.get(pk=added.pk).name, 'وحدة الأرشيف')

    def test_nothing_is_added_under_a_unit(self):
        for by in (self.root, self.head):
            with self.subTest(by=by.username), self.assertRaisesMessage(ValidationError, TREE_STOPS):
                create_department(by=by, name='قسم تحت وحدة', code='مف1وو', parent=self.unit)
        self.assertFalse(self.unit.children.exists())

    def test_no_move_or_rename_hangs_a_tree_under_a_unit(self):
        other = create_department(by=self.root, name='قسم آخر', code='مف2', parent=None)
        with self.assertRaisesMessage(ValidationError, TREE_STOPS):
            update_department(other, by=self.root, parent=self.unit)
        with self.assertRaisesMessage(ValidationError, BECOMES_UNIT):
            update_department(self.section, by=self.root, name='وحدة بديلة')
        bare = create_department(by=self.root, name='المخازن', code='مف3', parent=None)
        create_department(by=self.root, name='شعبة المخازن', code='مف3ش', parent=bare)
        with self.assertRaisesMessage(ValidationError, BECOMES_UNIT):
            update_department(bare, by=self.root, parent=self.section)   # بلا كلمةِ مستوى في العمق 2 = وحدة
        self.assertIsNone(Department.objects.get(pk=bare.pk).parent_id)
        self.assertEqual(Department.unit_level_ids() & {self.dept.pk, self.section.pk, bare.pk}, set())

    def test_a_move_checks_the_whole_subtree(self):
        top = create_department(by=self.root, name='قسم المخازن', code='مف4', parent=None)
        shelves = create_department(by=self.root, name='الرفوف', code='مف4ر', parent=top)       # شعبةٌ بالعمق
        create_department(by=self.root, name='الصناديق', code='مف4ص', parent=shelves)
        with self.assertRaisesMessage(ValidationError, BECOMES_UNIT):
            update_department(top, by=self.root, parent=self.section)   # «الرفوف» تصير وحدةً بالعمق ولها ابن
        self.assertIsNone(Department.objects.get(pk=top.pk).parent_id)

    def test_reactivation_is_checked_too(self):
        update_department(self.unit, by=self.root, is_active=False)
        update_department(self.section, by=self.root, name='وحدة بديلة')   # ابنُها معطَّل فلا يُمنع
        with self.assertRaisesMessage(ValidationError, TREE_STOPS):
            update_department(self.unit, by=self.root, is_active=True)
        self.assertFalse(Department.objects.get(pk=self.unit.pk).is_active)

    def test_the_panel_hides_tree_shaping_from_the_unit_head(self):
        self.client.force_login(self.unit_head)
        body = self.client.get(reverse('admin_panel') + '?tab=departments').content.decode()
        self.assertNotIn('قسم / شعبة / وحدة جديدة', body)
        self.assertIn('const CAN_SHAPE=false;', body)
        self.client.force_login(self.head)
        response = self.client.get(reverse('admin_panel') + '?tab=departments')
        self.assertIn('const CAN_SHAPE=true;', response.content.decode())
        parents = {d.pk for d in response.context['parent_departments']}
        self.assertEqual(parents, {self.dept.pk, self.section.pk})
        body = response.content.decode()   # الوحدةُ تبقى في قائمة التعديل معطَّلةً ليظهر الأبُ الحاليّ
        self.assertIn(f'<option value="{self.unit.pk}" data-locked="1" disabled>', body)
        self.assertIn(f'<option value="{self.section.pk}">', body)
        self.assertIn("o.disabled=no||o.dataset.locked==='1'", body)


class TextTests(AdminKeysCase):
    def test_the_role_names_say_what_the_roles_do(self):
        self.client.force_login(self.root)
        body = self.client.get(reverse('admin_panel') + '?tab=users').content.decode()
        self.assertIn('مختصّ البريد', body)
        for stale in ('مشرف المتابعة', 'مشرف متابعة', 'بريد/متابعة', 'سرّيّات كلّ الأقسام'):
            self.assertNotIn(stale, body)
