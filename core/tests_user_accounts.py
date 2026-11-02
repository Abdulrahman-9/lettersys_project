# -*- coding: utf-8 -*-
"""الحساباتُ من بابٍ واحد — **ولا نظامَ أدوارٍ موازٍ فيه**.

الدَّينُ الذي يحرسه هذا الملفّ: كانت صفحةُ ``/books/users/`` تُنشئ مجموعاتٍ إنكليزيّة
(``admin`` · ``controller`` · ``data_entry`` · ``viewer``) عند كلّ زيارة وتُسنِدها بفعلٍ اسمُه
``update`` — ولا تقرؤها بوّابةٌ واحدة. ثمّ بقيت بعد إصلاح ذلك بابَ إنشاءٍ ثانياً بلا أثرٍ ولا
تدويرِ كلمة مرور، فأُغلقت: عنوانُها يحوّل إلى تبويب الحسابات في لوحة الإدارة.
"""

from django.contrib.auth.models import Group, User
from django.test import TestCase

from core.models import Department
from core.roles import get_user_role

#: الأسماءُ التي كان النظامُ الميت يُنشئها — لا يجوز أن تعود.
DEAD_GROUP_NAMES = ('admin', 'controller', 'data_entry', 'viewer')

OLD_URL = '/books/users/'
PANEL = '/books/admin/'


class OneDoorForAccountsTests(TestCase):

    def setUp(self):
        self.admin = User.objects.create_superuser('boss', 'b@x.co', 'pass12345')
        self.dept = Department.objects.create(name='قسم الحسابات', code='ح-1')
        self.client.force_login(self.admin)

    def create(self, username, **extra):
        return self.client.post(PANEL, {
            'action': 'create_department_user', 'tab': 'users', 'department': self.dept.pk,
            'username': username, 'role': 'viewer', **extra})

    def english_groups(self):
        return list(Group.objects.filter(name__in=DEAD_GROUP_NAMES).values_list('name', flat=True))

    def test_the_old_address_leads_to_the_accounts_tab(self):
        response = self.client.get(OLD_URL)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], '/books/admin/?tab=users')

    def test_posting_to_the_old_address_changes_nothing(self):
        victim = User.objects.create_user('victim', 'v@x.co', 'pass12345')
        self.client.post(OLD_URL, {'action': 'create', 'username': 'ghost',
                                   'password': 'pass12345', 'password2': 'pass12345'})
        self.client.post(OLD_URL, {'action': 'delete', 'user_id': victim.pk})
        self.assertFalse(User.objects.filter(username='ghost').exists())
        self.assertTrue(User.objects.filter(pk=victim.pk).exists())

    def test_visiting_the_accounts_tab_creates_no_english_role_group(self):
        self.client.get(PANEL + '?tab=users')
        self.assertEqual(self.english_groups(), [])

    def test_creating_a_reader_joins_no_group(self):
        self.create('newbie', role_new='controller')
        newbie = User.objects.get(username='newbie')
        self.assertEqual(list(newbie.groups.values_list('name', flat=True)), [])
        self.assertEqual(get_user_role(newbie), 'viewer')
        self.assertEqual(self.english_groups(), [])

    def test_the_panel_creates_and_deletes(self):
        self.create('temp')
        temp = User.objects.get(username='temp')
        self.client.post(PANEL, {'action': 'delete_user', 'tab': 'users', 'user_id': temp.pk})
        self.assertFalse(User.objects.filter(username='temp').exists())

    def test_a_created_account_is_not_staff(self):
        """D‑1: ``is_staff`` بوّابةُ صفحات الإدارة لا دورُ عمل."""
        self.create('clerk')
        self.assertFalse(User.objects.get(username='clerk').is_staff)
