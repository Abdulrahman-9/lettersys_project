"""
عمودُ التسيير — التفريقُ والالتزامُ ومطاردتُه.

**شرطُ الكاتب لترك الدفتر** (§10 من الخطّة): «المهمّ الشفافيّة: لا يضيع مستندٌ
أبداً ولا تفاصيله». فهذه الاختباراتُ تسأل عن القنوات التي يضيع منها المستند:
صفٌّ يُكتب نصفَه · التزامٌ لا يراه صاحبُه · كتابٌ فُرِّق إلى وحدةٍ لا تراه ·
ودفترُ «إلى مَن وُزِّع» القائمُ يعمى عن التفريق الجديد.
"""

from datetime import timedelta

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone

from core.models import (Book, BookHistory, BookReferral, Department, Entity,
                         Notification, UserProfile)
from core.referral_service import (distribute, mark_done, mark_received,
                                   mark_returned, open_referrals_for, send_reminder)
from core.scoping import can_view_book, scope_books_for, scope_referrals_for


class ReferralTestCase(TestCase):
    """قسمُ المتابعة وفيه وحدتان، وقسمٌ آخر لا شأن له."""

    @classmethod
    def setUpTestData(cls):
        cls.dept = Department.objects.create(name='المتابعة', code='ر-ش13')
        cls.unit_budget = Department.objects.create(
            name='شعبة متابعة تنفيذ الموازنة', code='ر-ش13/1', parent=cls.dept,
            entity=Entity.objects.create(name='شعبة متابعة تنفيذ الموازنة'),
        )
        cls.unit_reports = Department.objects.create(
            name='وحدة التقارير', code='ر-ش13/2', parent=cls.dept,
            entity=Entity.objects.create(name='وحدة التقارير'),
        )
        cls.other = Department.objects.create(name='العقود', code='ر-ش5')
        cls.ministry = Entity.objects.create(name='وزارة النفط')

        def member(name, dept):
            u = User.objects.create_user(name, password='pw-%s-11111' % name)
            UserProfile.objects.create(user=u, department=dept)
            return u

        cls.clerk = member('rclerk', cls.dept)           # مختصُّ البريد
        cls.budget_staff = member('rbudget', cls.unit_budget)
        cls.reports_staff = member('rreports', cls.unit_reports)
        cls.outsider = member('rout', cls.other)

        cls.book = Book.objects.create(
            kind='incoming_external', title='تخصيصاتُ الحفر الاستكشافي',
            created_by=cls.clerk, department=cls.dept, our_number='2433',
        )


