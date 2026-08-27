# -*- coding: utf-8 -*-
"""حارسات كاشف صندوق «العدد»: عقد الهندسة والتدهور الرشيق.

لا يُختبَر هنا **دقّة** الكاشف (قيست على كاغل: M1 96% على 165 صورة تحقّق، وتطابق
ONNX/torch 98.2%) — بل العقدُ الذي يجعل تلك الدقّة تصل سليمةً إلى الأنبوب:
الإحداثيّات مُطبَّعةٌ على **الصفحة الكاملة** لا على قصاصة الـ55%، وغيابُ الملفّ
يُصمِت الكاشف بدل أن يكسر استخراجاً."""
from unittest import mock

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase, override_settings

from core.extraction.capture import persist_extraction_capture
from core.models import Attachment, Book, ExtractionFeedback
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


class NumberEmissionSuppressedTests(TestCase):
    """سياسة إصدار حقل «عدد الجهة» — نصّيٌّ مكتوم، بصريٌّ يُعرض بثقته.

    أُسكت الحقل كلّياً 2026-08-18 (4 صواب/24 خطأً تُملأ تلقائيّاً). ثمّ **أعاد المالك
    نطاقه** (2026-08-19) بعد رافعتين مقيستين — صفرُ الحشو (51.5⟵66.5%) وثقةُ السلسلة
    (فصل الحذف 0.903) — «يكتب ما يقرأ، والضعيف يُؤشَّر». فالقراءة البصريّة
    (`bbox_source == 'crnn'`) تمرّ بثقتها الحقيقيّة، ويبقى النصّيّ مكتوماً
    (قياسُه 2 صواب مقابل 17 خطأً، كلّها بثقة 0.70 تُعرض أصفر لا أحمر).

    قِيس على خطّ الأساس المُعتمَد (تشغيلة A، 100 كتابٍ نظيف، فاشل 0): إصابة 4 مقابل
    **خاطئ 24**، منها 6 بثقة ≥0.90 كلّها من مسار CRNN. والواجهة **بلا عتبة عرض** —
    تكتب أيّ اقتراحٍ في الحقل مهما كانت ثقته. فكلفةُ انتباه الكاتب تفوق ما توفّره
    الإصابات الأربع، والصمت المتّسق أصدق من صوابٍ عرَضيٍّ يرافقه خطأٌ واثق.

    يُعاد الفتح بشرطٍ مُسجَّل: إعادة تدريب CRNN عند 300 قصاصةٍ مؤكَّدة ثمّ نظرةٌ على
    e2e-B ببوّابةٍ مُسبَقة — لا بقلب الراية وحدها."""

    def _result(self, value='7369', conf=0.95):
        from core.extraction.pipeline import AIExtractionResult
        r = AIExtractionResult()
        r.raw_text = 'العدد : 7369'
        r.cleaned_text = r.raw_text
        r.sender_number = value
        r.sender_number_confidence = conf
        r.sender_number_bbox = [0.7, 0.1, 0.8, 0.13]
        r.sender_number_bbox_source = 'detector'
        r.sender_number_bbox_dims = [2480, 3508]
        return r

    def test_crnn_visual_read_passes_with_its_true_confidence(self):
        """إعادةُ نطاقٍ بأمر المالك (2026-08-19): القراءة البصريّة تُعرض بثقتها —
        «لا يكون خانة العدد صامتاً؛ يكتب ما يقرأ، والضعيف يُؤشَّر». التأشير مسؤوليّة
        الواجهة (ما دون 0.65 يُعرض أحمر «يجب التصحيح يدوياً»)، لا الإسكات."""
        from core.extraction.pipeline import _suppress_sender_number_emission as kill
        r = self._result(value='7099', conf=0.42)      # ضعيفةٌ عمداً — تُعرض وتُؤشَّر
        r.sender_number_bbox_source = 'crnn'
        kill(r)
        self.assertEqual(r.sender_number, '7099', 'القراءة البصريّة يجب ألّا تُكتم')
        self.assertAlmostEqual(r.sender_number_confidence, 0.42,
                               msg='الثقة الحقيقيّة تصل الواجهة كي تؤشّر الضعيف')

    def test_suppressor_dominates_any_writer(self):
        """النقطة الواحدة بعد الكُتّاب الخمسة ⟵ لا يهمّ من كتب القيمة."""
        from core.extraction.pipeline import _suppress_sender_number_emission as kill
        for src_conf in (0.70, 0.65, 0.95, 0.998):
            r = self._result(conf=src_conf)
            kill(r)
            self.assertIsNone(r.sender_number, 'نجا عددٌ بثقة %s' % src_conf)
            self.assertEqual(r.sender_number_confidence, 0.0)

    def test_neither_carrier_carries_the_value(self):
        """الحاملان: لقطةُ رمز المسح (scan_token) واستجابةُ الواجهة."""
        from core.extraction.pipeline import (_suppress_sender_number_emission as kill,
                                              result_to_scan_data)
        r = self._result()
        kill(r)
        snap = result_to_scan_data(r)
        self.assertFalse(snap.get('sender_number'), 'الرقم تسرّب في لقطة رمز المسح')
        self.assertFalse(snap.get('sender_number_confidence'))

    def test_flywheel_invariant_box_survives_suppression(self):
        """الصندوق ومقاسه ومصدره **مادّةُ تدريبٍ لا مادّةُ عرض** — تبقى بعد الإسكات."""
        from core.extraction.pipeline import (_suppress_sender_number_emission as kill,
                                              result_to_scan_data)
        r = self._result()
        kill(r)
        snap = result_to_scan_data(r)
        self.assertEqual(snap.get('sender_number_bbox'), [0.7, 0.1, 0.8, 0.13])
        self.assertEqual(snap.get('sender_number_bbox_source'), 'detector')
        self.assertEqual(snap.get('sender_number_bbox_dims'), [2480, 3508])

    def test_empty_suggestion_creates_no_feedback_row(self):
        """دلالةٌ نظيفة: «الكاتب صحّح ما عرضناه» — ولم نعرض شيئاً، فلا صفَّ تصحيح."""
        user = User.objects.create_user('emit', password='x')
        book = Book.objects.create(title='ت', kind='incoming_internal', created_by=user)
        att = Attachment.objects.create(book=book, file='attachments/a.pdf')
        res = persist_extraction_capture(
            book=book, attachment=att,
            suggested={'raw_text': 'نصّ', 'sender_number': '',
                       'sender_number_bbox': [0.7, 0.1, 0.8, 0.13],
                       'sender_number_bbox_source': 'detector'},
            final={'sender_number': '1754'}, user=user)
        self.assertIsNotNone(res)
        self.assertEqual(ExtractionFeedback.objects.filter(field_name='sender_number').count(), 0)
        # ومع ذلك يبقى زوجُ التدريب كاملاً
        self.assertEqual(res.additional_data['sender_number_final'], '1754')
        self.assertTrue(res.additional_data['sender_number_bbox'])


