"""
لوحةُ الإدارة — الأقسامُ والأدوارُ والعناقيد.

**أخطرُ شاشةٍ في النظام**: منها يُمنح الدورُ الذي يفتح سجلَّ القراءة والكتبَ
السرّيّة. فالاختباراتُ هنا تسأل عن ثلاثة: مَن يفتحها · وهل كلُّ منحٍ يترك أثراً ·
وهل تُحرَس الشجرةُ من الحلقة التي تُعلّق النظامَ كلَّه.
"""

from django.contrib.auth.models import Group, User
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from asgiref.sync import async_to_sync

from core.admin_service import (UNSET, assign_user, create_department,
                                create_department_user, save_group, update_department)
from core.logging_models import UserActivityLog
from core.models import Department, Entity, EntityGroup, UserProfile
from core.roles import (ARCHIVE_ALL_GROUP_NAME, ARCHIVIST_GROUP_NAME, CONTROLLER_GROUP_NAME,
                        ENTRY_GROUP_NAME)
from core.scoping import (can_manage_department, can_manage_departments, can_use_desk,
                          can_view_audit, subtree_ids)


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

    def test_a_department_head_opens_the_scoped_admin_panel(self):
        UserProfile.objects.filter(user=self.clerk).update(is_department_head=True)
        self.client.force_login(User.objects.get(pk=self.clerk.pk))
        self.assertEqual(self.client.get('/books/admin/').status_code, 200)

    def test_department_admin_gate_is_separate_from_global_account_admin(self):
        UserProfile.objects.filter(user=self.clerk).update(is_department_head=True)
        fresh = User.objects.get(pk=self.clerk.pk)
        self.assertTrue(can_manage_departments(fresh))
        self.assertFalse(can_manage_department(fresh, Department.objects.create(
            name='قسم خارج النطاق', code='خ-1')))

    def test_the_tree_data_reaches_the_script_as_an_array(self):
        """``json.dumps`` قبل ``json_script`` رمّزها مرّتين فوصل نصٌّ — والشجرةُ لا تُرسم."""
        import json
        import re
        self.client.force_login(self.root)
        html = self.client.get('/books/admin/', {'tab': 'departments'}).content.decode('utf-8')
        payload = re.search(r'<script id="depsData" type="application/json">(.*?)</script>', html, re.S)
        data = json.loads(payload.group(1))
        self.assertIsInstance(data, list)
        self.assertIn(self.dept.code, [d['c'] for d in data])

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
        self.assertEqual(d.entity.kind, Entity.KIND_INTERNAL)

    def test_child_departments_create_unit_entities(self):
        child = create_department(
            name='وحدة العقود', code='أ-ش5/1', parent=self.dept, by=self.root)
        self.assertEqual(child.entity.kind, Entity.KIND_UNIT)

    def test_an_existing_entity_may_be_linked_instead(self):
        """الحالةُ الغالبة: الدليلُ يحمل الوحدةَ منذ سنوات — فلا تُنشأ ثانيةً."""
        entity = Entity.objects.create(name='قسم الفحص الهندسي')
        d = create_department(name='قسم الفحص الهندسي', code='أ-ش7',
                              entity=entity, by=self.root)
        self.assertEqual(d.entity, entity)
        self.assertEqual(Entity.objects.filter(name='قسم الفحص الهندسي').count(), 1)

    def test_a_head_inherits_an_existing_unit_twin_by_name(self):
        """الوحدةُ التي ينشئها رئيسُ القسم ترث جهتَها القائمة — فتفتح أضبارتُها بماضيها."""
        entity = Entity.objects.create(name='وحدة الأرشفة', kind=Entity.KIND_UNIT)
        UserProfile.objects.filter(user=self.clerk).update(is_department_head=True)
        head = User.objects.get(pk=self.clerk.pk)
        d = create_department(name='وحدة الأرشفة', code='أ-ش13/9', parent=self.dept, by=head)
        self.assertEqual(d.entity, entity)

    def test_a_head_may_not_twin_an_external_entity_by_name(self):
        """وإلّا أعاد تعديلُ اسم الوحدة تسميةَ «الوزارة» على كلّ كتابٍ قديم."""
        Entity.objects.create(name='وزارة النفط', kind=Entity.KIND_EXTERNAL)
        UserProfile.objects.filter(user=self.clerk).update(is_department_head=True)
        head = User.objects.get(pk=self.clerk.pk)
        with self.assertRaises(ValidationError):
            create_department(name='وزارة النفط', code='أ-ش13/8', parent=self.dept, by=head)
        self.assertFalse(Department.objects.filter(code='أ-ش13/8').exists())

    def test_department_rename_keeps_its_entity_twin_in_sync(self):
        department = create_department(name='قبل التعديل', code='أ-ش9', by=self.root)
        update_department(department, by=self.root, name='بعد التعديل')
        department.refresh_from_db()
        self.assertEqual(department.entity.name, department.name)

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


