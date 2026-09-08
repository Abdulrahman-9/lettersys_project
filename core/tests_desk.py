"""
طاولةُ البريد — الورقتان المطبوعتان.

**والورقةُ أخطرُ من الشاشة لا أقلّ**: تخرج من الجهاز وتُترك على طاولة. فأشدُّ
ما تحرسه هذه الاختبارات أن يمرّ الكشفُ والدفترُ **بالبوّابتين نفسَيهما**
(النطاق + السرّيّة) لا بأقلَّ منهما.
"""

from django.contrib.auth.models import Group, User
from django.test import TestCase

from core.custody_service import record_custody
from core.models import (Book, CustodyEvent, Department, Entity, UserProfile)
from core.referral_service import distribute
from core.registration_service import register_book_here
from core.roles import CONTROLLER_GROUP_NAME


class DeskTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.dept = Department.objects.create(name='المتابعة', code='ط-ش13')
        cls.unit = Department.objects.create(
            name='شعبة الموازنة', code='ط-ش13/1', parent=cls.dept,
            entity=Entity.objects.create(name='شعبة الموازنة'),
        )
        cls.other = Department.objects.create(name='العقود', code='ط-ش5')

        def member(name, dept, *, head=False, controller=False):
            u = User.objects.create_user(name, password='pw-%s-11111' % name)
            UserProfile.objects.create(user=u, department=dept, is_department_head=head)
            if controller:
                group, _ = Group.objects.get_or_create(name=CONTROLLER_GROUP_NAME)
                u.groups.add(group)
            return u

        cls.officer = member('tofficer', cls.dept, controller=True)
        cls.head = member('thead', cls.dept, head=True)
        cls.plain = member('tplain', cls.dept)
        cls.outsider = member('tout', cls.other)

        cls.book = Book.objects.create(
            kind='incoming_external', title='تخصيصاتُ الحفر', created_by=cls.officer,
            department=cls.dept, our_number='2433',
        )
        cls.secret = Book.objects.create(
            kind='incoming_internal', title='مناقصةٌ سرّيّة', created_by=cls.officer,
            department=cls.dept, our_number='2437', secret_level='secret',
        )


class DeskAccessTests(DeskTestCase):
    """بوّابةُ سطحٍ يخرج من الجهاز — لا بوّابةُ سرّيّة."""

    def test_the_mail_officer_may_open_it(self):
        self.client.force_login(self.officer)
        self.assertEqual(self.client.get('/books/desk/ledger/').status_code, 200)

    def test_the_department_head_may_open_it(self):
        self.client.force_login(self.head)
        self.assertEqual(self.client.get('/books/desk/handover/').status_code, 200)

    def test_a_plain_member_may_not(self):
        self.client.force_login(self.plain)
        self.assertEqual(self.client.get('/books/desk/ledger/').status_code, 403)

    def test_anonymous_is_sent_to_login(self):
        resp = self.client.get('/books/desk/ledger/')
        self.assertIn(resp.status_code, (302, 301))


