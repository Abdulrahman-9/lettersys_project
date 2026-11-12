# -*- coding: utf-8 -*-
"""(ج‑3) إنشاءُ حساب — الأدوارُ بحسب القسم المختار، ثمّ يُفتح محرّرُه بكلمته المؤقّتة مرّةً واحدة (2026‑11‑12).

التصميمُ المعتمد shots_v2/v2_account_new.png. الصفحةُ لمدير النظام وحده؛ والخادمُ يعيد فحصَ الواجهة
(``roles_for_department``): وحدةٌ لا تمسك سجلّاً لا يُنشأ فيها مدخلٌ ولا مختصُّ بريد.
"""
import json
import re

from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from core import scoping as s
from core.models import Department, RoleCapabilityOverride, UserProfile
from core.roles import EXECUTOR_GROUP_NAME, ensure_role_groups

URL = reverse('system_account_new')


class NewAccountCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_role_groups()
        Group.objects.get_or_create(name=EXECUTOR_GROUP_NAME)
        cls.dept = Department.objects.create(name='قسم الإنشاء', code='نش1')
        cls.unit = Department.objects.create(name='وحدة الإنشاء', code='نش1و', parent=cls.dept, holds_register=False)
        cls.root = User.objects.create_superuser('c3_root', password='pw-c3-1111')

    def setUp(self):
        cache.clear()
        self.client.force_login(self.root)

    def create(self, **data):
        return self.client.post(URL, {'name': 'موظّف جديد', 'job_title': '', **data})


class PageTests(NewAccountCase):
    def test_the_page_is_the_system_admins(self):
        head = User.objects.create_user('c3_head', password='pw-c3-1111')
        UserProfile.objects.update_or_create(user=head, defaults={'department': self.dept, 'is_department_head': True})
        self.client.force_login(head)
        self.assertEqual(self.client.get(URL).status_code, 403)
        self.assertEqual(self.client.post(URL, {'username': 'c3_sneak', 'department': self.dept.pk,
                                                'role': 'reader'}).status_code, 403)
        self.assertFalse(User.objects.filter(username='c3_sneak').exists())
        self.client.force_login(self.root)
        self.assertEqual(self.client.get(URL).status_code, 200)

    def data(self, name):
        body = self.client.get(URL).content.decode()
        return body, json.loads(re.search(rf'<script id="{name}" type="application/json">(.*?)</script>',
                                          body, re.S).group(1))

    def test_each_department_offers_only_its_roles(self):
        body, roles = self.data('anDeptRoles')
        self.assertEqual(roles[str(self.dept.pk)], {'roles': list(s.roles_for_department(self.dept)), 'register': True})
        self.assertEqual(roles[str(self.unit.pk)], {'roles': list(s.roles_for_department(self.unit)), 'register': False})
        for role, label in s.ROLE_LABELS.items():
            self.assertIn(f'data-role="{role}"', body)
            self.assertIn(f'<b>{label}</b>', body)

    def test_the_summary_is_the_matrix_as_it_is_now(self):
        _body, meta = self.data('anRolesMeta')
        self.assertIn('الإدخال', meta['entry']['can'])
        self.assertIn('تشغيل البريد', meta['entry']['cannot'])
        self.assertEqual(meta['reader']['can'], ['قراءة كتب نطاقه'])
        self.assertNotIn(s.CAPABILITIES['book.comment'].label, meta['head']['can'])   # غيرُ موصول
        key = next(k for k in sorted(s.WIRED_CAPABILITIES) if not s.CAPABILITIES[k].locked
                   and not s.role_cell_frozen(k, 'entry') and 'entry' not in s.CAPABILITIES[k].holders)
        RoleCapabilityOverride.objects.create(role='entry', capability=key, allowed=True)
        _body, meta = self.data('anRolesMeta')
        self.assertIn(s.CAPABILITIES[key].label, meta['entry']['can'])

    def test_the_accounts_list_links_here_for_the_system_admin(self):
        self.assertIn(f'href="{URL}"', self.client.get(reverse('admin_panel') + '?tab=users').content.decode())


class CreateTests(NewAccountCase):
    def test_each_role_is_created_as_itself(self):
        for dept in (self.dept, self.unit):
            for role in s.roles_for_department(dept):
                with self.subTest(dept=dept.code, role=role):
                    username = f'c3_{dept.pk}_{role}'
                    response = self.create(username=username, department=dept.pk, role=role)
                    self.assertEqual(response.status_code, 200)
                    user = User.objects.get(username=username)
                    self.assertEqual((s.role_of(user), user.profile.department), (role, dept))
                    self.assertTrue(user.profile.must_change_password)

    def test_a_role_the_department_cannot_hold_is_refused(self):
        response = self.create(username='c3_unfit', department=self.unit.pk, role='entry')
        self.assertContains(response, 'اختر دوراً يُسند في هذا القسم.')
        self.assertContains(response, 'id="anForm"')
        self.assertFalse(User.objects.filter(username='c3_unfit').exists())

    def test_an_unknown_or_inactive_department_is_refused(self):
        closed = Department.objects.create(name='قسمٌ مغلق', code='نش2', is_active=False)
        for raw in ('', 'x', str(closed.pk)):
            with self.subTest(department=raw):
                response = self.create(username='c3_nodept', department=raw, role='reader')
                self.assertContains(response, 'اختر قسمَ الحساب.')
        self.assertFalse(User.objects.filter(username='c3_nodept').exists())

    def test_the_editor_opens_with_the_password_once_and_uncached(self):
        response = self.create(username='c3_new', department=self.dept.pk, role='mail', name='سالم أحمد علي')
        user = User.objects.get(username='c3_new')
        self.assertEqual((user.first_name, user.last_name), ('سالم', 'أحمد علي'))
        body = response.content.decode()
        self.assertIn('ae-secret', body)
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(response['Referrer-Policy'], 'no-referrer')
        editor = reverse('system_account', args=[user.pk])
        forms = re.findall(r'<form method="post"[^>]*>', body)   # العنوانُ عنوانُ الإنشاء: نموذجٌ بلا وجهة يُنشئ ثانيةً
        self.assertEqual([form for form in forms if 'action="' not in form], [])
        self.assertGreaterEqual(body.count(f'action="{editor}"'), 6)
        self.assertIn(f'data-url="{editor}"', body)

    def test_a_taken_username_keeps_what_was_typed(self):
        User.objects.create_user('c3_taken', password='pw-c3-1111')
        response = self.create(username='c3_taken', department=self.dept.pk, role='reader', name='اسمٌ مكتوب')
        self.assertContains(response, 'اسم المستخدم مستعملٌ سلفاً.')
        self.assertContains(response, 'value="اسمٌ مكتوب"')
        self.assertEqual(User.objects.filter(username='c3_taken').count(), 1)
