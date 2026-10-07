# -*- coding: utf-8 -*-
"""ممرّاتُ القراءة المتوازية (الدفعةُ الثانية من التسريع، 2026‑10‑06) — العقد: المخرَجُ نفسُه حرفاً.

تحرس هذه الاختبارات الآليّة: متى يُقبل التوازي، وأنّ أيَّ فشلٍ أو **تدهورٍ صامت** في ممرٍّ يُعاد
بكود اليوم على خيط الاستخراج، وأنّ الممرَّ لا يلمس القاعدة، وأنّ قيمةَ det1 تُستهلك بشرط اليوم.
والمطابقةُ طرفاً إلى طرف على 40 كتاباً حقيقيّاً (مُطفأ/مُشغَّل/تأخيرٌ عشوائيّ/إفشال/تدهور) في
D:/migration/extraction_speed/batch2/accept_identical_b2.py.
"""
import threading
import time
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings

from core.extraction import degrade
from core.extraction import lanes as L
from core.extraction import pipeline as P
from core.pdf_lock import MUPDF_LOCK, mupdf_locked


class _LanesState(SimpleTestCase):
    """يعزل الحالَ العامّة للوحدة (العدّاد، الفتحة، المقابض) بين الاختبارات."""

    def setUp(self):
        L.stats.clear()
        self._saved = (L._TEST_JITTER, set(L._TEST_FAULTS), set(L._TEST_DEGRADE), L._TEST_MEMORY_MB)
        L._TEST_MEMORY_MB = 5000
        self.addCleanup(self._restore)
        with L._state_lock:
            self._active_before = L._active
            L._active = 0

    def _restore(self):
        L._TEST_JITTER, L._TEST_FAULTS, L._TEST_DEGRADE, L._TEST_MEMORY_MB = (
            self._saved[0], self._saved[1], self._saved[2], self._saved[3])
        with L._state_lock:
            L._active = self._active_before

    def _admit_one(self):
        L.extraction_enter()
        self.addCleanup(L.extraction_exit)
        lanes = L.admit()
        if lanes is not None:
            self.addCleanup(lanes.release)
        return lanes


@override_settings(EXTRACTION_LANES=True, EXTRACTION_LANES_MIN_FREE_MB=500, EXTRACTION_LANES_MIN_COMMIT_MB=800)
class AdmissionTests(_LanesState):

    def test_admitted_when_alone_and_memory_is_enough(self):
        self.assertIsNotNone(self._admit_one())
        self.assertEqual(L.stats.get('admitted'), 1)
        self.assertEqual(L.stats.get('last_free_mb'), 5000)

    @override_settings(EXTRACTION_LANES=False)
    def test_setting_off_means_today_sequential_code(self):
        self.assertIsNone(self._admit_one())

    def test_a_second_extraction_running_keeps_both_sequential(self):
        L.extraction_enter()
        self.addCleanup(L.extraction_exit)
        self.assertIsNone(self._admit_one(), 'استخراجان معاً ولكلّ ممرّاته — الذروةُ تتضاعف على 8GB')
        self.assertEqual(L.stats.get('sequential_busy'), 1)

    def test_low_free_memory_alone_refuses(self):
        with mock.patch.object(L, 'memory_mb', return_value=(499, 5000)):
            self.assertIsNone(self._admit_one())
        self.assertEqual(L.stats.get('sequential_memory'), 1)

    def test_low_commit_headroom_alone_refuses(self):
        # الالتزامُ هو ما يُفشل malloc ولو كانت الحرّةُ وفيرة (MemoryError 10-06 عند متّسعٍ 194MB)
        with mock.patch.object(L, 'memory_mb', return_value=(5000, 799)):
            self.assertIsNone(self._admit_one())
        self.assertEqual(L.stats.get('sequential_memory'), 1)

    def test_exactly_at_both_thresholds_admits(self):
        with mock.patch.object(L, 'memory_mb', return_value=(500, 800)):
            self.assertIsNotNone(self._admit_one())

    def test_unknown_memory_refuses(self):
        L._TEST_MEMORY_MB = None
        with mock.patch.object(L, 'memory_mb', return_value=(None, None)):
            self.assertIsNone(self._admit_one())

    def test_the_slot_admits_one_fanned_extraction_at_a_time(self):
        first = self._admit_one()
        self.assertIsNotNone(first)
        self.assertIsNone(L.admit(), 'فتحتان لاستخراجين — ذروتان متوازيتان على 8GB')
        self.assertEqual(L.stats.get('sequential_slot'), 1)

    def test_slot_is_released_and_reusable(self):
        first = self._admit_one()
        self.assertIsNotNone(first)
        first.release()
        first.release()                      # مرّةً واحدة فقط
        L.extraction_exit()
        self.assertIsNotNone(self._admit_one(), 'الفتحةُ لم تُحرَّر')


