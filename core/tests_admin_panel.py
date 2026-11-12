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

from core.admin_service import (assign_user, create_department, create_department_user,
                                save_group, update_department)
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
        self.staff = User.objects.create_user('unit-staff', password='unit-staff-pass-123456')
        UserProfile.objects.create(user=self.staff, department=self.unit)

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
        assign_user(self.staff, job_title='كاتب وحدة', by=self.manager)
        # (ج‑2) قرارُ المستوى 2: الإدخالُ في ديوان القسم لا في الشعبة — يُرفض هناك ويُقبل هنا
        with self.assertRaises(ValidationError):
            assign_user(self.staff, is_entry=True, by=self.manager)
        UserProfile.objects.filter(user=self.staff).update(department=self.dept)
        self.staff = User.objects.get(pk=self.staff.pk)
        assign_user(self.staff, is_entry=True, by=self.manager)
        fresh = User.objects.get(pk=self.staff.pk)
        self.assertEqual(fresh.profile.job_title, 'كاتب وحدة')
        self.assertTrue(fresh.groups.filter(name=ENTRY_GROUP_NAME).exists())

    def test_manager_can_grant_controller_and_archivist_to_subtree_only(self):
        # رئيسُ القسم يمنح مشرف المتابعة والأرشيفي لمن في شجرته — في ديوان القسم (المستوى 2)
        UserProfile.objects.filter(user=self.staff).update(department=self.dept)
        self.staff = User.objects.get(pk=self.staff.pk)
        assign_user(self.staff, is_controller=True, by=self.manager)
        self.assertTrue(User.objects.get(pk=self.staff.pk)
                        .groups.filter(name=CONTROLLER_GROUP_NAME).exists())
        assign_user(self.staff, is_archivist=True, by=self.manager)
        self.assertTrue(User.objects.get(pk=self.staff.pk)
                        .groups.filter(name=ARCHIVIST_GROUP_NAME).exists())
        # لكنّه لا يمنح أرشيف الشركة ولا رئيس القسم
        with self.assertRaises(PermissionDenied):
            assign_user(self.staff, is_company_archivist=True, by=self.manager)
        with self.assertRaises(PermissionDenied):
            assign_user(self.staff, is_department_head=True, by=self.manager)

    def test_manager_cannot_edit_his_own_account(self):
        """مراجعةُ 10‑27: كان الرئيسُ يمنح نفسَه البريدَ (إعداداتُ بريد الشركة) والأرشفة."""
        for change in ({'is_controller': True}, {'is_archivist': True}, {'job_title': 'ملك'}):
            with self.subTest(**change), self.assertRaises(PermissionDenied):
                assign_user(self.manager, by=self.manager, **change)
        fresh = User.objects.get(pk=self.manager.pk)
        self.assertFalse(fresh.groups.filter(
            name__in=(CONTROLLER_GROUP_NAME, ARCHIVIST_GROUP_NAME)).exists())
        # والصفُّ في اللوحة قراءةٌ لا نموذج
        self.client.force_login(self.manager)
        self.assertNotContains(self.client.get('/books/admin/?tab=users'),
                               f'id="assign-user-{self.manager.pk}"')

    def test_moving_a_unit_head_is_for_the_admin(self):
        """نقلُ رئيس وحدةٍ إلى قسم الناقل يجعله رئيساً نظيراً على الشجرة كلّها (فيبل #5)."""
        UserProfile.objects.filter(user=self.staff).update(is_department_head=True)
        with self.assertRaises(PermissionDenied):
            assign_user(User.objects.get(pk=self.staff.pk), department=self.dept, by=self.manager)
        self.assertEqual(User.objects.get(pk=self.staff.pk).profile.department, self.unit)
        # ونقلُ موظّفٍ عاديّ داخل الشجرة باقٍ للرئيس
        plain = User.objects.create_user('unit-plain', password='unit-plain-pass-123456')
        UserProfile.objects.create(user=plain, department=self.unit)
        assign_user(plain, department=self.dept, by=self.manager)
        self.assertEqual(User.objects.get(pk=plain.pk).profile.department, self.dept)

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
        # (ج‑2) المستوى 2: الأرشيفُ في ديوان القسم لا في الشعبة
        archivist, _ = create_department_user(
            by=self.root, department=self.dept, username='new-co-archivist',
            role='company_archivist')
        self.assertTrue(archivist.groups.filter(name=ARCHIVE_ALL_GROUP_NAME).exists())

    def test_manager_cannot_manage_foreign_users(self):
        outside = User.objects.create_user('outside2', password='outside-pass-123456')
        UserProfile.objects.create(user=outside, department=self.other)
        with self.assertRaises(PermissionDenied):
            assign_user(outside, job_title='معدّل', by=self.manager)

    def test_manager_can_provision_controller_in_subtree_but_not_admin_role_or_foreign_dept(self):
        # رئيسُ القسم ينشئ مستخدماً بدور مشرف متابعة في شجرته — مسموح
        # (ج‑2) المستوى 2: مختصُّ البريد في ديوان القسم — والشعبةُ ترفضه
        with self.assertRaises(ValidationError):
            create_department_user(by=self.manager, department=self.unit, username='unit-controller',
                                   role='controller')
        user, _ = create_department_user(
            by=self.manager, department=self.dept, username='local-controller',
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
            'department': self.dept.pk,   # المدخلُ في الديوان (المستوى 2)
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
        # ``@never_cache`` يُلحق max-age=0… — المهمُّ أنّ no-store حاضرة
        self.assertIn('no-store, private', response['Cache-Control'])
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
        self.assertNotContains(password_page, 'title="كلّ الكتب"')

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


class MergedPanelTests(AdminPanelTestCase):
    """دمجُ لوحة الإدارة (قرارُ المالك 10‑27): تصميمُ الأمس + ميزاتُ الإنتاج السبع +
    إصلاحاتُ المراجعة + ما يخصّ اللوحةَ من دفعة 10‑28. (مراجعةُ فيبل قبل التنفيذ.)"""

    def setUp(self):
        self.unit = create_department(name='شعبة الدمج', code='أ-ش13/9', parent=self.dept, by=self.root)
        self.other = create_department(name='قسم غريب', code='أ-غ1', by=self.root)
        UserProfile.objects.filter(user=self.clerk).update(is_department_head=True)
        self.manager = User.objects.get(pk=self.clerk.pk)
        self.staff = User.objects.create_user('merge-staff', password='merge-staff-pass-1234')
        UserProfile.objects.create(user=self.staff, department=self.unit, must_change_password=True)

    def _get(self, user, **params):
        self.client.force_login(user)
        response = self.client.get('/books/admin/', params)
        self.assertEqual(response.status_code, 200)
        return response

    def test_the_panel_is_never_cached(self):
        """تُعرض فيه كلماتُ مرورٍ مؤقّتة — لا نسخةَ في ذاكرة المتصفّح."""
        self.assertIn('no-store', self._get(self.root)['Cache-Control'])

    def test_admin_tabs_fall_back_to_overview_for_a_head(self):
        for tab in ('groups', 'reservations', 'audit'):
            with self.subTest(tab=tab):
                self.assertEqual(self._get(self.manager, tab=tab).context['tab'], 'overview')
                self.assertEqual(self._get(self.root, tab=tab).context['tab'], tab)
        self.assertNotContains(self._get(self.manager), '?tab=reservations')

    def test_the_reservation_report_is_computed_in_its_tab_only(self):
        self.assertIn('reservation_summary', self._get(self.root, tab='reservations').context)
        self.assertNotIn('reservation_summary', self._get(self.root, tab='users').context)

    def test_overdue_per_department_stays_inside_the_scope(self):
        from datetime import timedelta

        from django.utils import timezone

        from core.models import Book

        today = timezone.localdate()
        for department, number in ((self.unit, '9101'), (self.other, '9102')):
            Book.objects.create(kind='incoming_internal', title='متأخّر', our_number=number,
                                created_by=self.root, department=department, date=today,
                                due_date=today - timedelta(days=3), is_archived=False)
        mine = {d['id']: d['o'] for d in self._get(self.manager).context['departments_data']}
        self.assertEqual(mine[self.unit.pk], 1)
        self.assertNotIn(self.other.pk, mine)
        whole = self._get(self.root).context
        overdue = {d['id']: d['o'] for d in whole['departments_data']}
        self.assertEqual((overdue[self.unit.pk], overdue[self.other.pk]), (1, 1))
        self.assertEqual(whole['org_overdue_total'], 2)
        self.assertEqual(whole['health_rows'][0]['overdue'], 1)   # الأكثرُ تأخّراً أوّلاً

    def test_admin_activity_is_scoped_and_hides_the_admins_own_rows(self):
        """دفعة 10‑28: فعلُ المدير يحمل لقطةَ قسمه فكان يظهر لرئيس ذلك القسم."""
        assign_user(self.staff, job_title='كاتب', by=self.manager)
        head_row = UserActivityLog.objects.filter(action='ASSIGN_USER', user=self.manager).get()
        admin_row = UserActivityLog.objects.create(
            user=self.root, action='ASSIGN_USER', username_snapshot='aroot', department=self.dept)
        foreign = UserActivityLog.objects.create(
            user=self.clerk, action='CREATE_DEPARTMENT', username_snapshot='x', department=self.other)
        seen = {entry.pk for entry in self._get(self.manager).context['admin_activity']}
        self.assertIn(head_row.pk, seen)
        self.assertNotIn(admin_row.pk, seen)
        self.assertNotIn(foreign.pk, seen)

    def test_each_kpi_equals_what_its_filter_shows(self):
        """«بانتظار تغيير كلمة المرور» من ``must_change_password`` لا ``last_login`` —
        والمعطَّلُ معدودٌ في العدّاد وفي تصفيته معاً."""
        off = User.objects.create_user('merge-off', password='merge-off-pass-1234', is_active=False)
        UserProfile.objects.create(user=off, department=self.unit, must_change_password=True)
        self.staff.groups.add(Group.objects.get_or_create(name=ARCHIVIST_GROUP_NAME)[0])
        context = self._get(self.manager).context
        for kpi, token in (('password_pending_count', 'password'),
                           ('sensitive_role_count', 'sensitive'),
                           ('inactive_user_count', 'inactive')):
            with self.subTest(kpi=kpi):
                self.assertEqual(context[kpi],
                                 sum(token in row['status'].split() for row in context['people']))
        self.assertEqual(context['password_pending_count'], 2)
        # الأرشيفيُّ حسّاس: يفتح سرّيّات قسمه (``_department_custodian``)
        self.assertIn('sensitive', next(r for r in context['people'] if r['user'] == self.staff)['status'])

    def test_the_grant_rule_has_one_source(self):
        import inspect

        from core import admin_service, scoping
        from core.views import admin_panel

        for module in (admin_service, admin_panel):
            source = inspect.getsource(module)
            with self.subTest(module=module.__name__):
                self.assertNotIn("'department_head', 'company_archivist'}", source)
                self.assertNotIn('_ADMIN_ONLY_ROLES', source)
        context = self._get(self.manager).context
        self.assertEqual({value for value, _ in context['role_options']}, scoping.HEAD_GRANTABLE_ROLES)
        self.assertEqual({col['role'] for col in context['role_columns']},
                         scoping.HEAD_GRANTABLE_ROLES - {'viewer'})
        self.assertEqual({value for value, _ in self._get(self.root).context['role_options']},
                         scoping.HEAD_GRANTABLE_ROLES | scoping.ADMIN_ONLY_ROLES)

    def test_a_head_posting_admin_roles_changes_nothing_but_his_own(self):
        """النموذجُ يُقرأ بما يمنحه الناظر، وغيابُ حقل القسم «لم يُغيَّر» لا «بلا قسم»."""
        UserProfile.objects.filter(user=self.staff).update(department=self.dept)   # المدخلُ في الديوان (المستوى 2)
        self.client.force_login(self.manager)
        self.client.post('/books/admin/', {
            'action': 'assign_user', 'tab': 'users', 'user_id': self.staff.pk,
            'is_department_head': '1', 'is_company_archivist': '1', 'is_entry': '1'})
        fresh = User.objects.get(pk=self.staff.pk)
        self.assertFalse(fresh.profile.is_department_head)
        self.assertFalse(fresh.groups.filter(name=ARCHIVE_ALL_GROUP_NAME).exists())
        self.assertTrue(fresh.groups.filter(name=ENTRY_GROUP_NAME).exists())
        self.assertEqual(fresh.profile.department, self.dept)

    def test_the_tree_is_keyed_by_id_not_by_the_arabic_code(self):
        response = self._get(self.root)
        unit = next(d for d in response.context['departments_data'] if d['id'] == self.unit.pk)
        self.assertEqual(unit['pid'], self.dept.pk)
        self.assertEqual((unit['o'], unit['e']), (0, True))
        self.assertNotIn('p', unit)
        body = response.content.decode('utf-8')
        self.assertIn("'dt-'+d.id", body)
        self.assertNotIn('replace(/[^a-z0-9]/gi', body)

    def test_the_empty_row_spans_every_column(self):
        import re

        for user, columns in ((self.root, 11), (self.manager, 9)):   # (ج‑4) عمودُ «تنفيذ»
            with self.subTest(user=user.username):
                body = self._get(user, tab='users').content.decode('utf-8')
                head = body.split('<table id="userTable">', 1)[1].split('</thead>', 1)[0]
                self.assertEqual(len(re.findall(r'<th[\s>]', head)), columns)
                self.assertIn(f'id="user-empty" hidden><td colspan="{columns}"', body)

    def test_rows_a_head_cannot_manage_are_read_only(self):
        archive_all = User.objects.create_user('merge-aa', password='merge-aa-pass-1234')
        UserProfile.objects.create(user=archive_all, department=self.unit)
        archive_all.groups.add(Group.objects.get_or_create(name=ARCHIVE_ALL_GROUP_NAME)[0])
        rows = {r['user'].pk: r for r in self._get(self.manager).context['people']}
        self.assertTrue(rows[self.staff.pk]['can_edit'])
        self.assertFalse(rows[archive_all.pk]['can_edit'])
        self.assertFalse(rows[self.manager.pk]['can_edit'])

    def test_settings_cards_open_real_pages(self):
        """رابطٌ ظاهرٌ = صفحةٌ تُفتح — والرئيسُ لا يرى بطاقاتِ إعدادات النظام."""
        from django.urls import reverse

        names = ('sequence_settings', 'entity_list', 'network_settings', 'settings_hub')
        body = self._get(self.root, tab='settings').content.decode('utf-8')
        for name in names:
            with self.subTest(page=name):
                self.assertIn(f'href="{reverse(name)}"', body)
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)
        head_body = self._get(self.manager, tab='settings').content.decode('utf-8')
        self.assertNotIn(f'href="{reverse("sequence_settings")}"', head_body)

    def test_the_level_comes_from_the_name_not_the_depth(self):
        """الشجرةُ الحيّة: «مكتب المدير العام» جذرٌ و«قسم المتابعة» تحته — العمقُ سمّاه شعبة."""
        office = create_department(name='مكتب المدير', code='أ-م0', by=self.root)
        follow = create_department(name='قسم الرصد', code='أ-م0/1', parent=office, by=self.root)
        section = create_department(name='شعبة الرصد', code='أ-م0/1/1', parent=follow, by=self.root)
        self.assertEqual(office.level(0), ('مكتب', 'office'))
        self.assertEqual(follow.level(1), ('قسم', 'dept'))
        self.assertEqual(Department(name='الأرشيف', code='x').level(1), ('شعبة', 'section'))
        levels = {d['id']: d['lv'] for d in self._get(self.root).context['departments_data']}
        self.assertEqual((levels[office.pk], levels[follow.pk], levels[section.pk]),
                         ('مكتب', 'قسم', 'شعبة'))
        self.assertEqual(levels[self.unit.pk], 'شعبة')   # الاسمُ «شعبة الدمج»

    def test_forced_password_rotation_blocks_api_requests_with_403(self):
        user = User.objects.create_user('api-limited', password='temporary-password-42')
        UserProfile.objects.create(
            user=user, department=self.unit, must_change_password=True)
        self.client.force_login(user)

        response = self.client.get(
            '/books/api/unified/data/',
            HTTP_ACCEPT='application/json',
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response['Content-Type'], 'application/json')
        self.assertIn('no-store', response['Cache-Control'])