class DistributeTests(ReferralTestCase):

    def test_creates_a_row_per_target(self):
        rows = distribute(self.book, [self.unit_budget, self.unit_reports], by=self.clerk)
        self.assertEqual(len(rows), 2)
        self.assertEqual(self.book.referrals.count(), 2)

    def test_each_unit_may_carry_its_own_directive(self):
        """«أو إعدادِ مذكّراتٍ **حسب اختصاص كلّ وحدة**» — التوجيهُ لا يُوحَّد قسراً."""
        rows = distribute(self.book, [
            {'target': self.unit_budget, 'margin': 'أعدّوا مذكّرةً بالتخصيصات'},
            {'target': self.unit_reports, 'purpose': BookReferral.INFO, 'margin': 'للعلم'},
        ], by=self.clerk)
        by_target = {r.to_department_id: r for r in rows}
        self.assertEqual(by_target[self.unit_budget.pk].margin, 'أعدّوا مذكّرةً بالتخصيصات')
        self.assertEqual(by_target[self.unit_reports.pk].purpose, BookReferral.INFO)

    def test_writes_one_history_event_naming_the_targets(self):
        """حدثٌ واحدٌ لا حدثٌ لكلّ هدف: تعميمٌ على 42 وحدةً يُغرق الخطَّ الزمنيّ."""
        distribute(self.book, [self.unit_budget, self.unit_reports], by=self.clerk)
        events = BookHistory.objects.filter(book=self.book, action='referral')
        self.assertEqual(events.count(), 1)
        self.assertIn('شعبة متابعة تنفيذ الموازنة', events.first().notes)
        self.assertIn('وحدة التقارير', events.first().notes)

    def test_projects_onto_the_existing_distribution_column(self):
        """دفترُ «إلى مَن وُزِّع» يقرأ M2M منذ سنوات — والصفوفُ وحدَها تتركه أعمى."""
        distribute(self.book, [self.unit_budget], by=self.clerk)
        self.assertIn(self.unit_budget.entity,
                      list(self.book.receiving_entities.all()))

    def test_does_not_touch_the_addressee_of_an_outgoing_book(self):
        """في الصادر ``receiving_entities`` مُخاطَبُه الحقيقيّ — الكتابةُ فيه تُفسد وجهتَه."""
        outgoing = Book.objects.create(
            kind='outgoing_external', title='إلى الوزارة', created_by=self.clerk,
            department=self.dept, our_number='7/551',
        )
        outgoing.receiving_entities.add(self.ministry)
        distribute(outgoing, [self.unit_budget], by=self.clerk)
        self.assertEqual([e.name for e in outgoing.receiving_entities.all()],
                         ['وزارة النفط'])

    def test_may_target_an_external_entity(self):
        """«أتابع حالة بريدي عندهم» — المطاردةُ تتجاوز أسوار الشركة."""
        row = distribute(self.book, [self.ministry], by=self.clerk)[0]
        self.assertEqual(row.to_entity, self.ministry)
        self.assertIsNone(row.to_department_id)
        self.assertEqual(row.target_name, 'وزارة النفط')

    def test_refuses_a_repeat_over_an_open_commitment(self):
        distribute(self.book, [self.unit_budget], by=self.clerk)
        with self.assertRaises(ValidationError):
            distribute(self.book, [self.unit_budget], by=self.clerk)

    def test_allows_a_repeat_after_the_commitment_closed(self):
        """الكتابُ يعود ويُفرَّق ثانيةً — واقعةٌ يوميّة لا خطأ."""
        row = distribute(self.book, [self.unit_budget], by=self.clerk)[0]
        mark_done(row, by=self.budget_staff)
        distribute(self.book, [self.unit_budget], by=self.clerk)
        self.assertEqual(self.book.referrals.count(), 2)

    def test_nothing_is_written_when_one_target_is_invalid(self):
        """تفريقٌ نصفُه ناجحٌ أسوأُ من تفريقٍ مرفوض."""
        with self.assertRaises(ValidationError):
            distribute(self.book, [self.unit_budget, self.clerk], by=self.clerk)
        self.assertEqual(self.book.referrals.count(), 0)
        self.assertEqual(BookHistory.objects.filter(action='referral').count(), 0)

    def test_a_stranger_cannot_distribute(self):
        with self.assertRaises(PermissionDenied):
            distribute(self.book, [self.unit_budget], by=self.outsider)

    def test_empty_targets_are_refused(self):
        with self.assertRaises(ValidationError):
            distribute(self.book, [], by=self.clerk)


class NotificationTests(ReferralTestCase):
    """«حسابُ الوحدة يجمع التنبيهات لكلّ موظّفيه بشفافيّة» — أمرُ المالك."""

    def test_every_member_of_the_unit_is_notified(self):
        colleague = User.objects.create_user('rbudget2', password='pw-b2-11111')
        UserProfile.objects.create(user=colleague, department=self.unit_budget)

        distribute(self.book, [self.unit_budget], by=self.clerk)
        notified = set(Notification.objects.values_list('user_id', flat=True))
        self.assertEqual(notified, {self.budget_staff.pk, colleague.pk})

    def test_the_distributor_is_not_notified_of_their_own_act(self):
        distribute(self.book, [self.unit_budget], by=self.clerk)
        self.assertFalse(Notification.objects.filter(user=self.clerk).exists())

    def test_an_external_target_notifies_no_one(self):
        distribute(self.book, [self.ministry], by=self.clerk)
        self.assertEqual(Notification.objects.count(), 0)

    def test_the_notification_links_to_the_book(self):
        distribute(self.book, [self.unit_budget], by=self.clerk)
        notice = Notification.objects.get(user=self.budget_staff)
        self.assertEqual(notice.link_url, '/books/%d/' % self.book.pk)
        self.assertIn('2433', notice.title)


