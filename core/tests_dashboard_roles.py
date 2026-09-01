# -*- coding: utf-8 -*-
"""حرّاسُ لوحة الأدوار — لكلّ دورٍ لوحتُه، وبوّابةُ القسم بوّابةُ صفحته."""

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from core.dashboard_sections import sections_for
from core.models import Book, Department, Entity, UserProfile
from core.roles import CONTROLLER_GROUP_NAME


class DashboardSectionTests(TestCase):
    def setUp(self):
        self.ent = Entity.objects.create(name='قسم اللوحة', code='ل.ق')
        self.dept = Department.objects.create(name='قسم اللوحة', code='ل.ق',
                                              entity=self.ent)
        self.unit = Department.objects.create(name='وحدة بلا توأم', code='ل.و',
                                              parent=self.dept)

    def _user(self, name, department=None, *, head=False, controller=False,
              admin=False):
        if admin:
            user = User.objects.create_superuser(name, name + '@x.co', 'pw')
        else:
            user = User.objects.create_user(name, name + '@x.co', 'pw')
        UserProfile.objects.update_or_create(
            user=user, defaults={'department': department, 'is_department_head': head})
        if controller:
            group, _ = Group.objects.get_or_create(name=CONTROLLER_GROUP_NAME)
            user.groups.add(group)
        return user

    def _keys(self, user):
        return [s['key'] for s in sections_for(user)]

    def test_an_ordinary_employee_sees_only_their_own(self):
        """موظّفُ الوحدة لا يرى طاولةَ الوارد ولا الإدارة ولا البريد."""
        worker = self._user('worker', self.dept)

        keys = self._keys(worker)

        self.assertIn('mine', keys)
        self.assertNotIn('desk', keys)
        self.assertNotIn('mail', keys)
        self.assertNotIn('admin', keys)

    def test_the_mail_officer_gets_the_desk_and_the_mail(self):
        """مسؤولُ البريد والأرشفة — الدورُ الذي سمّاه المالك."""
        clerk = self._user('clerk', self.dept, controller=True)

        keys = self._keys(clerk)

        self.assertIn('desk', keys)
        self.assertIn('mail', keys)
        self.assertNotIn('admin', keys)

    def test_the_department_head_gets_the_desk_without_the_mail(self):
        """رئيسُ الشعبة/الوحدة يقود العملَ ولا يمسك صندوقَ البريد."""
        head = self._user('head', self.dept, head=True)

        keys = self._keys(head)

        self.assertIn('desk', keys)
        self.assertIn('register', keys)
        self.assertNotIn('mail', keys)
        self.assertNotIn('admin', keys)

    def test_the_admin_sees_everything(self):
        boss = self._user('boss', self.dept, admin=True)

        keys = self._keys(boss)

        for key in ('mine', 'desk', 'register', 'mail', 'admin'):
            self.assertIn(key, keys)

    def test_a_unit_without_a_twin_has_no_dossier_section(self):
        """القسمُ الذي يُعيد بانيه None يُسقَط — لا صندوقٌ فارغٌ يُعلّم التجاهل."""
        loose = self._user('loose', self.unit)

        self.assertNotIn('dossier', self._keys(loose))

    def test_a_twinned_unit_gets_its_dossier(self):
        worker = self._user('worker2', self.dept)

        self.assertIn('dossier', self._keys(worker))

    def test_the_gate_is_the_page_gate_not_a_second_rule(self):
        """بوّابةُ «طاولة الوارد» هي `can_use_desk` نفسُها — لا صياغةٌ ثانية."""
        from core.scoping import can_use_desk

        for name, kwargs in (('a', {}), ('b', {'head': True}),
                             ('c', {'controller': True}), ('d', {'admin': True})):
            user = self._user('gate_' + name, self.dept, **kwargs)
            self.assertEqual('desk' in self._keys(user), can_use_desk(user),
                             msg=name)

    def test_every_counter_carries_a_link(self):
        """رقمٌ لا يُنقر يترك المستخدمَ يبحث عن الطريق بنفسه."""
        boss = self._user('boss2', self.dept, admin=True)

        for section in sections_for(boss):
            for counter in section['counters']:
                self.assertTrue(counter.get('href'), msg=section['key'])


class DashboardViewTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name='قسم العرض', code='ض.ق')
        self.owner = User.objects.create_superuser('root', 'r@x.co', 'pw')
        self.worker = User.objects.create_user('w', 'w@x.co', 'pw')
        UserProfile.objects.update_or_create(
            user=self.worker, defaults={'department': self.dept})

    def test_the_overview_uses_the_single_source(self):
        """كانت هنا نسخةٌ سابعةٌ من قاعدة الرؤية: «المشرف الكلّ وغيرُه كتبَه».

        يفشل عليها: موظّفُ القسم لم يُنشئ الكتابَ ويراه بحكم قسمه.
        """
        Book.objects.create(kind='incoming_external', title='ك', our_number='6001',
                            department=self.dept, created_by=self.owner)
        self.client.force_login(self.worker)

        res = self.client.get(reverse('dashboard'))

        self.assertEqual(res.context['total'], 1)

    def test_the_page_names_the_role_and_department(self):
        self.client.force_login(self.worker)

        res = self.client.get(reverse('dashboard'))

        self.assertEqual(res.context['my_department'], self.dept)
        self.assertContains(res, 'قسم العرض')
        self.assertContains(res, res.context['role_label'])

    def test_the_template_asks_no_role_questions(self):
        """القسمةُ في بايثون لا في القالب — شرطٌ هناك قاعدةٌ ثانيةٌ تنحرف."""
        import io
        with io.open('templates/core/_dashboard_sections.html', encoding='utf-8') as fh:
            markup = fh.read()

        for forbidden in ('is_superuser', 'dept_head', 'controller', 'role_key'):
            self.assertNotIn(forbidden, markup)
