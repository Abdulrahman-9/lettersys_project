"""
سجلُّ الحركات — «مَن رأى، مَن شاهد، مَن استلم، مَن فرّق، مَن عدّل، مَن حذف».

اختباراتٌ عدائيّة على أربع جبهات: **الطيّ** (وإلّا صارت القراءةُ ربعَ مليون
صفّ) · **ما لا يُطوى** (طيُّ «حمّله خمس مرّات» إتلافُ دليل) · **النطاق**
(السجلُّ أداةُ مراقبةِ أشخاص فبوّابتُه أضيقُ من كلّ ما سبق) · **ألّا يصير
السجلُّ نفسُه بابَ تسريبٍ للعناوين** — درسُ تصدير CSV حرفيّاً.
"""

from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from core.audit_service import client_ip, readers_of
from core.logging_models import UserActivityLog
from core.models import Attachment, Book, Department, UserProfile
from core.roles import CONTROLLER_GROUP_NAME
from core.scoping import can_view_audit, scope_activity_for


class AuditTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.dept = Department.objects.create(name='المتابعة', code='س-ش13')
        cls.unit = Department.objects.create(name='شعبة الموازنة', code='س-ش13/1',
                                             parent=cls.dept)
        cls.other = Department.objects.create(name='العقود', code='س-ش5')

        def member(name, dept, *, head=False, controller=False):
            u = User.objects.create_user(name, password='pw-%s-11111' % name)
            UserProfile.objects.create(user=u, department=dept, is_department_head=head)
            if controller:
                u.groups.add(Group.objects.get_or_create(name=CONTROLLER_GROUP_NAME)[0])
            return u

        cls.head = member('sahead', cls.dept, head=True)
        cls.officer = member('saofficer', cls.dept, controller=True)
        cls.clerk = member('saclerk', cls.dept)
        cls.unit_staff = member('saunit', cls.unit)
        cls.outsider = member('saout', cls.other)
        cls.root = User.objects.create_superuser('saroot', 'sa@x.com', 'pw-saroot-11')

        cls.book = Book.objects.create(
            kind='incoming_external', title='تخصيصاتُ الحفر', created_by=cls.clerk,
            department=cls.dept, our_number='2433',
        )
        cls.secret = Book.objects.create(
            kind='incoming_internal', title='مناقصةٌ سرّيّة', created_by=cls.head,
            department=cls.dept, our_number='2437', secret_level='secret',
        )
        cls.foreign = Book.objects.create(
            kind='incoming_internal', title='كتابُ العقود', created_by=cls.outsider,
            department=cls.other, our_number='991',
        )


class FoldingTests(AuditTestCase):
    """قراءةٌ خامّةٌ لكلّ فتحةٍ تُنتج ربعَ مليون صفٍّ سنويّاً بلا جوابٍ أفضل."""

    def setUp(self):
        self.client.force_login(self.clerk)

    def test_opening_a_book_is_recorded(self):
        """**الحضور** — والاختبارُ السلبيّ وحده لا يحرس."""
        self.client.get('/books/%d/' % self.book.pk)
        self.assertEqual(
            UserActivityLog.objects.filter(user=self.clerk, book=self.book,
                                           action=UserActivityLog.VIEW_BOOK).count(), 1)

    def test_opening_it_again_the_same_day_folds_into_one_row(self):
        for _ in range(4):
            self.client.get('/books/%d/' % self.book.pk)
        rows = UserActivityLog.objects.filter(user=self.clerk, book=self.book,
                                              action=UserActivityLog.VIEW_BOOK)
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().count, 4)

    def test_the_row_carries_the_last_time_seen(self):
        self.client.get('/books/%d/' % self.book.pk)
        row = UserActivityLog.objects.get(book=self.book, action=UserActivityLog.VIEW_BOOK)
        self.assertIsNotNone(row.last_seen_at)

    def test_another_day_is_another_row(self):
        self.client.get('/books/%d/' % self.book.pk)
        UserActivityLog.objects.update(day=timezone.localdate().replace(year=2020))
        self.client.get('/books/%d/' % self.book.pk)
        self.assertEqual(UserActivityLog.objects.filter(
            action=UserActivityLog.VIEW_BOOK).count(), 2)

    def test_two_readers_are_two_rows(self):
        self.client.get('/books/%d/' % self.book.pk)
        self.client.force_login(self.head)
        self.client.get('/books/%d/' % self.book.pk)
        self.assertEqual(UserActivityLog.objects.filter(
            action=UserActivityLog.VIEW_BOOK).count(), 2)

    def test_the_department_snapshot_is_stored(self):
        """لقطةُ القسم وقتَ الحدث — المستخدم ينتقل، والسجلُّ لا يتبعه."""
        self.client.get('/books/%d/' % self.book.pk)
        row = UserActivityLog.objects.get(action=UserActivityLog.VIEW_BOOK)
        self.assertEqual(row.department, self.dept)

    def test_readers_of_answers_who_saw_it(self):
        self.client.get('/books/%d/' % self.book.pk)
        self.client.get('/books/%d/' % self.book.pk)
        readers = list(readers_of(self.book))
        self.assertEqual(len(readers), 1)
        self.assertEqual(readers[0]['times'], 2)


