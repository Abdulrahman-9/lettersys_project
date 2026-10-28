# -*- coding: utf-8 -*-
"""عدسةُ القسم (?dept=) وإعادةُ كلمة المرور من رئيس القسم.

الوعدُ الذي تحرسه هذه الاختبارات: **العدسةُ تضيّق ولا توسّع أبداً** — في اللوحة
والقائمة والـAJAX والسجلّ — وما خارج نطاق الرئيس «غيرُ موجود» (404).
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.logging_models import UserActivityLog
from core.models import Book, Department, UserPassword, UserProfile


def _user(name, department=None, *, head=False, superuser=False):
    if superuser:
        user = User.objects.create_superuser(name, f'{name}@x.test', 'pw-lens-0000')
    else:
        user = User.objects.create_user(name, password='pw-lens-0000')
    UserProfile.objects.update_or_create(
        user=user, defaults={'department': department, 'is_department_head': head})
    return user


class DepartmentLensTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.office = Department.objects.create(name='مكتب العدسة العام', code='LN-O')
        cls.dept = Department.objects.create(name='قسم متابعة العدسة', code='LN-D', parent=cls.office)
        cls.section = Department.objects.create(name='شعبة موازنة العدسة', code='LN-S', parent=cls.dept)
        cls.unit = Department.objects.create(name='وحدة تقارير العدسة', code='LN-U', parent=cls.section)
        cls.other = Department.objects.create(name='قسم تقنية العدسة', code='LN-IT')
        cls.retired = Department.objects.create(name='قسم مطوي', code='LN-R', is_active=False)

        cls.admin = _user('lens-admin', superuser=True)
        cls.head = _user('lens-head', cls.section, head=True)
        cls.clerk = _user('lens-clerk', cls.unit)
        cls.outsider = _user('lens-outsider', cls.other)

        def book(dept, number, author):
            return Book.objects.create(kind='incoming_external', title=f'كتاب {number}',
                                       created_by=author, department=dept, our_number=number)
        cls.b_dept = book(cls.dept, '7701', cls.admin)
        cls.b_unit = book(cls.unit, '7702', cls.clerk)
        cls.b_other = book(cls.other, '7703', cls.outsider)
        cls.b_retired = book(cls.retired, '7704', cls.admin)

    # ── المستويات ──
    def test_level_comes_from_the_name_not_the_depth(self):
        self.assertEqual(self.office.level(0), ('مكتب', 'office'))
        self.assertEqual(self.dept.level(1), ('قسم', 'dept'))
        self.assertEqual(self.section.level(2), ('شعبة', 'section'))
        self.assertEqual(self.unit.level(3), ('وحدة', 'unit'))
        nameless = Department(name='الأرشيف', code='x')
        self.assertEqual(nameless.level(1), ('شعبة', 'section'))

    # ── اللوحة ──
    def test_superadmin_dashboard_is_whole_org_and_narrows_by_lens(self):
        self.client.force_login(self.admin)
        whole = self.client.get(reverse('dashboard'))
        self.assertEqual(whole.context['total'], 4)
        self.assertIsNone(whole.context['lens_department'])
        self.assertTrue(whole.context['scope_tree'])

        lensed = self.client.get(reverse('dashboard'), {'dept': self.office.pk})
        self.assertEqual(lensed.context['total'], 2)  # المتابعة + الوحدة تحتها
        self.assertEqual([s['name'] for s in lensed.context['lens_trail']], ['مكتب العدسة العام'])
        self.assertContains(lensed, f'&amp;dept={self.office.pk}')

    def test_scope_tree_counts_roll_up_the_subtree(self):
        self.client.force_login(self.admin)
        tree = {n['pk']: n for n in self.client.get(reverse('dashboard')).context['scope_tree']}
        self.assertEqual(tree[self.office.pk]['count'], 2)
        self.assertEqual(tree[self.section.pk]['count'], 1)
        self.assertEqual(tree[self.office.pk]['level_key'], 'office')

    def test_head_cannot_lens_outside_his_subtree(self):
        self.client.force_login(self.head)
        for name in ('dashboard', 'book_unified', 'api_unified_data', 'audit_log'):
            with self.subTest(view=name):
                self.assertEqual(
                    self.client.get(reverse(name), {'dept': self.dept.pk}).status_code, 404)
        self.assertEqual(self.client.get(reverse('dashboard'), {'dept': self.unit.pk}).status_code, 200)

    def test_staff_without_reports_ignore_the_lens(self):
        self.client.force_login(self.clerk)
        response = self.client.get(reverse('dashboard'), {'dept': self.other.pk})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['lens_department'])
        self.assertNotContains(response, 'كتاب 7703')

    def test_superadmin_can_lens_an_inactive_department(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('dashboard'), {'dept': self.retired.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total'], 1)

    def test_garbage_dept_is_404(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('dashboard'), {'dept': 'x1'}).status_code, 404)

    # ── القائمة و AJAX ──
    def test_ajax_list_honours_the_lens(self):
        self.client.force_login(self.admin)
        data = self.client.get(reverse('api_unified_data'),
                               {'tab': 'all', 'dept': self.section.pk}).json()
        self.assertEqual({b['id'] for b in data['books']}, {self.b_unit.pk})
        page = self.client.get(reverse('book_unified'), {'tab': 'all', 'dept': self.section.pk})
        self.assertEqual(page.context['lens_department'], self.section)
        self.assertContains(page, 'dept-lens-bar')

    # ── السجلّ ──
    def test_audit_lens_filters_and_keeps_dept_in_pagination(self):
        UserActivityLog.objects.create(user=self.clerk, action='VIEW_BOOK',
                                       username_snapshot='lens-clerk', department=self.unit,
                                       book=self.b_unit)
        UserActivityLog.objects.create(user=self.outsider, action='VIEW_BOOK',
                                       username_snapshot='lens-outsider', department=self.other,
                                       book=self.b_other)
        self.client.force_login(self.admin)
        response = self.client.get(reverse('audit_log'), {'tab': 'users', 'dept': self.dept.pk})
        names = {r['who'] for r in response.context['rows']}
        self.assertNotIn('lens-outsider', names)
        self.assertTrue(any(r['book_number'] for r in response.context['rows']))
        self.assertEqual(response.context['filters']['dept'], str(self.dept.pk))

    def test_head_does_not_see_superadmin_admin_rows(self):
        from core.scoping import scope_activity_for
        admin_row = UserActivityLog.objects.create(
            user=self.admin, action='PASSWORD_RESET', username_snapshot='lens-admin',
            department=self.section)
        book_row = UserActivityLog.objects.create(
            user=self.admin, action='VIEW_BOOK', username_snapshot='lens-admin',
            department=self.section, book=self.b_unit)
        seen = set(scope_activity_for(self.head).values_list('pk', flat=True))
        self.assertNotIn(admin_row.pk, seen)
        self.assertIn(book_row.pk, seen)


class HeadPasswordResetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dept = Department.objects.create(name='قسم الإعادة', code='RS-D')
        cls.unit = Department.objects.create(name='وحدة الإعادة', code='RS-U', parent=cls.dept)
        cls.other = Department.objects.create(name='قسم بعيد', code='RS-O')
        cls.head = _user('rs-head', cls.dept, head=True)
        cls.staff = _user('rs-staff', cls.unit)
        cls.far = _user('rs-far', cls.other)
        cls.peer_head = _user('rs-peer', cls.unit, head=True)

    def _reset(self, target):
        return self.client.post(reverse('admin_panel'), {
            'action': 'reset_user_password', 'tab': 'users', 'user_id': target.pk})

    def test_head_resets_staff_in_his_tree_once(self):
        self.client.force_login(self.head)
        response = self._reset(self.staff)
        self.assertEqual(response.status_code, 200)
        self.assertIn('no-store', response['Cache-Control'])
        password = response.context['created_credentials']['password']
        self.assertTrue(response.context['created_credentials']['is_reset'])
        self.staff.refresh_from_db()
        self.assertTrue(self.staff.check_password(password))
        self.assertTrue(self.staff.profile.must_change_password)
        self.assertEqual(UserPassword.objects.filter(user=self.staff).count(), 1)
        self.assertTrue(UserActivityLog.objects.filter(
            user=self.head, action='PASSWORD_RESET', metadata__user='rs-staff').exists())

    def test_head_cannot_reset_outside_peer_head_or_self(self):
        self.client.force_login(self.head)
        for target in (self.far, self.peer_head, self.head):
            with self.subTest(target=target.username):
                before = User.objects.get(pk=target.pk).password
                response = self._reset(target)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(User.objects.get(pk=target.pk).password, before)

    def test_inactive_account_is_refused(self):
        User.objects.filter(pk=self.staff.pk).update(is_active=False)
        self.client.force_login(self.head)
        before = User.objects.get(pk=self.staff.pk).password
        self.assertEqual(self._reset(self.staff).status_code, 302)
        self.assertEqual(User.objects.get(pk=self.staff.pk).password, before)