class LifecycleTests(ReferralTestCase):

    def setUp(self):
        self.row = distribute(self.book, [self.unit_budget], by=self.clerk)[0]

    def test_received_then_done(self):
        mark_received(self.row, by=self.budget_staff)
        self.assertEqual(self.row.status, BookReferral.RECEIVED)
        mark_done(self.row, by=self.budget_staff)
        self.assertEqual(self.row.status, BookReferral.DONE)
        self.assertFalse(self.row.is_open)

    def test_each_step_leaves_a_dated_trace(self):
        mark_received(self.row, by=self.budget_staff)
        mark_done(self.row, by=self.budget_staff, note='رُفعت المذكّرة')
        actions = list(BookHistory.objects.filter(book=self.book)
                       .values_list('action', flat=True))
        self.assertIn('referral-received', actions)
        self.assertIn('referral-done', actions)

    def test_returning_closes_it_too(self):
        mark_returned(self.row, by=self.budget_staff, note='ليس من اختصاصنا')
        self.assertEqual(self.row.status, BookReferral.RETURNED)
        self.assertFalse(self.row.is_open)

    def test_repeating_a_step_is_a_no_op_not_a_second_trace(self):
        mark_received(self.row, by=self.budget_staff)
        mark_received(self.row, by=self.budget_staff)
        self.assertEqual(
            BookHistory.objects.filter(book=self.book, action='referral-received').count(), 1)

    def test_a_stranger_cannot_advance_it(self):
        with self.assertRaises(PermissionDenied):
            mark_done(self.row, by=self.outsider)

    def test_a_sibling_unit_cannot_close_someone_else_commitment(self):
        """وحدةُ التقارير ليست طرفاً في هذه الإحالة ولا ترى كتابَ القسم الأمّ.

        (كتبتُ هذا الاختبارَ أوّلاً على افتراضٍ مقلوب — أنّ الشعبةَ ترث رؤيةَ
        قسمها — فأخفق. **الشجرةُ تسيل نزولاً لا صعوداً**، وما يخصّ الشعبةَ
        يصلها بالتفريق لا بالنطاق.)
        """
        with self.assertRaises(PermissionDenied):
            mark_done(self.row, by=self.reports_staff)


class OverdueTests(ReferralTestCase):

    def test_action_past_its_date_is_overdue(self):
        row = distribute(self.book, [self.unit_budget], by=self.clerk,
                         due_date=timezone.localdate() - timedelta(days=1))[0]
        self.assertTrue(row.is_overdue)

    def test_info_is_never_chased(self):
        """«للعلم» لا يُطارَد — وإلّا امتلأ الطابورُ بما لا إجابةَ له."""
        row = distribute(self.book, [self.unit_budget], by=self.clerk,
                         purpose=BookReferral.INFO,
                         due_date=timezone.localdate() - timedelta(days=1))[0]
        self.assertFalse(row.is_overdue)

    def test_a_closed_commitment_is_not_overdue(self):
        row = distribute(self.book, [self.unit_budget], by=self.clerk,
                         due_date=timezone.localdate() - timedelta(days=5))[0]
        mark_done(row, by=self.budget_staff)
        self.assertFalse(row.is_overdue)


class ReminderTests(ReferralTestCase):

    def setUp(self):
        self.row = distribute(self.book, [self.unit_budget], by=self.clerk)[0]

    def test_stamps_and_notifies_urgently(self):
        send_reminder(self.row, by=self.clerk)
        self.assertIsNotNone(self.row.last_reminder_at)
        urgent = Notification.objects.filter(user=self.budget_staff,
                                             priority=Notification.PRIORITY_URGENT)
        self.assertEqual(urgent.count(), 1)
        self.assertIn('تنبيه', urgent.first().title)

    def test_a_closed_commitment_cannot_be_nagged(self):
        mark_done(self.row, by=self.budget_staff)
        with self.assertRaises(ValidationError):
            send_reminder(self.row, by=self.clerk)