class NotFoldedTests(AuditTestCase):
    """ما يخرج من الجهاز: **طيُّ «حمّله خمس مرّات» إتلافُ دليل**."""

    def setUp(self):
        self.client.force_login(self.clerk)

    def test_each_export_is_its_own_row(self):
        for _ in range(3):
            resp = self.client.get('/books/api/unified/export/csv/', {'tab': 'all'})
            b''.join(resp.streaming_content)
        self.assertEqual(UserActivityLog.objects.filter(action='EXPORT_DATA').count(), 3)

    def test_each_print_is_its_own_row(self):
        self.client.get('/books/%d/report/' % self.book.pk)
        self.client.get('/books/%d/report/' % self.book.pk)
        self.assertEqual(UserActivityLog.objects.filter(action='PRINT').count(), 2)

    def test_a_secret_view_is_recorded_raw_beside_the_folded_one(self):
        """عددُ مرّات فتح السرّيّ ومواقيتُها هي الدليل — فلا تُطوى."""
        self.client.force_login(self.head)
        self.client.get('/books/%d/' % self.secret.pk)
        self.client.get('/books/%d/' % self.secret.pk)
        self.assertEqual(UserActivityLog.objects.filter(action='SECRET_VIEW').count(), 2)
        self.assertEqual(UserActivityLog.objects.filter(
            action=UserActivityLog.VIEW_BOOK, book=self.secret).count(), 1)

    def test_downloading_an_attachment_is_raw_and_viewing_is_folded(self):
        att = Attachment.objects.create(
            book=self.book, file=SimpleUploadedFile('s.pdf', b'%PDF-1.4'))
        url = '/media/%s' % att.file.name
        self.client.get(url)
        self.client.get(url)
        self.client.get(url, {'download': '1'})
        self.client.get(url, {'download': '1'})
        self.assertEqual(UserActivityLog.objects.filter(
            action=UserActivityLog.VIEW_ATTACHMENT).count(), 1)
        self.assertEqual(UserActivityLog.objects.filter(
            action='DOWNLOAD_ATTACHMENT').count(), 2)


class LoginTrailTests(AuditTestCase):

    def test_a_login_is_recorded(self):
        self.client.login(username='saclerk', password='pw-saclerk-11111')
        self.assertTrue(UserActivityLog.objects.filter(action='LOGIN').exists())

    def test_a_failed_login_keeps_the_attempted_name_and_no_password(self):
        self.client.login(username='saclerk', password='كلمةٌ خاطئة')
        row = UserActivityLog.objects.get(action='LOGIN_FAILED')
        self.assertEqual(row.username_snapshot, 'saclerk')
        self.assertIsNone(row.user_id)
        self.assertNotIn('كلمةٌ خاطئة', str(row.metadata))


class IpIsEvidenceTests(AuditTestCase):
    """عنوانٌ يُزوَّر في سجلٍّ غرضُه المساءلة ليس دليلاً."""

    def test_a_forged_forwarded_header_is_ignored(self):
        self.client.force_login(self.clerk)
        self.client.get('/books/%d/' % self.book.pk,
                        HTTP_X_FORWARDED_FOR='8.8.8.8')
        row = UserActivityLog.objects.get(action=UserActivityLog.VIEW_BOOK)
        self.assertNotEqual(row.ip_address, '8.8.8.8')

    def test_it_is_honoured_only_behind_a_declared_proxy(self):
        from django.test import RequestFactory

        request = RequestFactory().get('/', HTTP_X_FORWARDED_FOR='8.8.8.8')
        with self.settings(TRUST_X_FORWARDED_FOR=True):
            self.assertEqual(client_ip(request), '8.8.8.8')


