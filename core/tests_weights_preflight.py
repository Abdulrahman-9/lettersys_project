# -*- coding: utf-8 -*-
"""عتادُ النماذج: التدهورُ رشيقٌ ومسموع، والمساراتُ مثبَّتةٌ على جذر المشروع.

**العطبان اللذان تقفلهما هذه الاختبارات** — كلاهما مقيسٌ لا مُفترَض:

١. `_read_handwritten_sender_number` كان يعيد **ثنائيّةً** عند غياب القارئ
   والنداءُ يفكّ **رباعيّة** ⟵ `ValueError` يبتلعه `except` العامّ فيعود
   المستندُ كلُّه `status='failed'` بلا حقلٍ واحد. مُثبَتٌ بالتشغيل: نفسُ
   اختبارات `AIProcessingServiceTests` من مجلّدٍ آخر كانت تفشل.

٢. ستّةُ مساراتٍ كانت نسبيّةً لمجلّد العمل (`os.path.join('var', …)`) بينما
   الكاشفُ وحده مثبَّتٌ على `BASE_DIR` — وشغّالُ المشروع نفسُه يُقلع من
   `scripts/` (`run_server_background.py`). فخدمةٌ تعمل، ونسخةٌ أخرى تعمى.

والقائمةُ في `core/extraction/artifacts.py` **عقدٌ واحد**: يقرأ منه الكودُ الحيُّ
مساراتِه ويقرأ منه `models_healthcheck` ما يفحص — والاختبارُ الأخيرُ هنا يمنع
انجرافَهما (فحصٌ يفحص مسارَ غيرِ الذي يُحمَّل أسوأُ من لا فحص).
"""
import ast
import json
import os
import tempfile

from django.conf import settings
from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, override_settings

from core.extraction import artifacts as A


class _UnavailableReader:
    """قارئٌ غيرُ متاح — بمسارٍ حقيقيّ كي يمرّ التحذيرُ لا يُستثنى."""
    available = False
    model_path = '/nonexistent/handwritten_digits_crnn.onnx'


class HandwritingPathContractTests(SimpleTestCase):

    def test_unavailable_reader_returns_the_four_tuple(self):
        from core.extraction.pipeline import AIExtractionService
        svc = AIExtractionService()
        svc._hw_reader = _UnavailableReader()
        got = svc._read_handwritten_sender_number('x.jpg', None, want_date_crop=True)
        self.assertEqual(len(got), 4)
        # نفسُ فكّ النداء — لو عادت ثنائيّةً لارتفع ValueError هنا كما في الإنتاج
        num_res, date_crop, date_suggestion, (det_box, w, h) = got
        self.assertIsNone(num_res)
        self.assertIsNone(date_crop)
        self.assertIsNone(date_suggestion)
        self.assertIsNone(det_box)

    def test_every_return_in_the_pass_yields_four_values(self):
        """حرزٌ بنيويّ: أيُّ مخرجٍ جديدٍ بعرضٍ مختلف يفشل هنا لا في مستندِ كاتب."""
        path = os.path.join(settings.BASE_DIR, 'core', 'extraction', 'pipeline.py')
        with open(path, encoding='utf-8') as f:
            tree = ast.parse(f.read())
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == '_read_handwritten_sender_number')
        returns = [n for n in ast.walk(fn) if isinstance(n, ast.Return) and n.value is not None]
        self.assertGreaterEqual(len(returns), 2)
        for r in returns:
            self.assertIsInstance(r.value, ast.Tuple, ast.dump(r))
            self.assertEqual(len(r.value.elts), 4,
                             'مخرجٌ بعرضٍ %d عند السطر %d — النداءُ يفكّ أربعة'
                             % (len(r.value.elts), r.lineno))

    def test_missing_weight_is_announced_once(self):
        """الصمتُ كان العطب: سطرٌ واحدٌ لكلّ مفتاحٍ ثمّ صمتٌ (لا إغراقَ سجلّ)."""
        from core.extraction import pipeline as P
        P._WARNED_ARTIFACTS.discard('probe_key')
        with self.assertLogs('core.extraction.pipeline', level='ERROR') as cm:
            P._warn_missing_artifact('probe_key', '/nope.onnx', 'أثرٌ ما')
        self.assertIn('probe_key', cm.output[0])
        self.assertIn('models_healthcheck', cm.output[0])
        # النداءُ الثاني صامت — `assertNoLogs` غيرُ متاحٍ في 3.9، فنقيس بالحارس
        before = len(P._WARNED_ARTIFACTS)
        P._warn_missing_artifact('probe_key', '/nope.onnx', 'أثرٌ ما')
        self.assertEqual(len(P._WARNED_ARTIFACTS), before)


