# -*- coding: utf-8 -*-
"""
(2026‑10‑12، قرارُ المالك) **حُذفت «طاولة الأرشفة»**: قيسَت في الإنتاج فكانت
طاولةَ رقابةٍ لا طاولةَ عمل (18 من 19 كتاباً حيّاً «لم يُوجَّه» وثلاثُ إحالاتٍ
في القاعدة كلِّها)، والمتابعةُ تتمّ من «قائمة الكتب» و«طاولة الوارد».

يبقى **دورُ** مسؤول الأرشفة وأدواتُه (السلّة · الأضابير · الإدخال · صلاحيّةُ
أرشفةِ الكتاب)، وهذا الملفُّ يحرس الأمرين: الصفحةُ لا تعود من بابٍ خلفيّ،
والدورُ لا يُفقَد معها.
"""

from django.contrib.auth.models import Group, User
from django.test import TestCase

from core.models import Book, Department, UserProfile
from core.roles import ARCHIVIST_GROUP_NAME, CONTROLLER_GROUP_NAME

URL = '/books/desk/archive/'

def _member(name, department, *, head=False, controller=False,
            archivist=False, admin=False):
    if admin:
        user = User.objects.create_superuser(name, name + '@x.co', 'pw')
    else:
        user = User.objects.create_user(name, name + '@x.co', 'pw')
    UserProfile.objects.update_or_create(
        user=user, defaults={'department': department, 'is_department_head': head})
    for wanted, group_name in ((controller, CONTROLLER_GROUP_NAME),
                               (archivist, ARCHIVIST_GROUP_NAME)):
        if wanted:
            user.groups.add(Group.objects.get_or_create(name=group_name)[0])
    return user


class ArchiveDeskRemovedTests(TestCase):
    """الصفحةُ حُذفت — فلا مسارَ ولا رابطَ ولا قسمَ لوحةٍ يَعِد بها."""

    def setUp(self):
        self.dept = Department.objects.create(name='قسم الحذف', code='ح.ذ')
        self.archivist = _member('arch', self.dept, archivist=True)

    def test_the_old_url_is_gone(self):
        for user in (self.archivist, _member('root', self.dept, admin=True)):
            self.client.force_login(user)

            self.assertEqual(self.client.get(URL).status_code, 404, user.username)

    def test_no_link_or_dashboard_section_promises_it(self):
        Book.objects.create(kind='incoming_external', title='ك', our_number='8801',
                            department=self.dept, created_by=self.archivist)
        self.client.force_login(self.archivist)

        res = self.client.get('/')

        for gone in ('طاولة الأرشفة', 'لا قيدَ ناقصاً', 'قُيِّد ولم يُوجَّه', URL):
            self.assertNotContains(res, gone)

class ArchiveNavGateTests(TestCase):
    """رابطٌ ظاهرٌ = صفحةٌ تُفتح — وإلّا عَلَّم المستخدمَ أن يتجاهل الشريط."""

    def setUp(self):
        self.dept = Department.objects.create(name='قسم الشريط', code='ش.ر')

    def test_the_mail_desk_link_is_hidden_from_those_refused_at_its_door(self):
        """كان يظهر للجميع ويردّ 403 — وعدٌ لا يفي أسوأُ من إخفاء."""
        self.client.force_login(_member('plain2', self.dept))

        self.assertNotContains(self.client.get('/'), 'طاولة الوارد')


class ArchiveToolsTests(TestCase):
    """أدواتُ الدور: السلّةُ والأضابيرُ والاستعلامُ والإدخال.

    «يُدخل الكتبَ ويؤرشفها ويستعلم عنها ويفتح الأضابير» — أربعةٌ، ولا تكفي
    البوّابةُ الأولى وحدَها ما لم تُفتح الأبوابُ الأربعة فعلاً.
    """

    def setUp(self):
        self.dept = Department.objects.create(name='قسم الأدوات', code='أ.د')
        self.archivist = _member('arch', self.dept, archivist=True)
        self.client.force_login(self.archivist)

    def test_he_reaches_the_pages_his_role_needs(self):
        for path in ('/books/unified/', '/books/dossiers/', '/books/trash/',
                     '/books/extract/smart-desktop/'):
            self.assertEqual(self.client.get(path).status_code, 200, path)

    def test_the_trash_link_is_offered_to_him(self):
        """يستعيد ورقاً حُذف خطأً — وكان الرابطُ محجوباً بـ`is_staff` وحدَها."""
        self.assertContains(self.client.get('/'), 'سلة المهملات')

    def test_the_trash_link_stays_hidden_from_a_plain_employee(self):
        self.client.force_login(_member('plain', self.dept))

        self.assertNotContains(self.client.get('/'), 'سلة المهملات')

    def test_a_plain_employee_gets_no_archive_section(self):
        self.client.force_login(_member('plain2', self.dept))

        self.assertNotContains(self.client.get('/'), 'أُنجز ولم يُحفَظ')


class AuditLinkTests(TestCase):
    """بوّابةٌ بُنيت ولم يستعملها أحد — والرابطُ الغائب صفحةٌ لا تُزار."""

    def setUp(self):
        self.dept = Department.objects.create(name='قسم السجلّ', code='ج.ل')

    def test_the_department_head_finds_the_audit_link(self):
        self.client.force_login(_member('head', self.dept, head=True))

        self.assertContains(self.client.get('/'), 'سجلّ الحركات')

    def test_a_plain_employee_does_not(self):
        self.client.force_login(_member('plain', self.dept))

        self.assertNotContains(self.client.get('/'), 'سجلّ الحركات')

    def test_the_archivist_does_not_either(self):
        """يحفظ الورقَ ولا يراقب مَن قرأه."""
        self.client.force_login(_member('arch', self.dept, archivist=True))

        self.assertNotContains(self.client.get('/'), 'سجلّ الحركات')
