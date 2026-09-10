# -*- coding: utf-8 -*-
"""صفحةُ الحسابات `/books/users/` — **ولا نظامَ أدوارٍ موازٍ فيها** (T7.5‑3).

الدَّينُ الذي يحرسه هذا الملفّ: كانت الصفحةُ تُنشئ مجموعاتٍ إنكليزيّة
(``admin`` · ``controller`` · ``data_entry`` · ``viewer``) عند كلّ زيارة
وتُسنِدها بفعلٍ اسمُه ``update`` — **ولا تقرؤها بوّابةٌ واحدة**: البوّاباتُ في
``core/scoping.py`` تسأل مجموعاتِ ``core/roles.py`` العربيّة وملفَّ المستخدم.
فكان المديرُ يرى «✅ حُدِّث الدور» ولا يتغيّر شيء — أسوأُ من عطبٍ صريح.

والحارسُ يقيس ثلاثةَ أشياء: لا مجموعةَ إنكليزيّةً تُخلَق · فعلُ ``update``
لا يُبدّل صلاحيّةً · والدورُ المعروض يُقرأ من المصدر الذي تسأله البوّابات.
"""

from django.contrib.auth.models import Group, User
from django.test import TestCase

from core.roles import CONTROLLER_GROUP_NAME, get_user_role

#: الأسماءُ التي كان النظامُ الميت يُنشئها — لا يجوز أن يعود أحدُها.
DEAD_GROUP_NAMES = ('admin', 'controller', 'data_entry', 'viewer')

URL = '/books/users/'


class DeadRoleSystemIsGoneTests(TestCase):

    def setUp(self):
        self.boss = User.objects.create_superuser('boss', 'b@x.co', 'pass12345')
        self.client.force_login(self.boss)

    def test_the_page_still_opens(self):
        self.assertEqual(self.client.get(URL).status_code, 200)

    def test_visiting_the_page_creates_no_english_role_group(self):
        """`get_or_create` عند كلّ زيارة كان يزرع أربعَ مجموعاتٍ ميّتة."""
        self.client.get(URL)

        self.assertEqual(
            list(Group.objects.filter(name__in=DEAD_GROUP_NAMES).values_list('name', flat=True)),
            [])

    def test_creating_a_user_joins_no_english_role_group(self):
        res = self.client.post(URL, {
            'action': 'create', 'username': 'newbie',
            'password': 'pass12345', 'password2': 'pass12345',
            # الحقلُ الميت يُرسَل عمداً: لو بقي مستهلِكٌ له لالتقطه هذا الصفّ.
            'role_new': 'controller',
        }, follow=True)
        self.assertEqual(res.status_code, 200)

        newbie = User.objects.get(username='newbie')
        self.assertEqual(list(newbie.groups.values_list('name', flat=True)), [])
        self.assertEqual(get_user_role(newbie), 'viewer')

    def test_the_update_action_no_longer_assigns_anything(self):
        """الفعلُ المُزال يُردّ «إجراء غير صالح» ولا يمسّ صلاحيّةً."""
        victim = User.objects.create_user('victim', 'v@x.co', 'pass12345')

        res = self.client.post(URL, {'action': 'update', 'user_id': victim.pk,
                                     'role': 'admin'}, follow=True)

        victim.refresh_from_db()
        self.assertFalse(victim.is_superuser)
        self.assertEqual(list(victim.groups.values_list('name', flat=True)), [])
        self.assertContains(res, 'إجراء غير صالح')

    def test_the_displayed_role_comes_from_the_gate_source(self):
        """«مشرف المتابعة» عربيّةً — لا `controller` إنكليزيّةً من جدولٍ ثانٍ."""
        officer = User.objects.create_user('officer', 'o@x.co', 'pass12345')
        officer.groups.add(Group.objects.get_or_create(name=CONTROLLER_GROUP_NAME)[0])

        rows = {row['username']: row for row in self.client.get(URL).context['users']}

        self.assertEqual(rows['officer']['role'], 'controller')
        self.assertEqual(rows['officer']['role_label'], CONTROLLER_GROUP_NAME)

    def test_the_account_page_still_creates_and_deletes(self):
        """الإزالةُ لا تأخذ معها ما يعمل: الحسابُ يُنشأ ويُحذف."""
        self.client.post(URL, {'action': 'create', 'username': 'temp',
                               'password': 'pass12345', 'password2': 'pass12345'})
        temp = User.objects.get(username='temp')

        self.client.post(URL, {'action': 'delete', 'user_id': temp.pk})

        self.assertFalse(User.objects.filter(username='temp').exists())