class ReferralScopeTests(ReferralTestCase):
    """الحضورُ والغيابُ معاً — **الاختبارُ السلبيّ وحده لا يحرس** (درسُ البند ①)."""

    def setUp(self):
        self.row = distribute(self.book, [self.unit_budget], by=self.clerk)[0]

    def test_the_receiving_unit_sees_the_referred_book(self):
        """الحضور: بلا هذا الشقّ تُكتب الصفوفُ ولا يراها أحد."""
        titles = [b.title for b in scope_books_for(self.budget_staff, Book.objects.all())]
        self.assertIn('تخصيصاتُ الحفر الاستكشافي', titles)

    def test_the_row_predicate_agrees_with_the_queryset(self):
        """توأمان لا ينفرجان: القائمةُ تُظهره ⟵ فتحُه لا يُرفض."""
        self.assertTrue(can_view_book(self.book, self.budget_staff))

    def test_another_department_still_sees_nothing(self):
        self.assertEqual(list(scope_books_for(self.outsider, Book.objects.all())), [])
        self.assertFalse(can_view_book(self.book, self.outsider))

    def test_a_closed_referral_still_keeps_the_book_visible(self):
        """الوحدةُ التي أنجزت كتاباً قبل شهرٍ يجب أن تجده حين تُسأل عنه."""
        mark_done(self.row, by=self.budget_staff)
        self.assertTrue(can_view_book(self.book, self.budget_staff))

    def test_the_book_is_not_duplicated_by_many_referrals(self):
        """استعلامٌ فرعيّ لا وصلة — الوصلةُ تُكرّر الصفَّ بعدد إحالاته."""
        distribute(self.book, [self.unit_reports], by=self.clerk)
        self.assertEqual(scope_books_for(self.clerk, Book.objects.all()).count(), 1)

    def test_referral_rows_are_scoped_to_their_three_parties(self):
        self.assertEqual(scope_referrals_for(self.budget_staff).count(), 1)
        self.assertEqual(scope_referrals_for(self.clerk).count(), 1)
        self.assertEqual(scope_referrals_for(self.outsider).count(), 0)

    def test_a_sibling_unit_does_not_see_the_row(self):
        """التزامُ شعبةٍ لا يظهر لشعبةٍ أختٍ — ولا كتابُه."""
        self.assertEqual(scope_referrals_for(self.reports_staff).count(), 0)
        self.assertFalse(can_view_book(self.book, self.reports_staff))

    def test_the_department_sees_its_units_registers(self):
        """**الشجرةُ نزولاً:** رئيسُ القسم ومختصُّ بريده يريان دفاترَ الشُّعب.

        بلا هذا يكون القسمُ أعمى عن عمله: كتابٌ تُنشئه الشعبةُ لا يراه القسم
        الذي يوقّع عنه ويجيب عنه أمام الشركة.
        """
        unit_book = Book.objects.create(
            kind='outgoing_internal', title='مذكّرةُ الشعبة', created_by=self.budget_staff,
            department=self.unit_budget, our_number='2440',
        )
        self.assertTrue(can_view_book(unit_book, self.clerk))
        self.assertIn(unit_book, list(scope_books_for(self.clerk, Book.objects.all())))
        # ولا تسيل صعوداً: الشعبةُ لا ترى دفترَ الأمّ
        self.assertFalse(can_view_book(self.book, self.reports_staff))


class QueueTests(ReferralTestCase):

    def test_open_referrals_for_a_unit(self):
        open_row = distribute(self.book, [self.unit_budget], by=self.clerk)[0]
        second = Book.objects.create(
            kind='incoming_internal', title='كتابٌ ثانٍ', created_by=self.clerk,
            department=self.dept, our_number='2434',
        )
        closed = distribute(second, [self.unit_budget], by=self.clerk)[0]
        mark_done(closed, by=self.budget_staff)

        queue = list(open_referrals_for(self.unit_budget))
        self.assertEqual(queue, [open_row])