class LaneSetTests(_LanesState):

    def _lanes(self):
        lanes = L.LaneSet()
        self.addCleanup(lanes.join_all)
        return lanes

    def test_take_returns_the_lane_value(self):
        lanes = self._lanes()
        lanes.start('r4', lambda: 42)
        self.assertEqual(lanes.take('r4', lambda: self.fail('inline must not run')), 42)

    def test_not_started_runs_today_inline_code(self):
        self.assertEqual(self._lanes().take('det', lambda: 'inline'), 'inline')

    def test_a_raising_lane_falls_back_to_inline_once(self):
        lanes = self._lanes()
        lanes.start('r1', lambda: 1 / 0)
        calls = []
        self.assertEqual(lanes.take('r1', lambda: calls.append(1) or 'inline'), 'inline')
        self.assertEqual(calls, [1])
        self.assertEqual(L.stats.get('fallback_r1'), 1)

    def test_a_silently_degraded_lane_is_not_consumed(self):
        """الثغرةُ القاطعة في مراجعة الهويّة: الإخفاقاتُ المبتلَعة تعود «ناجحة»."""
        def swallowed():
            degrade.mark('detector-decode')
            return {'number': None, 'subject': None}
        lanes = self._lanes()
        lanes.start('det', swallowed)
        self.assertEqual(lanes.take('det', lambda: 'inline'), 'inline')

    def test_test_knobs_fault_and_degrade_force_the_fallback(self):
        L._TEST_FAULTS = {'r4'}
        L._TEST_DEGRADE = {'det'}
        lanes = self._lanes()
        lanes.start('r4', lambda: 'lane')
        lanes.start('det', lambda: 'lane')
        self.assertEqual(lanes.take('r4', lambda: 'inline'), 'inline')
        self.assertEqual(lanes.take('det', lambda: 'inline'), 'inline')

    def test_degrade_flag_does_not_leak_between_lanes(self):
        lanes = self._lanes()
        lanes.start('det', lambda: degrade.mark('x') or 'bad')
        lanes.take('det', lambda: None)
        lanes.start('r4', lambda: 'clean')
        self.assertEqual(lanes.take('r4', lambda: 'inline'), 'clean')

    def test_join_all_swallows_and_is_idempotent(self):
        lanes = self._lanes()
        lanes.start('r1', lambda: 1 / 0)
        lanes.join_all()
        lanes.join_all()

    def test_start_is_idempotent(self):
        lanes = self._lanes()
        runs = []
        lanes.start('r4', lambda: runs.append(1) or 'a')
        lanes.start('r4', lambda: runs.append(2) or 'b')
        self.assertEqual(lanes.take('r4', lambda: None), 'a')
        self.assertEqual(runs, [1])

    def test_lanes_run_on_named_threads(self):
        lanes = self._lanes()
        lanes.start('r4', lambda: threading.current_thread().name)
        self.assertTrue(lanes.take('r4', lambda: '').startswith('extraction-lane'))

    def test_finish_waits_for_every_started_lane(self):
        """finish() يسبق حذفَ الملفّ المؤقّت وعملَ الخيط التالي — لا يعود وممرٌّ ما يزال يعمل."""
        self.assertTrue(L._FANOUT_SLOTS.acquire(blocking=False))
        lanes = self._lanes()
        done = []
        lanes.start('r4', lambda: time.sleep(0.2) or done.append('r4'))
        lanes.start('det', lambda: time.sleep(0.3) or done.append('det'))
        lanes.finish()
        self.assertEqual(sorted(done), ['det', 'r4'])
        self.assertTrue(L._FANOUT_SLOTS.acquire(blocking=False), 'finish() يحرّر الفتحة')
        L._FANOUT_SLOTS.release()


