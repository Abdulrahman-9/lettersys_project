"""
لوحةُ دورة الحياة في صفحة التفاصيل.

كلُّ ما بُني في البنود ②③④ كان **غيرَ مرئيّ**: جداولُ تمتلئ ولا شاشةَ تقرؤها.
وهذه اللوحةُ هي المكانُ الذي يرى فيه الكاتبُ ما بناه النظامُ له — «بعهدة مَن»
أوّلاً لأنّها الميزةُ الحاكمة، ثمّ مَن ردّ ومَن تأخّر.
"""

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from core.custody_service import record_custody
from core.linking_service import add_link
from core.models import (Book, BookLink, CustodyEvent, Department, Entity,
                         UserProfile)
from core.referral_service import distribute
from core.registration_service import register_book_here


class LifecyclePanelTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.dept = Department.objects.create(name='المتابعة', code='ل-ش13')
        cls.unit = Department.objects.create(
            name='شعبة الموازنة', code='ل-ش13/1', parent=cls.dept,
            entity=Entity.objects.create(name='شعبة الموازنة'),
        )
        cls.gm = Department.objects.create(name='مكتب المدير العام', code='ل-م')

        cls.clerk = User.objects.create_user('lpclerk', password='pw-lp-11111')
        UserProfile.objects.create(user=cls.clerk, department=cls.dept)

        cls.book = Book.objects.create(
            kind='incoming_external', title='تخصيصاتُ الحفر', created_by=cls.clerk,
            department=cls.dept, our_number='2433',
        )
        cls.bare = Book.objects.create(
            kind='incoming_external', title='كتابٌ منقولٌ من الورق',
            created_by=cls.clerk, department=cls.dept, our_number='825',
        )

    def setUp(self):
        self.client.force_login(self.clerk)

    def _page(self, book):
        resp = self.client.get('/books/%d/' % book.pk)
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode()


class PanelContentTests(LifecyclePanelTestCase):

    def test_it_shows_who_holds_the_book(self):
        record_custody(self.book, CustodyEvent.UNIT_RECEIPT, to_department=self.unit,
                       by=self.clerk, note='بموجب كشف التسليم 14')
        body = self._page(self.book)
        self.assertIn('بعهدة', body)
        self.assertIn('شعبة الموازنة', body)
        self.assertIn('بموجب كشف التسليم 14', body)

    def test_it_shows_the_referral_with_its_directive(self):
        distribute(self.book, [self.unit], by=self.clerk, margin='أعدّوا مذكّرة')
        body = self._page(self.book)
        self.assertIn('أعدّوا مذكّرة', body)

    def test_an_overdue_action_is_marked(self):
        distribute(self.book, [self.unit], by=self.clerk,
                   due_date=timezone.localdate() - timedelta(days=3))
        body = self._page(self.book)
        self.assertIn('متأخّر', body)

    def test_it_shows_the_registers_the_paper_passed_through(self):
        """رحلةُ الورقة كاملةً — ومَن يرى نصفَها لا يرى شيئاً."""
        row = register_book_here(self.book, self.gm, by=self.clerk)
        body = self._page(self.book)
        self.assertIn('مكتب المدير العام', body)
        self.assertIn(row.number, body)

    def test_a_link_label_reads_correctly_from_this_side(self):
        """«جواب على» على كتابٍ *أجابه* غيرُه تُقرأ عكسَ معناها."""
        other = Book.objects.create(
            kind='outgoing_internal', title='الجواب', created_by=self.clerk,
            department=self.dept, our_number='2455',
        )
        add_link(other, self.book, BookLink.REPLY, by=self.clerk)
        self.assertIn('أجابه', self._page(self.book))
        self.assertIn('جواب على', self._page(other))


class EmptyStateTests(LifecyclePanelTestCase):
    """11,183 كتاباً منقولاً من الورق: أربعُ حالاتٍ فارغةٍ عليها ضجيجٌ لا معلومة."""

    def test_a_book_with_no_movement_gets_one_honest_line(self):
        body = self._page(self.bare)
        self.assertIn('لا حركةَ تسييرٍ على هذا الكتاب', body)
        self.assertNotIn('لم يُفرَّق هذا الكتاب على أحد بعد', body)

    def test_the_panel_still_has_its_place(self):
        """لا تُخفى تماماً — كي يبقى مكانُها معروفاً حين يبدأ التسيير."""
        self.assertIn('lifecycleCard', self._page(self.bare))

    def test_one_movement_opens_the_full_panel(self):
        distribute(self.bare, [self.unit], by=self.clerk)
        body = self._page(self.bare)
        self.assertIn('دورة حياة الكتاب', body)
        self.assertNotIn('لا حركةَ تسييرٍ على هذا الكتاب', body)
