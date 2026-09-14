"""
بوّابةُ المحتوى — عمليّاتُ الكتابة على كتابٍ سرّيّ.

**عيبٌ متكرّرٌ للمرّة الثالثة:** نسختان يدويّتان من قاعدة الرؤية كانتا باقيتين
في `book_detail` عند البند ①، ثمّ ظهرت **خمسٌ أخرى** عند البند ⑥ — كلُّها
`is_superuser or is_staff or created_by == user` في **عمليّات محتوى**: التعديل
وتغييرُ الحالة والتعليق. أثرُها مزدوج: `is_staff` يوسّع الرؤية (وقد أُلغي)،
والسرّيُّ **يُعدَّل بمن يرى سطرَه في الدفتر فقط**.

فهذه الاختباراتُ **سلوكيّة لا نصّيّة**: كنسُ النمط أخطأ الصياغاتِ مرّتين،
والحارسُ الوحيد الذي لا يُخطئ هو الذي يستدعي المسار.
"""

import json

from django.contrib.auth.models import User
from django.test import TestCase

from core.models import Attachment, Book, Department, OCRResult, UserProfile


class ContentGateTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.dept = Department.objects.create(name='المتابعة', code='ح-ش13')

        def member(name, **flags):
            u = User.objects.create_user(name, password='pw-%s-11111' % name, **flags)
            UserProfile.objects.create(user=u, department=cls.dept)
            return u

        cls.author = member('hauthor')
        cls.colleague = member('hcolleague')
        # موظّفٌ إداريّ — `is_staff` لم تعد توسّع الرؤية (قرارُ المرحلة أ)
        cls.staffer = member('hstaff', is_staff=True)

        cls.secret = Book.objects.create(
            kind='incoming_internal', title='مناقصةٌ سرّيّة', created_by=cls.author,
            department=cls.dept, our_number='2437', secret_level='secret',
        )
        cls.plain = Book.objects.create(
            kind='incoming_internal', title='كتابٌ علنيّ', created_by=cls.author,
            department=cls.dept, our_number='2400',
        )


class EditIsContentTests(ContentGateTestCase):

    def test_a_colleague_cannot_open_the_secret_edit_form(self):
        self.client.force_login(self.colleague)
        self.assertEqual(self.client.get('/books/%d/edit/' % self.secret.pk).status_code, 403)

    def test_a_colleague_may_edit_a_plain_book_of_the_department(self):
        """حارسُ عدم الانحدار: التضييقُ لا يُغلق العلنيّ في وجه القسم.

        و302 هي النجاح هنا: `book_edit` تُحوّل GET إلى شاشة الاستخراج في وضع
        التعديل — والمرفوضُ يأتيه 403 قبل التحويل.
        """
        self.client.force_login(self.colleague)
        self.assertEqual(self.client.get('/books/%d/edit/' % self.plain.pk).status_code, 302)

    def test_is_staff_no_longer_opens_a_secret(self):
        """`is_staff` صفةٌ إداريّةٌ في جانغو لا دورٌ عندنا — وقد فُصلت في المرحلة أ."""
        self.client.force_login(self.staffer)
        self.assertEqual(self.client.get('/books/%d/edit/' % self.secret.pk).status_code, 403)

    def test_the_author_still_edits_their_own_secret(self):
        self.client.force_login(self.author)
        self.assertEqual(self.client.get('/books/%d/edit/' % self.secret.pk).status_code, 302)


class CommentIsContentTests(ContentGateTestCase):

    def _comment(self, book):
        return self.client.post(
            '/books/api/book-comments/%d/add/' % book.pk,
            data=json.dumps({'content': 'تعليق'}),
            content_type='application/json',
        )

    def test_a_colleague_cannot_comment_on_a_secret(self):
        self.client.force_login(self.colleague)
        self.assertEqual(self._comment(self.secret).status_code, 403)

    def test_a_colleague_may_comment_on_a_plain_book(self):
        self.client.force_login(self.colleague)
        self.assertEqual(self._comment(self.plain).status_code, 200)


class StaffIsNotAContentKeyTests(ContentGateTestCase):
    """**ستُّ نسخٍ نجت من كنس T7.5‑2**: `merge_api` (×4) و`attachment_ocr_text`
    و`api_book_inline_status` — كلُّها `created_by or is_staff`. فحاملُ `is_staff`
    من قسمٍ آخر كان يفتح مرفقَ أيّ كتابٍ ونصَّ OCR السرّيّ ويُبدّل الحالة.

    والرفضُ **404 لا 403**: رمزان مفترقان عرّافٌ يُثبت وجودَ ما لا يملكه السائل.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        elsewhere = Department.objects.create(name='الحسابات', code='ح-ش14')
        cls.outsider = User.objects.create_user(
            'houtsider', password='pw-houtsider-11111', is_staff=True)
        UserProfile.objects.create(user=cls.outsider, department=elsewhere)

        cls.secret_att = Attachment.objects.create(book=cls.secret)
        cls.plain_att = Attachment.objects.create(book=cls.plain)
        OCRResult.objects.create(attachment=cls.secret_att, cleaned_text='نصُّ المناقصة')

    def _ocr(self, att):
        return self.client.get('/books/api/attachment/%d/ocr/' % att.pk)

    def _status(self, book):
        return self.client.post(
            '/books/api/book/%d/status-inline/' % book.pk,
            data=json.dumps({'status': 'archived'}),
            content_type='application/json',
        )

    # ── نصُّ OCR ──
    def test_is_staff_does_not_read_the_ocr_of_a_secret(self):
        self.client.force_login(self.staffer)
        self.assertEqual(self._ocr(self.secret_att).status_code, 404)

    def test_is_staff_from_another_department_does_not_read_ocr(self):
        self.client.force_login(self.outsider)
        self.assertEqual(self._ocr(self.plain_att).status_code, 404)

    def test_the_author_still_reads_the_ocr_of_their_secret(self):
        self.client.force_login(self.author)
        res = self._ocr(self.secret_att)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['text'], 'نصُّ المناقصة')

    # ── الحالة ──
    def test_is_staff_from_another_department_cannot_change_status(self):
        before = Book.objects.get(pk=self.plain.pk).is_archived
        self.client.force_login(self.outsider)
        self.assertEqual(self._status(self.plain).status_code, 404)
        self.assertEqual(Book.objects.get(pk=self.plain.pk).is_archived, before)

    def test_a_colleague_may_change_the_status_of_a_plain_book(self):
        """حارسُ عدم الانحدار: القسمُ يُنهي متابعةَ علنيِّه كما يعلّق عليه."""
        self.client.force_login(self.colleague)
        self.assertEqual(self._status(self.plain).status_code, 200)

    # ── واجهةُ الدمج: مُوجَّهةٌ بلا زرّ فتُبلَغ بالرابط ──
    def test_is_staff_from_another_department_cannot_list_versions(self):
        self.client.force_login(self.outsider)
        res = self.client.get('/books/api/attachments/%d/versions/' % self.plain_att.pk)
        self.assertEqual(res.status_code, 404)

    def test_is_staff_cannot_delete_an_attachment_of_a_secret(self):
        self.client.force_login(self.staffer)
        res = self.client.delete('/books/api/attachments/%d/delete_file/' % self.secret_att.pk)
        self.assertEqual(res.status_code, 404)
        self.assertFalse(Attachment.objects.get(pk=self.secret_att.pk).is_deleted)

    def test_the_author_still_lists_versions_of_their_secret(self):
        self.client.force_login(self.author)
        res = self.client.get('/books/api/attachments/%d/versions/' % self.secret_att.pk)
        self.assertEqual(res.status_code, 200)
