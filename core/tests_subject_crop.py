"""«أين الموضوع؟» — قصاصةُ الموضوع (قرارُ المالك 2026‑09‑11): المخزن، الهندسة، البوّابة،
ونقطتا النهاية. OCR يُحقَن (لا محرّكَ في الاختبارات)؛ الصورُ تُرسَم بـPIL."""

import json
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from PIL import Image, ImageDraw

from core.extraction import subject_crop as sc


def _lines(*items):
    """(text, y, h, x=0.1, w=0.6)"""
    out = []
    for it in items:
        text, y, h = it[:3]
        x = it[3] if len(it) > 3 else 0.1
        w = it[4] if len(it) > 4 else 0.6
        out.append({'text': text, 'x': x, 'y': y, 'w': w, 'h': h})
    return out


def _page(underline_y=None):
    img = Image.new('L', (1000, 1400), 255)
    d = ImageDraw.Draw(img)
    if underline_y is not None:
        d.line([(200, int(underline_y * 1400)), (800, int(underline_y * 1400))], fill=0, width=3)
    return img


class GeometryTests(SimpleTestCase):

    def test_structural_band_needs_both_anchors(self):
        self.assertIsNone(sc.structural_box(_lines(('الى/ السادة', 0.20, 0.02), ('موضوع مهم', 0.24, 0.02))))
        box = sc.structural_box(_lines(('الى/ السادة', 0.20, 0.02), ('م/ تنفيذ الأعمال', 0.24, 0.02),
                                       ('تحية طيبة', 0.30, 0.02)))
        self.assertIsNotNone(box)
        self.assertLessEqual(box['y'], 0.24); self.assertGreaterEqual(box['y'] + box['h'], 0.26)

    def test_scoring_prefers_the_underlined_short_line_between_anchors(self):
        lines = _lines(('العدد 1234', 0.10, 0.02), ('التاريخ 2026/9/1', 0.13, 0.02),
                       ('الى/ السادة قسم المتابعة', 0.20, 0.02),
                       ('اعمال ازالة الالغام في القاطع الشمالي', 0.25, 0.02, 0.2, 0.5),
                       ('نود اعلامكم بأن الاعمال المذكورة اعلاه قد اكتملت حسب الجدول المرفق', 0.31, 0.02, 0.05, 0.9),
                       ('تحية طيبة', 0.29, 0.02))
        cands = sc.score_lines(lines, _page(underline_y=0.275))
        self.assertTrue(cands)
        self.assertIn('الالغام', cands[0]['text'])
        self.assertIn('underline', cands[0]['why'])
        self.assertNotIn('اعلامكم', cands[0]['text'])

    def test_marker_hint_beats_plain_line(self):
        lines = _lines(('الى/ السيد المدير', 0.20, 0.02), ('كلام عادي قصير', 0.24, 0.02),
                       ('م/ الاجازات', 0.27, 0.02), ('تحية طيبة', 0.32, 0.02))
        cands = sc.score_lines(lines)
        self.assertIn('الاجازات', cands[0]['text'])

    def test_underline_rows_detects_a_long_dark_row(self):
        rows = sc.underline_rows(_page(underline_y=0.5))
        self.assertTrue(any(abs(r - 0.5) < 0.01 for r in rows))
        self.assertEqual(sc.underline_rows(_page()), [])

    def test_normalise_rejects_a_stray_click(self):
        self.assertIsNone(sc.normalise_box({'x': 0.5, 'y': 0.5, 'w': 0.01, 'h': 0.01}))
        self.assertEqual(sc.normalise_box({'x': 0.9, 'y': 0.9, 'w': 0.5, 'h': 0.5}),
                         {'x': 0.9, 'y': 0.9, 'w': 0.1, 'h': 0.1})