class LaneDatabaseGuardTests(TestCase):

    def setUp(self):
        L.stats.clear()

    def test_a_lane_that_opens_a_db_connection_is_counted_and_closed(self):
        from django.db import connections

        def touches_db():
            with connections['default'].cursor() as cur:
                cur.execute('SELECT 1')
            return 'ok'
        lanes = L.LaneSet()
        lanes.start('r4', touches_db)
        lanes.take('r4', lambda: 'inline')
        lanes.join_all()
        self.assertEqual(L.stats.get('db_touch'), 1, 'ممرٌّ لمس القاعدة ولم يُكشف')


class DetectorFallbackConsumptionTests(SimpleTestCase):
    """قيمةُ det1 من الممرّ تُستهلك بشرط اليوم حرفاً: فقط حين يصمت det2 عن العدد.
    والذراعُ يعود **مع** الصندوق — لا صفةَ صنفٍ يتبادلها استخراجان متزامنان."""

    def test_det2_found_ignores_the_lane_fallback(self):
        boxes = {'number': ([0.1, 0.1, 0.2, 0.15], 0.9), 'subject': None}
        got = P.AIExtractionService._detector_box_from_file('x.pdf', boxes=boxes,
                                                            fallback=([0.5, 0.1, 0.6, 0.2], 0.8))
        self.assertEqual(got, ([0.1, 0.1, 0.2, 0.15], 'det2'))

    def test_det2_silent_consumes_the_lane_fallback_without_rendering(self):
        boxes = {'number': None, 'subject': None}
        with mock.patch.object(P.AIExtractionService, '_render_for_detector') as render:
            got = P.AIExtractionService._detector_box_from_file('x.pdf', boxes=boxes,
                                                                fallback=([0.5, 0.1, 0.6, 0.2], 0.8))
        render.assert_not_called()
        self.assertEqual(got, ([0.5, 0.1, 0.6, 0.2], 'det1'))

    def test_not_run_keeps_today_inline_det1(self):
        boxes = {'number': None, 'subject': None}
        with mock.patch.object(P.AIExtractionService, '_render_for_detector', return_value='IM') as render,                 mock.patch('core.extraction.handwriting.detector.detect_number_box_fallback',
                           return_value=([0.4, 0.1, 0.5, 0.2], 0.7)) as det1:
            got = P.AIExtractionService._detector_box_from_file('x.pdf', boxes=boxes)
        render.assert_called_once_with('x.pdf')
        det1.assert_called_once_with('IM')
        self.assertEqual(got, ([0.4, 0.1, 0.5, 0.2], 'det1'))

    def test_no_box_anywhere_has_no_arm(self):
        boxes = {'number': None, 'subject': None}
        got = P.AIExtractionService._detector_box_from_file('x.pdf', boxes=boxes, fallback=None)
        self.assertEqual(got, (None, ''))

    def test_lane_fallback_low_box_is_still_guarded(self):
        boxes = {'number': None, 'subject': None}
        got = P.AIExtractionService._detector_box_from_file('x.pdf', boxes=boxes,
                                                            fallback=([0.5, 0.6, 0.6, 0.7], 0.8))
        self.assertEqual(got, (None, ''), 'حارسُ الارتفاع 0.45 تُخُطّي لقيمة الممرّ')

    def test_a_failure_has_no_box_and_no_arm(self):
        with mock.patch.object(P.AIExtractionService, '_detector_boxes_from_file',
                               side_effect=RuntimeError):
            self.assertEqual(P.AIExtractionService._detector_box_from_file('x.pdf'), (None, ''))

    def test_the_arm_is_never_parked_in_shared_state(self):
        """الجذر: صفةُ صنفٍ يكتبها كلُّ طلب ⟵ استخراجان متزامنان يتبادلان الذراع. والسباقُ لا
        يُستنسخ حتميّاً تحت GIL (الكتابةُ والقراءةُ تكادان تكونان ذرّيّتين)، فالحرزُ بنيويّ:
        الدالّةُ لا تُسند إلى أيّ صفةٍ ولا تنادي setattr — الذراعُ يعيش في قيمتها المُعادة وحدها."""
        import ast
        import inspect
        import textwrap
        src = textwrap.dedent(inspect.getsource(P.AIExtractionService._detector_box_from_file))
        fn = ast.parse(src).body[0]
        targets = []
        for n in ast.walk(fn):
            if isinstance(n, ast.Assign):
                targets.extend(n.targets)
            elif isinstance(n, (ast.AugAssign, ast.AnnAssign)):
                targets.append(n.target)
        shared = [ast.dump(t) for t in targets if isinstance(t, ast.Attribute)]
        shared += [ast.dump(n) for n in ast.walk(fn) if isinstance(n, ast.Call)
                   and isinstance(n.func, ast.Name) and n.func.id == 'setattr']
        self.assertEqual(shared, [], 'كتابةٌ في حالةٍ مشتركة داخل مسار الذراع')