class ArtifactPathTests(SimpleTestCase):

    def test_paths_are_anchored_to_the_project_root(self):
        """لا مسارَ نسبيّاً لمجلّد العمل — وإلّا عميت خدمةٌ تُقلَع من مكانٍ آخر."""
        for art in A.ARTIFACTS:
            p = art.path_fn()
            self.assertTrue(os.path.isabs(p), '%s: %s' % (art.key, p))
            self.assertTrue(os.path.abspath(p).startswith(
                os.path.abspath(str(settings.BASE_DIR))), '%s: %s' % (art.key, p))

    @override_settings(HANDWRITTEN_NUMBER_ONNX=r'D:\elsewhere\x.onnx')
    def test_settings_override_wins(self):
        self.assertEqual(A.number_model_path(), r'D:\elsewhere\x.onnx')

    def test_loaders_use_the_same_contract(self):
        """حرزُ الانجراف: الفحصُ يفحص ما يُحمَّل فعلاً، لا مساراً موازياً."""
        from core.extraction import entity_profiles as EP
        from core.extraction.handwriting import date_reader as DR
        from core.extraction.handwriting import detector as DET
        from core.extraction.handwriting import reader as RD
        self.assertEqual(RD._MODEL_PATH, A.number_model_path())
        self.assertEqual(RD._CHARSET_PATH, A.number_charset_path())
        self.assertEqual(DR._DATE_MODEL, A.date_model_path())
        self.assertEqual(DR._DATE_CHARSET, A.date_charset_path())
        self.assertEqual(DET._model_path(), A.detector_path())
        self.assertEqual(DET._fallback_path(), A.detector_fallback_path())
        self.assertEqual(EP.PROFILES_PATH, A.entity_profiles_path())


class SystemCheckTests(SimpleTestCase):

    def test_no_warning_when_everything_is_present(self):
        from core.checks import check_runtime_artifacts
        if not all(os.path.exists(a.path_fn()) for a in A.ARTIFACTS
                   if a.level in ('required', 'degrades')):
            self.skipTest('عتادٌ ناقصٌ على هذا الجهاز — الحالةُ الأخرى مُختبَرةٌ أدناه')
        self.assertEqual(check_runtime_artifacts(None), [])

    @override_settings(HANDWRITTEN_NUMBER_ONNX=r'D:\nope\missing.onnx')
    def test_warning_lists_the_missing_artifact(self):
        from core.checks import MISSING_ARTIFACTS_ID, check_runtime_artifacts
        found = check_runtime_artifacts(None)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].id, MISSING_ARTIFACTS_ID)
        self.assertIn('قارئُ العدد', found[0].msg)
        # تحذيرٌ لا خطأ: `Error` يُسقط مجموعةَ الاختبارات على أيّ نسخةٍ جديدة
        self.assertEqual(found[0].level, 30)


class ModelsHealthcheckCommandTests(SimpleTestCase):

    def _run(self, **kw):
        from io import StringIO
        out = StringIO()
        call_command('models_healthcheck', stdout=out, stderr=out, **kw)
        return out.getvalue()

    def test_passes_on_a_complete_machine(self):
        if not all(os.path.exists(a.path_fn()) for a in A.ARTIFACTS):
            self.skipTest('عتادٌ ناقصٌ على هذا الجهاز')
        self.assertIn('فحصُ العتاد نجح', self._run())

    @override_settings(HANDWRITTEN_DATE_ONNX=r'D:\nope\missing.onnx')
    def test_missing_model_warns_by_default_and_fails_under_strict(self):
        self.assertIn('تحذير', self._run())          # جهازُ تطويرٍ لا يُعاقَب
        with self.assertRaises(CommandError):
            self._run(strict=True)                    # بوّابةُ النشر تصرخ

    def test_date_charset_without_the_separator_is_rejected(self):
        """طقمٌ بلا «/» = طقمُ الأرقام في غير موضعه ⟵ فكُّ الترميز يرفع IndexError."""
        with tempfile.TemporaryDirectory() as d:
            bad = os.path.join(d, 'charset.json')
            with open(bad, 'w', encoding='utf-8') as f:
                json.dump({'charset': '0123456789', 'blank': 0}, f)
            with override_settings(HANDWRITTEN_DATE_CHARSET=bad):
                with self.assertRaises(CommandError):
                    self._run()

    def test_every_artifact_is_reported(self):
        """لا ملفَّ يمرّ بلا سطر — تقريرٌ ناقصٌ يوهم بأنّ المفقود غيرُ مفحوص."""
        out = self._run()
        for art in A.ARTIFACTS:
            self.assertIn(art.label, out, art.key)
