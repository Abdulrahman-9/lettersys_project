# -*- coding: utf-8 -*-
"""
(قراراتُ الدورة §6 — 2026‑09‑11) أُزيل الرفُّ: لا «تمامَ أرشفة» ولا موضعَ حفظ؛ الطاولةُ طابوران.
حرّاسُ «طاولة الأرشفة» — البوّابةُ وصدقُ الطوابير.

**الدرسُ الذي يحرسه هذا الملفّ**: طابورٌ لا يُفرَغ يُهجَر في أسبوع. والقاعدةُ
الحيّة فيها 13,037 مرفقاً و13,076 كتاباً دخلت **بالجملة** من القاعدة القديمة
ولم تمرّ بيدِ أرشيفيّ قطّ. فكلُّ استعلامٍ هنا يحمل ``source_ref=''`` و
``is_training=False``؛ وحارسُ ``test_the_queues_never_show_the_bulk_import``
يسقط لحظةَ يُنسى أحدُهما — قبل أن يفتح الأرشيفيُّ طاولةً بـ13 ألف صفّ.
"""

from django.contrib.auth.models import Group, User
from django.test import TestCase

from core.models import (Attachment, Book, BookReferral, CustodyEvent,
                         Department, UserProfile)
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


class ArchiveDeskGateTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name='قسم الطاولة', code='ط.ق')
        self.archivist = _member('arch', self.dept, archivist=True)

    def test_the_archivist_opens_his_desk(self):
        self.client.force_login(self.archivist)

        self.assertEqual(self.client.get(URL).status_code, 200)

    def test_everyone_else_is_refused(self):
        """الطاولةُ أداةُ دورٍ لا صفحةُ اطّلاع."""
        for user in (_member('plain', self.dept),
                     _member('officer', self.dept, controller=True),
                     _member('head', self.dept, head=True)):
            self.client.force_login(user)

            self.assertEqual(self.client.get(URL).status_code, 403, user.username)

    def test_the_root_opens_it_too(self):
        self.client.force_login(_member('root', self.dept, admin=True))

        self.assertEqual(self.client.get(URL).status_code, 200)


