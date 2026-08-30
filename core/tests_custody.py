"""
العهدة — «لا يضيع مستندٌ أبداً ولا تفاصيله».

هذا الجدولُ هو **الميزةُ الحاكمة**: سُئل الكاتبُ ما الذي يجعله يترك دفترَ
التواقيع الورقيَّ فأجاب بشرطٍ واحد — أن يرى **كلَّ تفاصيل الاستلام وبعهدة مَن**.
فالاختباراتُ هنا تسأل عن القنوات التي تنكسر بها السلسلة: صفٌّ بلا حامل ·
مؤشّرٌ ينفرج عن سجلّه · استلامٌ لا يُقرّ الإحالة · تسجيلٌ بأثرٍ رجعيّ يقلب
«بعهدة مَن» إلى الوراء.
"""

from datetime import timedelta

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from core.custody_service import custody_chain, held_by, record_custody, undelivered
from core.models import (Book, BookHistory, BookReferral, CustodyEvent, Department,
                         Entity, UserProfile)
from core.referral_service import distribute


class CustodyTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.dept = Department.objects.create(name='المتابعة', code='ع-ش13')
        cls.unit = Department.objects.create(
            name='شعبة الموازنة', code='ع-ش13/1', parent=cls.dept,
            entity=Entity.objects.create(name='شعبة الموازنة'),
        )
        cls.other = Department.objects.create(name='العقود', code='ع-ش5')

        def member(name, dept):
            u = User.objects.create_user(name, password='pw-%s-11111' % name)
            UserProfile.objects.create(user=u, department=dept)
            return u

        cls.clerk = member('cclerk', cls.dept)
        cls.staff = member('cstaff', cls.unit)
        cls.outsider = member('cout', cls.other)

        cls.book = Book.objects.create(
            kind='incoming_external', title='كتابُ الوزارة', created_by=cls.clerk,
            department=cls.dept, our_number='2433',
        )


class RecordCustodyTests(CustodyTestCase):

    def test_writes_the_event_and_moves_the_pointer(self):
        moment = record_custody(self.book, CustodyEvent.INTAKE,
                                to_department=self.dept, by=self.clerk)
        self.book.refresh_from_db()
        self.assertEqual(self.book.current_custody, moment)
        self.assertEqual(self.book.current_custody.holder_name, str(self.dept))

    def test_leaves_a_trace_in_the_book_history(self):
        record_custody(self.book, CustodyEvent.ARCHIVE_DONE, to_department=self.dept,
                       note='الرفّ ب/12', by=self.clerk)
        event = BookHistory.objects.get(book=self.book, action='custody')
        self.assertIn('الرفّ ب/12', event.notes)

    def test_a_courier_needs_no_account(self):
        """سلسلةُ العهدة لا تنقطع عند أوّل حاملٍ من خارج الحسابات."""
        moment = record_custody(self.book, CustodyEvent.COURIER_PICKUP,
                                to_name='مُتعهّدُ البريد — أبو أحمد', by=self.clerk)
        self.assertEqual(moment.holder_name, 'مُتعهّدُ البريد — أبو أحمد')

    def test_custody_to_nobody_is_refused(self):
        with self.assertRaises(ValidationError):
            record_custody(self.book, CustodyEvent.INTAKE, by=self.clerk)

    def test_the_database_refuses_a_holderless_row_too(self):
        """الحارسُ في الخدمة **وفي القاعدة** — لأنّ الخدمةَ يمكن تجاوزُها."""
        with self.assertRaises(IntegrityError), transaction.atomic():
            CustodyEvent.objects.create(book=self.book, event=CustodyEvent.INTAKE,
                                        signed_at=timezone.now())

    def test_an_unknown_event_is_refused(self):
        with self.assertRaises(ValidationError):
            record_custody(self.book, 'ما-شئت', to_department=self.dept, by=self.clerk)

    def test_a_referral_of_another_book_is_refused(self):
        other_book = Book.objects.create(
            kind='incoming_internal', title='كتابٌ آخر', created_by=self.clerk,
            department=self.dept, our_number='2434',
        )
        alien = distribute(other_book, [self.unit], by=self.clerk)[0]
        with self.assertRaises(ValidationError):
            record_custody(self.book, CustodyEvent.UNIT_RECEIPT, referral=alien,
                           to_department=self.unit, by=self.clerk)

    def test_a_stranger_cannot_record_custody(self):
        with self.assertRaises(PermissionDenied):
            record_custody(self.book, CustodyEvent.INTAKE, to_department=self.other,
                           by=self.outsider)

    def test_the_default_signature_is_paper(self):
        """ادّعاءُ التوقيع الرقميّ حيث لا يوجد يُفسد الحجّة."""
        moment = record_custody(self.book, CustodyEvent.INTAKE,
                                to_department=self.dept, by=self.clerk)
        self.assertEqual(moment.signature_mode, CustodyEvent.PAPER)

    def test_an_unknown_signature_mode_is_refused(self):
        with self.assertRaises(ValidationError):
            record_custody(self.book, CustodyEvent.INTAKE, to_department=self.dept,
                           mode='بصمة', by=self.clerk)