@override_settings(SUBJECT_BOXES_PATH='/tmp/lettersys_subject_boxes_test.json')
class StoreAndGateTests(TestCase):

    def setUp(self):
        import os
        p = sc.store_path()
        if os.path.exists(p):
            os.remove(p)

    def test_learning_needs_three_confirmed_samples_and_uses_the_median(self):
        for y in (0.20, 0.21, 0.40):
            sc.record_sample(7, {'x': 0.1, 'y': y, 'w': 0.7, 'h': 0.03}, 'موضوع')
            self.assertIsNone(sc.learned_box(7) if y != 0.40 else None)
        box = sc.learned_box(7)
        self.assertEqual(box['y'], 0.21, 'الوسيطُ لا المتوسّط — القصّةُ الشاذّة لا تجرّ الباقي')

    def test_relative_proposal_follows_the_recipient_line(self):
        lines = _lines(('الى/ السادة', 0.20, 0.02), ('تحية طيبة', 0.30, 0.02))
        for _ in range(3):
            sc.record_sample_with_anchor(9, {'x': 0.1, 'y': 0.25, 'w': 0.7, 'h': 0.03}, 'م', lines)
        shifted = _lines(('الى/ السادة', 0.32, 0.02), ('تحية طيبة', 0.42, 0.02))
        prop = sc.propose(9, shifted)
        self.assertEqual(prop['source'], 'learned-relative')
        self.assertAlmostEqual(prop['box']['y'], 0.37, places=3)

    def test_green_gate_reads_the_learned_box_and_respects_the_guards(self):
        for _ in range(3):
            sc.record_sample(11, {'x': 0.1, 'y': 0.25, 'w': 0.7, 'h': 0.04}, 'م')
        img = _page()
        good = sc.learned_fill(img, 11, ocr=lambda region: 'الموضوع: تنفيذ اعمال ازالة الالغام')
        self.assertIsNotNone(good)
        self.assertEqual(good['text'], 'تنفيذ اعمال ازالة الالغام')
        self.assertEqual(good['confidence'], sc.LEARNED_CONFIDENCE)
        junk = sc.learned_fill(img, 11, ocr=lambda region: ',+ t? I \\\\,(')
        self.assertIsNone(junk, 'خردةٌ اجتازت البوّابة الخضراء')
        self.assertIsNone(sc.learned_fill(img, 12345, ocr=lambda r: 'أيّ شيء'), 'جهةٌ بلا عيّنات مُلئت')

    def test_edited_text_never_teaches(self):
        u = User.objects.create_user('sbx', password='pw-sbx-11')
        self.client.force_login(u)
        cache.set('subject_lines:tok1', [], 900)
        r = self.client.post(reverse('ai_subject_box_confirm'), data=json.dumps({
            'page_token': 'tok1', 'entity_id': 21, 'box': {'x': 0.1, 'y': 0.2, 'w': 0.6, 'h': 0.03},
            'text': 'موضوع', 'edited': True}), content_type='application/json')
        self.assertEqual(r.json()['learned'], False)
        self.assertEqual(sc.samples_of(21), [])
        r = self.client.post(reverse('ai_subject_box_confirm'), data=json.dumps({
            'page_token': 'tok1', 'entity_id': 21, 'box': {'x': 0.1, 'y': 0.2, 'w': 0.6, 'h': 0.03},
            'text': 'موضوع', 'edited': False}), content_type='application/json')
        self.assertEqual(r.json()['learned'], True)
        self.assertEqual(len(sc.samples_of(21)), 1)

    def test_read_endpoint_uses_the_cached_page_and_expires(self):
        import io
        u = User.objects.create_user('sbr', password='pw-sbr-11')
        self.client.force_login(u)
        buf = io.BytesIO(); _page().save(buf, format='JPEG')
        cache.set('subject_page:tok2', buf.getvalue(), 900)
        with mock.patch.object(sc, '_default_ocr', return_value='م/ ضوابط استيراد المواد'):
            r = self.client.post(reverse('ai_subject_box_read'), data=json.dumps({
                'page_token': 'tok2', 'box': {'x': 0.1, 'y': 0.2, 'w': 0.6, 'h': 0.05}}),
                content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content[:200])
        self.assertEqual(r.json()['text'], 'ضوابط استيراد المواد')
        self.assertTrue(r.json()['accepted'])
        r = self.client.post(reverse('ai_subject_box_read'), data=json.dumps({
            'page_token': 'nope', 'box': {'x': 0.1, 'y': 0.2, 'w': 0.6, 'h': 0.05}}),
            content_type='application/json')
        self.assertEqual(r.status_code, 410)