class ArchiveDeskQueueTests(TestCase):
    """صدقُ الطوابير — كلُّ صفٍّ يُعرض عملٌ يُغلقه إنسانٌ اليوم."""

    def setUp(self):
        self.dept = Department.objects.create(name='قسم الطوابير', code='ط.ب')
        self.archivist = _member('arch', self.dept, archivist=True)
        self.client.force_login(self.archivist)

    def _book(self, number, **extra):
        return Book.objects.create(
            kind='incoming_external', title='ك %s' % number, our_number=number,
            department=self.dept, created_by=self.archivist, **extra)

    def _queues(self):
        return {q['key']: q for q in self.client.get(URL).context['queues']}

    # ── الطابورُ الذي يُعرّف الدور ───────────────────────────────────────
    def test_a_book_that_never_moved_sits_in_the_idle_queue(self):
        self._book('9903')

        self.assertEqual(self._queues()['idle']['total'], 1)

    def test_a_book_without_an_attachment_is_listed(self):
        self._book('9904')

        self.assertEqual(self._queues()['nofile']['total'], 1)

    def test_a_book_whose_only_attachment_was_deleted_is_listed_too(self):
        """(د‑4 في 7.4‑هـ) الضمُّ لا يمرّ بمدير: ``attachments__isnull`` كان يرى
        المرفقَ المحذوفَ ناعماً فيُخفي الكتابَ عن طابور «بلا مرفق»."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.utils import timezone
        from core.models import Attachment
        book = self._book('9908')
        Attachment.objects.create(
            book=book, file=SimpleUploadedFile('x.pdf', b'%PDF-1.4'),
            is_deleted=True, deleted_at=timezone.now())

        self.assertEqual(self._queues()['nofile']['total'], 1,
                         'كتابٌ مرفقُه الوحيدُ محذوفٌ يجب أن يظهر في «بلا مرفق»')

    def test_the_queues_never_show_the_bulk_import(self):
        """**13 ألفَ صفٍّ لا يُغلقها إنسان** — وطابورٌ لا يُفرَغ يُهجَر.

        الكتبُ المنقولة من القاعدة القديمة (`source_ref`) وكتبُ التدريب دخلت
        بالجملة ولم تمرّ بيدِ أرشيفيّ. لو سقط أحدُ الشرطين من الاستعلام لفتح
        الأرشيفيُّ طاولةً بحجم القاعدة كلِّها — فيُهملها ويُهمل الدور معها.
        """
        self._book('9907', source_ref='IIMAIL_2025#4671')
        self._book('T99', is_training=True)

        queues = self._queues()

        for key in ('idle', 'nofile'):
            self.assertEqual(queues[key]['total'], 0, key)

    def test_the_legacy_backlog_is_stated_not_counted_as_work(self):
        """يُذكر سطراً — فلا الطاولةُ تكذب بالفراغ ولا تغرق بالإرث."""
        self._book('9908', source_ref='IIMAIL_2025#900')

        res = self.client.get(URL)

        self.assertEqual(res.context['legacy_total'], 1)
        self.assertContains(res, 'منقولاً من القاعدة القديمة')

    def test_a_book_of_another_department_never_appears(self):
        other = Department.objects.create(name='قسمٌ آخر', code='ط.خ')
        stranger = _member('stranger', other)
        Book.objects.create(kind='incoming_external', title='ملفُّ الغريب',
                            our_number='9909', department=other,
                            created_by=stranger)

        for queue in self._queues().values():
            self.assertEqual(queue['total'], 0, queue['key'])


class ArchiveDeskRowShapeTests(TestCase):
    """ثلاثةُ أنواعِ صفوفٍ في قالبٍ واحد — والحجبُ في البانِي لا في القالب."""

    def setUp(self):
        self.dept = Department.objects.create(name='قسم الشكل', code='ش.ك')
        self.archivist = _member('arch', self.dept, archivist=True)
        self.client.force_login(self.archivist)

    def test_a_book_row_carries_no_referral_and_no_meta_date(self):
        Book.objects.create(kind='incoming_external', title='كتابٌ ساكن',
                            our_number='9910', department=self.dept,
                            created_by=self.archivist)

        row = {q['key']: q for q in
               self.client.get(URL).context['queues']}['idle']['rows'][0]

        self.assertIsNone(row['referral'])
        self.assertIsNone(row['meta_date'])
        self.assertEqual(row['title'], 'كتابٌ ساكن')

    def test_a_secret_title_is_masked_in_the_builder(self):
        """قاعدةُ الحجب في بايثون — وشرطٌ في القالب قاعدةٌ ثانيةٌ تنحرف."""
        other = Department.objects.create(name='قسمٌ آخر', code='ش.خ')
        book = Book.objects.create(
            kind='incoming_external', title='عنوانٌ لا يُعرض', our_number='9912',
            secret_level='secret', department=other,
            created_by=_member('owner', other))
        BookReferral.objects.create(
            book=book, from_department=other, to_department=self.dept,
            status=BookReferral.DONE, created_by=self.archivist)

        res = self.client.get(URL)

        self.assertNotContains(res, 'عنوانٌ لا يُعرض')


class ArchiveNavGateTests(TestCase):
    """رابطٌ ظاهرٌ = صفحةٌ تُفتح — وإلّا عَلَّم المستخدمَ أن يتجاهل الشريط."""

    def setUp(self):
        self.dept = Department.objects.create(name='قسم الشريط', code='ش.ر')

    def test_the_archive_link_shows_only_for_the_archivist(self):
        self.client.force_login(_member('arch', self.dept, archivist=True))

        self.assertContains(self.client.get('/'), 'طاولة الأرشفة')

    def test_the_archive_link_is_hidden_from_everyone_else(self):
        self.client.force_login(_member('plain', self.dept))

        self.assertNotContains(self.client.get('/'), 'طاولة الأرشفة')

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

    def test_his_dashboard_carries_the_archive_section(self):
        res = self.client.get('/')

        self.assertContains(res, 'الأرشفة')
        self.assertContains(res, 'قُيِّد ولم يُوجَّه')

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
