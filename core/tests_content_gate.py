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

from core.models import Book, Department, UserProfile


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
