"""
التعميمُ والعناقيدُ ومصفوفةُ الردود.

طلبُ المالك: «لو كنتُ أستطيع أن أحدّد عنقوداً من الجهات بمسمّىً واحد… ومباشرةً
يذهب إلى كلّ الأقسام بهذا الاسم دفعةً واحدة بعد ضغط حفظ وإرسال»، ثمّ «يحتاج
ردَّ كلّ قسم… تتجمّع الردود أسفل الكتاب عند صاحبه».

**وأخطرُ فخٍّ يحرسه هذا الملفّ:** عضويّةٌ ثابتةٌ باسم «جميع الهيئات والأقسام»
تتيبّس عند دخول القسم الثالث والأربعين — فيُعمَّم على 42 ويظنّ المُعمِّم أنّه
عمّم على الجميع.
"""

from datetime import timedelta

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from core.models import (Book, BookHistory, BookReferral, Department, Entity,
                         EntityGroup, UserProfile)
from core.referral_service import (mark_done, reply_matrix, send_circular,
                                   send_reminder)
from core.registration_service import register_reply


class CircularTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.dept = Department.objects.create(name='المتابعة', code='ن-ش13')
        cls.contracts = Department.objects.create(
            name='العقود', code='ن-ش5',
            entity=Entity.objects.create(name='قسم العقود'),
        )
        cls.hr = Department.objects.create(
            name='الموارد البشرية', code='ن-د',
            entity=Entity.objects.create(name='قسم الموارد البشرية'),
        )
        cls.ministry = Entity.objects.create(name='وزارة النفط')   # خارجيّةٌ بلا قسم

        def member(name, dept):
            u = User.objects.create_user(name, password='pw-%s-11111' % name)
            UserProfile.objects.create(user=u, department=dept)
            return u

        cls.clerk = member('nclerk', cls.dept)
        cls.contracts_clerk = member('ncontracts', cls.contracts)
        cls.hr_clerk = member('nhr', cls.hr)

        cls.book = Book.objects.create(
            kind='outgoing_internal', title='تعميمٌ بشأن الدوام الرسميّ',
            created_by=cls.clerk, department=cls.dept, our_number='2433',
        )


class GroupMembershipTests(CircularTestCase):

    def test_a_static_group_resolves_to_its_members(self):
        group = EntityGroup.objects.create(name='قسما العقود والموارد')
        group.members.add(self.contracts.entity, self.hr.entity)
        self.assertEqual(group.resolved_members().count(), 2)

    def test_the_dynamic_rule_never_calcifies(self):
        """الفخُّ المضمونُ الوقوع: قسمٌ جديدٌ يدخل بعد بناء العنقود."""
        group = EntityGroup.objects.create(
            name='جميع الهيئات والأقسام',
            auto_rule=EntityGroup.ALL_REGISTRY_DEPARTMENTS,
        )
        before = group.resolved_members().count()

        Department.objects.create(name='قسمٌ ثالثٌ وأربعون', code='ن-ش43',
                                  entity=Entity.objects.create(name='القسم 43'))
        self.assertEqual(group.resolved_members().count(), before + 1)

    def test_an_inactive_department_leaves_the_dynamic_group(self):
        group = EntityGroup.objects.create(
            name='النشطة', auto_rule=EntityGroup.ALL_REGISTRY_DEPARTMENTS)
        before = group.resolved_members().count()
        Department.objects.filter(pk=self.hr.pk).update(is_active=False)
        self.assertEqual(group.resolved_members().count(), before - 1)

    def test_an_entity_without_a_department_is_not_in_the_dynamic_group(self):
        group = EntityGroup.objects.create(
            name='الأقسام', auto_rule=EntityGroup.ALL_REGISTRY_DEPARTMENTS)
        self.assertNotIn(self.ministry, list(group.resolved_members()))


