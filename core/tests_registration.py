"""
القيدُ في دفترِ قسم، وتسجيلُ الردّ.

«يدخل مرّةً بوارد مكتب المدير العامّ ثمّ مرّةً أخرى بوارد الأقسام المختصّة»،
و«ندخله برقم الكتاب الأصليّ… **ورقمِ واردٍ خاصٍّ بنا**» — تصحيحُ المالك الذي
كشف أنّ `Book.our_number` وحدَه لا يكفي: الورقةُ الواحدة لها أرقامُ واردٍ بعدد
الدفاتر التي مرّت بها.

وتسجيلُ الردّ يُغلق الدائرة: **جوابٌ يُربط ولا يُقفل التزامَه** يترك الكتابَ في
طابور المطاردة بعد أن أُجيب — وطابورٌ فيه ما أُنجز يفقد ثقةَ قارئه فيهمله.
"""

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from core.models import (Book, BookHistory, BookLink, BookReferral, BookRegistration,
                         BookSequence, Department, Entity, UserProfile)
from core.referral_service import distribute
from core.registration_service import (register_book_here, register_reply,
                                       registrations_of)


class RegistrationTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.gm = Department.objects.create(name='مكتب المدير العام', code='ق-م')
        cls.dept = Department.objects.create(name='المتابعة', code='ق-ش13')
        cls.contracts = Department.objects.create(name='العقود', code='ق-ش5')

        def member(name, dept):
            u = User.objects.create_user(name, password='pw-%s-11111' % name)
            UserProfile.objects.create(user=u, department=dept)
            return u

        cls.gm_clerk = member('qgm', cls.gm)
        cls.clerk = member('qclerk', cls.dept)
        cls.contracts_clerk = member('qcontracts', cls.contracts)

        # كتابُ الوزارة كما دخل أوّلاً في دفتر مكتب المدير العامّ
        cls.book = Book.objects.create(
            kind='incoming_external', title='كتابُ وزارة النفط', created_by=cls.gm_clerk,
            department=cls.gm, our_number='1180',
        )


class RegisterHereTests(RegistrationTestCase):

    def test_the_same_paper_carries_a_number_in_each_register(self):
        """جوهرُ التصحيح: رقمٌ لكلّ دفترٍ مرّ به الكتاب."""
        distribute(self.book, [self.dept], by=self.gm_clerk)
        mine = register_book_here(self.book, self.dept, by=self.gm_clerk)

        self.assertEqual(self.book.our_number, '1180')       # رقمُ الدفتر الأوّل لم يُمَسّ
        self.assertTrue(mine.number)                          # ولنا رقمُنا
        self.assertNotEqual(mine.number, '1180')

    def test_the_number_comes_from_the_department_counter(self):
        """لا رقمَ يُكتب بيدٍ هنا — `numbering.py` هو المصدرُ الوحيد."""
        expected = BookSequence.get_next('incoming_external', department=self.dept)['formatted']
        row = register_book_here(self.book, self.dept, by=self.gm_clerk)
        self.assertEqual(row.number, expected)

    def test_two_departments_get_independent_numbers(self):
        a = register_book_here(self.book, self.dept, by=self.gm_clerk)
        b = register_book_here(self.book, self.contracts, by=self.gm_clerk)
        self.assertEqual(a.number, b.number)     # عدّادان مستقلّان ⟵ الرقمُ نفسُه جائز
        self.assertNotEqual(a.department, b.department)

    def test_registering_twice_in_the_same_register_is_refused(self):
        register_book_here(self.book, self.dept, by=self.gm_clerk)
        with self.assertRaises(ValidationError):
            register_book_here(self.book, self.dept, by=self.gm_clerk)

    def test_a_numberless_registration_consumes_no_counter(self):
        """الاستثناءُ المدعوم: كتابٌ بلا رقمٍ رسميّ لا يفتح فجوةً في الدفتر."""
        before = BookSequence.get_next('incoming_external', department=self.dept)['number']
        row = register_book_here(self.book, self.dept, by=self.gm_clerk, numberless=True)
        after = BookSequence.get_next('incoming_external', department=self.dept)['number']
        self.assertEqual(row.number, '')
        self.assertEqual(before, after)

    def test_direction_is_from_the_registrar_point_of_view(self):
        """كتابٌ صادرٌ من قسمٍ آخر هو **واردٌ داخليّ** في دفتري."""
        outgoing = Book.objects.create(
            kind='outgoing_internal', title='مذكّرةُ العقود', created_by=self.contracts_clerk,
            department=self.contracts, our_number='355',
        )
        row = register_book_here(outgoing, self.contracts, by=self.contracts_clerk)
        self.assertEqual(row.direction, 'incoming_internal')

    def test_external_stays_external(self):
        row = register_book_here(self.book, self.dept, by=self.gm_clerk)
        self.assertEqual(row.direction, 'incoming_external')

    def test_it_leaves_a_trace(self):
        row = register_book_here(self.book, self.dept, by=self.gm_clerk)
        event = BookHistory.objects.get(book=self.book, action='registered')
        self.assertIn(row.number, event.notes)
        self.assertIn('المتابعة', event.notes)

    def test_a_stranger_cannot_register_it(self):
        with self.assertRaises(PermissionDenied):
            register_book_here(self.book, self.contracts, by=self.contracts_clerk)

    def test_a_referral_of_another_book_is_refused(self):
        other = Book.objects.create(
            kind='incoming_internal', title='آخر', created_by=self.gm_clerk,
            department=self.gm, our_number='1181',
        )
        alien = distribute(other, [self.dept], by=self.gm_clerk)[0]
        with self.assertRaises(ValidationError):
            register_book_here(self.book, self.dept, by=self.gm_clerk, via_referral=alien)

    def test_nothing_is_written_when_the_row_is_refused(self):
        """المعاملةُ تتراجع بالكامل — ولا يُستهلك عدّادٌ لقيدٍ لم يُنشأ."""
        register_book_here(self.book, self.dept, by=self.gm_clerk)
        before = BookSequence.get_next('incoming_external', department=self.dept)['number']
        with self.assertRaises(ValidationError):
            register_book_here(self.book, self.dept, by=self.gm_clerk)
        after = BookSequence.get_next('incoming_external', department=self.dept)['number']
        self.assertEqual(before, after)


