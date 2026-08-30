"""
طبقةُ السرّيّة — حجبُ محتوىً لا حجبُ صفّ.

**تصحيحُ قاعدةٍ شُحنت خطأً في المرحلة أ:** كانت تُخفي الصفَّ كلَّه عمّن ليس
مُنشئه أو رئيسَ قسمه. وقرارُ المالك — ومعه شهادةُ موظّف البريد («السرّي يُحفظ في
السجلّ **عاديّ**») — أنّ السجلَّ يكشف الرقمَ والتاريخ للجميع والمظروفَ مغلق.

وهذه الاختباراتُ عدائيّة: تسأل عن **كلّ قناةٍ يمكن أن يتسرّب منها المحتوى**.
"""

from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from core.models import Attachment, Book, Department, SecretAccessGrant, UserProfile
from core.roles import CONTROLLER_GROUP_NAME
from core.scoping import ACCESS_FULL, ACCESS_STUB, can_open_content, can_view_book, secret_access


class SecrecyTestCase(TestCase):
    """قسمٌ فيه كتابٌ عاديٌّ وكتابٌ سرّيّ، وخمسةُ فاعلين."""

    @classmethod
    def setUpTestData(cls):
        cls.dept = Department.objects.create(name='المتابعة', code='س-ش13')
        cls.other = Department.objects.create(name='العقود', code='س-ش5')

        def member(name, dept, *, head=False, controller=False):
            u = User.objects.create_user(name, password=f'pw-{name}-1111')
            UserProfile.objects.create(user=u, department=dept, is_department_head=head)
            if controller:
                group, _ = Group.objects.get_or_create(name=CONTROLLER_GROUP_NAME)
                u.groups.add(group)
            return u

        cls.clerk   = member('clerk', cls.dept)                     # مُدخِلٌ عاديّ
        cls.head    = member('head', cls.dept, head=True)           # رئيسُ القسم
        cls.officer = member('officer', cls.dept, controller=True)  # مختصُّ البريد
        cls.author  = member('author', cls.dept)                    # مُنشئُ السرّي
        cls.stranger = member('stranger', cls.other)                # قسمٌ آخر
        cls.root = User.objects.create_superuser('root', 'r@x.com', 'pw-root-1111')

        cls.plain = Book.objects.create(
            kind='incoming_internal', title='كتابٌ علنيّ', created_by=cls.clerk,
            department=cls.dept, our_number='2400',
        )
        cls.secret = Book.objects.create(
            kind='incoming_internal', title='مناقصةُ الحفر السرّيّة', created_by=cls.author,
            department=cls.dept, our_number='2437', secret_level='secret',
            sender_number='ش/9 771', margin='هامشٌ حسّاس',
        )


class AccessMatrixTests(SecrecyTestCase):

    def test_full_for_the_five(self):
        for user in (self.root, self.head, self.officer, self.author):
            self.assertEqual(secret_access(user, self.secret), ACCESS_FULL, user.username)

    def test_stub_for_plain_member(self):
        self.assertEqual(secret_access(self.clerk, self.secret), ACCESS_STUB)

    def test_non_secret_is_always_full(self):
        self.assertEqual(secret_access(self.clerk, self.plain), ACCESS_FULL)

    def test_head_of_another_department_gets_stub(self):
        """الدورُ يُخوِّل داخل القسم لا خارجه."""
        other_head = User.objects.create_user('oh', password='pw-oh-11111')
        UserProfile.objects.create(user=other_head, department=self.other, is_department_head=True)
        self.assertEqual(secret_access(other_head, self.secret), ACCESS_STUB)


class RowIsVisibleContentIsNotTests(SecrecyTestCase):
    """جوهرُ التصحيح: الصفُّ يُرى والمحتوى لا."""

    def test_plain_member_sees_the_row(self):
        self.assertTrue(can_view_book(self.secret, self.clerk),
                        'الصفُّ اختفى — هذا هو الخطأ الذي نُصحّحه')

    def test_plain_member_cannot_open_content(self):
        self.assertFalse(can_open_content(self.secret, self.clerk))

    def test_officer_opens_content(self):
        self.assertTrue(can_open_content(self.secret, self.officer))

    def test_stranger_sees_neither(self):
        self.assertFalse(can_view_book(self.secret, self.stranger))


