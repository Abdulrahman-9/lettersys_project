# -*- coding: utf-8 -*-
"""حرزُ اقتراح التاريخ — القانون: **صفرُ ملءٍ تلقائيٍّ صامت**، وامتناعٌ عند الالتباس.

سابقةُ التسميم (2026-07-16 ⟵ الجذر 2026-08-19): كان الحقل يُملأ بتاريخ اليوم
تلقائيّاً فحُفظ تاريخُ الإدخال بدل حبر الجهة في آلاف الصفوف. وقارئُ D2 دقّتُه
71.1% — فوضعُ قراءته في `sender_date` (وهو ما تكتبه مسارات الملء في الحقل
صامتاً) كان سيُعيد بناء التسميم آليّاً. هذه الاختبارات تقفل ذلك بالبناء.
"""
import datetime

from django.test import SimpleTestCase

from core.extraction.handwriting.date_parse import parse_drawn_date
from core.extraction.pipeline import AIExtractionResult, result_to_scan_data


class DrawnDateParseTests(SimpleTestCase):
    ENTRY = datetime.date(2026, 8, 26)

    def test_four_digit_year_left_is_ymd(self):
        self.assertEqual(parse_drawn_date('2025/3/6')[0], '2025-03-06')

    def test_four_digit_year_right_is_dmy(self):
        self.assertEqual(parse_drawn_date('6/3/2025')[0], '2025-03-06')

    def test_day_over_31_end_is_year_even_with_two_digits(self):
        """طرفٌ يفوق أقصى يومٍ سنةٌ حصراً — لا التباس."""
        self.assertEqual(parse_drawn_date('99/3/6')[0], None)      # 2099 خارج النافذة

    def test_two_digit_year_resolves_when_only_one_side_plausible(self):
        # 25 سنةٌ معقولة و6 ليست (2006 < 2014) ⟵ حسمٌ بلا نافذة
        self.assertEqual(parse_drawn_date('25/3/6')[0], '2025-03-06')
        self.assertEqual(parse_drawn_date('6/3/25')[0], '2025-03-06')

    def test_both_sides_plausible_years_use_entry_window(self):
        """«24/8/26» — 2024-08-26 و2026-08-24 كلاهما صالح؛ النافذة تحسم."""
        iso, status = parse_drawn_date('24/8/26', entry_date=self.ENTRY)
        self.assertEqual((iso, status), ('2026-08-24', 'ok'))

    def test_ambiguous_without_window_abstains(self):
        iso, status = parse_drawn_date('24/8/26')
        self.assertIsNone(iso)
        self.assertEqual(status, 'ambiguous')

    def test_impossible_calendar_date_abstains_not_repairs(self):
        """31/2 ليست 28/2 — «الإصلاح» تخمينٌ صامتٌ ممنوع."""
        self.assertEqual(parse_drawn_date('31/2/2025'), (None, 'invalid'))

    def test_month_out_of_range_abstains(self):
        self.assertEqual(parse_drawn_date('2025/13/6'), (None, 'invalid'))

    def test_malformed_shapes_abstain(self):
        for raw in ('', '2025', '2025/3', '2025/3/6/7', 'ab/3/6', None):
            self.assertEqual(parse_drawn_date(raw)[1], 'invalid', raw)


class SuggestionPayloadTests(SimpleTestCase):
    def test_suggestion_never_lands_in_sender_date(self):
        """المفتاحان منفصلان — الواجهةُ تكتب `sender_date` في الحقل صامتاً."""
        r = AIExtractionResult()
        r.sender_date_suggestion = {'raw': '2025/3/6', 'iso': '2025-03-06',
                                    'parse': 'ok', 'confidence': 0.99}
        data = result_to_scan_data(r)
        self.assertIsNone(data['sender_date'])
        self.assertEqual(data['sender_date_suggestion']['iso'], '2025-03-06')

    def test_absent_suggestion_is_none_not_missing(self):
        data = result_to_scan_data(AIExtractionResult())
        self.assertIn('sender_date_suggestion', data)
        self.assertIsNone(data['sender_date_suggestion'])

    def test_suggestion_confidence_stays_out_of_field_confidences(self):
        """وإلّا جرّت `overall_confidence` فقلبت كتباً إلى manual_review صامتاً."""
        r = AIExtractionResult()
        r.sender_date_suggestion = {'iso': '2025-03-06', 'confidence': 0.10}
        self.assertNotIn('sender_date', (r.field_confidences or {}))
        self.assertNotIn('sender_date_suggestion', (r.field_confidences or {}))


class ZeroAutofillSourceGuardTests(SimpleTestCase):
    """حرزٌ بنيويٌّ على مصدر الواجهة — لا مُشغّلَ اختباراتٍ لـJS في المشروع.

    يقفل قانون «صفرُ ملءٍ تلقائيٍّ صامت» عند حدّه الحقيقيّ: الموضعُ **الوحيد**
    الذي يكتب قيمةً في حقل تاريخ الجهة من الاقتراح هو دالّةُ التأكيد.
    """

    JS = 'static/extraction_smart.js'

    def _src(self):
        import os
        from django.conf import settings
        with open(os.path.join(settings.BASE_DIR, self.JS), encoding='utf-8') as f:
            return f.read()

    def test_only_the_confirm_function_writes_the_field(self):
        src = self._src()
        body = src[src.index('function _confirmSenderDateSuggestion'):]
        body = body[:body.index('\n}')]
        self.assertIn("el.value = card.dataset.iso", body)
        # خارج دالّة التأكيد: لا كتابةَ قيمةٍ في العنصر من الاقتراح
        rest = src.replace(body, '')
        for forbidden in ("senderDate').value =", 'senderDate").value =',
                          "setVal('senderDate', data.sender_date_suggestion"):
            self.assertNotIn(forbidden, rest)

    def test_renderer_is_the_single_entry_point_for_all_three_paths(self):
        """مسارات الملء الثلاثة (كاش المسح · البثّ · الرفع) تمرّ بنقطةٍ واحدة."""
        self.assertGreaterEqual(self._src().count('applySenderDateSuggestion('), 3)