class HandoverSheetTests(DeskTestCase):

    def setUp(self):
        self.client.force_login(self.officer)
        distribute(self.book, [self.unit], by=self.officer, margin='للمداولة')

    def test_the_unit_appears_with_its_pending_count(self):
        body = self.client.get('/books/desk/handover/').content.decode()
        self.assertIn('شعبة الموازنة', body)

    def test_the_sheet_lists_the_unsigned_book(self):
        body = self.client.get('/books/desk/handover/', {'to': self.unit.pk}).content.decode()
        self.assertIn('تخصيصاتُ الحفر', body)
        self.assertIn('2433', body)
        self.assertIn('للمداولة', body)

    def test_a_signed_book_leaves_the_sheet(self):
        """جوهرُ الكشف: ما وُقّع عليه لا يُطلب توقيعُه ثانية."""
        record_custody(self.book, CustodyEvent.UNIT_RECEIPT, to_department=self.unit,
                       by=self.officer)
        body = self.client.get('/books/desk/handover/', {'to': self.unit.pk}).content.decode()
        self.assertNotIn('تخصيصاتُ الحفر', body)

    def test_it_carries_a_signature_column(self):
        body = self.client.get('/books/desk/handover/', {'to': self.unit.pk}).content.decode()
        self.assertIn('توقيع المستلم', body)
        self.assertIn('sign-cell', body)

    def test_an_unknown_unit_shows_nothing(self):
        body = self.client.get('/books/desk/handover/', {'to': 99999}).content.decode()
        self.assertNotIn('تخصيصاتُ الحفر', body)

    def test_a_secret_book_is_listed_without_its_subject(self):
        """الكشفُ يخرج من الجهاز — فالحجبُ فيه أوجبُ منه على الشاشة."""
        distribute(self.secret, [self.unit], by=self.officer)
        self.client.force_login(self.head)   # رئيسُ القسم يرى السرّيّ
        body = self.client.get('/books/desk/handover/', {'to': self.unit.pk}).content.decode()
        self.assertIn('مناقصةٌ سرّيّة', body)

        # ومن لا يملك محتواه لا يراه في الورقة — ولو كان مخوَّلاً بالطاولة
        Book.objects.filter(pk=self.secret.pk).update(department=self.other)
        body = self.client.get('/books/desk/handover/', {'to': self.unit.pk}).content.decode()
        self.assertNotIn('مناقصةٌ سرّيّة', body)


class LedgerTests(DeskTestCase):

    def setUp(self):
        self.client.force_login(self.officer)

    def test_it_lists_books_we_own(self):
        body = self.client.get('/books/desk/ledger/').content.decode()
        self.assertIn('تخصيصاتُ الحفر', body)
        self.assertIn('2433', body)

    def test_it_lists_books_registered_here_with_our_number(self):
        """الرقمُ رقمُ **دفترنا** لا رقمُ صاحبه — جوهرُ القيود المتعدّدة."""
        foreign = Book.objects.create(
            kind='incoming_internal', title='كتابُ العقود', created_by=self.outsider,
            department=self.other, our_number='991',
        )
        distribute(foreign, [self.dept], by=self.outsider)
        row = register_book_here(foreign, self.dept, by=self.officer)

        body = self.client.get('/books/desk/ledger/').content.decode()
        self.assertIn('كتابُ العقود', body)
        self.assertIn(row.number, body)

    def test_it_carries_the_clerk_five_columns(self):
        for column in ('الرقم', 'التاريخ', 'الموضوع', 'إلى مَن وُزِّع', 'مَن استلم'):
            with self.subTest(column=column):
                body = self.client.get('/books/desk/ledger/').content.decode()
                self.assertIn(column, body)

    def test_distribution_and_receipt_show_in_their_columns(self):
        distribute(self.book, [self.unit], by=self.officer)
        record_custody(self.book, CustodyEvent.UNIT_RECEIPT, to_department=self.unit,
                       by=self.officer)
        body = self.client.get('/books/desk/ledger/').content.decode()
        self.assertIn('شعبة الموازنة', body)

    def test_another_department_book_never_appears(self):
        Book.objects.create(
            kind='incoming_internal', title='لا شأنَ لنا به', created_by=self.outsider,
            department=self.other, our_number='992',
        )
        body = self.client.get('/books/desk/ledger/').content.decode()
        self.assertNotIn('لا شأنَ لنا به', body)

    def test_the_date_range_narrows_it(self):
        body = self.client.get('/books/desk/ledger/',
                               {'date_from': '1990-01-01', 'date_to': '1990-12-31'}).content.decode()
        self.assertNotIn('تخصيصاتُ الحفر', body)

    def test_a_broken_date_is_ignored_not_fatal(self):
        resp = self.client.get('/books/desk/ledger/', {'date_from': 'ليس تاريخاً'})
        self.assertEqual(resp.status_code, 200)
