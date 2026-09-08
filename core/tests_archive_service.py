# -*- coding: utf-8 -*-
"""حرّاسُ «تمامِ الأرشفة» — الحدثُ هو العلامة، والخاتمةُ ليست إخفاءً.

**ما يحرسه هذا الملفّ قبل كلّ شيء**: أنّ الأرشفة لا تُبنى على
``Book.is_archived``. الحقلُ صادقٌ في معناه («انتهت المتابعة») وكاذبٌ في
المعنى الذي نريده هنا: 13,188 من 13,194 كتاباً عليه في القاعدة الحيّة لمجرّد
غياب ``due_date``. وحارسُ ``test_a_book_without_a_due_date_is_not_archived_paper``
يسقط لحظةَ يُعاد ربطُ الأرشفة بالعلَم.
"""

from django.contrib.auth.models import Group, User
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from core.archive_service import (archive_book, archived_books, is_archived,
                                  reopen_archive, unarchived_books)
from core.models import (Book, BookHistory, BookReferral, CustodyEvent,
                         Department, UserProfile)
from core.roles import (ARCHIVE_ALL_GROUP_NAME, ARCHIVIST_GROUP_NAME,
                        CONTROLLER_GROUP_NAME)


def _member(name, department, *, controller=False, archivist=False,
            company_archivist=False, admin=False):
    if admin:
        user = User.objects.create_superuser(name, name + '@x.co', 'pw')
    else:
        user = User.objects.create_user(name, name + '@x.co', 'pw')
    UserProfile.objects.update_or_create(user=user, defaults={'department': department})
    for wanted, group_name in ((controller, CONTROLLER_GROUP_NAME),
                               (archivist, ARCHIVIST_GROUP_NAME),
                               (company_archivist, ARCHIVE_ALL_GROUP_NAME)):
        if wanted:
            user.groups.add(Group.objects.get_or_create(name=group_name)[0])
    return user


class ArchiveWriteTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name='قسم الحفظ', code='ح.ف')
        self.archivist = _member('arch', self.dept, archivist=True)
        self.officer = _member('officer', self.dept, controller=True)
        self.book = Book.objects.create(
            kind='incoming_external', title='كتابٌ يُحفظ', our_number='9800',
            department=self.dept, created_by=self.archivist)

    # ── الأثرُ الثلاثيّ ──────────────────────────────────────────────────
    def test_archiving_writes_a_custody_event_a_history_row_and_the_place(self):
        """حدثٌ له وقتٌ وفاعلٌ وحاملٌ وموضعُ حفظ — لا علَمٌ بلا شهادة."""
        moment = archive_book(self.book, by=self.archivist, place='رفّ 3 / صندوق ب')

        self.assertEqual(moment.event, CustodyEvent.ARCHIVE_DONE)
        self.assertEqual(moment.to_holder_department_id, self.dept.pk)
        self.assertIn('رفّ 3', moment.note)
        self.assertTrue(BookHistory.objects.filter(
            book=self.book, action='archived').exists())
        self.assertTrue(is_archived(self.book))

    def test_the_holder_is_the_department_not_the_archivist(self):
        """الورقةُ تُحفظ في أرشيف القسم — ولا تخرج مع مَن حفظها."""
        moment = archive_book(self.book, by=self.archivist)

        self.assertIsNone(moment.to_holder_user_id)
        self.assertEqual(moment.holder_name, self.dept.name)

    # ── الخاتمةُ ليست إخفاءً ────────────────────────────────────────────
    def test_an_open_obligation_refuses_the_archive_and_names_the_holder(self):
        """الورقةُ ما زالت عند وحدةٍ تعمل — والرفضُ يقول **أين** هي."""
        unit = Department.objects.create(name='وحدة التقارير', code='ح.و',
                                         parent=self.dept)
        BookReferral.objects.create(
            book=self.book, from_department=self.dept, to_department=unit,
            status=BookReferral.SENT, created_by=self.archivist)

        with self.assertRaises(ValidationError) as caught:
            archive_book(self.book, by=self.archivist)

        self.assertIn('وحدة التقارير', caught.exception.messages[0])
        self.assertFalse(is_archived(self.book))

    def test_a_received_obligation_still_blocks_the_archive(self):
        """«استلمتُه» ليست «أنجزتُه» — والورقةُ على مكتب الوحدة الآن.

        (اصطاد هذا الحارسَ **غيابُه**: طفرةٌ ضيّقت الشرطَ إلى `SENT` وحدَه
        فمرّت خضراءَ — أي أنّ نصفَ الحالة المفتوحة كان بلا حارس.)
        """
        BookReferral.objects.create(
            book=self.book, from_department=self.dept, to_department=self.dept,
            status=BookReferral.RECEIVED, created_by=self.archivist)

        with self.assertRaises(ValidationError):
            archive_book(self.book, by=self.archivist)

    def test_a_finished_obligation_does_not_block_the_archive(self):
        BookReferral.objects.create(
            book=self.book, from_department=self.dept, to_department=self.dept,
            status=BookReferral.DONE, created_by=self.archivist)

        archive_book(self.book, by=self.archivist)

        self.assertTrue(is_archived(self.book))

    def test_archiving_twice_is_refused_plainly(self):
        archive_book(self.book, by=self.archivist)

        with self.assertRaises(ValidationError):
            archive_book(self.book, by=self.archivist)

    # ── التخويل ─────────────────────────────────────────────────────────
    def test_the_mail_officer_may_not_archive(self):
        """يُسلّم ويستلم ويُفرّق — ولا يقيّد تمامَ الحفظ."""
        with self.assertRaises(PermissionDenied):
            archive_book(self.book, by=self.officer)

    def test_a_plain_employee_may_not_archive(self):
        with self.assertRaises(PermissionDenied):
            archive_book(self.book, by=_member('worker', self.dept))


