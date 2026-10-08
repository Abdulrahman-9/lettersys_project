# -*- coding: utf-8 -*-
"""تدقيقُ 2026-10-08، مجموعةُ «الإدخال الذكيّ والاستخراج».

١. **ثغرةُ قراءةٍ وكتابة (IDOR)**: صفحةُ نتيجة الاستخراج (`/books/extract/results/<id>/`) وواجهتُها
   (`GET /books/api/extract/<attachment_id>/`) كانتا لكلّ مَن سجّل الدخول — تعدادُ الأرقام يكشف
   رقمَ كلّ كتابٍ وعنوانَه وهامشَه، والسرّيُّ منها. و`feedback/` و`review/` تكتبان على مفرداتِ أيّ
   كتاب، و`POST /books/api/extract/` يُطلق استخراجاً على مرفق أيّ كتاب. الآن القراءةُ بحكم
   ``can_open_content`` والكتابةُ بحكم ``can_edit_book`` — من `core/scoping.py` — و404 لا 403.
٢. **الحفظُ يقول ما العمل**: انتهاءُ الجلسة (تحويلٌ إلى صفحة الدخول) وردٌّ ليس JSON صارا رسالتين
   تُقرآن، و«تفريغ الحقول» و«إلغاء» بحواريّة التطبيق.
"""
import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core.models import Attachment, Book, DataExtractionResult, ExtractionFeedback
from core.scoping import can_open_extraction, can_review_extraction

ROOT = Path(__file__).resolve().parent.parent
User = get_user_model()


class ExtractionScopeTests(TestCase):
    """المالكُ يقرأ ويراجع؛ الغريبُ 404 في كلّ مسار؛ والمديرُ يرى ما لا كتابَ له."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user('ex_owner', password='pw-ex-owner-1')
        cls.stranger = User.objects.create_user('ex_stranger', password='pw-ex-stranger-1')
        cls.boss = User.objects.create_superuser('ex_boss', 'b@x.co', 'pw-ex-boss-1')
        cls.book = Book.objects.create(kind='incoming_external', our_number='7301',
                                       title='عنوانٌ لا يراه الغريب', created_by=cls.owner)
        cls.att = Attachment.objects.create(
            book=cls.book, file=SimpleUploadedFile('s.jpg', b'x', content_type='image/jpeg'))
        cls.extraction = DataExtractionResult.objects.create(
            attachment=cls.att, title='عنوانٌ لا يراه الغريب', margin_text='هامشٌ سرّيّ',
            book_number='7301', status='extracted')
        cls.orphan = DataExtractionResult.objects.create(title='بلا كتاب', status='extracted')

    def test_rules(self):
        self.assertTrue(can_open_extraction(self.extraction, self.owner))
        self.assertTrue(can_review_extraction(self.extraction, self.owner))
        self.assertFalse(can_open_extraction(self.extraction, self.stranger))
        self.assertFalse(can_review_extraction(self.extraction, self.stranger))
        # ما لا كتابَ له لمدير النظام وحده
        self.assertFalse(can_open_extraction(self.orphan, self.owner))
        self.assertTrue(can_open_extraction(self.orphan, self.boss))

    def test_results_page(self):
        url = reverse('extraction-results-ui', args=[self.extraction.pk])
        self.client.force_login(self.stranger)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)
        self.assertNotContains(resp, 'هامشٌ سرّيّ', status_code=404)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_result_api(self):
        url = '/books/api/extract/%d/' % self.att.pk
        self.client.force_login(self.stranger)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)
        self.assertNotIn('هامشٌ سرّيّ', resp.content.decode('utf-8'))
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(url).json()['margin_text'], 'هامشٌ سرّيّ')

    def test_feedback_and_review_are_writes(self):
        self.client.force_login(self.stranger)
        fb = self.client.post(reverse('ai_submit_feedback', args=[self.extraction.pk]),
                              data=json.dumps({'field_name': 'title', 'feedback_type': 'incorrect'}),
                              content_type='application/json')
        rv = self.client.post(reverse('ai_review_extraction', args=[self.extraction.pk]),
                              data=json.dumps({'action': 'approve', 'fields': {'title': 'مُسمَّم'}}),
                              content_type='application/json')
        self.assertEqual((fb.status_code, rv.status_code), (404, 404))
        self.extraction.refresh_from_db()
        self.assertEqual(self.extraction.title, 'عنوانٌ لا يراه الغريب')
        self.assertEqual(self.extraction.status, 'extracted')
        self.assertFalse(ExtractionFeedback.objects.filter(extraction=self.extraction).exists())

    def test_reading_is_not_reviewing(self):
        """مُنشئٌ صار كتابُه لقسمٍ آخر: يقرأ (``can_open_content``) ولا يراجع (``can_edit_book``)."""
        from core.models import Department, UserProfile

        mine = Department.objects.create(name='قسم الكاتب', code='ك.ت')
        other = Department.objects.create(name='قسم المالك', code='م.ل')
        writer = User.objects.create_user('ex_writer', password='pw-ex-writer-1')
        UserProfile.objects.update_or_create(user=writer, defaults={'department': mine})
        book = Book.objects.create(kind='incoming_external', our_number='7302', title='انتقل',
                                   department=other, created_by=writer)
        att = Attachment.objects.create(
            book=book, file=SimpleUploadedFile('m.jpg', b'x', content_type='image/jpeg'))
        extraction = DataExtractionResult.objects.create(attachment=att, title='انتقل', status='extracted')
        self.assertTrue(can_open_extraction(extraction, writer))
        self.assertFalse(can_review_extraction(extraction, writer))
        self.client.force_login(writer)
        rv = self.client.post(reverse('ai_review_extraction', args=[extraction.pk]),
                              data=json.dumps({'action': 'reject'}), content_type='application/json')
        self.assertEqual(rv.status_code, 404)

    def test_start_extraction_on_a_foreign_attachment(self):
        self.client.force_login(self.stranger)
        resp = self.client.post('/books/api/extract/', {'attachment_id': self.att.pk})
        self.assertEqual(resp.status_code, 404)


class EntryScriptsTests(SimpleTestCase):
    def read(self, rel):
        return (ROOT / rel).read_text(encoding='utf-8')

    def test_save_paths_name_session_expiry_and_bad_responses(self):
        src = self.read('static/extraction_smart.js')
        self.assertIn('_sessionExpired(response) {', src)
        self.assertEqual(src.count('this._sessionExpired('), 2)        # الحفظُ الجديد والتعديل
        self.assertNotIn('const data = await response.json();\n', src)
        self.assertNotIn("saveFail: 'تعذر الحفظ',", src)

    def test_no_native_confirm_on_the_entry_page(self):
        src = self.read('static/extraction_smart.js')
        clear = src[src.index("btnId === 'clearFormButton'"):]
        clear = clear[:clear.index("btnId === 'extractButton'")]
        self.assertNotIn('window.confirm(', clear)
        self.assertIn('window.confirmDelete({', clear)
        tpl = self.read('templates/core/extraction_smart_desktop.html')
        self.assertNotIn("!confirm('لديك تغييرات غير محفوظة", tpl)
        self.assertIn("okText: 'غادِر بلا حفظ'", tpl)