class PipelineHookTests(TestCase):
    """الخطّافُ في الأنبوب: صمتٌ ⟵ اقتراحٌ برمزِ صفحةٍ محفوظة؛ جهةٌ متعلَّمة ⟵ بوّابةٌ خضراء."""

    def _service(self):
        from core.extraction.pipeline import AIExtractionService
        return AIExtractionService()

    @override_settings(SUBJECT_BOXES_PATH='/tmp/lettersys_subject_boxes_hook.json')
    def test_silence_yields_a_proposal_with_a_cached_page(self):
        import os, tempfile
        from core.extraction.pipeline import AIExtractionResult
        path = sc.store_path()
        if os.path.exists(path): os.remove(path)
        fd, tmp = tempfile.mkstemp(suffix='.png'); os.close(fd)
        _page(underline_y=0.3).save(tmp)
        svc = self._service()
        res = AIExtractionResult()
        res.title = ''; res.issuing_entity_id = None
        with mock.patch.object(svc, '_ensure_ocr_stack', side_effect=RuntimeError('no ocr')):
            svc._propose_subject_box(res, tmp)
        prop = res.subject_box_proposal
        self.assertIsNotNone(prop)
        self.assertIn(prop['source'], ('default', 'structural', 'scored'))
        self.assertTrue(prop['page_preview'].startswith('data:image/jpeg;base64,'))
        self.assertTrue(cache.get('subject_page:' + prop['page_token']))
        self.assertEqual(res.title, '')

    @override_settings(SUBJECT_BOXES_PATH='/tmp/lettersys_subject_boxes_hook2.json')
    def test_learned_entity_fills_the_title_green(self):
        import os, tempfile
        from core.extraction.pipeline import AIExtractionResult
        path = sc.store_path()
        if os.path.exists(path): os.remove(path)
        for _ in range(3):
            sc.record_sample(55, {'x': 0.1, 'y': 0.25, 'w': 0.7, 'h': 0.04}, 'م')
        fd, tmp = tempfile.mkstemp(suffix='.png'); os.close(fd)
        _page().save(tmp)
        svc = self._service()
        res = AIExtractionResult()
        res.title = ''; res.issuing_entity_id = 55
        with mock.patch.object(svc, '_ensure_ocr_stack', side_effect=RuntimeError('no ocr')), \
             mock.patch.object(sc, '_default_ocr', return_value='الموضوع: تقرير الربع الثالث'):
            svc._propose_subject_box(res, tmp)
        self.assertEqual(res.title, 'تقرير الربع الثالث')
        self.assertEqual(res.title_confidence, sc.LEARNED_CONFIDENCE)
        self.assertEqual(res.subject_box_proposal['source'], 'learned-filled')

    def test_the_input_page_carries_the_card_and_the_script(self):
        u = User.objects.create_user('sbp', password='pw-sbp-11')
        self.client.force_login(u)
        r = self.client.get(reverse('extraction-smart-desktop'))
        self.assertContains(r, 'id="subjectLocate"')
        self.assertContains(r, 'js/subject_locate.js')


class EntityProfileCacheSelfHealsTests(TestCase):
    """الكاشُ «الذي يشفى ذاتيّاً» (إنتاج 2026‑09‑01) لم يكن يشفى: `Entity` غيرُ مستورَد
    فيُبتلَع NameError ويبقى العدُّ القديم. الآن تغيّرُ عدد الجهات يُعيد البناء."""

    def test_adding_an_entity_invalidates_the_cached_store(self):
        from core.extraction.entity_profiles import EntityResolver
        from core.models import Entity
        EntityResolver._cache = None; EntityResolver._cache_n = -1
        first = EntityResolver.get()
        Entity.objects.create(name='جهةٌ جديدة تُعيد البناء')
        second = EntityResolver.get()
        self.assertIsNot(first, second, 'الكاشُ لم يُعَد بناؤه بعد تغيّر عدد الجهات')