class R4CertaintyTests(SimpleTestCase):

    def test_no_first_page_text_means_r4_runs(self):
        self.assertTrue(P._r4_certain(''))

    def test_strict_reference_found_leaves_r4_to_today_code(self):
        with mock.patch.object(P, 'strict_ref_match', return_value='NK-20260233'), \
                mock.patch.object(P, 'canonical_sender_number', return_value='20260233'):
            self.assertFalse(P._r4_certain('any text'))

    def test_no_strict_reference_means_r4_runs(self):
        with mock.patch.object(P, 'strict_ref_match', return_value=None):
            self.assertTrue(P._r4_certain('any text'))


class VisualLaneStartTests(_LanesState):

    def test_render_failure_starts_no_lane(self):
        svc = P.AIExtractionService()
        svc._offline_provider = mock.Mock(_pytesseract=mock.Mock(), lang='ara', psm='3')
        lanes = L.LaneSet()
        with mock.patch.object(svc, '_render_r4', side_effect=MemoryError), \
                mock.patch('core.extraction.handwriting.detector._session', None):
            svc._start_visual_lanes(lanes, 'x.pdf')
        self.assertFalse(lanes.started('r4'))
        self.assertFalse(lanes.started('det'))

    def test_detector_lane_needs_an_already_loaded_session(self):
        svc = P.AIExtractionService()
        svc._offline_provider = mock.Mock(_pytesseract=mock.Mock(), lang='ara', psm='3')
        lanes = L.LaneSet()
        self.addCleanup(lanes.join_all)
        with mock.patch.object(svc, '_render_r4', side_effect=MemoryError), \
                mock.patch('core.extraction.handwriting.detector._session', None), \
                mock.patch.object(P.AIExtractionService, '_render_for_detector') as render:
            svc._start_visual_lanes(lanes, 'x.pdf')
        render.assert_not_called()
        self.assertFalse(lanes.started('det'), 'تحميلُ جلسةٍ داخل ممرّ — فشلُه يُطفئ الكاشف حتّى الإقلاع')


