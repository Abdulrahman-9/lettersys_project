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
class MeasuredFixesTests(SimpleTestCase):
    """حرّاسُ الإصلاحات الثلاثة المقيسة (2026-09-13، مذكّرةُ فيبل الخامسة).

    كلٌّ منها كان عطباً صامتاً لم يلتقطه اختبارٌ قائم: `test_silence_yields_a_proposal_with_a_cached_page`
    يُطفئ حزمةَ OCR عمداً فيقبل `default`، فلا يرى هندسةَ أسطرٍ ميتة. وكلُّ حارسٍ هنا يُطفَّر فيحمرّ.
    """

    def _dict_tsv(self):
        # شكلُ pytesseract.Output.DICT حرفيّاً: قاموسُ **أعمدة** لا قائمةُ صفوف.
        return {
            'level': [5, 5, 5], 'page_num': [1, 1, 1], 'block_num': [1, 1, 1], 'par_num': [1, 1, 1],
            'line_num': [1, 1, 2], 'word_num': [1, 2, 1],
            'left': [100, 300, 100], 'top': [50, 50, 120], 'width': [150, 120, 400], 'height': [30, 30, 30],
            'conf': ['90', '88', '91'], 'text': ['تخصيص', 'مبالغ', 'الصيانة'],
        }

    def test_column_dict_tsv_yields_rows_not_key_names(self):
        rows = sc._tsv_records(self._dict_tsv())
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]['text'], 'تخصيص')
        self.assertEqual(int(rows[2]['line_num']), 2)

    def test_lines_from_dict_tsv_is_not_silent(self):
        # قبل الإصلاح: list(dict) يُعيد أسماءَ المفاتيح ⟵ AttributeError ⟵ lines=[] بصمتٍ عند المستدعي.
        lines = sc.lines_from_tsv(self._dict_tsv(), 1000, 1000)
        self.assertEqual(len(lines), 2)
        self.assertLess(lines[0]['y'], lines[1]['y'])

    def test_footer_recipient_does_not_drag_the_top_anchor_below_the_subject(self):
        # «إلى/» في الذيل (نسخةٌ إلى) كان يدفع المرساةَ العليا تحت الموضوع فيُقصيه (37% مقيسة).
        lines = _lines(
            ('إلى/ السيد المدير العام', 0.15, 0.02),
            ('تخصيص مبالغ صيانة المحطة', 0.30, 0.02, 0.2, 0.4),
            ('تحية طيبة وبعد', 0.40, 0.02),
            ('إلى/ السيد مدير الحسابات للعلم', 0.85, 0.02),
        )
        texts = [c['text'] for c in sc.score_lines(lines, None)]
        self.assertIn('تخصيص مبالغ صيانة المحطة', texts)

    def test_underline_swallowed_inside_the_line_box_still_counts(self):
        # Tesseract يضع الخطَّ **داخل** صندوق السطر: الصفُّ الداكنُ فوق y+h بقليل.
        # النافذةُ القديمة [y+h, y+h+0.012] لا تراه؛ المتناظرةُ [y+h−0.012, y+h+0.012] تراه.
        img = Image.new('L', (1000, 1400), 255)
        d = ImageDraw.Draw(img)
        d.rectangle([200, 440, 800, 442], fill=0)           # y≈0.3143–0.3157 < y+h=0.32
        lines = _lines(
            ('إلى/ السيد المدير العام', 0.15, 0.02),
            ('تخصيص مبالغ صيانة المحطة', 0.30, 0.02, 0.2, 0.4),
            ('تحية طيبة وبعد', 0.40, 0.02),
        )
        cand = next(c for c in sc.score_lines(lines, img) if c['text'] == 'تخصيص مبالغ صيانة المحطة')
        self.assertIn('underline', cand['why'])


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
            svc._propose_subject_box(res, tmp, det_boxes={'number': None, 'subject': None})
        prop = res.subject_box_proposal
        self.assertIsNotNone(prop)
        self.assertEqual(prop['source'], 'default')          # det2 صامت ⟵ الحزامُ الافتراضيّ للسحب
        self.assertTrue(prop['page_preview'].startswith('data:image/jpeg;base64,'))
        self.assertTrue(cache.get('subject_page:' + prop['page_token']))
        self.assertEqual(res.title, '')

    def _tmp_page(self):
        import os, tempfile
        fd, tmp = tempfile.mkstemp(suffix='.png'); os.close(fd)
        _page().save(tmp)
        return tmp

    @override_settings(SUBJECT_BOXES_PATH='/tmp/lettersys_subject_boxes_det2.json')
    def test_det2_subject_box_is_the_proposal_and_its_crop_only_a_suggestion(self):
        """مذكّرة فيبل 10: صندوقُ det2 موضعُ الاقتراح، ونصُّ قصاصته **اقتراحٌ** يحلّ محلّ
        اقتراح المُنتقي الضعيف — لا يبلغ الحقلَ وحده."""
        from core.extraction.pipeline import AIExtractionResult
        svc = self._service()
        res = AIExtractionResult()
        res.title = ''; res.issuing_entity_id = None
        res.title_suggestion = {'value': 'سطرٌ احتياطيّ', 'confidence': 0.0, 'source': 'fallback'}
        boxes = {'number': None, 'subject': ([0.10, 0.20, 0.80, 0.25], 0.87)}
        with mock.patch.object(sc, '_default_ocr', return_value='م/ تقرير الربع الثالث'):
            svc._propose_subject_box(res, self._tmp_page(), det_boxes=boxes)
        prop = res.subject_box_proposal
        self.assertEqual(prop['source'], 'det2')
        self.assertAlmostEqual(prop['box']['y'], 0.20, places=3)
        self.assertEqual(res.title, '')                                   # لا ملء
        self.assertEqual(res.title_suggestion['source'], 'det2_crop')
        self.assertEqual(res.title_suggestion['value'], 'تقرير الربع الثالث')

    @override_settings(SUBJECT_BOXES_PATH='/tmp/lettersys_subject_boxes_det2b.json')
    def test_proposal_never_reads_the_whole_page_again(self):
        """حارسُ السرعة: المُقترِح القديم كلّف قراءةَ psm 3 ثانيةً للصفحة (وسيط 1.60 ث)."""
        from core.extraction.pipeline import AIExtractionResult
        svc = self._service()
        res = AIExtractionResult()
        res.title = ''; res.issuing_entity_id = None
        boxes = {'number': None, 'subject': ([0.10, 0.20, 0.80, 0.25], 0.9)}
        with mock.patch('pytesseract.image_to_data', side_effect=AssertionError('قراءةُ صفحةٍ ثانية')), \
             mock.patch.object(sc, '_default_ocr', return_value='م/ صيانة المضخّات'):
            svc._propose_subject_box(res, self._tmp_page(), det_boxes=boxes)
        self.assertEqual(res.title_suggestion['source'], 'det2_crop')

    @override_settings(SUBJECT_BOXES_PATH='/tmp/lettersys_subject_boxes_det2c.json',
                       SUBJECT_DET2_SUGGESTION=False)
    def test_kill_switch_keeps_the_box_but_reads_nothing(self):
        from core.extraction.pipeline import AIExtractionResult
        svc = self._service()
        res = AIExtractionResult()
        res.title = ''; res.issuing_entity_id = None
        boxes = {'number': None, 'subject': ([0.10, 0.20, 0.80, 0.25], 0.9)}
        # قراءةٌ صالحةٌ متاحة — فلو تجاهل الكودُ المفتاحَ لصارت اقتراحاً (read_box يبتلع الأخطاء،
        # فالحارسُ يُختبر بما كان سيحدث لا باستثناءٍ يُبتلَع — طفرةٌ نجت بالصيغة الأولى)
        with mock.patch.object(sc, '_default_ocr', return_value='م/ تقرير الربع الثالث') as ocr:
            svc._propose_subject_box(res, self._tmp_page(), det_boxes=boxes)
        self.assertEqual(res.subject_box_proposal['source'], 'det2')
        self.assertIsNone(getattr(res, 'title_suggestion', None))
        ocr.assert_not_called()

    @override_settings(SUBJECT_BOXES_PATH='/tmp/lettersys_subject_boxes_order.json')
    def test_ocr_stack_is_ready_before_the_green_gate_reads(self):
        """F1: البوّابةُ الخضراء تقرأ بـ`_default_ocr` — في مسار الكاش (لا OCR قبلها) كان أوّلُ
        استخراجٍ في العمليّة يسقط إلى EasyOCR لأنّ التهيئةَ صارت في فرع det2 وحدَه."""
        from core.extraction.pipeline import AIExtractionResult
        svc = self._service()
        res = AIExtractionResult()
        res.title = ''; res.issuing_entity_id = 56
        calls = []
        with mock.patch.object(svc, '_ensure_ocr_stack', side_effect=lambda: calls.append('stack')), \
             mock.patch.object(sc, 'learned_fill', side_effect=lambda *a, **k: calls.append('gate')):
            svc._propose_subject_box(res, self._tmp_page(), det_boxes={'number': None, 'subject': None})
        self.assertEqual(calls[:2], ['stack', 'gate'])

    @override_settings(SUBJECT_BOXES_PATH='/tmp/lettersys_subject_boxes_learned.json')
    def test_det2_silence_proposes_the_entity_learned_box(self):
        """F3: صمتُ det2 وقراءةٌ متعلَّمةٌ لم تجتز الحرّاس ⟵ صندوقُ الجهة موضعاً للسحب (كما كان
        `sc.propose`) لا الحزامُ الافتراضيّ — ولا اقتراحَ نصّيّاً منه."""
        import os
        from core.extraction.pipeline import AIExtractionResult
        path = sc.store_path()
        if os.path.exists(path): os.remove(path)
        for _ in range(3):
            sc.record_sample(57, {'x': 0.1, 'y': 0.33, 'w': 0.7, 'h': 0.04}, 'م')
        svc = self._service()
        res = AIExtractionResult()
        res.title = ''; res.issuing_entity_id = 57
        with mock.patch.object(svc, '_ensure_ocr_stack'), \
             mock.patch.object(sc, '_default_ocr', return_value=',+ t? I \\\\,('):
            svc._propose_subject_box(res, self._tmp_page(), det_boxes={'number': None, 'subject': None})
        prop = res.subject_box_proposal
        self.assertEqual(prop['source'], 'learned')
        self.assertAlmostEqual(prop['box']['y'], 0.33, places=3)
        self.assertEqual(res.title, '')
        self.assertIsNone(getattr(res, 'title_suggestion', None))

    def test_number_path_reuses_the_shared_detector_result(self):
        """استدلالٌ واحدٌ للاستخراج: مسارُ العدد يأخذ صندوقَه من النتيجة المشتركة."""
        from core.extraction.pipeline import AIExtractionService as S
        boxes = {'number': ([0.70, 0.10, 0.80, 0.13], 0.9), 'subject': None}
        with mock.patch('core.extraction.handwriting.detector.detect_boxes',
                        side_effect=AssertionError('استدلالٌ ثانٍ')):
            self.assertEqual(S._detector_box_from_file(self._tmp_page(), boxes=boxes),
                             ([0.70, 0.10, 0.80, 0.13], 'det2'))

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


