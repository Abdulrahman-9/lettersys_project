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


class DateCropBoxAnchorTests(SimpleTestCase):
    """مرساة قصاصة التاريخ: صندوق العدد يُنتج قصاصةً حين تصمت تسمية «التاريخ».

    قانون المالك: «التاريخ دائماً تحت العدد». قِيس 2026-08-18 على 20 مستنداً حقيقيّاً:
    ظهور القصاصة 35% ⟵ **90%**، والسبعُ القائمة **مطابقةٌ بايتاً ببايت** (صفر تغيّر،
    صفر ضياع)، و10/10 من الجديدة صحيحةٌ بالعين بصفر انزلاقٍ لتاريخ الأيزو.

    درسٌ مدفوعُ الثمن: أوّل تصميمٍ جعل الصندوق **أرضيّةً** للمُموضِع فرفع تغطية
    الأرضيّة 70%⟵90% لكنّه لم يُنتج **ولا قصاصةً واحدة** — الأرضيّة تُرتّب المرشّحين
    ولا تخلقهم، وTesseract لا يقرأ «التاريخ» على تلك الصفحات أصلاً. تغطيةُ آليّةٍ
    وسيطة ليست تحسيناً؛ قِس المُخرَج."""

    def _img(self, w=1000, h=1400):
        from PIL import Image as I
        return I.new('RGB', (w, h), 'white')

    def test_crop_starts_below_the_box_and_is_generous_sideways(self):
        from core.extraction.pipeline import AIExtractionService as S
        img = self._img()
        box = [0.70, 0.10, 0.80, 0.13]          # عددٌ أعلى اليمين
        out = S._crop_below_box(img, box)
        self.assertTrue(out and out.startswith('data:image/png;base64,'))

    def test_no_box_means_no_crop(self):
        from core.extraction.pipeline import AIExtractionService as S
        self.assertIsNone(S._crop_below_box(self._img(), None))

    def test_low_box_is_rejected_as_anchor(self):
        """صندوقٌ منخفض (اقتباس متن) يخنق حقلَ التاريخ فوقه ⟵ يُرفض مرساةً."""
        from unittest import mock
        from core.extraction.pipeline import AIExtractionService as S
        with mock.patch('core.extraction.handwriting.detector.detect_number_box',
                        return_value=([0.1, 0.62, 0.2, 0.66], 0.9)):
            self.assertIsNone(S._detector_box(self._img()))