class DetectorLaneTests(SimpleTestCase):

    def test_det2_found_never_runs_det1(self):
        from core.extraction.handwriting import detector as D
        with mock.patch.object(D, 'detect_boxes', return_value={'number': ([0.1, 0.1, 0.2, 0.2], 0.9),
                                                                 'subject': None}), \
                mock.patch.object(D, 'detect_number_box_fallback') as det1, \
                mock.patch.object(D, '_fb_session', object()):
            out = P._detector_lane('IM')
        det1.assert_not_called()
        self.assertIs(out['fallback'], L.NOT_RUN)

    def test_det2_silent_and_det1_not_loaded_leaves_det1_to_today_code(self):
        from core.extraction.handwriting import detector as D
        with mock.patch.object(D, 'detect_boxes', return_value={'number': None, 'subject': None}), \
                mock.patch.object(D, 'detect_number_box_fallback') as det1, \
                mock.patch.object(D, '_fb_session', None):
            out = P._detector_lane('IM')
        det1.assert_not_called()
        self.assertIs(out['fallback'], L.NOT_RUN)

    def test_det2_silent_and_det1_loaded_runs_det1_on_the_same_render(self):
        from core.extraction.handwriting import detector as D
        with mock.patch.object(D, 'detect_boxes', return_value={'number': None, 'subject': None}), \
                mock.patch.object(D, 'detect_number_box_fallback', return_value=([0.5, 0.1, 0.6, 0.2], 0.7)) as det1, \
                mock.patch.object(D, '_fb_session', object()):
            out = P._detector_lane('IM')
        det1.assert_called_once_with('IM')
        self.assertEqual(out['fallback'], ([0.5, 0.1, 0.6, 0.2], 0.7))

    def test_failed_det_lane_falls_back_to_the_same_shape(self):
        svc = P.AIExtractionService()
        lanes = L.LaneSet()
        lanes.start('det', lambda: 1 / 0)
        boxes = {'number': None, 'subject': None}
        with mock.patch.object(P.AIExtractionService, '_detector_boxes_from_file', return_value=boxes):
            got = svc._det_from_lanes(lanes, 'x.pdf')
        lanes.join_all()
        self.assertEqual(got, {'boxes': boxes, 'fallback': L.NOT_RUN})
        self.assertIsNone(svc._det_from_lanes(None, 'x.pdf'))