class ArchiveScopeTests(TestCase):
    """**الرؤيةُ ليست الأرشفة** — أخطرُ ما كان ناقصاً في أوّل صياغة."""

    def setUp(self):
        self.owner = Department.objects.create(name='القسم المالك', code='م.ل')
        self.other = Department.objects.create(name='قسمٌ غريب', code='غ.ر')
        self.unit = Department.objects.create(name='وحدةٌ تابعة', code='ت.ب',
                                              parent=self.owner)
        self.mine = _member('mine', self.owner, archivist=True)
        self.stranger = _member('stranger', self.other, archivist=True)
        self.root = _member('root', self.owner, admin=True)
        self.book = Book.objects.create(
            kind='incoming_external', title='ملفُّ القسم', our_number='9820',
            department=self.owner, created_by=self.mine)

    def test_an_archivist_of_another_department_cannot_close_our_file(self):
        """يراه لأنّه فُرِّق إليه — ولا يملك إغلاقَ ملفّ القسم المالك."""
        BookReferral.objects.create(
            book=self.book, from_department=self.owner, to_department=self.other,
            status=BookReferral.DONE, created_by=self.mine)

        with self.assertRaises(PermissionDenied):
            archive_book(self.book, by=self.stranger)

    def test_a_refused_stranger_learns_nothing_about_the_open_obligations(self):
        """ترتيبُ الفحوص: الحقُّ قبل الحال — وإلّا سرّبت رسالةُ الرفض.

        لو سبق فحصُ الالتزام فحصَ الحقّ لتعلّم الغريبُ من الرسالة أنّ الكتابَ
        مُفرَّقٌ وإلى أين. فالإذنُ أوّلاً، والخطأُ من نوعه.
        """
        BookReferral.objects.create(
            book=self.book, from_department=self.owner, to_department=self.other,
            status=BookReferral.SENT, created_by=self.mine)

        with self.assertRaises(PermissionDenied):
            archive_book(self.book, by=self.stranger)

    def test_the_archivist_of_the_parent_may_file_a_unit_book(self):
        """الشجرةُ لا المساواة — أرشيفُ الوحدة تحت أرشيفيّ قسمها."""
        book = Book.objects.create(
            kind='incoming_external', title='ملفُّ الوحدة', our_number='9821',
            department=self.unit, created_by=self.mine)

        archive_book(book, by=self.mine)

        self.assertTrue(is_archived(book))

    def test_the_root_may_file_any_department(self):
        archive_book(self.book, by=self.root)

        self.assertTrue(is_archived(self.book))

    def test_a_place_longer_than_the_column_is_refused_not_truncated(self):
        """البترُ الصامت يأكل موضعَ الرفّ — وهو الشيءُ الذي يُسأل عنه بعد سنة."""
        with self.assertRaises(ValidationError):
            archive_book(self.book, by=self.mine, place='ر' * 300)

        self.assertFalse(is_archived(self.book))
        self.assertEqual(CustodyEvent.objects.filter(book=self.book).count(), 0)


class ArchiveReopenTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name='قسم الفتح', code='ف.ت')
        self.archivist = _member('arch', self.dept, archivist=True)
        self.book = Book.objects.create(
            kind='incoming_external', title='كتابٌ يُفتح', our_number='9801',
            department=self.dept, created_by=self.archivist)
        archive_book(self.book, by=self.archivist, place='رفّ 1')

    def test_reopening_needs_a_recorded_reason(self):
        """فتحُ ملفٍّ مقفولٍ بلا سببٍ هو ما يجعل الأرشيفَ بلا معنى."""
        with self.assertRaises(ValidationError):
            reopen_archive(self.book, by=self.archivist, reason='   ')

    def test_reopening_keeps_the_archive_event_and_adds_its_own(self):
        """الأحداثُ لا تُحذف — السلسلةُ تُقرأ كما جرت."""
        reopen_archive(self.book, by=self.archivist, reason='طلبُ الديوان')

        self.assertFalse(is_archived(self.book))
        self.assertTrue(CustodyEvent.objects.filter(
            book=self.book, event=CustodyEvent.ARCHIVE_DONE).exists())
        self.assertTrue(BookHistory.objects.filter(
            book=self.book, action='archive-reopened').exists())

    def test_a_reopened_book_may_be_archived_again(self):
        reopen_archive(self.book, by=self.archivist, reason='طلبُ الديوان')

        archive_book(self.book, by=self.archivist, place='رفّ 2')

        self.assertTrue(is_archived(self.book))
        self.assertEqual(CustodyEvent.objects.filter(
            book=self.book, event=CustodyEvent.ARCHIVE_DONE).count(), 2)

    def test_an_ordinary_return_never_unarchives(self):
        """حدثٌ مخصَّصٌ لا ``RETURN`` المشترك — ورجوعُ متعهّدٍ ليس فتحَ أرشيف."""
        from core.custody_service import record_custody

        record_custody(self.book, CustodyEvent.RETURN,
                       to_name='متعهّد البريد', by=self.archivist)

        self.assertTrue(is_archived(self.book))


class ArchiveQuerySetTests(TestCase):
    """التوأمُ الاستعلاميُّ يطابق الصفَّ الواحد — وإلّا انفرجت النسختان."""

    def setUp(self):
        self.dept = Department.objects.create(name='قسم الاستعلام', code='س.ت')
        self.archivist = _member('arch', self.dept, archivist=True)
        self.kept = self._book('9810')
        self.open_again = self._book('9811')
        self.never = self._book('9812')
        archive_book(self.kept, by=self.archivist)
        archive_book(self.open_again, by=self.archivist)
        reopen_archive(self.open_again, by=self.archivist, reason='مراجعة')

    def _book(self, number):
        return Book.objects.create(
            kind='incoming_external', title='ك %s' % number, our_number=number,
            department=self.dept, created_by=self.archivist)

    def test_the_queryset_splits_the_three_states(self):
        archived = set(archived_books().values_list('pk', flat=True))
        pending = set(unarchived_books().values_list('pk', flat=True))

        self.assertEqual(archived, {self.kept.pk})
        self.assertIn(self.open_again.pk, pending)
        self.assertIn(self.never.pk, pending)

    def test_the_queryset_and_the_row_never_disagree(self):
        """حارسٌ بنيويّ: `is_archived` و`archived_books` قاعدةٌ واحدةٌ بصيغتين."""
        archived = set(archived_books().values_list('pk', flat=True))

        for book in (self.kept, self.open_again, self.never):
            self.assertEqual(is_archived(book), book.pk in archived,
                             'انفرجا على %s' % book.our_number)

    def test_a_book_without_a_due_date_is_not_archived_paper(self):
        """**الحارسُ الأهمّ**: العلَمُ المنطقيُّ ليس حفظَ الورقة.

        `Book.save()` يجعل كلَّ كتابٍ بلا `due_date` علَمُه `is_archived=True`
        (13,188 من 13,194 في القاعدة الحيّة). فلو بُنيت الأرشفةُ على العلَم
        لولد الطابورُ كاذباً وصارت القاعدةُ كلُّها «محفوظة» بلا أن يلمسها أحد.
        """
        self.never.refresh_from_db()

        self.assertTrue(self.never.is_archived)      # العلَمُ المنطقيّ مرفوع
        self.assertFalse(is_archived(self.never))    # والورقةُ لم تُحفظ بعد


