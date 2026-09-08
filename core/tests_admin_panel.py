"""
لوحةُ الإدارة — الأقسامُ والأدوارُ والعناقيد.

**أخطرُ شاشةٍ في النظام**: منها يُمنح الدورُ الذي يفتح سجلَّ القراءة والكتبَ
السرّيّة. فالاختباراتُ هنا تسأل عن ثلاثة: مَن يفتحها · وهل كلُّ منحٍ يترك أثراً ·
وهل تُحرَس الشجرةُ من الحلقة التي تُعلّق النظامَ كلَّه.
"""

from django.contrib.auth.models import Group, User
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from core.admin_service import (UNSET, assign_user, create_department, save_group,
                                update_department)
from core.logging_models import UserActivityLog
from core.models import Department, Entity, EntityGroup, UserProfile
from core.roles import CONTROLLER_GROUP_NAME
from core.scoping import can_use_desk, can_view_audit, subtree_ids


class AdminPanelTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.root = User.objects.create_superuser('aroot', 'a@x.com', 'pw-aroot-1111')
        UserProfile.objects.create(user=cls.root)

        cls.dept = Department.objects.create(name='المتابعة', code='أ-ش13')
        cls.clerk = User.objects.create_user('aclerk', password='pw-aclerk-1111')
        UserProfile.objects.create(user=cls.clerk, department=cls.dept)


class GateTests(AdminPanelTestCase):

    def test_a_superuser_opens_it(self):
        self.client.force_login(self.root)
        self.assertEqual(self.client.get('/books/admin/').status_code, 200)

    def test_a_plain_member_may_not(self):
        self.client.force_login(self.clerk)
        self.assertEqual(self.client.get('/books/admin/').status_code, 403)

    def test_a_department_head_may_not_yet(self):
        """رئيسُ القسم يرى سجلَّه وطاولتَه — وإدارةُ الأقسام قرارٌ أوسع."""
        UserProfile.objects.filter(user=self.clerk).update(is_department_head=True)
        self.client.force_login(User.objects.get(pk=self.clerk.pk))
        self.assertEqual(self.client.get('/books/admin/').status_code, 403)

    def test_the_service_refuses_a_non_admin_too(self):
        """الحارسُ في الخدمة لا في العرض وحده — العرضُ يُتجاوز."""
        with self.assertRaises(PermissionDenied):
            create_department(name='قسمٌ مُهرَّب', code='خ1', by=self.clerk)


class TwinEntityTests(AdminPanelTestCase):
    """قاعدةُ التوأمة: عقدةُ القسم وجهتُه إسقاطان لشيءٍ واحد."""

    def test_creating_a_department_creates_its_twin(self):
        d = create_department(name='قسم العقود', code='أ-ش5', by=self.root)
        self.assertIsNotNone(d.entity_id)
        self.assertEqual(d.entity.name, 'قسم العقود')

    def test_an_existing_entity_may_be_linked_instead(self):
        """الحالةُ الغالبة: الدليلُ يحمل الوحدةَ منذ سنوات — فلا تُنشأ ثانيةً."""
        entity = Entity.objects.create(name='قسم الفحص الهندسي')
        d = create_department(name='قسم الفحص الهندسي', code='أ-ش7',
                              entity=entity, by=self.root)
        self.assertEqual(d.entity, entity)
        self.assertEqual(Entity.objects.filter(name='قسم الفحص الهندسي').count(), 1)

    def test_one_entity_cannot_serve_two_departments(self):
        entity = Entity.objects.create(name='جهةٌ واحدة')
        create_department(name='أوّل', code='أ-1', entity=entity, by=self.root)
        with self.assertRaises(ValidationError):
            create_department(name='ثانٍ', code='أ-2', entity=entity, by=self.root)

    def test_a_duplicate_code_is_refused(self):
        with self.assertRaises(ValidationError):
            create_department(name='اسمٌ آخر', code='أ-ش13', by=self.root)

    def test_a_blank_name_is_refused(self):
        with self.assertRaises(ValidationError):
            create_department(name='   ', code='أ-9', by=self.root)


