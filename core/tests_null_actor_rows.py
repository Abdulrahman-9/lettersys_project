# -*- coding: utf-8 -*-
"""صفٌّ في السجلّ بلا حساب ولا اسم لا يُسقط صفحة.

وسيطُ المرشِّح في قوالب جانغو يرفع ``VariableDoesNotExist`` إن كان ما قبله فارغاً، فكان
``{{ a|default:row.user.username }}`` ينهار على FK فارغ. وأسقط هذا لوحةَ مدير النظام في
2026‑11‑03 بصفٍّ واحد كتبه سكربت صيانة. فصارت القوالبُ ``{% firstof %}``.
"""
import pathlib
import re

from django.conf import settings
from django.contrib.auth.models import User
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse

from core.logging_models import UserActivityLog
from core.models import Department


class NullActorPagesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser('na_root', password='x')
        cls.dept = Department.objects.create(name='قسم بلا فاعل', code='ف1')
        UserActivityLog.objects.create(action='EDIT_SETTINGS', department=cls.dept, username_snapshot='')

    def test_the_dashboard_survives_a_row_without_an_actor(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'مستخدم محذوف')

    def test_the_department_page_survives_it(self):
        from core.views.system_admin import system_department_view
        request = RequestFactory().get('/')
        request.user = self.admin
        request.session = {}
        response = system_department_view(request, pk=self.dept.pk)
        self.assertEqual(response.status_code, 200)
        self.assertIn('النظام', response.content.decode('utf-8'))

    def test_a_name_kept_on_the_row_is_shown(self):
        UserActivityLog.objects.create(action='EDIT_SETTINGS', username_snapshot='اسمٌ محفوظ')
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse('dashboard')), 'اسمٌ محفوظ')


class NoCrashingFallbackTests(SimpleTestCase):
    def test_no_template_passes_a_nullable_relation_as_a_filter_argument(self):
        pattern = re.compile(r"\|default:(?!request\.user\.|user\.)[\w.]+\.(?:username|get_full_name)\b")
        found = []
        for path in pathlib.Path(settings.BASE_DIR, 'templates').rglob('*.html'):
            text = path.read_text(encoding='utf-8')
            found += [f'{path.name}: {m.group(0)}' for m in pattern.finditer(text)]
        self.assertEqual(found, [])
