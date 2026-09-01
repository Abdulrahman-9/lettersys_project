# -*- coding: utf-8 -*-
"""حرزُ أمر `learning_stats` — بديلِ `ExtractionLearningSystem` المحذوف.

الغايةُ ليست تثبيت أرقامٍ بعينها بل ثلاثة أشياء لا تُرى بالعين: أن الأمر لا
يسقط على قاعدةٍ فارغة (فلا يُترَك المالكُ بلا قياسٍ إطلاقاً)، وأن المؤشّر
الرابع يلتقط اختلافاً **حقيقيّاً** بين الملتقَط وقيمة الكتاب الحيّة، وأن نبضَ
الحياة يصرخ حين تنقطع الحلقةُ لا حين تبطؤ.

  $env:PYTHONIOENCODING="utf-8"; python manage.py test core.tests_learning_stats --settings=lettersys.settings_test
"""
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from core.extraction.capture import persist_extraction_capture
from core.models import (Attachment, Book, DataExtractionResult,
                         ExtractionFeedback, OCRResult)


def _run(**opts):
    out = StringIO()
    call_command('learning_stats', stdout=out, stderr=out, **opts)
    return out.getvalue()


class LearningStatsEmptyTests(TestCase):
    def test_runs_on_empty_database(self):
        """قاعدةٌ فارغة: لا قسمةَ على صفر ولا استثناء — والمؤشّرات تُطبع بلا مقام."""
        out = _run()
        self.assertIn('مؤشّراتُ التعلّم المستمرّ', out)
        for head in ('① ', '② ', '③ ', '④ ', 'نبضُ الحياة'):
            self.assertIn(head, out)
        self.assertIn('—', out)          # المعدّلاتُ بلا مقام تُطبع شرطةً لا 0%

    def test_days_argument_is_honoured(self):
        self.assertIn('آخر 7 يوماً', _run(days=7))