class DepartmentManagerScopeTests(AdminPanelTestCase):

    def setUp(self):
        self.unit = create_department(name='شعبة القسم', code='أ-ش13/1',
                                      parent=self.dept, by=self.root)
        self.other = create_department(name='قسم آخر', code='أ-ش8', by=self.root)
        UserProfile.objects.filter(user=self.clerk).update(is_department_head=True)
        self.manager = User.objects.get(pk=self.clerk.pk)

    def test_department_manager_sees_only_their_subtree_and_staff(self):
        outside = User.objects.create_user('outside', password='outside-pass-123456')
        UserProfile.objects.create(user=outside, department=self.other)
        self.client.force_login(self.manager)
        response = self.client.get('/books/admin/?tab=users')
        body = response.content.decode('utf-8')
        self.assertContains(response, self.unit.name)
        self.assertNotContains(response, self.other.name)
        self.assertNotContains(response, 'outside')
        self.assertNotContains(response, '?tab=groups')
        self.assertContains(response, '/books/admin/')
        self.assertNotContains(response, '/books/users/')

    def test_manager_may_create_children_but_not_root_departments(self):
        child = create_department(name='وحدة داخلية', code='أ-ش13/1/1',
                                  parent=self.dept, by=self.manager)
        self.assertEqual(child.parent, self.dept)
        with self.assertRaises(PermissionDenied):
            create_department(name='قسم مستقل', code='أ-م9', by=self.manager)
        with self.assertRaises(PermissionDenied):
            create_department(name='تحت قسم أجنبي', code='أ-م10',
                              parent=self.other, by=self.manager)

    def test_manager_cannot_move_or_edit_a_department_outside_scope(self):
        with self.assertRaises(PermissionDenied):
            update_department(self.other, name='اسم مستولى عليه', by=self.manager)
        with self.assertRaises(PermissionDenied):
            update_department(self.unit, parent=self.other, by=self.manager)

    def test_manager_may_assign_operational_details_only_inside_scope(self):
        assign_user(self.clerk, job_title='رئيس وحدة', by=self.manager)
        assign_user(self.clerk, is_entry=True, by=self.manager)
        fresh = User.objects.get(pk=self.clerk.pk)
        self.assertEqual(fresh.profile.job_title, 'رئيس وحدة')
        self.assertTrue(fresh.groups.filter(name=ENTRY_GROUP_NAME).exists())

    def test_manager_can_grant_controller_and_archivist_to_subtree_only(self):
        # رئيسُ القسم يمنح مشرف المتابعة والأرشيفي لمن في شجرته
        assign_user(self.clerk, is_controller=True, by=self.manager)
        self.assertTrue(User.objects.get(pk=self.clerk.pk)
                        .groups.filter(name=CONTROLLER_GROUP_NAME).exists())
        assign_user(self.clerk, is_archivist=True, by=self.manager)
        self.assertTrue(User.objects.get(pk=self.clerk.pk)
                        .groups.filter(name=ARCHIVIST_GROUP_NAME).exists())
        # لكنّه لا يمنح أرشيف الشركة ولا رئيس القسم
        with self.assertRaises(PermissionDenied):
            assign_user(self.clerk, is_company_archivist=True, by=self.manager)
        with self.assertRaises(PermissionDenied):
            assign_user(self.clerk, is_department_head=True, by=self.manager)

    def test_manager_cannot_touch_a_company_archivist_account(self):
        """أرشيفُ الشركة يمنحه المديرُ وحدَه — فلا يُعطّله رئيسُ القسم ولا يغيّره."""
        archivist = User.objects.create_user('co-archivist', password='co-archivist-123456')
        UserProfile.objects.create(user=archivist, department=self.unit)
        archivist.groups.add(Group.objects.get_or_create(name=ARCHIVE_ALL_GROUP_NAME)[0])
        with self.assertRaises(PermissionDenied):
            assign_user(archivist, is_active=False, by=self.manager)

    def test_manager_cannot_touch_a_peer_head_in_their_own_department(self):
        """رئيسٌ نظيرٌ في القسم نفسِه ليس تابعاً في الشجرة (قرارُ المالك 2026‑10‑26)."""
        peer = User.objects.create_user('peer-head', password='peer-head-123456')
        UserProfile.objects.create(user=peer, department=self.dept, is_department_head=True)
        with self.assertRaises(PermissionDenied):
            assign_user(peer, job_title='معدّل', by=self.manager)

    def test_manager_still_manages_the_head_of_a_child_unit(self):
        """الحارسُ لا يتّسع: رئيسُ الشعبة تابعٌ في الشجرة فيبقى في يد رئيس القسم."""
        unit_head = User.objects.create_user('unit-head', password='unit-head-123456')
        UserProfile.objects.create(user=unit_head, department=self.unit, is_department_head=True)
        assign_user(unit_head, job_title='رئيس الشعبة', by=self.manager)
        self.assertEqual(UserProfile.objects.get(user=unit_head).job_title, 'رئيس الشعبة')

    def test_the_admin_only_roles_take_effect_at_creation(self):
        """الدورُ المختار يُطبَّق فعلاً — لا حسابٌ قارئٌ يسجّل السجلُّ أنّه رئيس."""
        head, _ = create_department_user(
            by=self.root, department=self.unit, username='new-head', role='department_head')
        self.assertTrue(UserProfile.objects.get(user=head).is_department_head)
        archivist, _ = create_department_user(
            by=self.root, department=self.unit, username='new-co-archivist',
            role='company_archivist')
        self.assertTrue(archivist.groups.filter(name=ARCHIVE_ALL_GROUP_NAME).exists())

    def test_manager_cannot_manage_foreign_users(self):
        outside = User.objects.create_user('outside2', password='outside-pass-123456')
        UserProfile.objects.create(user=outside, department=self.other)
        with self.assertRaises(PermissionDenied):
            assign_user(outside, job_title='معدّل', by=self.manager)

    def test_manager_can_provision_controller_in_subtree_but_not_admin_role_or_foreign_dept(self):
        # رئيسُ القسم ينشئ مستخدماً بدور مشرف متابعة في شجرته — مسموح
        user, _ = create_department_user(
            by=self.manager, department=self.unit, username='local-controller',
            role='controller')
        self.assertTrue(user.groups.filter(name=CONTROLLER_GROUP_NAME).exists())
        # لكنّه لا ينشئ رئيس قسم
        with self.assertRaises(PermissionDenied):
            create_department_user(
                by=self.manager, department=self.unit, username='local-head',
                role='department_head')
        # ولا ينشئ في قسمٍ خارج شجرته
        with self.assertRaises(PermissionDenied):
            create_department_user(
                by=self.manager, department=self.other, username='foreign-user')

    def test_local_account_creation_returns_one_time_password_and_forces_rotation(self):
        self.client.force_login(self.manager)
        response = self.client.post('/books/admin/', {
            'action': 'create_department_user',
            'department': self.unit.pk,
            'username': 'local-clerk',
            'first_name': 'كاتب',
            'job_title': 'محرر',
            'role': 'entry',
            'tab': 'users',
        })
        self.assertEqual(response.status_code, 200)
        user = User.objects.get(username='local-clerk')
        self.assertTrue(user.profile.must_change_password)
        self.assertTrue(user.groups.filter(name=ENTRY_GROUP_NAME).exists())
        password = response.context['created_credentials']['password']
        self.assertTrue(user.check_password(password))
        self.assertEqual(response['Cache-Control'], 'no-store, private')
        log = UserActivityLog.objects.get(action='CREATE_USER')
        self.assertNotIn(password, str(log.metadata))

        self.client.force_login(user)
        blocked = self.client.get('/books/')
        self.assertEqual(blocked.status_code, 302)
        self.assertEqual(blocked.url, '/password/')
        password_page = self.client.get('/password/')
        self.assertEqual(password_page.status_code, 200)
        self.assertContains(password_page, 'تغيير كلمة المرور')
        self.assertNotContains(password_page, 'title="لوحة التحكم"')
        self.assertNotContains(password_page, 'title="قائمة الكتب"')

        changed = 'Changed-Temporary-Password-42'
        result = self.client.post('/password/', {
            'old_password': password,
            'new_password1': changed,
            'new_password2': changed,
        })
        self.assertEqual(result.status_code, 302)
        user.refresh_from_db()
        self.assertFalse(user.profile.must_change_password)
        self.assertTrue(user.check_password(changed))
        self.assertFalse(hasattr(user, 'temp_password'))

    def test_temporary_password_session_cannot_bypass_gate_over_websocket(self):
        from core.ws_security import FirstLoginPasswordChangeWebsocketMiddleware

        profile = self.manager.profile
        profile.must_change_password = True
        profile.save(update_fields=['must_change_password'])
        events = []

        async def application(scope, receive, send):
            await send({'type': 'websocket.accept'})

        async def receive():
            return {'type': 'websocket.connect'}

        async def send(event):
            events.append(event)

        middleware = FirstLoginPasswordChangeWebsocketMiddleware(application)
        async_to_sync(middleware)(
            {'type': 'websocket', 'user': self.manager}, receive, send)
        self.assertEqual(events, [{'type': 'websocket.close', 'code': 4403}])

    def test_superuser_still_sees_organization_wide_data(self):
        self.client.force_login(self.root)
        response = self.client.get('/books/admin/?tab=departments')
        self.assertContains(response, self.other.name)
        self.assertContains(response, 'العناقيد')


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
