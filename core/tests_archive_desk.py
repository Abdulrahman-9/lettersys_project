# -*- coding: utf-8 -*-
"""حرّاسُ «طاولة الأرشفة» — البوّابةُ وصدقُ الطوابير.

**الدرسُ الذي يحرسه هذا الملفّ**: طابورٌ لا يُفرَغ يُهجَر في أسبوع. والقاعدةُ
الحيّة فيها 13,037 مرفقاً و13,076 كتاباً دخلت **بالجملة** من القاعدة القديمة
ولم تمرّ بيدِ أرشيفيّ قطّ. فكلُّ استعلامٍ هنا يحمل ``source_ref=''`` و
``is_training=False``؛ وحارسُ ``test_the_queues_never_show_the_bulk_import``
يسقط لحظةَ يُنسى أحدُهما — قبل أن يفتح الأرشيفيُّ طاولةً بـ13 ألف صفّ.
"""

from django.contrib.auth.models import Group, User
from django.test import TestCase

from core.archive_service import archive_book
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
    def test_a_finished_referral_puts_the_book_in_the_filing_queue(self):
        book = self._book('9900')
        BookReferral.objects.create(
            book=book, from_department=self.dept, to_department=self.dept,
            status=BookReferral.DONE, created_by=self.archivist)

        self.assertEqual(self._queues()['finished']['total'], 1)

    def test_an_open_referral_keeps_it_out_of_the_filing_queue(self):
        """ما زال عند الوحدة — ليس عملَ الأرشيفيّ بعد."""
        book = self._book('9901')
        BookReferral.objects.create(
            book=book, from_department=self.dept, to_department=self.dept,
            status=BookReferral.SENT, created_by=self.archivist)

        self.assertEqual(self._queues()['finished']['total'], 0)

    def test_filing_the_book_empties_the_queue(self):
        book = self._book('9902')
        BookReferral.objects.create(
            book=book, from_department=self.dept, to_department=self.dept,
            status=BookReferral.DONE, created_by=self.archivist)

        archive_book(book, by=self.archivist, place='رفّ 1')

        self.assertEqual(self._queues()['finished']['total'], 0)
        self.assertEqual(self._queues()['recent']['total'], 1)

    # ── بقيّةُ الطوابير ──────────────────────────────────────────────────
    def test_a_book_that_never_moved_sits_in_the_idle_queue(self):
        self._book('9903')

        self.assertEqual(self._queues()['idle']['total'], 1)

    def test_a_book_without_an_attachment_is_listed(self):
        self._book('9904')

        self.assertEqual(self._queues()['nofile']['total'], 1)

    def test_filing_without_a_place_is_surfaced_for_repair(self):
        """حُفظ ولم يُقل أين — وهو أوّلُ ما يُسأل عنه بعد سنة."""
        archive_book(self._book('9905'), by=self.archivist)

        self.assertEqual(self._queues()['placeless']['total'], 1)

    def test_filing_with_a_place_is_not_surfaced(self):
        archive_book(self._book('9906'), by=self.archivist, place='رفّ ب/12')

        self.assertEqual(self._queues()['placeless']['total'], 0)

    # ── الحارسُ الأهمّ ───────────────────────────────────────────────────
    def test_the_queues_never_show_the_bulk_import(self):
        """**13 ألفَ صفٍّ لا يُغلقها إنسان** — وطابورٌ لا يُفرَغ يُهجَر.

        الكتبُ المنقولة من القاعدة القديمة (`source_ref`) وكتبُ التدريب دخلت
        بالجملة ولم تمرّ بيدِ أرشيفيّ. لو سقط أحدُ الشرطين من الاستعلام لفتح
        الأرشيفيُّ طاولةً بحجم القاعدة كلِّها — فيُهملها ويُهمل الدور معها.
        """
        self._book('9907', source_ref='IIMAIL_2025#4671')
        self._book('T99', is_training=True)

        queues = self._queues()

        for key in ('finished', 'idle', 'nofile'):
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

    def test_a_custody_row_shows_the_holder_and_the_signing_date(self):
        book = Book.objects.create(kind='incoming_external', title='كتابٌ محفوظ',
                                   our_number='9911', department=self.dept,
                                   created_by=self.archivist)
        moment = archive_book(book, by=self.archivist, place='رفّ 1')

        row = {q['key']: q for q in
               self.client.get(URL).context['queues']}['recent']['rows'][0]

        self.assertEqual(row['meta_label'], self.dept.name)
        self.assertEqual(row['meta_date'], moment.signed_at.date())

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