class SendCircularTests(CircularTestCase):

    def setUp(self):
        self.group = EntityGroup.objects.create(name='قسما العقود والموارد')
        self.group.members.add(self.contracts.entity, self.hr.entity)

    def test_one_press_creates_a_commitment_per_member(self):
        rows = send_circular(self.book, self.group, by=self.clerk)
        self.assertEqual(len(rows), 2)
        self.assertEqual(self.book.referrals.count(), 2)

    def test_a_member_with_a_twin_department_targets_the_department(self):
        """الجسرُ بين الطبقتين — وبلا هذا لا يصل التعميمُ طاولةَ وارد الوحدة."""
        rows = send_circular(self.book, self.group, by=self.clerk)
        self.assertTrue(all(r.to_department_id for r in rows))
        self.assertIsNone(rows[0].to_entity_id)

    def test_an_external_member_stays_an_entity(self):
        group = EntityGroup.objects.create(name='وزاراتٌ')
        group.members.add(self.ministry)
        row = send_circular(self.book, group, by=self.clerk)[0]
        self.assertEqual(row.to_entity, self.ministry)
        self.assertIsNone(row.to_department_id)

    def test_the_book_keeps_one_number_and_records_the_group(self):
        """رقمُ صادرٍ **واحد** — هذا هو الورقُ نفسه؛ ورقمٌ لكلّ عضوٍ يفجّر الدفتر."""
        send_circular(self.book, self.group, by=self.clerk)
        self.book.refresh_from_db()
        self.assertEqual(self.book.our_number, '2433')
        self.assertEqual(self.book.sent_to_group, self.group)

    def test_it_leaves_one_trace_naming_the_group(self):
        send_circular(self.book, self.group, by=self.clerk)
        event = BookHistory.objects.get(book=self.book, action='circular')
        self.assertIn('قسما العقود والموارد', event.notes)
        self.assertIn('2', event.notes)

    def test_a_member_may_carry_its_own_directive(self):
        """«أحياناً إلى قسمين أو ثلاثة» — بتوجيهاتٍ مختلفة."""
        rows = send_circular(self.book, self.group, by=self.clerk, margin='للتنفيذ',
                             member_overrides={self.hr.entity.pk: {
                                 'purpose': BookReferral.INFO, 'margin': 'للعلم'}})
        by_dept = {r.to_department_id: r for r in rows}
        self.assertEqual(by_dept[self.contracts.pk].margin, 'للتنفيذ')
        self.assertEqual(by_dept[self.hr.pk].purpose, BookReferral.INFO)

    def test_an_empty_group_is_refused(self):
        empty = EntityGroup.objects.create(name='عنقودٌ فارغ')
        with self.assertRaises(ValidationError):
            send_circular(self.book, empty, by=self.clerk)

    def test_membership_changes_do_not_touch_a_past_circular(self):
        """**صفوفُ الإحالة هي لقطةُ العضويّة** — بلا جدولِ لقطاتٍ إضافيّ."""
        send_circular(self.book, self.group, by=self.clerk)
        self.group.members.remove(self.hr.entity)
        self.assertEqual(self.book.referrals.count(), 2)

    def test_recirculating_is_allowed(self):
        """تعميمٌ ثانٍ على العنقود نفسِه واقعةٌ تحدث — تذكيرٌ رسميٌّ بكتابٍ سابق."""
        send_circular(self.book, self.group, by=self.clerk)
        send_circular(self.book, self.group, by=self.clerk)
        self.assertEqual(self.book.referrals.count(), 4)


class ReplyMatrixTests(CircularTestCase):
    """«تتجمّع الردودُ أسفل الكتاب عند صاحبه وتُميَّز» — طلبُ المالك."""

    def setUp(self):
        self.group = EntityGroup.objects.create(name='قسما العقود والموارد')
        self.group.members.add(self.contracts.entity, self.hr.entity)
        self.rows = send_circular(self.book, self.group, by=self.clerk,
                                  due_date=timezone.localdate() - timedelta(days=2))

    def test_it_lists_every_target(self):
        matrix = reply_matrix(self.book, self.clerk)
        self.assertEqual({row['target'] for row in matrix}, {'العقود', 'الموارد البشرية'})

    def test_an_open_action_past_its_date_is_flagged_overdue(self):
        matrix = reply_matrix(self.book, self.clerk)
        self.assertTrue(all(row['is_overdue'] for row in matrix))

    def test_info_is_never_flagged_overdue(self):
        """المطاردةُ على «للتنفيذ» فقط — وإلّا امتلأ الطابورُ بما لا إجابةَ له."""
        book = Book.objects.create(
            kind='outgoing_internal', title='تعميمٌ للعلم', created_by=self.clerk,
            department=self.dept, our_number='2434',
        )
        send_circular(book, self.group, by=self.clerk, purpose=BookReferral.INFO,
                      due_date=timezone.localdate() - timedelta(days=9))
        self.assertFalse(any(row['is_overdue'] for row in reply_matrix(book, self.clerk)))

    def test_a_registered_reply_shows_in_the_matrix(self):
        reply = Book.objects.create(
            kind='outgoing_internal', title='جوابُ العقود', created_by=self.contracts_clerk,
            department=self.contracts, our_number='355',
        )
        register_reply(self.book, reply, by=self.contracts_clerk)

        matrix = {row['target']: row for row in reply_matrix(self.book, self.clerk)}
        self.assertEqual(matrix['العقود']['reply_id'], reply.pk)
        self.assertFalse(matrix['العقود']['is_open'])
        self.assertTrue(matrix['الموارد البشرية']['is_open'])

    def test_a_reminder_stamp_is_visible(self):
        row = next(r for r in self.rows if r.to_department_id == self.hr.pk)
        send_reminder(row, by=self.clerk)
        matrix = {r['target']: r for r in reply_matrix(self.book, self.clerk)}
        self.assertIsNotNone(matrix['الموارد البشرية']['reminded_at'])

    def test_a_member_sees_only_its_own_line(self):
        """المصفوفةُ لصاحب الكتاب — والعضوُ لا يرى أداءَ زملائه."""
        matrix = reply_matrix(self.book, self.hr_clerk)
        self.assertEqual([row['target'] for row in matrix], ['الموارد البشرية'])

    def test_a_done_row_leaves_the_chase(self):
        row = next(r for r in self.rows if r.to_department_id == self.contracts.pk)
        mark_done(row, by=self.contracts_clerk)
        matrix = {r['target']: r for r in reply_matrix(self.book, self.clerk)}
        self.assertFalse(matrix['العقود']['is_overdue'])
