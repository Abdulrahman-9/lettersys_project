# -*- coding: utf-8 -*-
"""حرزُ اقتراح التاريخ — القانون: **صفرُ ملءٍ تلقائيٍّ صامت**، وامتناعٌ عند الالتباس.

سابقةُ التسميم (2026-07-16 ⟵ الجذر 2026-08-19): كان الحقل يُملأ بتاريخ اليوم
تلقائيّاً فحُفظ تاريخُ الإدخال بدل حبر الجهة في آلاف الصفوف. وقارئُ D2 دقّتُه
71.1% — فوضعُ قراءته في `sender_date` (وهو ما تكتبه مسارات الملء في الحقل
صامتاً) كان سيُعيد بناء التسميم آليّاً. هذه الاختبارات تقفل ذلك بالبناء.
"""
import datetime

from django.test import SimpleTestCase, TestCase

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


class DrawnDateCandidatesTests(SimpleTestCase):
    """بندُ نيلسن 7 (مذكّرة فيبل 10): الغامضُ يعرض مرشّحَيه زرَّين يختار الكاتبُ أحدهما —
    **لا حسمَ آليّ**؛ وكلُّ حالةٍ غيرِ غامضةٍ بلا مرشّحين (لا يفتح بابَ تخمين)."""
    TODAY = datetime.date(2026, 9, 29)

    def test_ambiguous_gives_both_readings_sorted(self):
        from core.extraction.handwriting.date_parse import drawn_date_candidates
        self.assertEqual(drawn_date_candidates('26/9/15', today=self.TODAY), ['2015-09-26', '2026-09-15'])

    def test_resolved_or_invalid_gives_none(self):
        from core.extraction.handwriting.date_parse import drawn_date_candidates
        for raw in ('2026/9/15', '25/3/6', '31/2/2025', 'ab/3/6', ''):
            self.assertEqual(drawn_date_candidates(raw, today=self.TODAY), [], raw)

    def test_window_that_resolves_leaves_no_candidates(self):
        from core.extraction.handwriting.date_parse import drawn_date_candidates
        self.assertEqual(drawn_date_candidates('24/8/26', entry_date=datetime.date(2026, 8, 26),
                                               today=self.TODAY), [])

    def test_no_candidate_after_the_entry_date(self):
        """«26/12/15» ⟵ 2015‑12‑26 و2026‑12‑15؛ الثاني بعد اليوم/القيد فلا يُعرض زرّاً (نقرةٌ عليه
        كانت تكتبه `confirmed`). الباقي وحدَه يبقى **مرشّحاً** يُنقر لا حسماً (الامتناعُ قائم)."""
        from core.extraction.handwriting.date_parse import drawn_date_candidates
        self.assertEqual(drawn_date_candidates('26/12/15', today=self.TODAY), ['2015-12-26'])
        self.assertEqual(drawn_date_candidates('26/12/15', entry_date=datetime.date(2026, 9, 20),
                                               today=self.TODAY), ['2015-12-26'])
        self.assertEqual(parse_drawn_date('26/12/15', today=self.TODAY), (None, 'ambiguous'))

    def test_parse_behaviour_unchanged_by_the_refactor(self):
        """استخراجُ المرشّحين دالّةً مشتركة لا يغيّر حكمَ التحليل (مصدرٌ واحد)."""
        self.assertEqual(parse_drawn_date('26/9/15', today=self.TODAY), (None, 'ambiguous'))
        self.assertEqual(parse_drawn_date('26/9/15', entry_date=datetime.date(2026, 9, 20),
                                          today=self.TODAY), ('2026-09-15', 'ok'))


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

    **القانونُ بعد قرار المالك (2026-09-01)**: الملءُ التلقائيّ مسموحٌ للقراءة
    الخضراء وحدَها وموسوماً — لا مكتوماً ولا صامتاً. فالمحروسُ هنا شيئان:
      1. كاتبا الحقل **اثنان لا غير**: التأكيدُ بنقرة، والملءُ الأخضر.
      2. شرطُ الملء مجموعٌ في موضعٍ واحد (`_sdAutofillEligible`) يضمّ العتبةَ
         المقيسة وسلامةَ التحليل وحارسَ الفارق — فارتخاءُ أحدها يفشل صاخباً.
    وجذرُ التسميم الأصليّ (ملءُ **تاريخ اليوم** بلا قراءة) يبقى ممنوعاً بالبناء:
    القيمةُ المكتوبة هي `iso` القادمُ من القارئ لا تاريخٌ مُختلَق.
    """

    JS = 'static/extraction_smart.js'

    def _src(self):
        import os
        from django.conf import settings
        with open(os.path.join(settings.BASE_DIR, self.JS), encoding='utf-8') as f:
            return f.read()

    def _body(self, src, header):
        body = src[src.index(header):]
        return body[:body.index(chr(10) + '}')]

    def test_only_two_named_functions_write_the_field(self):
        """كاتبا الحقل اثنان: **نقرةُ الكاتب** (`_writeSenderDate` — يمرّ بها «تأكيد» وزرّا مرشّحَي
        الغامض، نيلسن 7) و**الملءُ الأخضر** (`_autofillSenderDate`)."""
        src = self._src()
        writer = self._body(src, 'function _writeSenderDate')
        autofill = self._body(src, 'function _autofillSenderDate')
        confirm = self._body(src, 'function _confirmSenderDateSuggestion')
        self.assertIn("el.value = iso", writer)
        self.assertIn('PROV_CONFIRMED', writer)
        self.assertIn("el.value = iso", autofill)
        self.assertIn('_writeSenderDate(card.dataset.iso)', confirm)
        # خارجهما: لا كتابةَ قيمةٍ في العنصر من الاقتراح
        rest = src.replace(writer, '').replace(autofill, '')
        for forbidden in ("senderDate').value =", 'senderDate").value =', 'el.value = iso',
                          "setVal('senderDate', data.sender_date_suggestion"):
            self.assertNotIn(forbidden, rest)

    def test_enter_never_overwrites_a_different_typed_date(self):
        """نيلسن 2: Enter للانتقال لا لاستبدال تاريخٍ كتبه الكاتب."""
        confirm = self._body(self._src(), 'function _confirmSenderDateSuggestion')
        self.assertIn('if (cur && cur !== card.dataset.iso) return false;', confirm)

    def test_ambiguous_shows_choices_never_autofills(self):
        """الغامضُ: مرشّحان زرّان — ولا يبلغ الملءَ التلقائيّ (لا iso)."""
        renderer = self._body(self._src(), 'function applySenderDateSuggestion')
        self.assertIn("sug.parse === 'ambiguous'", renderer)
        self.assertIn('date-suggest__choice', renderer)
        eligible = self._body(self._src(), 'function _sdAutofillEligible')
        self.assertIn('sug.iso', eligible)

    def test_autofill_requires_green_and_parse_and_gap_guard(self):
        """الشروطُ الثلاثة في موضعٍ واحد — ارتخاءُ أيّها يفشل هنا لا في الإنتاج."""
        eligible = self._body(self._src(), 'function _sdAutofillEligible')
        self.assertIn("conf >= green", eligible)
        self.assertIn("sug.parse === 'ok'", eligible)
        self.assertIn("guard.state === 'ok'", eligible)

    def test_autofill_marks_provenance_and_never_overwrites(self):
        """المملوءُ آليّاً يُستبعَد من ذهب التدريب، وقيمةُ الكاتب لا تُدهَس."""
        autofill = self._body(self._src(), 'function _autofillSenderDate')
        self.assertIn('PROV_AUTOFILLED', autofill)
        self.assertIn("if (String(el.value || '').trim()) return false;", autofill)

    def test_autofill_is_reached_only_through_the_eligibility_gate(self):
        """لا نداءَ ثانياً للملء يلتفّ على الشرط."""
        src = self._src()
        self.assertEqual(src.count('_autofillSenderDate('), 2)   # تعريفٌ + نداءٌ واحد
        renderer = self._body(src, 'function applySenderDateSuggestion')
        self.assertIn('_sdAutofillEligible(sug, conf, green, guard)', renderer)

    def test_renderer_is_the_single_entry_point_for_all_three_paths(self):
        """مسارات الملء الثلاثة (كاش المسح · البثّ · الرفع) تمرّ بنقطةٍ واحدة."""
        self.assertGreaterEqual(self._src().count('applySenderDateSuggestion('), 3)


class PrintedNumberEmissionTests(SimpleTestCase):
    """S4: المطبوعُ يُفتح سقوطاً ثانياً — **والمرآةُ تبقى crnn-فقط**.

    الفخُّ الذي تقفله هذه الاختبارات (تحذيرُ فيبل 2026-08-26): لو عُدّ المطبوعُ
    ناجياً في `_sender_number_survives_emission`، لمنع شرطُ `not _survives`
    المحاولةَ البصريّة — **فيُنقض S3′ صامتاً** بلا خطأٍ ولا اختبارٍ أحمر.
    """

    def _r(self, **kw):
        r = AIExtractionResult()
        for k, v in kw.items():
            setattr(r, k, v)
        return r

    def test_printed_anchor_survives_emission(self):
        from core.extraction.pipeline import _suppress_sender_number_emission
        r = self._r(sender_number='NK-20260350', sender_number_confidence=0.70,
                    sender_number_source='printed_anchor')
        _suppress_sender_number_emission(r)
        self.assertEqual(r.sender_number, 'NK-20260350')

    def test_other_text_writers_stay_silenced(self):
        from core.extraction.pipeline import _suppress_sender_number_emission
        r = self._r(sender_number='1942', sender_number_confidence=0.65,
                    sender_number_source='ref_num')
        _suppress_sender_number_emission(r)
        self.assertFalsy = self.assertFalse(r.sender_number)

    def test_mirror_stays_crnn_only(self):
        """**الحرزُ الأهمّ**: المطبوعُ لا ينجو في المرآة — وإلّا مُنعت المحاولةُ البصريّة."""
        from core.extraction.pipeline import _sender_number_survives_emission
        printed = self._r(sender_number='NK-1', sender_number_source='printed_anchor')
        visual = self._r(sender_number='7099', sender_number_bbox_source='crnn')
        self.assertFalse(_sender_number_survives_emission(printed),
                         'المطبوعُ نجا في المرآة ⟵ المحاولةُ البصريّة ستُمنع وS3′ يُنقض صامتاً')
        self.assertTrue(_sender_number_survives_emission(visual))

    def test_printed_confidence_below_confident_wrong_threshold(self):
        """0.70 دون 0.90 بنائيّاً — فلا يستطيع هذا المسار خرقَ الحارس رياضيّاً."""
        from core.extraction.handwriting.reader import CONF_GATE
        self.assertLess(0.70, CONF_GATE)


class StructuralVetoTests(TestCase):
    """حرزُ النقض البنيويّ — يفشل **صاخباً** إن انجرفت واجهةُ البصمات.

    النسخةُ الأولى حرست نفسَها بـ`hasattr` على واجهتين غير موجودتين، فتدهورت
    إلى **صفر نقضٍ صامت**: لا خطأٌ ولا تنبيهٌ ولا أثر. هذه الاختبارات تستدعي
    الواجهةَ الحقيقيّة مباشرةً فلا يمكن أن يتكرّر الصمت.
    """

    def test_profiles_expose_the_interface_the_veto_uses(self):
        from core.extraction.matchers.profile import SenderNumberProfiles
        p = SenderNumberProfiles()
        self.assertTrue(callable(getattr(p, 'repair', None)),
                        'واجهةُ repair اختفت — النقضُ البنيويّ سيصمت')
        self.assertTrue(callable(getattr(p, '_ensure_index', None)))
        self.assertIsInstance(getattr(p, '_profiles', None), dict)

    def test_known_prefix_set_builds(self):
        from core.extraction.matchers.profile import SenderNumberProfiles
        from core.extraction.pipeline import _known_prefixes
        self.assertIsInstance(_known_prefixes(SenderNumberProfiles()), set)

    def test_no_entity_means_no_veto(self):
        from core.extraction.pipeline import _printed_number_vetoed
        r = AIExtractionResult()
        r.sender_number = 'llK-20260257'
        self.assertFalse(_printed_number_vetoed(r))

    def test_plain_digits_are_never_vetoed(self):
        """النقضُ يخصّ البادئات الألفبائيّة وحدها — الأرقامُ المجرّدة خارجه."""
        from core.extraction.pipeline import _printed_number_vetoed
        r = AIExtractionResult()
        r.sender_number = '7099'
        r.issuing_entity_id = 1
        self.assertFalse(_printed_number_vetoed(r))


class FailClosedGuardTests(SimpleTestCase):
    """حارسُ الفارق يُغلَق عند الفراغ، والوسمُ `autofilled` صار يُقرأ لا يُكتب فقط.

    مراجعة 2026-09-01: `_senderDateGuard` كان يعود `ok` حين يخلو تاريخُ القيد
    فيُملأ الأخضرُ بلا فحصِ التباس الختم — فشلٌ مفتوحٌ في مشروعٍ سمّمه افتراضٌ
    مفتوح. و`harvest_dates.py` لم يكن يستشير الوسمَ إطلاقاً، فالضمانُ المكتوبُ في
    السجلّ («المملوءُ آليّاً يخرج من ذهب التدريب») كان حبراً.
    """

    def _read(self, rel):
        import os
        from django.conf import settings
        with open(os.path.join(settings.BASE_DIR, rel), encoding='utf-8') as f:
            return f.read()

    def test_empty_registration_date_is_unknown_not_ok(self):
        src = self._read('static/extraction_smart.js')
        body = src[src.index('function _senderDateGuard'):]
        body = body[:body.index('\n}')]
        self.assertIn("if (gap === null) return { state: 'unknown', gap: null };", body)
        self.assertNotIn("if (gap === null) return { state: 'ok'", body)

    def test_autofill_requires_a_known_ok_gap(self):
        src = self._read('static/extraction_smart.js')
        body = src[src.index('function _sdAutofillEligible'):]
        body = body[:body.index('\n}')]
        self.assertIn("guard.state === 'ok'", body)

    def test_date_harvest_excludes_autofilled_rows(self):
        src = self._read('scripts/eval/harvest_dates.py')
        self.assertIn("additional_data__sender_date_provenance='autofilled'", src)
        self.assertIn('if bid in _autofilled_dates:', src)
