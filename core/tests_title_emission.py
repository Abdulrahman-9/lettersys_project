# -*- coding: utf-8 -*-
"""حرزُ سياسة انبعاث الموضوع — المسارُ القويّ يملأ، والضعيفُ بطاقةٌ لا قيمة.

**ما تقفله هذه الاختبارات** (قرار المالك 2026-09-01): كان مُنتقي الموضوع يكتب
قيمتَه في حقل الكاتب مهما كان مسارُه، والثقةُ تُلوّن الشارة ولا تحجب القيمة —
فقِيس على المجموعة المختومة subject-200 أنّ **ربع المستندات** (الاحتياطيّ 46
والقوس 5 من 190) يُملأ حقلُها بقيمةٍ خاطئةٍ 91% من الوقت. الآن يُوجَّه الضعيفُ
إلى مفتاحٍ منفصل، وبلا اختبارٍ هنا يعود الملءُ صامتاً بأيّ إعادةِ ترتيبٍ للأسطر
(نفسُ فخّ المرآة في جبهة العدد).
"""
from django.test import SimpleTestCase

from core.extraction.pipeline import (AIExtractionResult, TITLE_DIRECT_FILL_SOURCES,
                                      _route_title_emission, result_to_scan_data)


def _r(title='موضوع الكتاب المُختبَر', conf=0.75):
    r = AIExtractionResult()
    r.title = title
    r.title_confidence = conf
    return r


class TitleEmissionRoutingTests(SimpleTestCase):

    def test_marker_path_fills_the_field(self):
        """المسارُ الوحيد المقيس صالحاً 72.9% — يبقى ملءً مباشراً."""
        r = _r()
        _route_title_emission(r, 'marker')
        self.assertEqual(r.title, 'موضوع الكتاب المُختبَر')
        self.assertEqual(r.title_confidence, 0.75)
        self.assertIsNone(r.title_suggestion)

    def test_fallback_path_becomes_a_suggestion(self):
        r = _r(conf=0.35)
        _route_title_emission(r, 'fallback')
        self.assertEqual(r.title, '')
        self.assertEqual(r.title_confidence, 0.0)
        self.assertEqual(r.title_suggestion['value'], 'موضوع الكتاب المُختبَر')
        self.assertEqual(r.title_suggestion['confidence'], 0.35)
        self.assertEqual(r.title_suggestion['source'], 'fallback')

    def test_bracket_paths_become_suggestions(self):
        for source in ('bracket_ar', 'bracket_en'):
            r = _r(conf=0.0)
            _route_title_emission(r, source)
            self.assertEqual(r.title, '', source)
            self.assertEqual(r.title_suggestion['source'], source)

    def test_unknown_future_source_is_weak_by_default(self):
        """كاتبٌ جديدٌ لا يُملأ حتّى يُقاس — الافتراضُ ضدّ الملء لا معه."""
        r = _r(conf=0.9)
        _route_title_emission(r, 'crop_reader_v1')
        self.assertEqual(r.title, '')
        self.assertEqual(r.title_suggestion['source'], 'crop_reader_v1')

    def test_silence_stays_silence(self):
        r = _r(title='', conf=0.0)
        _route_title_emission(r, '')
        self.assertEqual(r.title, '')
        self.assertIsNone(r.title_suggestion)

    def test_only_marker_is_a_direct_fill_source(self):
        """توسيعُ المجموعة يحتاج قياساً على مجموعةٍ مختومة — لا تمريرَ صامتاً."""
        self.assertEqual(tuple(TITLE_DIRECT_FILL_SOURCES), ('marker',))


class TitleSuggestionPayloadTests(SimpleTestCase):

    def test_suggestion_never_lands_in_title(self):
        r = _r(conf=0.35)
        _route_title_emission(r, 'fallback')
        data = result_to_scan_data(r)
        self.assertEqual(data['title'], '')
        self.assertEqual(data['title_confidence'], 0.0)
        self.assertEqual(data['title_suggestion']['value'], 'موضوع الكتاب المُختبَر')

    def test_absent_suggestion_is_none_not_missing(self):
        data = result_to_scan_data(AIExtractionResult())
        self.assertIn('title_suggestion', data)
        self.assertIsNone(data['title_suggestion'])

    def test_weak_confidence_leaves_field_confidences(self):
        """قيمةٌ لا تبلغ الكاتب لا تجرّ `overall_confidence` إلى manual_review."""
        r = _r(conf=0.35)
        _route_title_emission(r, 'fallback')
        self.assertEqual(r.title_confidence, 0.0)


class TitleZeroAutofillSourceGuardTests(SimpleTestCase):
    """حرزٌ بنيويٌّ على مصدر الواجهة — لا مُشغّلَ اختباراتِ JS في المشروع."""

    JS = 'static/extraction_smart.js'

    def _src(self):
        import os
        from django.conf import settings
        with open(os.path.join(settings.BASE_DIR, self.JS), encoding='utf-8') as f:
            return f.read()

    def _body(self, src, header):
        body = src[src.index(header):]
        return body[:body.index(chr(10) + '}')]

    def test_only_the_confirm_function_writes_the_title(self):
        src = self._src()
        confirm = self._body(src, 'function _confirmTitleSuggestion')
        self.assertIn("el.value = card.dataset.value", confirm)
        # العارضُ لا يمسك عنصرَ الحقل أصلاً — حرزٌ أقوى من منع الإسناد:
        # لا يستطيع الكتابةَ فيه ولو أُعيدت كتابةُ جسمه.
        render = self._body(src, 'function applyTitleSuggestion')
        self.assertNotIn("_tsEl('title')", render)
        self.assertNotIn("getElementById('title')", render)
        rest = src.replace(confirm, '')
        for forbidden in ("setVal('title', data.title_suggestion",
                          "'title', data.title_suggestion"):
            self.assertNotIn(forbidden, rest)

    def test_confirmed_not_typed(self):
        """نقرةُ تأكيدٍ ليست شهادةَ تقييمٍ مستقلّة — ولا حقيقةَ تدريبٍ نظيفة."""
        confirm = self._body(self._src(), 'function _confirmTitleSuggestion')
        self.assertIn('PROV_CONFIRMED', confirm)

    def test_title_is_in_the_provenance_contract(self):
        """بلا الوسم يعود الحصادُ يدرّب المُنتقي على مخرجه هو."""
        src = self._src()
        self.assertIn("const PROVENANCE_FIELD_IDS = ['senderNumber', 'senderDate', 'title'];", src)
        self.assertIn("formData.append('title_provenance', _tProv)", src)

    def test_renderer_is_called_from_all_three_fill_paths(self):
        self.assertGreaterEqual(self._src().count('applyTitleSuggestion('), 4)