class GrantTests(SecrecyTestCase):
    """التفويضُ لكتابٍ بعينه — «أو تفويضُ موظّفٍ معيّنٍ للاطّلاع»."""

    def test_live_grant_opens_it(self):
        SecretAccessGrant.objects.create(book=self.secret, user=self.clerk, granted_by=self.head)
        self.assertEqual(secret_access(self.clerk, self.secret), ACCESS_FULL)

    def test_expired_grant_falls_back_to_stub(self):
        SecretAccessGrant.objects.create(
            book=self.secret, user=self.clerk, granted_by=self.head,
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        self.assertEqual(secret_access(self.clerk, self.secret), ACCESS_STUB)

    def test_revoked_grant_falls_back_to_stub(self):
        SecretAccessGrant.objects.create(
            book=self.secret, user=self.clerk, granted_by=self.head,
            revoked_at=timezone.now(),
        )
        self.assertEqual(secret_access(self.clerk, self.secret), ACCESS_STUB)

    def test_grant_does_not_leak_to_another_book(self):
        other_secret = Book.objects.create(
            kind='incoming_internal', title='سرٌّ آخر', created_by=self.author,
            department=self.dept, secret_level='secret',
        )
        SecretAccessGrant.objects.create(book=self.secret, user=self.clerk, granted_by=self.head)
        self.assertEqual(secret_access(self.clerk, other_secret), ACCESS_STUB)


class SearchIsNotAnInterrogationToolTests(SecrecyTestCase):
    """أخطرُ قناةِ تسريب: حجبُ العنوان بلا قيمةٍ إن كشفه البحثُ بكلمةٍ منه."""

    def setUp(self):
        self.client.force_login(self.clerk)

    def _titles(self, q):
        resp = self.client.get('/books/api/unified/data/', {'q': q})
        self.assertEqual(resp.status_code, 200)
        return [b['title'] for b in resp.json()['books']]

    def test_searching_a_word_from_a_secret_title_returns_nothing(self):
        self.assertEqual(self._titles('مناقصة'), [])

    def test_searching_the_margin_text_returns_nothing(self):
        self.assertEqual(self._titles('حسّاس'), [])

    def test_number_search_still_finds_it_as_a_stub(self):
        """الرقمُ ظاهرٌ في الدفتر — فالبحثُ به مشروعٌ، والعنوانُ يبقى محجوباً."""
        titles = self._titles('2437')
        self.assertEqual(titles, ['— سرّي —'])

    def test_plain_book_text_search_still_works(self):
        self.assertIn('كتابٌ علنيّ', self._titles('علنيّ'))

    def test_officer_finds_it_by_title(self):
        self.client.force_login(self.officer)
        self.assertIn('مناقصةُ الحفر السرّيّة', self._titles('مناقصة'))


class ListPayloadIsStubbedTests(SecrecyTestCase):

    def test_stub_payload_blanks_the_content_fields(self):
        self.client.force_login(self.clerk)
        resp = self.client.get('/books/api/unified/data/')
        row = next(b for b in resp.json()['books'] if b['our_number'] == '2437')

        self.assertEqual(row['title'], '— سرّي —')
        self.assertTrue(row['is_secret_stub'])
        self.assertEqual(row['sender_number'], '')
        self.assertEqual(row['margin'], '')
        self.assertEqual(row['issuing_entities'], [])
        # وما يكشفه الدفترُ الورقيّ يبقى ظاهراً:
        self.assertEqual(row['our_number'], '2437')
        self.assertTrue(row['date_display'])

    def test_officer_gets_the_real_payload(self):
        self.client.force_login(self.officer)
        resp = self.client.get('/books/api/unified/data/')
        row = next(b for b in resp.json()['books'] if b['our_number'] == '2437')
        self.assertEqual(row['title'], 'مناقصةُ الحفر السرّيّة')
        self.assertFalse(row['is_secret_stub'])


class DetailAndAttachmentsAreClosedTests(SecrecyTestCase):

    def setUp(self):
        self.att = Attachment.objects.create(
            book=self.secret, file=SimpleUploadedFile('s.pdf', b'%PDF-1.4'),
        )

    def test_detail_page_renders_the_restricted_view(self):
        self.client.force_login(self.clerk)
        resp = self.client.get(f'/books/{self.secret.pk}/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '— سرّي —')
        self.assertNotContains(resp, 'مناقصةُ الحفر السرّيّة')
        self.assertContains(resp, self.secret.our_number)      # الدفترُ يكشف الرقم

    def test_officer_gets_the_full_detail_page(self):
        self.client.force_login(self.officer)
        resp = self.client.get(f'/books/{self.secret.pk}/')
        self.assertContains(resp, 'مناقصةُ الحفر السرّيّة')

    def test_modal_json_is_refused(self):
        self.client.force_login(self.clerk)
        resp = self.client.get(f'/books/api/book/{self.secret.pk}/detail/')
        self.assertIn(resp.status_code, (403, 404))

    def test_printable_report_is_refused(self):
        self.client.force_login(self.clerk)
        resp = self.client.get(f'/books/{self.secret.pk}/report/')
        self.assertIn(resp.status_code, (403, 404))

    def test_attachment_file_is_refused(self):
        self.client.force_login(self.clerk)
        resp = self.client.get(f'/media/{self.att.file.name}')
        self.assertIn(resp.status_code, (403, 404))

    def test_plain_book_detail_still_opens_for_the_department(self):
        """حارسُ عدم الانحدار: التصحيحُ لا يُغلق العلنيّ."""
        self.client.force_login(self.clerk)
        self.assertEqual(self.client.get(f'/books/{self.plain.pk}/').status_code, 200)
