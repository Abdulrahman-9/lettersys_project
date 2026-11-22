# -*- coding: utf-8 -*-
"""خطأُ الحقل بجوار حقله (11-22) — مركزُ الإعدادات والنسخُ الاحتياطيّ وصفحتا الحساب.

كانت الأخطاءُ توستاً في الزاوية بعد التحويل. الحارسُ الأوّل يطابق كلَّ حقلٍ تسمّه الخوادمُ بموضعه
في قالب صفحته (وإلّا اختفت الرسالة: التوستُ العامّ يتخطّاها)، والبقيّةُ ترسم الصفحةَ كما يراها المستخدم.
"""
import re
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core.models import Department
from core.roles import ensure_role_groups

ROOT = Path(settings.BASE_DIR)


def _read(rel):
    return (ROOT / rel).read_text(encoding='utf-8')


def _slots(template):
    return set(re.findall(r"\{% field_error '(\w+)' '\w+' %\}", _read(template)))


class EveryTaggedFieldHasItsSlotTests(SimpleTestCase):
    # (الملفّ الذي يسمّي الحقول، النمط، القالبُ الذي يعود إليه الطلب)
    SOURCES = (
        ('core/views/settings_hub.py', r"field_error\(request, '(\w+)'", 'templates/core/settings/hub.html'),
        ('core/views/dashboard.py', r'field_error\(request, "(\w+)"', 'templates/core/backup.html'),
        ('core/admin_service.py', r"code=FIELD_CODE \+ '(\w+)'", 'templates/core/system_admin/account_new.html'),
        ('core/views/system_admin.py', r"code=FIELD_CODE \+ '(\w+)'", 'templates/core/system_admin/account_new.html'),
    )

    def test_no_field_error_is_dropped_for_want_of_a_slot(self):
        for source, pattern, template in self.SOURCES:
            with self.subTest(source=source):
                named = set(re.findall(pattern, _read(source)))
                self.assertTrue(named, 'لا حقلَ مسمّى في %s — تغيّر النمطُ؟' % source)
                self.assertEqual(named - _slots(template), set(), 'حقولٌ بلا موضعٍ في %s' % template)

    def test_the_editor_draws_whatever_assign_user_can_name(self):
        # محرّرُ الحساب يحفظ بـassign_user وحدها: حقولُها الموسومة قسمٌ واسمٌ ومستوى وظيفيّ
        src = _read('core/admin_service.py')
        body = src[src.index('def assign_user('):src.index('\ndef ', src.index('def assign_user(') + 1)]
        named = set(re.findall(r"code=FIELD_CODE \+ '(\w+)'", body))
        self.assertEqual(named, {'department', 'job_title', 'name'})
        self.assertEqual(named - _slots('templates/core/system_admin/account.html'), set())

    def test_the_global_toasts_skip_field_errors(self):
        loop = _read('templates/base.html')
        loop = loop[loop.index('{% for m in messages %}'):]
        self.assertIn("{% if 'lx-field-' not in tag %}", loop[:loop.index('<div class="toast fancy-toast"')])


class RenderedNextToTheFieldTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        ensure_role_groups()
        cls.dept = Department.objects.create(name='قسم الحقول', code='حق1')
        cls.root = User.objects.create_superuser('fe_root', password='pw-fe-1122')

    def setUp(self):
        self.client.force_login(self.root)

    def _next_to(self, page, input_id, text):
        slot = re.search(r'<p class="lx-field-error" id="%s-error" data-field-error-for="%s">(.*?)</p>'
                         % (input_id, input_id), page, re.S)
        self.assertIsNotNone(slot, 'لا خطأَ تحت الحقل %s' % input_id)
        self.assertIn(text, slot.group(1))
        toasts = ''.join(re.findall(r'<div class="toast fancy-toast".*?</div>\s*</div>\s*</div>', page, re.S))
        self.assertNotIn(text, toasts, 'خطأُ الحقل ظهر توستاً أيضاً')

    def test_hub_fields(self):
        cases = (
            ('settings_general_save', {'app_name': '  '}, 'gen_app_name', 'اسم النظام مطلوب'),
            ('settings_security_save', {'password_min_length': 'ثمانية'}, 'sec_min_len', 'بين 4 و64'),
            ('settings_ai_save', {'low_confidence_threshold': 'عالٍ'}, 'ai_threshold', 'بين 0 و1'),
        )
        for name, data, input_id, text in cases:
            with self.subTest(view=name):
                page = self.client.post(reverse(name), data, follow=True).content.decode()
                self._next_to(page, input_id, text)

    def test_backup_path(self):
        with mock.patch('core.views.dashboard.create_encrypted_pg_backup', side_effect=OSError('denied')):
            page = self.client.post(reverse('backup_database'), {'target_directory': 'Z:/لا'}, follow=True)
        self._next_to(page.content.decode(), 'bkDir', 'تعذّرت كتابةُ النسخة')

    def test_new_account(self):
        page = self.client.post(reverse('system_account_new'),
                                {'name': 'جديد', 'username': '', 'department': self.dept.pk, 'role': 'reader'})
        self._next_to(page.content.decode(), 'anUser', 'اسم المستخدم مطلوب')
        page = self.client.post(reverse('system_account_new'), {'name': 'جديد', 'username': 'fe_x', 'role': 'reader'})
        self._next_to(page.content.decode(), 'anDept', 'اختر قسمَ الحساب')

    def test_account_editor(self):
        user = User.objects.create_user('fe_target', password='pw-fe-1122')
        data = {'action': 'save', 'name': 'س' * 200, 'department': str(self.dept.pk), 'job_title': '', 'is_active': '1',
                'confirm_department': '1'}
        page = self.client.post(reverse('system_account', args=[user.pk]), data, follow=True).content.decode()
        self._next_to(page, 'aeName', 'الاسم يتجاوز 150 حرفاً')

    def test_an_unnamed_error_stays_a_toast(self):
        user = User.objects.create_user('fe_plain', password='pw-fe-1122')
        page = self.client.post(reverse('system_account', args=[user.pk]), {'action': 'nonsense'},
                                follow=True).content.decode()
        self.assertIn('class="toast fancy-toast"', page)
        self.assertNotIn('class="lx-field-error"', page)
