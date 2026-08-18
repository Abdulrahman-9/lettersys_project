# -*- coding: utf-8 -*-
"""حارسات كاشف صندوق «العدد»: عقد الهندسة والتدهور الرشيق.

لا يُختبَر هنا **دقّة** الكاشف (قيست على كاغل: M1 96% على 165 صورة تحقّق، وتطابق
ONNX/torch 98.2%) — بل العقدُ الذي يجعل تلك الدقّة تصل سليمةً إلى الأنبوب:
الإحداثيّات مُطبَّعةٌ على **الصفحة الكاملة** لا على قصاصة الـ55%، وغيابُ الملفّ
يُصمِت الكاشف بدل أن يكسر استخراجاً."""
from unittest import mock

from django.test import SimpleTestCase, override_settings
from PIL import Image

from core.extraction.handwriting import detector as D


class DetectorGracefulTests(SimpleTestCase):
    def setUp(self):
        D._session = None
        D._load_failed = False

    tearDown = setUp

    @override_settings(NUMBER_DETECTOR_ONNX=r'/nonexistent/number_detector.onnx')
    def test_missing_model_is_silent_not_fatal(self):
        """غياب الملفّ ⟵ None، فيعود الأنبوب لسلوكه السابق حرفيّاً."""
        self.assertIsNone(D.detect_number_box(Image.new('RGB', (800, 1100), 'white')))

    @override_settings(NUMBER_DETECTOR_ONNX=r'/nonexistent/x.onnx')
    def test_missing_model_probed_once_only(self):
        """الفشل يُخزَّن: لا نضرب القرص لكلّ صفحة."""
        img = Image.new('RGB', (400, 600), 'white')
        with mock.patch('os.path.exists', return_value=False) as ex:
            D.detect_number_box(img)
            D.detect_number_box(img)
        self.assertEqual(ex.call_count, 1, 'الفحص يجب أن يقع مرّةً واحدة')


class DetectorGeometryContractTests(SimpleTestCase):
    """العقد: يُقصّ أعلى 55% داخليّاً، ويُعاد الصندوق مُطبَّعاً على الصفحة الكاملة."""

    def setUp(self):
        D._session = None
        D._load_failed = False

    tearDown = setUp

    def test_box_is_normalised_to_full_page_not_crop(self):
        # صندوقٌ في منتصف القصاصة رأسيّاً ⟵ يجب أن يخرج عند ~0.275 من الصفحة
        # (0.5 × 0.55)، لا عند 0.5. هذا الفرق هو فخّ 1600/2600/3500 بعينه.
        W = H = 1280
        import numpy as np
        pred = np.zeros((1, 5, 1), dtype=np.float32)
        pred[0, 0, 0] = W / 2          # cx
        pred[0, 1, 0] = H / 2          # cy وسط اللوحة المُلبَّدة
        pred[0, 2, 0] = 40             # w
        pred[0, 3, 0] = 20             # h
        pred[0, 4, 0] = 0.9            # conf

        class _Sess:
            def get_inputs(self):
                return [mock.Mock(name='images')]

            def run(self, _o, _f):
                return [pred]

        D._session = _Sess()
        page = Image.new('RGB', (1000, 2000), 'white')      # صفحةٌ طويلة: النسبة تهمّ
        out = D.detect_number_box(page)
        self.assertIsNotNone(out)
        box, conf = out
        cy = (box[1] + box[3]) / 2
        self.assertAlmostEqual(cy, 0.5 * D.TRAIN_CROP, delta=0.02,
                               msg='الصندوق مُطبَّعٌ على القصاصة لا على الصفحة — عقدٌ مكسور')
        self.assertTrue(0.0 <= box[0] < box[2] <= 1.0)