@override_settings(EXTRACTION_LANES_MIN_FREE_MB=300, EXTRACTION_LANES_MIN_COMMIT_MB=500)
class LanesWiringTests(TestCase):
    """الأنبوبُ كاملاً مرّتين (مُطفأ/مُشغَّل) بقراءاتٍ خامٍ مُستبدَلة: النتيجةُ نفسُها، وكلُّ قراءةٍ
    تُحسب مرّةً واحدة، والملفُّ المؤقّت حيٌّ ما دامت القراءةُ الرئيسيّة تقرؤه، ولا يُنتظَر ممرٌّ
    وخيطُ الاستخراج يمسك قفلَ PDF."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import fitz
        import tempfile
        cls.tmpdir = tempfile.mkdtemp()
        cls.pdf = f'{cls.tmpdir}/page.pdf'
        doc = fitz.open()
        page = doc.new_page(width=200, height=280)
        page.insert_text((20, 40), 'Ref 2026/101', fontsize=12)
        doc.save(cls.pdf)
        doc.close()

    def setUp(self):
        L.stats.clear()
        self._mem = L._TEST_MEMORY_MB
        L._TEST_MEMORY_MB = 5000
        self.addCleanup(setattr, L, '_TEST_MEMORY_MB', self._mem)
        self.calls = {'extract': 0, 'tsv': 0, 'det2': 0, 'det1': 0}

    def _run(self, lanes_on, text_layer=None, extract_error=None):
        from contextlib import ExitStack
        from core.extraction.handwriting import detector as D
        from core.extraction.handwriting.reader import HandwrittenNumberReader
        from core.extraction.ocr import providers as PR
        import os as _os
        calls = self.calls

        def fake_extract(prov_self, path):
            calls['extract'] += 1
            self.assertTrue(_os.path.exists(path), 'الملفُّ المؤقّت حُذف والقراءةُ تقرؤه')
            if extract_error is not None:
                raise extract_error
            return {'raw_text': 'وزارة\nالموضوع: اجتماع\nالعدد 101', 'avg_confidence': 0.9,
                    'details': None, 'num_lines': 3, 'processing_time': 0.0}

        def fake_tsv(pt, img, **kw):
            calls['tsv'] += 1
            return {'text': [], 'conf': [], 'left': [], 'top': [], 'width': [], 'height': [],
                    'block_num': [], 'par_num': [], 'line_num': [], 'word_num': [], 'level': [],
                    'page_num': []}

        def fake_det2(im):
            calls['det2'] += 1
            return {'number': None, 'subject': None}

        def fake_det1(im):
            calls['det1'] += 1
            return ([0.1, 0.1, 0.3, 0.15], 0.8)

        real_take = L.LaneSet.take

        def take_without_pdf_lock(lane_self, name, inline):
            self.assertFalse(MUPDF_LOCK._is_owned(), 'خيطُ الاستخراج ينتظر ممرّاً وهو يمسك قفل PDF')
            return real_take(lane_self, name, inline)

        from core.extraction.matchers.pattern import PatternMatcher
        real_patterns = PatternMatcher.extract_all_data

        def patterns_with_no_lane_running(pm_self, *a, **k):
            # الأنماطُ فما بعدها (الجهات، صندوق الموضوع، CRNN) تبتلع أعطالها — لا تجري وممرٌّ يضغط
            if L._FANOUT_SLOTS.acquire(blocking=False):
                L._FANOUT_SLOTS.release()
            else:
                self.fail('خيطُ الاستخراج تابع عمله والممرّاتُ جارية (finish لم يُنادَ)')
            return real_patterns(pm_self, *a, **k)

        with override_settings(EXTRACTION_LANES=lanes_on), \
                mock.patch.object(PR.TesseractOCRProvider, 'extract', fake_extract), \
                mock.patch.object(PR, 'tesseract_image_to_data', fake_tsv), \
                mock.patch.object(D, '_session', object()), \
                mock.patch.object(D, '_fb_session', object()), \
                mock.patch.object(D, 'detect_boxes', fake_det2), \
                mock.patch.object(D, 'detect_number_box_fallback', fake_det1), \
                mock.patch.object(HandwrittenNumberReader, 'read_best', return_value=(None, 0.0)), \
                mock.patch.object(P.AIExtractionService, '_suggest_date', return_value=None), \
                mock.patch.object(L.LaneSet, 'take', take_without_pdf_lock), \
                mock.patch.object(PatternMatcher, 'extract_all_data', patterns_with_no_lane_running), \
                ExitStack() as extra:
            if text_layer is not None:
                # مسارُ طبقة النصّ: الطبقةُ «تكسب مكانها» بعددٍ في المسبار، فلا قراءةَ رئيسيّة
                extra.enter_context(mock.patch.object(
                    P.AIExtractionService, '_extract_pdf_text_layer', return_value=text_layer))
                extra.enter_context(mock.patch.object(
                    PatternMatcher, 'extract_sender_number', return_value=('101', 0.9)))
            svc = P.AIExtractionService()
            svc.save_to_cache = lambda *a, **k: True
            svc.check_cache = lambda h: None
            res = svc._process_image_internal(self.pdf, False, None, 'incoming_internal', None)
        return res

    def _fields(self, res):
        return {k: getattr(res, k, None) for k in (
            'status', 'raw_text', 'title', 'sender_number', 'sender_number_bbox',
            'sender_number_bbox_source', 'sender_number_detector_arm', 'sender_date_crop',
            'ocr_engine', 'overall_confidence')}

    def test_lanes_on_equals_off_and_each_read_runs_once(self):
        off = self._fields(self._run(False))
        calls_off = dict(self.calls)
        self.calls.update({k: 0 for k in self.calls})
        on = self._fields(self._run(True))
        self.assertEqual(on, off)
        self.assertEqual(self.calls, calls_off, 'قراءةٌ حُسبت مرّتين أو لم تُحسب')
        self.assertEqual(calls_off['extract'], 1)
        self.assertEqual(off['sender_number_detector_arm'], 'det1',
                         'det2 صامتٌ وdet1 وجد ⟵ الذراعُ يُنشر مع الصندوق')
        for lane in ('r1', 'r4', 'det'):
            self.assertEqual(L.stats.get('started_' + lane), 1, lane)
        self.assertEqual(L.active_extractions(), 0, 'العدّادُ لم يعد إلى الصفر')
        self.assertTrue(L._FANOUT_SLOTS.acquire(blocking=False), 'الفتحةُ لم تُحرَّر')
        L._FANOUT_SLOTS.release()

    def test_text_layer_path_finishes_lanes_before_any_other_work(self):
        text = 'وزارة\nالعدد: 101\nالموضوع: اجتماع\n' * 3
        off = self._fields(self._run(False, text_layer=text))
        on = self._fields(self._run(True, text_layer=text))
        self.assertEqual(on, off)
        self.assertEqual(off['ocr_engine'], 'pdf_text_layer', 'الاختبارُ لم يسلك مسارَ طبقة النصّ')
        self.assertEqual(L.stats.get('admitted'), 1, 'الممرّاتُ لم تُقبَل فالاختبارُ فارغ')
        self.assertEqual(self.calls['extract'], 0)

    def test_an_exception_mid_extraction_still_frees_the_slot_and_counter(self):
        """القراءةُ الرئيسيّة تفشل في الممرّ وفي كود اليوم معاً ⟵ الاستثناءُ يقفز فوق finish() العاديّ؛
        finally وحده يحرّر الفتحةَ والعدّاد، وإلّا أُطفئ التوازي حتّى إعادة الإقلاع."""
        res = self._run(True, extract_error=RuntimeError('boom'))
        self.assertEqual(res.status, 'failed')
        self.assertEqual(L.stats.get('started_r4'), 1, 'لا ممرَّ بدأ فالاختبارُ فارغ')
        self.assertEqual(L.active_extractions(), 0)
        self.assertTrue(L._FANOUT_SLOTS.acquire(blocking=False), 'الفتحةُ عالقة')
        L._FANOUT_SLOTS.release()

    def test_a_raising_r1_lane_gives_the_same_result_via_today_code(self):
        off = self._fields(self._run(False))
        L._TEST_FAULTS = {'r1', 'r4', 'det'}
        self.addCleanup(setattr, L, '_TEST_FAULTS', set())
        on = self._fields(self._run(True))
        self.assertEqual(on, off)
        for lane in ('r1', 'r4', 'det'):
            self.assertEqual(L.stats.get('fallback_' + lane), 1, lane)


class EveryPdfOpenIsLockedTests(SimpleTestCase):
    """كلُّ فتحٍ لـPDF في مسارات الاستخراج يجري والقفلُ ممسوك — سياقُ MuPDF وحيدُ الخيط."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import fitz
        import tempfile
        cls.pdf = f'{tempfile.mkdtemp()}/p.pdf'
        doc = fitz.open()
        doc.new_page(width=120, height=160).insert_text((10, 30), 'Ref 101', fontsize=10)
        doc.save(cls.pdf)
        doc.close()

    def _assert_locked_opens(self, call):
        import fitz
        real_open = fitz.open
        seen = []

        def checked_open(*a, **k):
            seen.append(MUPDF_LOCK._is_owned())
            return real_open(*a, **k)
        with mock.patch.object(fitz, 'open', checked_open):
            call()
        self.assertTrue(seen, 'لم يُفتح PDF أصلاً — الاختبارُ لا يقيس شيئاً')
        self.assertTrue(all(seen), 'فتحُ PDF خارج القفل')

    def test_extraction_renders_and_text_reads(self):
        from core.extraction.ocr.image import ImageProcessor
        svc = P.AIExtractionService()
        self._assert_locked_opens(lambda: svc._render_r4(self.pdf))
        self._assert_locked_opens(lambda: P.AIExtractionService._render_for_detector(self.pdf))
        self._assert_locked_opens(lambda: svc._open_page_image(self.pdf))
        self._assert_locked_opens(lambda: P.pdf_first_page_text(self.pdf))
        self._assert_locked_opens(lambda: svc._extract_pdf_text_layer(self.pdf))
        self._assert_locked_opens(lambda: ImageProcessor(self.pdf, preprocess_pdf=False, max_ocr_dim=3500))

    def test_services(self):
        from core import page_render
        from core.attachment_service import remove_blank_pages
        data = open(self.pdf, 'rb').read()
        self._assert_locked_opens(lambda: page_render.page_count(self.pdf))
        self._assert_locked_opens(lambda: remove_blank_pages(data))