class RegistrationVisibilityTests(RegistrationTestCase):

    def setUp(self):
        register_book_here(self.book, self.dept, by=self.gm_clerk)
        register_book_here(self.book, self.contracts, by=self.gm_clerk)

    def test_a_department_sees_only_its_own_register_entry(self):
        """قائمةُ الدفاتر التي مرّ بها الكتابُ خريطةُ توزيعٍ لا يملكها غيرُ الطرف."""
        rows = registrations_of(self.book, self.clerk)
        self.assertEqual([r.department for r in rows], [self.dept])

    def test_a_superuser_sees_them_all(self):
        root = User.objects.create_superuser('qroot', 'q@x.com', 'pw-qroot-111')
        self.assertEqual(len(registrations_of(self.book, root)), 2)


class RegisterReplyTests(RegistrationTestCase):
    """الدائرةُ تُغلق: الجوابُ يُربط **ويُقفل التزامَه**.

    **ومَن يُسجّله؟** المُجيبُ نفسُه — وهو الوحيد الذي يرى الطرفين: الأصلُ
    مُفرَّقٌ إليه (فيراه بالإحالة) والجوابُ كتابُه. وهذا ليس قيداً اخترعناه بل
    نتيجةُ حارس `add_link`، ويطابق الواقع: العقودُ تُصدر الجواب فتربطه.
    """

    def setUp(self):
        self.referral = distribute(self.book, [self.contracts], by=self.gm_clerk)[0]
        self.reply = Book.objects.create(
            kind='outgoing_internal', title='جوابُ العقود', created_by=self.contracts_clerk,
            department=self.contracts, our_number='356',
        )

    def test_creates_the_reply_edge(self):
        link, _ = register_reply(self.book, self.reply, by=self.contracts_clerk)
        self.assertEqual(link.relation, BookLink.REPLY)
        self.assertEqual(link.to_book, self.book)

    def test_closes_the_matching_open_commitment(self):
        _, closed = register_reply(self.book, self.reply, by=self.contracts_clerk)
        self.assertEqual(closed, self.referral)
        self.referral.refresh_from_db()
        self.assertEqual(self.referral.status, BookReferral.DONE)

    def test_the_closing_link_is_recorded_on_the_row(self):
        """«بمَ أُقفل هذا الالتزام؟» سؤالٌ يُسأل بعد سنة — والجوابُ مخزَّن."""
        link, _ = register_reply(self.book, self.reply, by=self.contracts_clerk)
        self.referral.refresh_from_db()
        self.assertEqual(self.referral.closed_by_link, link)

    def test_a_reply_closes_its_own_commitment_not_a_sibling_one(self):
        """كتابٌ مُفرَّقٌ إلى قسمين: جوابُ أحدهما لا يُبرّئ الآخر."""
        sibling = distribute(self.book, [self.dept], by=self.gm_clerk)[0]
        _, closed = register_reply(self.book, self.reply, by=self.contracts_clerk)
        self.assertEqual(closed, self.referral)
        sibling.refresh_from_db()
        self.assertEqual(sibling.status, BookReferral.SENT)

    def test_a_reply_with_no_matching_commitment_closes_nothing(self):
        """لا يُختلق إقفال: صفٌّ يُقفل بلا مطابقةٍ صحيحة يُخفي التزاماً قائماً."""
        own = Book.objects.create(
            kind='incoming_internal', title='كتابُ العقود نفسِه', created_by=self.contracts_clerk,
            department=self.contracts, our_number='991',
        )
        answer = Book.objects.create(
            kind='outgoing_internal', title='جوابُهم عليه', created_by=self.contracts_clerk,
            department=self.contracts, our_number='992',
        )
        _, closed = register_reply(own, answer, by=self.contracts_clerk)
        self.assertIsNone(closed)

    def test_the_oldest_open_commitment_closes_first(self):
        second = distribute(self.book, [self.contracts], by=self.gm_clerk,
                            allow_repeat=True)[0]
        _, closed = register_reply(self.book, self.reply, by=self.contracts_clerk)
        self.assertEqual(closed, self.referral)
        second.refresh_from_db()
        self.assertEqual(second.status, BookReferral.SENT)

    def test_a_closed_commitment_is_not_reclosed(self):
        register_reply(self.book, self.reply, by=self.contracts_clerk)
        another = Book.objects.create(
            kind='outgoing_internal', title='جوابٌ ثانٍ', created_by=self.contracts_clerk,
            department=self.contracts, our_number='357',
        )
        _, closed = register_reply(self.book, another, by=self.contracts_clerk)
        self.assertIsNone(closed)

    def test_both_traces_are_written(self):
        register_reply(self.book, self.reply, by=self.contracts_clerk)
        actions = set(BookHistory.objects.filter(book=self.book)
                      .values_list('action', flat=True))
        self.assertIn('link-added', actions)
        self.assertIn('referral-done', actions)