class TwoClassDecodeTests(SimpleTestCase):
    """فكُّ ترميزٍ يقوده الشكل — والتراجعُ ملفُّ أوزانٍ فقط (خطّة فيبل 2026-08-26).

    الخطرُ الذي تقفله هذه الاختبارات: مع `nc=2` صار ذيلُ ONNX `[c0, c1]` لا
    objectness، فقراءةُ `pred[:,4]` وحدها تُعيد درجةَ صنف العدد **وتُسقط الصنف
    الثاني صامتاً** — عطبٌ لا يُصدر خطأً ولا يظهر إلّا في غياب ميزةٍ كاملة.
    """

    class _FakeSess:
        """جلسةٌ تُخرج مرشَّحاً واحداً بقنواتٍ يحدّدها المُنشئ."""

        def __init__(self, channels, scores):
            import numpy as np
            n = 8
            a = np.zeros((channels, n), dtype=np.float32)
            a[0, :] = 640.0        # cx وسطَ اللوحة
            a[1, :] = 320.0
            a[2, :] = 120.0        # w
            a[3, :] = 40.0         # h
            for k, sc in enumerate(scores):
                a[4 + k, 0] = sc
            if channels == 6 and len(scores) > 1:
                a[1, 1] = 700.0    # مرشَّحٌ ثانٍ أخفضُ للموضوع
                a[5, 1] = scores[1]
                a[5, 0] = 0.0
            self._out = a[None]

        def run(self, _o, _f):
            return [self._out]

        def get_inputs(self):
            class _I:
                name = 'images'
            return [_I()]

    def _detect(self, channels, scores):
        from PIL import Image
        from core.extraction.handwriting import detector as det
        prev, prev_failed = det._session, det._load_failed
        det._session, det._load_failed = self._FakeSess(channels, scores), False
        try:
            return det.detect_boxes(Image.new('RGB', (1000, 1400), 'white'))
        finally:
            det._session, det._load_failed = prev, prev_failed

    def test_two_classes_yield_two_independent_boxes(self):
        r = self._detect(6, [0.9, 0.8])
        self.assertIsNotNone(r['number'], 'صنفُ العدد ضاع')
        self.assertIsNotNone(r['subject'], 'صنفُ الموضوع أُسقط صامتاً — العطبُ المقصود')
        self.assertNotEqual(r['number'][0], r['subject'][0], 'الصندوقان متطابقان')

    def test_old_single_class_weights_still_work(self):
        """مسارُ التراجع: أوزانٌ خماسيّة ⟵ العدد يعمل والموضوع None."""
        r = self._detect(5, [0.9])
        self.assertIsNotNone(r['number'])
        self.assertIsNone(r['subject'])

    def test_one_class_below_gate_does_not_silence_the_other(self):
        r = self._detect(6, [0.9, 0.05])
        self.assertIsNotNone(r['number'])
        self.assertIsNone(r['subject'])

    def test_unknown_channel_count_degrades_quietly(self):
        r = self._detect(7, [0.9, 0.8, 0.7])
        self.assertIsNone(r['number'])
        self.assertIsNone(r['subject'])

    def test_legacy_wrapper_signature_unchanged(self):
        from PIL import Image
        from core.extraction.handwriting import detector as det
        prev, prev_failed = det._session, det._load_failed
        det._session, det._load_failed = self._FakeSess(6, [0.9, 0.8]), False
        try:
            got = det.detect_number_box(Image.new('RGB', (1000, 1400), 'white'))
        finally:
            det._session, det._load_failed = prev, prev_failed
        self.assertIsInstance(got, tuple)
        self.assertEqual(len(got), 2)
        self.assertIsInstance(got[0], list)