class DegradeMarksTests(SimpleTestCase):

    def setUp(self):
        degrade.clear()
        self.addCleanup(degrade.clear)

    def test_detector_from_file_failure_marks_the_thread(self):
        with mock.patch.object(P.AIExtractionService, '_render_for_detector', side_effect=MemoryError):
            out = P.AIExtractionService._detector_boxes_from_file('missing.png')
        self.assertEqual(out, {'number': None, 'subject': None})
        self.assertEqual(degrade.reason(), 'detector-from-file')

    def test_detector_decode_failure_marks_the_thread(self):
        from core.extraction.handwriting import detector as D
        sess = mock.Mock()
        sess.get_inputs.side_effect = MemoryError
        from PIL import Image
        out = D._decode(sess, Image.new('RGB', (40, 60), 'white'))
        self.assertEqual(out, {'number': None, 'subject': None})
        self.assertEqual(degrade.reason(), 'detector-decode')

    def test_failed_tesseract_escalation_marks_the_thread(self):
        from core.extraction.ocr import providers as PR
        prov = PR.TesseractOCRProvider()
        prov.adaptive_threshold = 0.75
        calls = []

        def run(img):
            calls.append(img)
            if len(calls) == 2:
                raise MemoryError
            return 'نص', 0.5, 1
        from PIL import Image
        with mock.patch.object(prov, '_run_tesseract', side_effect=run), \
                mock.patch.object(prov, '_png_read_as_is', return_value=False), \
                mock.patch.object(prov, '_to_pil', return_value=Image.new('L', (8, 8), 255)):
            out = prov.extract(b'x')
        self.assertEqual(out['raw_text'], 'نص')
        self.assertEqual(degrade.reason(), 'tesseract-escalation')

    def test_clean_runs_leave_no_mark(self):
        from core.extraction.handwriting import detector as D
        sess = mock.Mock()
        sess.get_inputs.return_value = [mock.Mock(name='images')]
        import numpy as np
        sess.run.return_value = [np.zeros((1, 6, 0), dtype=np.float32)]
        from PIL import Image
        D._decode(sess, Image.new('RGB', (40, 60), 'white'))
        self.assertIsNone(degrade.reason())


class MupdfLockTests(SimpleTestCase):

    def test_decorated_function_runs_under_the_lock(self):
        seen = []

        @mupdf_locked
        def body():
            seen.append(MUPDF_LOCK._is_owned())
        body()
        self.assertEqual(seen, [True])
        self.assertFalse(MUPDF_LOCK._is_owned())

    def test_lock_is_reentrant(self):
        @mupdf_locked
        def inner():
            return 'ok'

        @mupdf_locked
        def outer():
            return inner()
        self.assertEqual(outer(), 'ok')

    def test_another_thread_waits_while_held(self):
        order = []

        def other():
            with MUPDF_LOCK:
                order.append('other')
        with MUPDF_LOCK:
            t = threading.Thread(target=other)
            t.start()
            t.join(0.2)
            order.append('owner')
        t.join(2)
        self.assertEqual(order, ['owner', 'other'])