class TreeGuardTests(AdminPanelTestCase):
    """حلقةٌ في الشجرة تُعلّق ``subtree_ids`` — والحارسُ في الخدمة لا في الواجهة."""

    def setUp(self):
        self.unit = create_department(name='شعبة الموازنة', code='أ-ش13/1',
                                      parent=self.dept, by=self.root)
        self.sub = create_department(name='وحدة التقارير', code='أ-ش13/1/1',
                                     parent=self.unit, by=self.root)

    def test_the_tree_flows_down(self):
        self.assertEqual(set(subtree_ids(self.dept.pk)),
                         {self.dept.pk, self.unit.pk, self.sub.pk})
        self.assertEqual(set(subtree_ids(self.sub.pk)), {self.sub.pk})

    def test_a_department_cannot_be_its_own_parent(self):
        with self.assertRaises(ValidationError):
            update_department(self.unit, parent=self.unit, by=self.root)

    def test_a_grandparent_cannot_be_moved_under_its_grandchild(self):
        with self.assertRaises(ValidationError):
            update_department(self.dept, parent=self.sub, by=self.root)

    def test_a_legitimate_move_is_allowed(self):
        update_department(self.sub, parent=self.dept, by=self.root)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.parent, self.dept)

    def test_detaching_to_the_root_is_allowed(self):
        update_department(self.unit, parent=None, by=self.root)
        self.unit.refresh_from_db()
        self.assertIsNone(self.unit.parent_id)

    def test_omitting_parent_leaves_it_untouched(self):
        """``UNSET`` تفترق عن ``None`` — و«لم أُغيّره» ليس «اجعله بلا أب»."""
        update_department(self.unit, name='شعبة الموازنة والتخطيط', by=self.root)
        self.unit.refresh_from_db()
        self.assertEqual(self.unit.parent, self.dept)

    def test_a_department_with_active_children_is_not_disabled(self):
        with self.assertRaises(ValidationError):
            update_department(self.dept, is_active=False, by=self.root)

    def test_a_leaf_may_be_disabled(self):
        update_department(self.sub, is_active=False, by=self.root)
        self.sub.refresh_from_db()
        self.assertFalse(self.sub.is_active)


class RoleAssignmentTests(AdminPanelTestCase):
    """الدورُ يفتح سجلَّ القراءة والكتبَ السرّيّة — فمنحُه بلا أثرٍ يُبطل السجلّ."""

    def test_granting_head_opens_the_audit_log(self):
        assign_user(self.clerk, is_department_head=True, by=self.root)
        self.assertTrue(can_view_audit(User.objects.get(pk=self.clerk.pk)))

    def test_granting_controller_opens_the_desk_only(self):
        assign_user(self.clerk, is_controller=True, by=self.root)
        fresh = User.objects.get(pk=self.clerk.pk)
        self.assertTrue(can_use_desk(fresh))
        self.assertFalse(can_view_audit(fresh), 'مختصُّ البريد لا يراقب الأشخاص')

    def test_revoking_a_role_takes_effect(self):
        assign_user(self.clerk, is_controller=True, by=self.root)
        assign_user(self.clerk, is_controller=False, by=self.root)
        self.assertFalse(User.objects.get(pk=self.clerk.pk)
                         .groups.filter(name=CONTROLLER_GROUP_NAME).exists())

    def test_every_grant_leaves_a_trace(self):
        assign_user(self.clerk, is_department_head=True, by=self.root)
        row = UserActivityLog.objects.get(action='ASSIGN_USER')
        self.assertEqual(row.user, self.root)
        self.assertEqual(row.metadata['user'], 'aclerk')
        self.assertTrue(row.metadata['is_department_head'])

    def test_a_no_op_leaves_no_trace(self):
        """سجلٌّ يمتلئ بلا شيءٍ حدث يفقد قارئَه."""
        assign_user(self.clerk, is_department_head=False, by=self.root)
        self.assertFalse(UserActivityLog.objects.filter(action='ASSIGN_USER').exists())

    def test_a_user_without_a_profile_gets_one(self):
        naked = User.objects.create_user('anaked', password='pw-anaked-111')
        assign_user(naked, department=self.dept, by=self.root)
        self.assertEqual(User.objects.get(pk=naked.pk).profile.department, self.dept)

    def test_creating_a_department_leaves_a_trace(self):
        create_department(name='قسمٌ جديد', code='أ-ج1', by=self.root)
        row = UserActivityLog.objects.get(action='CREATE_DEPARTMENT')
        self.assertEqual(row.metadata['code'], 'أ-ج1')