class AuditScopeTests(AuditTestCase):
    """السجلُّ أداةُ مراقبةِ أشخاص — فبوّابتُه أضيقُ من كلّ ما سبقه."""

    def test_the_department_head_may_open_it(self):
        self.client.force_login(self.head)
        self.assertEqual(self.client.get('/books/audit/').status_code, 200)

    def test_the_mail_officer_may_not(self):
        """أمينُ السرّيّ تشغيليّاً — لكنّ مراقبةَ الأشخاص ليست عملَ بريد."""
        self.assertFalse(can_view_audit(self.officer))
        self.client.force_login(self.officer)
        self.assertEqual(self.client.get('/books/audit/').status_code, 403)

    def test_a_plain_member_may_not(self):
        self.client.force_login(self.clerk)
        self.assertEqual(self.client.get('/books/audit/').status_code, 403)

    def test_a_head_sees_their_subtree_and_not_another_department(self):
        self.client.force_login(self.clerk)
        self.client.get('/books/%d/' % self.book.pk)
        self.client.force_login(self.outsider)
        self.client.get('/books/%d/' % self.foreign.pk)

        visible = scope_activity_for(self.head)
        self.assertTrue(visible.filter(book=self.book).exists())
        self.assertFalse(visible.filter(book=self.foreign).exists())

    def test_a_unit_member_activity_is_visible_to_the_parent_head(self):
        """الشجرةُ تسيل نزولاً هنا أيضاً — وإلّا انفرج النطاقُ الرابع عن الثلاثة."""
        self.client.force_login(self.unit_staff)
        self.client.get('/books/%d/' % self.book.pk)
        self.assertTrue(scope_activity_for(self.head).filter(user=self.unit_staff).exists())

    def test_opening_the_log_is_itself_recorded(self):
        """مَن يراقب المراقبين."""
        self.client.force_login(self.head)
        self.client.get('/books/audit/')
        self.assertTrue(UserActivityLog.objects.filter(action='VIEW_AUDIT_LOG').exists())


class LogIsNotABackDoorTests(AuditTestCase):
    """درسُ تصدير CSV حرفيّاً: كلُّ سطحٍ يُخرج محتوىً يمرّ بالقرار نفسه."""

    def test_a_secret_title_is_stubbed_for_a_head_of_another_department(self):
        other_head = User.objects.create_user('saoh', password='pw-saoh-1111')
        UserProfile.objects.create(user=other_head, department=self.other,
                                   is_department_head=True)
        # موظّفُ العقود يقرأ كتابَ قسمه، وسرّيُّ المتابعة يبقى محجوباً عن رئيسه
        self.client.force_login(self.head)
        self.client.get('/books/%d/' % self.secret.pk)

        self.client.force_login(other_head)
        body = self.client.get('/books/audit/', {'tab': 'users'}).content.decode()
        self.assertNotIn('مناقصةٌ سرّيّة', body)

    def test_the_owning_head_does_see_it(self):
        self.client.force_login(self.head)
        self.client.get('/books/%d/' % self.secret.pk)
        body = self.client.get('/books/audit/', {'tab': 'users'}).content.decode()
        self.assertIn('مناقصةٌ سرّيّة', body)

    def test_the_page_declares_where_the_log_begins(self):
        """13,193 كتاباً سبقت التفعيل — والسكوتُ عن ذلك يجعل الواجهةَ تكذب."""
        self.client.force_login(self.head)
        self.client.get('/books/%d/' % self.book.pk)
        body = self.client.get('/books/audit/', {'tab': 'users'}).content.decode()
        self.assertIn('السجل يبدأ من', body)


class LoggingNeverBreaksThePageTests(AuditTestCase):
    """سجلُّ تدقيقٍ يُسقط صفحةً عطلٌ يوميّ، وعطلٌ يوميّ يُطفئه أحدُهم."""

    def test_a_failing_write_leaves_the_page_intact(self):
        from unittest.mock import patch

        self.client.force_login(self.clerk)
        with patch('core.logging_models.UserActivityLog.objects.get_or_create',
                   side_effect=RuntimeError('القاعدة ممتلئة')):
            resp = self.client.get('/books/%d/' % self.book.pk)
        self.assertEqual(resp.status_code, 200)
