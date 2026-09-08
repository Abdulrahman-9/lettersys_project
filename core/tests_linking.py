"""
نسيجُ الوثائق — `BookLink` والمنتقي والبحثُ في نصّ المسح.

كان النظام **عاجزاً بنيويّاً** عن التعبير عن «إلحاقاً بمذكّرتكم المرقّمة…»:
صفرُ علاقةٍ من كتابٍ إلى كتاب في النموذج. وهذه الاختباراتُ تحرس العقد الجديد
وحدودَه — خاصّةً ألّا يصير النسيجُ ثغرةً جانبيّةً تكشف ما حجبته السرّيّة.
"""

from django.contrib.auth.models import Group, User
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import ProtectedError
from django.test import TestCase

from core.linking_service import add_link, links_of, remove_link
from core.models import Attachment, Book, BookHistory, BookLink, Department, OCRResult, UserProfile
from core.roles import CONTROLLER_GROUP_NAME


class LinkingTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.dept = Department.objects.create(name='المتابعة', code='ل-ش13')
        cls.other = Department.objects.create(name='العقود', code='ل-ش5')

        cls.clerk = User.objects.create_user('lclerk', password='pw-lclerk-1')
        UserProfile.objects.create(user=cls.clerk, department=cls.dept)
        cls.outsider = User.objects.create_user('lout', password='pw-lout-111')
        UserProfile.objects.create(user=cls.outsider, department=cls.other)

        cls.original = Book.objects.create(
            kind='outgoing_internal', title='مذكّرة الموازنة الاستثمارية',
            created_by=cls.clerk, department=cls.dept, our_number='2311',
        )
        cls.reply = Book.objects.create(
            kind='incoming_internal', title='إجابة شعبة الموازنة',
            created_by=cls.clerk, department=cls.dept, our_number='2451',
        )
        cls.foreign = Book.objects.create(
            kind='incoming_internal', title='كتابُ قسمٍ آخر',
            created_by=cls.outsider, department=cls.other, our_number='990',
        )


class AddLinkTests(LinkingTestCase):

    def test_creates_the_edge(self):
        link = add_link(self.reply, self.original, BookLink.REPLY, by=self.clerk)
        self.assertEqual(link.relation, BookLink.REPLY)
        self.assertEqual(self.original.links_in.count(), 1)

    def test_writes_history_on_both_books(self):
        """الضلعُ وحدَه نصفُ الحقيقة — ونصفُها الآخر أثرُه في تاريخ الطرفين."""
        add_link(self.reply, self.original, BookLink.REPLY, by=self.clerk)
        for book in (self.reply, self.original):
            self.assertTrue(BookHistory.objects.filter(book=book, action='link-added').exists(),
                            f'لا أثرَ في تاريخ {book.our_number}')

    def test_self_link_is_refused(self):
        with self.assertRaises(ValidationError):
            add_link(self.reply, self.reply, BookLink.REPLY, by=self.clerk)

    def test_unknown_relation_is_refused(self):
        with self.assertRaises(ValidationError):
            add_link(self.reply, self.original, 'ما-شئت', by=self.clerk)

    def test_duplicate_is_refused_without_leaving_history(self):
        add_link(self.reply, self.original, BookLink.REPLY, by=self.clerk)
        before = BookHistory.objects.count()
        with self.assertRaises(ValidationError):
            add_link(self.reply, self.original, BookLink.REPLY, by=self.clerk)
        self.assertEqual(BookHistory.objects.count(), before,
                         'المعاملةُ لم تتراجع — بقي أثرٌ لضلعٍ لم يُنشأ')

    def test_cannot_link_a_book_outside_your_scope(self):
        with self.assertRaises(PermissionDenied):
            add_link(self.reply, self.foreign, BookLink.REFERS, by=self.clerk)

    def test_same_pair_may_carry_two_relations(self):
        add_link(self.reply, self.original, BookLink.REPLY, by=self.clerk)
        add_link(self.reply, self.original, BookLink.FOLLOWUP, by=self.clerk)
        self.assertEqual(BookLink.objects.count(), 2)


class ProtectionTests(LinkingTestCase):
    """الأصلُ المرجعيُّ محميٌّ من التفريغ — حمايةُ السلسلة من الانقطاع."""

    def test_referenced_original_cannot_be_hard_deleted(self):
        add_link(self.reply, self.original, BookLink.REPLY, by=self.clerk)
        with self.assertRaises(ProtectedError):
            self.original.delete()

    def test_the_referring_book_may_be_deleted(self):
        add_link(self.reply, self.original, BookLink.REPLY, by=self.clerk)
        self.reply.delete()
        self.assertEqual(BookLink.objects.count(), 0)


class RemoveLinkTests(LinkingTestCase):

    def test_removes_and_records(self):
        link = add_link(self.reply, self.original, BookLink.REPLY, by=self.clerk)
        remove_link(link, by=self.clerk)
        self.assertEqual(BookLink.objects.count(), 0)
        self.assertEqual(BookHistory.objects.filter(action='link-removed').count(), 2)