class LearningStatsSignalTests(TestCase):
    """بياناتٌ اصطناعيّة: كتابٌ + مرفق + التقاط."""

    def setUp(self):
        self.user = get_user_model().objects.create_user('t', password='x')

    def _capture(self, *, suggested_number, final_number, conf=0.99, bbox=True):
        book = Book.objects.create(kind='incoming_internal', our_number='',
                                   title='عنوان', sender_number=final_number,
                                   created_by=self.user)
        att = Attachment.objects.create(book=book)
        sug = {'raw_text': 'نصّ', 'cleaned_text': 'نصّ', 'title': 'عنوان',
               'sender_number': suggested_number, 'sender_number_confidence': conf,
               'overall_confidence': 0.8}
        if bbox:
            sug['sender_number_bbox'] = [0.1, 0.15, 0.2, 0.18]
        ex = persist_extraction_capture(
            book=book, attachment=att, suggested=sug,
            # `displayed_fields` وسمُ الواجهة «عُرض على الكاتب فعلاً»؛ يُتجاهَل
            # بلا ضرر إن لم يكن الكاتبُ يفهمه بعد (فيسقط القارئ إلى الاستدلال).
            final={'sender_number': final_number, 'displayed_fields': ['sender_number']},
            user=self.user)
        self.assertIsNotNone(ex)
        return book, ex

    def test_pair_counted_and_gate_remaining_printed(self):
        """زوجٌ واحد يُعدّ، والمتبقّي للعتبة يُطبع صريحاً (القرار: متى تُفتح)."""
        self._capture(suggested_number='1831', final_number='1831')
        out = _run()
        self.assertIn('1 / 500 زوجاً', out)
        self.assertIn('يتبقّى 499', out)
        self.assertIn('متّفقٌ عليه 1', out)

    def test_handwritten_pair_counts_toward_hard_quota(self):
        """اقتراحٌ فارغ + قيمةٌ نهائيّة = مكتوبٌ بيد ⟵ يُحسب في حصّة الـ150."""
        self._capture(suggested_number='', final_number='762', conf=0.0)
        out = _run()
        self.assertIn('مكتوبٌ بيد 1', out)
        self.assertIn('تصحيحٌ/مكتوبٌ بيد 1 / 150', out)

    def test_confident_and_corrected_raises_freeze_alarm(self):
        """تصحيحٌ على اقتراحٍ عُرض بثقة 0.99 = «واثقٌ‑ومصحَّح» ⟵ يُجمَّد الإصدار."""
        self._capture(suggested_number='154', final_number='1831', conf=0.99)
        out = _run()
        self.assertIn('1 / 1 = 100.0%', out)
        self.assertIn('لا إصدارَ جديد', out)

    def test_low_confidence_correction_is_not_confident_and_corrected(self):
        """نفسُ التصحيح تحت عتبة العرض الواثق: لا إنذار (وإلّا صار المؤشّر بلا معنى)."""
        self._capture(suggested_number='154', final_number='1831', conf=0.40)
        out = _run()
        self.assertNotIn('لا إصدارَ جديد', out)
        self.assertIn('0 / 0', out)

    def test_undisplayed_suggestion_is_not_confident_and_corrected(self):
        """اقتراحٌ لم يُعرض على الكاتب لا يدخل المقام: «لم يُصحَّح» عنه لا يعني «صحيح».

        يُبنى الصفُّ هنا يدويّاً لا عبر الالتقاط — هذا حرزُ **القارئ** لعقد
        المفاتيح، فيجب أن يصمد ولو تبدّل الكاتب.
        """
        book = Book.objects.create(kind='incoming_internal', our_number='',
                                   title='ع', sender_number='1831', created_by=self.user)
        att = Attachment.objects.create(book=book)
        ocr = OCRResult.objects.create(attachment=att, status='completed', raw_text='x')
        ex = DataExtractionResult.objects.create(
            ocr_result=ocr, attachment=att, book=book, status='reviewed',
            additional_data={
                'book_kind': 'incoming_internal',
                'sender_number_suggested': '154', 'sender_number_final': '1831',
                'sender_number_confidence': 0.99,
                'sender_number_bbox': [0.1, 0.15, 0.2, 0.18],
                'sender_number_displayed': False,      # الرايةُ تحسم
            })
        ExtractionFeedback.objects.create(
            extraction=ex, field_name='sender_number', feedback_type='incorrect',
            original_value='154', corrected_value='1831', created_by=self.user)

        out = _run()
        self.assertIn('1 / 500 زوجاً', out)            # الزوجُ يُعدّ للتدريب
        self.assertIn('العدد   (عُرض بثقة ≥0.90) : 0 / 0', out)   # ولا يدخل المقام
        self.assertNotIn('لا إصدارَ جديد', out)

    def test_late_correction_detected_after_book_changes(self):
        """المؤشّر ④: تعديلُ الكتاب بعد الالتقاط يجعل الزوجَ مسموماً ⟵ يُعدّ."""
        book, _ = self._capture(suggested_number='1831', final_number='1831')
        self.assertIn('0 / 1 صفّاً', _run())        # قبل التعديل: مطابق

        book.sender_number = '1837'                 # الكاتب صحّح لاحقاً
        book.save(update_fields=['sender_number'])
        out = _run()
        self.assertIn('1 / 1 صفّاً', out)
        self.assertIn('متأخّرة 1', out)

    def test_digit_script_change_is_not_a_late_correction(self):
        """أرقامٌ عربيّة-هنديّة لنفس القيمة ليست تصحيحاً (نظيرُ حارس الالتقاط)."""
        book, _ = self._capture(suggested_number='1831', final_number='1831')
        book.sender_number = '١٨٣١'
        book.save(update_fields=['sender_number'])
        self.assertIn('0 / 1 صفّاً', _run())

    def test_heartbeat_screams_when_saves_exist_without_capture(self):
        """حفظاتُ واردٍ بلا التقاطٍ في نفس الأسبوع = حلقةٌ مقطوعة لا بطيئة."""
        Book.objects.create(kind='incoming_internal', our_number='', title='ت',
                            created_by=self.user)
        out = _run()
        self.assertIn('صفرُ التقاطٍ في أسبوعٍ نشط', out)
        self.assertIn('عيّنةٌ منحازة', out)          # التغطية 0% تحت الأرضيّة

    def test_imported_paper_rows_excluded_from_coverage_denominator(self):
        """المستوردُ من الورق (`source_ref`) لا يمرّ بالمسح — إدخالُه يزيّف التغطية."""
        Book.objects.create(kind='incoming_internal', our_number='', title='ورق',
                            source_ref='IIMAIL_2025#7', created_by=self.user)
        self._capture(suggested_number='1831', final_number='1831')
        out = _run()
        self.assertIn('حفظاتُ وارد (بالتطبيق) 1 · سجلّاتُ التقاط 1 ⟵ 100.0%', out)
        self.assertIn('1 صفّاً مستورداً من الورق', out)
