# -*- coding: utf-8 -*-
"""تدقيقُ 2026-10-08، مجموعةُ «المستخدمون ولوحة الإدارة والنسخ والاستعادة».

١. **زرُّ حذف المستخدم**: كان `onclick="deleteUser('…', '{{ u.username }}')"` — الاسمُ في سلسلة JS داخل صفة
   حدث (تهريبُ HTML لا يحميها)، ويُعرض لصاحب الحساب حذفٌ يرفضه الخادم. الآن نموذجٌ بـ`data-confirm`، ولا
   زرَّ حذفٍ على صفّك.
٢. **اسمُ المستخدم بلا مُدقِّق**: `User.objects.create()` لا يستدعي `UnicodeUsernameValidator`، فكان يمرّ
   اسمٌ بمسافةٍ أو علامة اقتباس. الآن مُدقِّقُ Django نفسُه (والعربيّةُ مقبولة).
٣. **الاستعادةُ الذكيّة**: ثلاثُ نوافذ `confirm()` أصليّة ⟵ حواريّةُ التطبيق؛ وطلبُ الإلغاء كان يفشل صامتاً
   والزرُّ معطّلٌ إلى الأبد.
٤. جدولُ النسخ: وحدتان للحجم (MB في الرأس و«م.ب» في الخليّة) وتاريخ ISO.
"""
import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

ROOT = Path(__file__).resolve().parent.parent
User = get_user_model()


class UserRolesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.boss = User.objects.create_superuser('roles_boss', 'r@x.co', 'pw-roles-boss-1')
        cls.other = User.objects.create_user('roles_other', password='pw-roles-other-1')

    def setUp(self):
        self.client.force_login(self.boss)

    def html(self):
        return self.client.get(reverse('user_roles')).content.decode('utf-8')

    def test_delete_is_a_confirmed_form_and_not_on_my_row(self):
        html = self.html()
        self.assertNotIn('deleteUser(', html)
        forms = re.findall(r'<form method="post" class="d-inline" data-confirm="سيُحذف المستخدم «([^»]+)»', html)
        self.assertIn('roles_other', forms)
        self.assertNotIn('roles_boss', forms)

    def test_bad_usernames_are_refused(self):
        for bad in ('a b', "x');alert(1);('", '<b>x</b>'):
            with self.subTest(username=bad):
                self.client.post(reverse('user_roles'), {'action': 'create', 'username': bad,
                                                         'password': 'Pw-long-enough-1', 'password2': 'Pw-long-enough-1'})
                self.assertFalse(User.objects.filter(username=bad).exists())

    def test_an_arabic_username_is_fine(self):
        self.client.post(reverse('user_roles'), {'action': 'create', 'username': 'كاتب_الوارد',
                                                 'password': 'Pw-long-enough-1', 'password2': 'Pw-long-enough-1'})
        self.assertTrue(User.objects.filter(username='كاتب_الوارد').exists())


class AdminScriptsTests(SimpleTestCase):
    def test_restore_page_asks_through_the_app(self):
        src = (ROOT / 'static' / 'js' / 'data_restore.js').read_text(encoding='utf-8')
        # النافذةُ الأصليّة احتياطٌ وحيدٌ داخل ask() حين تغيب الحواريّة
        self.assertEqual(len(re.findall(r'(?<![\w.])confirm\(', src)), 0)
        self.assertEqual(src.count('window.confirm('), 1)
        for title in ("title: 'اعتماد الربط'", "title: 'بدء الدمج'", "title: 'إلغاء المهمّة'"):
            self.assertIn(title, src)

    def test_cancel_failure_is_reported(self):
        src = (ROOT / 'static' / 'js' / 'data_restore.js').read_text(encoding='utf-8')
        fn = src[src.index('function cancelJob()'):]
        fn = fn[:fn.index('\n  }\n')]
        self.assertIn('.catch(function ()', fn)
        self.assertIn("$('rsJobCancel').disabled = false;", fn)

    def test_backup_table(self):
        src = (ROOT / 'templates' / 'core' / 'backup.html').read_text(encoding='utf-8')
        self.assertNotIn('<th>الحجم (MB)</th>', src)
        self.assertIn('backup.modified|date:"d/m/Y H:i"', src)