class LinksOfPresentationTests(LinkingTestCase):
    """النسيجُ لا يصير ثغرةً جانبيّة."""

    def test_shows_both_directions(self):
        add_link(self.reply, self.original, BookLink.REPLY, by=self.clerk)
        self.assertEqual(len(links_of(self.original, self.clerk)), 1)
        self.assertEqual(links_of(self.original, self.clerk)[0]['direction'], 'in')
        self.assertEqual(links_of(self.reply, self.clerk)[0]['direction'], 'out')

    def test_the_label_carries_its_direction(self):
        """الضلعُ الواحد يُقرأ من طرفيه بمعنيين — و«جواب على» على كتابٍ *أجابه*
        غيرُه تُقرأ عكسَ معناها. كشفته العينُ في لوحة دورة الحياة."""
        add_link(self.reply, self.original, BookLink.REPLY, by=self.clerk)
        outgoing = links_of(self.reply, self.clerk)[0]
        incoming = links_of(self.original, self.clerk)[0]
        self.assertEqual(outgoing['relation_label'], 'جواب على')
        self.assertEqual(incoming['relation_label'], 'أجابه')

    def test_edge_to_a_secret_book_is_restricted_not_revealed(self):
        secret = Book.objects.create(
            kind='incoming_internal', title='سرٌّ لا يُقرأ', created_by=self.outsider,
            department=self.dept, our_number='2500', secret_level='secret',
        )
        BookLink.objects.create(from_book=self.reply, to_book=secret,
                                relation=BookLink.REFERS, created_by=self.outsider)

        row = links_of(self.reply, self.clerk)[0]
        self.assertTrue(row['restricted'])
        self.assertEqual(row['title'], '— سرّي —')
        self.assertIsNone(row['book_id'], 'أُعطي رابطاً لفتح كتابٍ لا يملك محتواه')
        self.assertEqual(row['number'], secret.our_number_display)   # الرقمُ في الدفتر أصلاً

    def test_edge_to_another_department_is_not_hinted_at(self):
        BookLink.objects.create(from_book=self.foreign, to_book=self.original,
                                relation=BookLink.REFERS, created_by=self.outsider)
        self.assertEqual(links_of(self.original, self.clerk), [],
                         'لُمِّح إلى وجود كتابٍ خارج النطاق')


class PickerTests(LinkingTestCase):

    def setUp(self):
        self.client.force_login(self.clerk)

    def _pick(self, q, exclude=None):
        params = {'q': q}
        if exclude:
            params['exclude'] = exclude
        return self.client.get('/books/api/links/picker/', params).json()['results']

    def test_finds_by_number(self):
        numbers = [r['number'] for r in self._pick('2311')]
        self.assertIn('2311', numbers)

    def test_falls_back_to_title_search(self):
        """طلبُ المالك الثالث: «وإذا لا يوجد هذا الكتاب ممكن يبحث بالعنوان»."""
        titles = [r['title'] for r in self._pick('الموازنة')]
        self.assertIn('مذكّرة الموازنة الاستثمارية', titles)

    def test_excludes_the_current_book(self):
        ids = [r['id'] for r in self._pick('2311', exclude=self.original.pk)]
        self.assertNotIn(self.original.pk, ids)

    def test_never_offers_another_department(self):
        self.assertEqual(self._pick('990'), [])

    def test_empty_query_returns_nothing(self):
        self.assertEqual(self._pick(''), [])

    def test_card_carries_disambiguation_fields(self):
        card = self._pick('2311')[0]
        for key in ('number', 'title', 'date', 'department', 'is_mine'):
            self.assertIn(key, card)


class PickerApiWritesTests(LinkingTestCase):

    def setUp(self):
        self.client.force_login(self.clerk)

    def test_add_and_remove_through_the_api(self):
        resp = self.client.post(
            f'/books/api/book/{self.reply.pk}/links/add/',
            data=f'{{"to_book": {self.original.pk}, "relation": "reply"}}',
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        link_id = resp.json()['id']

        resp = self.client.post(f'/books/api/book/{self.reply.pk}/links/{link_id}/remove/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(BookLink.objects.count(), 0)

    def test_foreign_target_is_not_found(self):
        resp = self.client.post(
            f'/books/api/book/{self.reply.pk}/links/add/',
            data=f'{{"to_book": {self.foreign.pk}, "relation": "refers"}}',
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 404)


class OcrTextSearchTests(LinkingTestCase):
    """النصُّ الممسوح كان يُخزَّن منذ سنوات والبحثُ لا يمسّه."""

    def setUp(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        att = Attachment.objects.create(
            book=self.original, file=SimpleUploadedFile('scan.pdf', b'%PDF-1.4'),
        )
        OCRResult.objects.create(
            attachment=att, status='completed',
            cleaned_text='إشارة إلى كتابكم المرقّم 1120 بخصوص تخصيصات الحفر الاستكشافي',
        )
        self.client.force_login(self.clerk)

    def _titles(self, q):
        # التبويبُ الافتراضيّ في هذه النقطة `incoming` — نطلب `all` صراحةً كي
        # يختبر هذا الاختبارُ البحثَ لا التبويب.
        resp = self.client.get('/books/api/unified/data/', {'q': q, 'tab': 'all'})
        return [b['title'] for b in resp.json()['books']]

    def test_finds_a_book_by_a_word_inside_its_scan(self):
        self.assertIn('مذكّرة الموازنة الاستثمارية', self._titles('الاستكشافي'))

    def test_a_word_in_no_scan_finds_nothing(self):
        self.assertEqual(self._titles('كلمةٌ لا وجود لها'), [])

    def test_ocr_search_respects_secrecy(self):
        """البحثُ في المتن لا يفتح باباً خلفيّاً لما حجبته الطبقة."""
        from django.core.files.uploadedfile import SimpleUploadedFile

        secret = Book.objects.create(
            kind='incoming_internal', title='سرّي', created_by=self.outsider,
            department=self.dept, our_number='2600', secret_level='secret',
        )
        att = Attachment.objects.create(
            book=secret, file=SimpleUploadedFile('s2.pdf', b'%PDF-1.4'),
        )
        OCRResult.objects.create(attachment=att, status='completed',
                                 cleaned_text='كلمةٌ سرّيّةٌ جدّاً في المتن')
        self.assertEqual(self._titles('سرّيّةٌ'), [])