class ArchiveApiTests(TestCase):
    """الغلافُ رقيقٌ: HTTP ⟵ استدعاء، والرسالةُ من الخادم بنصّها."""

    def setUp(self):
        self.dept = Department.objects.create(name='قسم الواجهة', code='و.ج')
        self.archivist = _member('arch', self.dept, archivist=True)
        self.officer = _member('officer', self.dept, controller=True)
        self.book = Book.objects.create(
            kind='incoming_external', title='كتابُ الواجهة', our_number='9950',
            department=self.dept, created_by=self.archivist)
        self.url = '/books/api/book/%d/archive/' % self.book.pk

    def _post(self, url, payload):
        import json
        return self.client.post(url, data=json.dumps(payload),
                                content_type='application/json')

    def test_the_archivist_files_the_book_through_the_api(self):
        self.client.force_login(self.archivist)

        res = self._post(self.url, {'place': 'رفّ ب/12'})

        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()['success'])
        self.assertTrue(CustodyEvent.objects.filter(
            book=self.book, event=CustodyEvent.ARCHIVE_DONE).exists())

    def test_the_mail_officer_is_refused_with_403(self):
        self.client.force_login(self.officer)

        res = self._post(self.url, {})

        self.assertEqual(res.status_code, 403)
        self.assertIn('الأرشفة', res.json()['message'])

    def test_a_book_outside_the_scope_is_missing_not_forbidden(self):
        """خارجُ النطاق **404 لا 403** — و403 تُقرّ بوجود ما لا يُرى."""
        other = Department.objects.create(name='قسمٌ آخر', code='و.خ')
        hidden = Book.objects.create(
            kind='incoming_external', title='خفيّ', our_number='9951',
            department=other, created_by=_member('owner', other))
        self.client.force_login(self.archivist)

        res = self._post('/books/api/book/%d/archive/' % hidden.pk, {})

        self.assertEqual(res.status_code, 404)

    def test_the_open_obligation_message_reaches_the_browser_verbatim(self):
        """رسالةُ الخطأ من الخادم بنصّها — لا تُخترع في الواجهة."""
        unit = Department.objects.create(name='وحدة الردّ', code='و.ر',
                                         parent=self.dept)
        BookReferral.objects.create(
            book=self.book, from_department=self.dept, to_department=unit,
            status=BookReferral.SENT, created_by=self.archivist)
        self.client.force_login(self.archivist)

        res = self._post(self.url, {})

        self.assertEqual(res.status_code, 400)
        self.assertIn('وحدة الردّ', res.json()['message'])

    def test_reopening_needs_a_reason_through_the_api(self):
        archive_book(self.book, by=self.archivist)
        self.client.force_login(self.archivist)

        res = self._post('/books/api/book/%d/archive/reopen/' % self.book.pk,
                         {'reason': ''})

        self.assertEqual(res.status_code, 400)


class ArchiveButtonTests(TestCase):
    """الزرُّ يظهر لصاحبه ويتبدّل بحال الكتاب — ولا شرطَ دورٍ في القالب."""

    def setUp(self):
        self.dept = Department.objects.create(name='قسم الزرّ', code='ز.ر')
        self.archivist = _member('arch', self.dept, archivist=True)
        self.book = Book.objects.create(
            kind='incoming_external', title='كتابُ الزرّ', our_number='9960',
            department=self.dept, created_by=self.archivist)

    def _detail(self):
        return self.client.get('/books/%d/' % self.book.pk)

    def test_the_archivist_sees_the_filing_button_and_its_dialog(self):
        self.client.force_login(self.archivist)

        res = self._detail()

        self.assertContains(res, 'تمامُ أرشفة')
        self.assertContains(res, 'archiveModal')

    def test_the_mail_officer_sees_neither(self):
        self.client.force_login(_member('officer', self.dept, controller=True))

        res = self._detail()

        self.assertNotContains(res, 'archiveModal')

    def test_a_filed_book_offers_reopening_instead(self):
        archive_book(self.book, by=self.archivist)
        self.client.force_login(self.archivist)

        res = self._detail()

        self.assertContains(res, 'فتحُ المؤرشَف')
        self.assertNotContains(res, 'archiveModal')
