# -*- coding: utf-8 -*-
"""يتحقّق أنّ حلقة الالتقاط تسجّل العدد قيمةً وتصحيحاً بعد توصيله (2026-07-22).

يشغّل بـ settings_test (SQLite في الذاكرة):
  $env:PYTHONIOENCODING="utf-8"; python manage.py test core.tests_capture_sender_number --settings=lettersys.settings_test
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from core.extraction.capture import persist_extraction_capture
from core.models import (Attachment, Book, DataExtractionResult,
                         ExtractionFeedback)


class SenderNumberCaptureTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('t', password='x')
        self.book = Book.objects.create(kind='incoming_internal', our_number='12345',
                                        title='عنوان', created_by=self.user)
        self.att = Attachment.objects.create(book=self.book)

    def _suggested(self, number, conf=0.9):
        return {'raw_text': 'نصّ الترويسة', 'cleaned_text': 'نصّ الترويسة',
                'sender_number': number, 'sender_number_confidence': conf,
                'title': 'عنوان', 'overall_confidence': 0.8}

    def test_kept_value_is_recorded_in_additional_data(self):
        """حين يُبقي الموظّف الرقم المُقترَح: يُسجَّل الزوج، ولا إشارة تصحيح."""
        self.book.sender_number = '1831'
        self.book.save()
        ex = persist_extraction_capture(
            book=self.book, attachment=self.att, suggested=self._suggested('1831'),
            final={'sender_number': self.book.sender_number}, user=self.user)
        self.assertIsNotNone(ex)
        ad = ex.additional_data
        self.assertEqual(ad['sender_number_suggested'], '1831')
        self.assertEqual(ad['sender_number_final'], '1831')
        self.assertEqual(ad['sender_number_confidence'], 0.9)
        self.assertIsNone(ad['sender_number_bbox'])  # حامل الموضع فارغ اليوم
        self.assertFalse(ExtractionFeedback.objects.filter(
            extraction=ex, field_name='sender_number').exists())

    def test_bbox_is_captured_when_present(self):
        """موضع القصّ يُخزَّن في additional_data (رافعة التوضيع: زوج قيمة+موضع)."""
        self.book.sender_number = '1831'
        self.book.save()
        sug = self._suggested('1831')
        sug['sender_number_bbox'] = [0.11, 0.16, 0.19, 0.18]
        ex = persist_extraction_capture(
            book=self.book, attachment=self.att, suggested=sug,
            final={'sender_number': self.book.sender_number}, user=self.user)
        self.assertEqual(ex.additional_data['sender_number_bbox'], [0.11, 0.16, 0.19, 0.18])

    def test_corrected_value_creates_feedback(self):
        """حين يصحّح الموظّف الرقم: إشارة تصحيح بالقيمتين = عيّنة تدريب سالبة."""
        self.book.sender_number = '1831'
        self.book.save()
        ex = persist_extraction_capture(
            book=self.book, attachment=self.att,
            suggested=self._suggested('154'),                 # النموذج ابتلع خانة
            final={'sender_number': self.book.sender_number}, user=self.user)
        fb = ExtractionFeedback.objects.get(extraction=ex, field_name='sender_number')
        self.assertEqual(fb.original_value, '154')
        self.assertEqual(fb.corrected_value, '1831')
        self.assertEqual(ex.additional_data['sender_number_final'], '1831')

    def test_capture_never_raises(self):
        """السلامة الأعلى: بيانات ناقصة لا تُفشل الحفظ (تُعيد None)."""
        self.assertIsNone(persist_extraction_capture(
            book=self.book, attachment=self.att, suggested=None,
            final={'sender_number': '1'}, user=self.user))

    def test_outgoing_does_not_manufacture_sender_number_feedback(self):
        """الصادر: الواجهة تُفرّغ الحقل والأنبوب يقترح رقماً — يجب ألّا يُسجَّل تصحيحٌ
        كاذب «154→''»، ويجب ختم book_kind وعدم كتابة مفاتيح العدد (Fable، إيداع 0)."""
        self.book.kind = 'outgoing_internal'
        self.book.sender_number = ''
        self.book.save()
        ex = persist_extraction_capture(
            book=self.book, attachment=self.att, suggested=self._suggested('154'),
            final={'sender_number': ''}, user=self.user)
        self.assertIsNotNone(ex)
        self.assertFalse(ExtractionFeedback.objects.filter(
            extraction=ex, field_name='sender_number').exists())
        self.assertEqual(ex.additional_data['book_kind'], 'outgoing_internal')
        self.assertNotIn('sender_number_suggested', ex.additional_data)

    def test_arabic_indic_digits_not_logged_as_correction(self):
        """قراءةٌ صحيحةٌ بأرقامٍ لاتينية مقابل إدخالٍ عربيٍّ-هنديّ لنفس القيمة: لا تصحيح."""
        self.book.sender_number = '١٨٣١'   # نفس 1831 بخطٍّ عربيّ-هنديّ
        self.book.save()
        ex = persist_extraction_capture(
            book=self.book, attachment=self.att, suggested=self._suggested('1831'),
            final={'sender_number': self.book.sender_number}, user=self.user)
        self.assertFalse(ExtractionFeedback.objects.filter(
            extraction=ex, field_name='sender_number').exists())