class GroupAdminTests(AdminPanelTestCase):

    def test_a_static_group_keeps_its_members(self):
        a = Entity.objects.create(name='جهة أ')
        b = Entity.objects.create(name='جهة ب')
        g = save_group(name='عنقودٌ ثابت', member_ids=[a.pk, b.pk], by=self.root)
        self.assertEqual(g.resolved_members().count(), 2)

    def test_a_dynamic_group_ignores_manual_members(self):
        """الاحتفاظُ بعضويّةٍ يدويّةٍ تحت قاعدةٍ محسوبة يُوهم قارئَ الشاشة."""
        a = Entity.objects.create(name='جهة ج')
        create_department(name='قسمٌ نشط', code='أ-ن1', by=self.root)
        g = save_group(name='كلُّ الأقسام', member_ids=[a.pk],
                       auto_rule=EntityGroup.ALL_REGISTRY_DEPARTMENTS, by=self.root)
        self.assertEqual(g.members.count(), 0)
        self.assertGreater(g.resolved_members().count(), 0)
        self.assertNotIn(a, list(g.resolved_members()))

    def test_an_unknown_rule_is_refused(self):
        with self.assertRaises(ValidationError):
            save_group(name='عنقود', auto_rule='قاعدةٌ مخترَعة', by=self.root)

    def test_a_duplicate_name_is_refused(self):
        save_group(name='عنقودٌ فريد', by=self.root)
        with self.assertRaises(ValidationError):
            save_group(name='عنقودٌ فريد', by=self.root)

    def test_editing_keeps_the_same_row(self):
        g = save_group(name='قبل', by=self.root)
        again = save_group(name='بعد', group=g, by=self.root)
        self.assertEqual(again.pk, g.pk)
        self.assertEqual(EntityGroup.objects.count(), 1)


class PanelWritesTests(AdminPanelTestCase):
    """المسارُ الكامل عبر الشاشة — لا عبر الخدمة وحدها."""

    def setUp(self):
        self.client.force_login(self.root)

    def test_creating_a_department_through_the_form(self):
        resp = self.client.post('/books/admin/', {
            'action': 'create_department', 'tab': 'departments',
            'name': 'قسم تقنية المعلومات', 'code': 'أ-ش12',
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(Department.objects.filter(code='أ-ش12').exists())

    def test_a_bad_input_shows_an_error_and_writes_nothing(self):
        before = Department.objects.count()
        resp = self.client.post('/books/admin/', {
            'action': 'create_department', 'tab': 'departments',
            'name': '', 'code': 'أ-ش99',
        }, follow=True)
        self.assertContains(resp, 'مطلوب')
        self.assertEqual(Department.objects.count(), before)

    def test_an_unknown_action_is_refused_quietly(self):
        resp = self.client.post('/books/admin/', {'action': 'drop_everything'}, follow=True)
        self.assertContains(resp, 'غير معروف')

    def test_assigning_a_role_through_the_form(self):
        self.client.post('/books/admin/', {
            'action': 'assign_user', 'tab': 'users',
            'user_id': self.clerk.pk, 'department': self.dept.pk,
            'is_department_head': '1',
        }, follow=True)
        self.assertTrue(User.objects.get(pk=self.clerk.pk).profile.is_department_head)

    def test_an_unchecked_box_revokes_the_role(self):
        """صندوقٌ غيرُ مؤشَّرٍ لا يُرسَل أصلاً — والسحبُ يجب أن يعمل رغم ذلك."""
        assign_user(self.clerk, is_department_head=True, by=self.root)
        self.client.post('/books/admin/', {
            'action': 'assign_user', 'tab': 'users',
            'user_id': self.clerk.pk, 'department': self.dept.pk,
        }, follow=True)
        self.assertFalse(User.objects.get(pk=self.clerk.pk).profile.is_department_head)


class TreeRenderingTests(AdminPanelTestCase):
    """القائمةُ المسطّحة تُخفي البنيةَ التي بُنيت لأجلها."""

    def test_children_are_indented_under_their_parent(self):
        from core.views.admin_panel import _department_rows

        unit = create_department(name='شعبةٌ تابعة', code='أ-ت1',
                                 parent=self.dept, by=self.root)
        rows = {r['department'].pk: r['depth'] for r in _department_rows()}
        self.assertEqual(rows[self.dept.pk], 0)
        self.assertEqual(rows[unit.pk], 1)

    def test_every_department_appears_exactly_once(self):
        from core.views.admin_panel import _department_rows

        create_department(name='شعبةٌ أولى', code='أ-و1', parent=self.dept, by=self.root)
        create_department(name='قسمٌ مستقلّ', code='أ-م1', by=self.root)
        rows = _department_rows()
        self.assertEqual(len(rows), Department.objects.count())
        self.assertEqual(len({r['department'].pk for r in rows}), len(rows))