class HeadPasswordResetTests(AdminPanelTestCase):
    """دفعة 10‑28 بعد الدمج: الرئيسُ يعيد كلمةَ موظّفٍ عاديٍّ في شجرته — لا حسّاساً.
    الكلمةُ المؤقّتة تُعرض له، فإعادتُها لرئيس وحدةٍ أو أرشيفيٍّ دخولٌ بحسابه."""

    def setUp(self):
        self.unit = create_department(name='وحدة الإعادة', code='RS-U', parent=self.dept, by=self.root)
        self.other = create_department(name='قسم بعيد', code='RS-O', by=self.root)
        UserProfile.objects.filter(user=self.clerk).update(is_department_head=True)
        self.manager = User.objects.get(pk=self.clerk.pk)

        def member(name, department, *, head=False, group=None):
            user = User.objects.create_user(name, password=f'{name}-pass-123456')
            UserProfile.objects.create(user=user, department=department, is_department_head=head)
            if group:
                user.groups.add(Group.objects.get_or_create(name=group)[0])
            return user

        self.staff = member('rs-staff', self.unit)
        self.far = member('rs-far', self.other)
        self.unit_head = member('rs-unit-head', self.unit, head=True)
        self.archivist = member('rs-archivist', self.unit, group=ARCHIVIST_GROUP_NAME)

    def _reset(self, by, target):
        self.client.force_login(by)
        return self.client.post('/books/admin/', {
            'action': 'reset_user_password', 'tab': 'users', 'user_id': target.pk})

    def test_head_resets_staff_in_his_tree_once(self):
        from core.models import UserPassword

        response = self._reset(self.manager, self.staff)
        self.assertEqual(response.status_code, 200)
        self.assertIn('no-store', response['Cache-Control'])
        credentials = response.context['created_credentials']
        self.assertTrue(credentials['is_reset'])
        self.staff.refresh_from_db()
        self.assertTrue(self.staff.check_password(credentials['password']))
        self.assertTrue(self.staff.profile.must_change_password)
        self.assertEqual(UserPassword.objects.filter(user=self.staff).count(), 1)
        self.assertTrue(UserActivityLog.objects.filter(
            user=self.manager, action='PASSWORD_RESET', metadata__user='rs-staff').exists())

    def test_head_cannot_reset_outside_sensitive_or_self(self):
        for target in (self.far, self.unit_head, self.archivist, self.manager):
            with self.subTest(target=target.username):
                before = User.objects.get(pk=target.pk).password
                self.assertEqual(self._reset(self.manager, target).status_code, 302)
                self.assertEqual(User.objects.get(pk=target.pk).password, before)

    def test_the_admin_resets_a_sensitive_account(self):
        response = self._reset(self.root, self.archivist)
        self.assertEqual(response.status_code, 200)
        self.archivist.refresh_from_db()
        self.assertTrue(self.archivist.check_password(response.context['created_credentials']['password']))

    def test_inactive_account_is_refused(self):
        User.objects.filter(pk=self.staff.pk).update(is_active=False)
        before = User.objects.get(pk=self.staff.pk).password
        self.assertEqual(self._reset(self.manager, self.staff).status_code, 302)
        self.assertEqual(User.objects.get(pk=self.staff.pk).password, before)

    def test_the_button_follows_the_guard(self):
        self.client.force_login(self.manager)
        rows = {r['user'].pk: r for r in self.client.get('/books/admin/?tab=users').context['people']}
        self.assertTrue(rows[self.staff.pk]['can_reset'])
        for user in (self.unit_head, self.archivist, self.manager):
            with self.subTest(user=user.username):
                self.assertFalse(rows[user.pk]['can_reset'])