class ArchiveFollowupOrderTests(TestCase):
    """**الحفظُ يستلزم انتهاءَ المتابعة** — قرارُ المالك 2026-09-06.

    المفهومان يبقيان منفصلين في التخزين (`is_archived` علَمُ متابعةٍ، والحفظُ
    حدثُ عهدة)؛ وهذا شرطُ **ترتيبٍ** بينهما لا دمجٌ لهما: ورقةٌ لها موعدُ
    استحقاقٍ قائمٌ ما زالت في طابور المطارَدة، وحفظُها يُخرجها من عينِ مطاردها.
    """

    def setUp(self):
        self.dept = Department.objects.create(name='قسم الترتيب', code='ر.ت')
        self.archivist = _member('arch', self.dept, archivist=True)

    def _book(self, number, **extra):
        return Book.objects.create(
            kind='incoming_external', title='ك %s' % number, our_number=number,
            department=self.dept, created_by=self.archivist, **extra)

    def test_a_book_still_under_followup_is_refused(self):
        from datetime import timedelta

        from django.utils import timezone

        live = self._book('9970', due_date=timezone.localdate() + timedelta(days=7))
        live.is_archived = False
        live.save()

        with self.assertRaises(ValidationError) as caught:
            archive_book(live, by=self.archivist)

        self.assertIn('المتابعةُ ما زالت قائمة', caught.exception.messages[0])
        self.assertFalse(is_archived(live))

    def test_a_book_whose_followup_is_closed_may_be_filed(self):
        closed = self._book('9971')          # بلا موعد ⟵ المتابعةُ منتهية

        archive_book(closed, by=self.archivist)

        self.assertTrue(is_archived(closed))


class CompanyArchiveTests(TestCase):
    """أرشيفُ الشركة — **موسّعُ نطاقٍ لا دورٌ رابع**."""

    def setUp(self):
        self.owner = Department.objects.create(name='قسمٌ مالك', code='ك.م')
        self.other = Department.objects.create(name='قسمٌ آخر', code='ك.خ')
        self.local = _member('local', self.other, archivist=True)
        self.central = _member('central', self.other, company_archivist=True)
        self.book = Book.objects.create(
            kind='incoming_external', title='ملفُّ الغير', our_number='9980',
            department=self.owner, created_by=_member('owner', self.owner))
        BookReferral.objects.create(
            book=self.book, from_department=self.owner, to_department=self.other,
            status=BookReferral.DONE, created_by=self.local)

    def test_the_company_archivist_files_another_departments_book(self):
        archive_book(self.book, by=self.central)

        self.assertTrue(is_archived(self.book))

    def test_the_local_archivist_still_cannot(self):
        """الاستثناءُ يُمنح صراحةً — ولا يتسرّب إلى مَن لم يُمنح."""
        with self.assertRaises(PermissionDenied):
            archive_book(self.book, by=self.local)

    def test_the_wider_group_carries_the_base_role_with_it(self):
        """لا حالَ ميّتة: «أرشيفُ شركةٍ» بلا صلاحيّةِ أرشفة."""
        from core.scoping import can_archive, is_archivist, is_company_archivist

        self.assertTrue(is_archivist(self.central))
        self.assertTrue(can_archive(self.central))
        self.assertTrue(is_company_archivist(self.central))
        self.assertFalse(is_company_archivist(self.local))