class ReceiptClosesTheLoopTests(CustodyTestCase):
    """استلامُ الوحدة **هو** إقرارُ الإحالة — وفصلُهما يُنتج وحدةً «استلمت» ولم «تستلم»."""

    def setUp(self):
        self.referral = distribute(self.book, [self.unit], by=self.clerk)[0]

    def test_unit_receipt_advances_the_referral(self):
        record_custody(self.book, CustodyEvent.UNIT_RECEIPT, referral=self.referral,
                       to_department=self.unit, by=self.staff)
        self.referral.refresh_from_db()
        self.assertEqual(self.referral.status, BookReferral.RECEIVED)

    def test_the_two_traces_are_written_together(self):
        record_custody(self.book, CustodyEvent.UNIT_RECEIPT, referral=self.referral,
                       to_department=self.unit, by=self.staff)
        actions = set(BookHistory.objects.filter(book=self.book)
                      .values_list('action', flat=True))
        self.assertIn('custody', actions)
        self.assertIn('referral-received', actions)

    def test_another_event_does_not_touch_the_referral(self):
        record_custody(self.book, CustodyEvent.ARCHIVE_DONE, referral=self.referral,
                       to_department=self.unit, by=self.clerk)
        self.referral.refresh_from_db()
        self.assertEqual(self.referral.status, BookReferral.SENT)


class PointerIntegrityTests(CustodyTestCase):
    """المؤشّرُ لا ينفرج عن سجلّه — وإلّا صار «بعهدة مَن» كذبةً موثّقة."""

    def test_the_latest_event_wins(self):
        record_custody(self.book, CustodyEvent.INTAKE, to_department=self.dept,
                       by=self.clerk)
        second = record_custody(self.book, CustodyEvent.UNIT_RECEIPT,
                                to_department=self.unit, by=self.clerk)
        self.book.refresh_from_db()
        self.assertEqual(self.book.current_custody, second)

    def test_a_backdated_entry_does_not_drag_the_pointer_back(self):
        """كشفُ تسليمٍ يُدخَل متأخّراً بتاريخ أمس لا يقلب «بعهدة مَن»."""
        now = timezone.now()
        current = record_custody(self.book, CustodyEvent.UNIT_RECEIPT,
                                 to_department=self.unit, signed_at=now, by=self.clerk)
        record_custody(self.book, CustodyEvent.INTAKE, to_department=self.dept,
                       signed_at=now - timedelta(days=1), by=self.clerk)
        self.book.refresh_from_db()
        self.assertEqual(self.book.current_custody, current)

    def test_the_backdated_row_is_still_kept_in_the_chain(self):
        """لا يُحرَّك المؤشّر — **ولا يُهمل الصفّ**: السلسلةُ تحفظ كلَّ شيء."""
        now = timezone.now()
        record_custody(self.book, CustodyEvent.UNIT_RECEIPT, to_department=self.unit,
                       signed_at=now, by=self.clerk)
        record_custody(self.book, CustodyEvent.INTAKE, to_department=self.dept,
                       signed_at=now - timedelta(days=1), by=self.clerk)
        self.assertEqual(custody_chain(self.book).count(), 2)

    def test_the_chain_is_newest_first(self):
        first = record_custody(self.book, CustodyEvent.INTAKE, to_department=self.dept,
                               by=self.clerk)
        second = record_custody(self.book, CustodyEvent.UNIT_RECEIPT,
                                to_department=self.unit, by=self.clerk)
        self.assertEqual(list(custody_chain(self.book)), [second, first])

    def test_saving_the_pointer_does_not_disturb_other_fields(self):
        """``update_fields`` ضيّقٌ عمداً — كتابةُ الكتاب كاملاً هنا تدهس تعديلاً موازياً."""
        self.book.title = 'عنوانٌ عُدّل في نافذةٍ أخرى'
        Book.objects.filter(pk=self.book.pk).update(title='عنوانٌ عُدّل في نافذةٍ أخرى')
        record_custody(self.book, CustodyEvent.INTAKE, to_department=self.dept,
                       by=self.clerk)
        self.book.refresh_from_db()
        self.assertEqual(self.book.title, 'عنوانٌ عُدّل في نافذةٍ أخرى')


class DeskQueryTests(CustodyTestCase):
    """أعمدةُ الطاولة — و«لم يُستلم» أخطرُها: خرج من يدٍ ولم يدخل يداً."""

    def setUp(self):
        self.referral = distribute(self.book, [self.unit], by=self.clerk)

    def test_held_by_lists_what_a_unit_holds_now(self):
        record_custody(self.book, CustodyEvent.UNIT_RECEIPT, to_department=self.unit,
                       by=self.staff)
        self.assertEqual(list(held_by(self.unit)), [self.book])
        self.assertEqual(list(held_by(self.other)), [])

    def test_undelivered_lists_what_was_referred_but_never_signed(self):
        rows = list(undelivered(self.unit))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].book, self.book)

    def test_signing_clears_it_from_the_undelivered_queue(self):
        record_custody(self.book, CustodyEvent.UNIT_RECEIPT, to_department=self.unit,
                       by=self.staff)
        self.assertEqual(list(undelivered(self.unit)), [])

    def test_an_archive_signature_does_not_count_as_unit_receipt(self):
        """توقيعُ الأرشفة ليس توقيعَ استلام — والخلطُ يُفرغ الطابور كذباً."""
        record_custody(self.book, CustodyEvent.ARCHIVE_DONE, to_department=self.unit,
                       by=self.clerk)
        self.assertEqual(len(list(undelivered(self.unit))), 1)