class AttachmentPagesAndMergeLogTests(TestCase):
    """قرارُ المالك 2026‑09‑13: كم ورقةً في المرفق، ومَن ألحق وكم أضاف.
    `AttachmentVersion.page_count` كان حقلاً موجوداً **لا يُملأ أبداً** — فلا أحد يعرف
    أنّ المرفقَ صار خمسَ ورقاتٍ بعد أن كان ورقتين."""

    def _pdf(self, pages=1):
        import fitz, io
        doc = fitz.open()
        for _ in range(pages):
            doc.new_page()
        buf = doc.tobytes()
        doc.close()
        return buf

    def setUp(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from core.models import Attachment, Book
        self.user = User.objects.create_user('mrg', password='pw-mrg-11', is_staff=True)
        self.book = Book.objects.create(kind='incoming_internal', title='مرفقات', created_by=self.user)
        self.att = Attachment.objects.create(
            book=self.book, file=SimpleUploadedFile('a.pdf', self._pdf(2), content_type='application/pdf'))

    def test_merging_records_pages_added_and_who(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from core.merge_service import SmartMergeService
        svc = SmartMergeService(self.att, self.user)
        svc.merge_files(SimpleUploadedFile('b.pdf', self._pdf(3), content_type='application/pdf'))
        v = self.att.versions.order_by('-version_number').first()
        self.assertEqual(v.page_count, 5, 'عددُ ورقات المرفق بعد الإلحاق لم يُسجَّل')
        self.assertEqual(v.merge_metadata.get('added_pages'), 3)
        self.assertEqual(v.merge_metadata.get('pages_before'), 2)
        self.assertEqual(v.created_by, self.user)

    def test_the_attachment_exposes_pages_and_last_merge(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from core.merge_service import SmartMergeService
        self.assertEqual(self.att.page_count, 2)
        self.assertEqual(self.att.last_merge_by, '')
        SmartMergeService(self.att, self.user).merge_files(
            SimpleUploadedFile('c.pdf', self._pdf(1), content_type='application/pdf'))
        att = type(self.att).objects.get(pk=self.att.pk)
        self.assertEqual(att.page_count, 3)
        self.assertEqual(att.last_merge_by, 'mrg')
        self.assertEqual(att.last_merge_added, 1)

    def test_the_preview_json_carries_the_merge_log(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from core.merge_service import SmartMergeService
        SmartMergeService(self.att, self.user).merge_files(
            SimpleUploadedFile('d.pdf', self._pdf(2), content_type='application/pdf'))
        self.client.force_login(self.user)
        data = self.client.get(reverse('api_book_detail_json', args=[self.book.pk])).json()
        att = data['attachments'][0]
        self.assertEqual(att['page_count'], 4)
        self.assertEqual(att['merge_log'][0]['added_pages'], 2)
        self.assertEqual(att['merge_log'][0]['by'], 'mrg')

    def test_the_row_passes_pages_and_report_to_the_dialog(self):
        self.client.force_login(self.user)
        r = self.client.get(reverse('book_unified'))
        self.assertContains(r, 'data-doc-pages=')
        self.assertContains(r, 'data-doc-report=')
        self.assertContains(r, 'id="docPreviewPrint"')


class DocViewerToolsTests(TestCase):
    """عارضُ الصور (تكبير/تدوير/سحب) والتنقّلُ بين المرفقات داخل الحوار (2026‑09‑13)."""

    def test_the_dialog_carries_image_tools_and_navigation(self):
        u = User.objects.create_user('dvt', password='pw-dvt-11')
        self.client.force_login(u)
        r = self.client.get(reverse('book_unified'))
        for marker in ('id="docPreviewZoomIn"', 'id="docPreviewRotate"', 'id="docPreviewReset"',
                       'id="docPreviewNav"', 'id="docPreviewCounter"'):
            self.assertContains(r, marker)

    def test_the_script_mounts_a_stage_only_for_images_and_exposes_series(self):
        src = open('static/js/doc_view.js', encoding='utf-8').read()
        self.assertIn('function mountImage', src)
        self.assertIn("node.tagName === 'IMG'", src)
        self.assertIn('openSeries', src)
        self.assertIn('rotate(', src)

    def test_the_detail_page_publishes_its_attachment_series(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from core.models import Attachment, Book
        u = User.objects.create_user('dvs', password='pw-dvs-11', is_staff=True)
        b = Book.objects.create(kind='incoming_internal', title='سلسلة', created_by=u)
        for n in ('p1.pdf', 'p2.pdf'):
            Attachment.objects.create(book=b, file=SimpleUploadedFile(n, b'%PDF-1.4'))
        self.client.force_login(u)
        r = self.client.get(reverse('book_detail', args=[b.pk]))
        self.assertContains(r, 'id="bookAttachmentsSeries"')
        self.assertContains(r, 'data-doc-series="1"')
