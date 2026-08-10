# -*- coding: utf-8 -*-
"""اختبارات تموضع شريط الرقم اليدوي (مرحلة 1) — منطق التسمية/الـprior بلا OCR."""
import os
import tempfile

from django.test import SimpleTestCase

from core.extraction.handwriting import EntityLayoutPriors, NumberStripLocator


def tsv(words):
    """يبني قاموس TSV اصطناعياً: [(text, left, top, w, h), ...]"""
    return {'text': [w[0] for w in words], 'left': [w[1] for w in words],
            'top': [w[2] for w in words], 'width': [w[3] for w in words],
            'height': [w[4] for w in words]}


class FindLabelTests(SimpleTestCase):
    W, H = 1000, 1400

    def test_top_zone_label_found(self):
        t = tsv([('جمهورية', 400, 50, 100, 30), ('العدد:', 700, 200, 80, 30)])
        lb = NumberStripLocator().find_label(t, self.W, self.H)
        self.assertIsNotNone(lb)
        self.assertEqual(lb.source, 'label')
        self.assertEqual(lb.top, 200)

    def test_body_instance_rejected(self):
        # «المرقم/عدد» في جملة متن (أسفل الحزام) — خطأ المسبار الرئيس، يجب رفضه
        t = tsv([('نرافق', 500, 700, 80, 30), ('عدد', 400, 700, 60, 30)])
        self.assertIsNone(NumberStripLocator().find_label(t, self.W, self.H))

    def test_topmost_wins_over_lower(self):
        t = tsv([('عدد', 400, 420, 60, 30), ('العدد', 700, 180, 80, 30)])
        lb = NumberStripLocator().find_label(t, self.W, self.H)
        self.assertEqual(lb.top, 180)

    def test_prior_admits_candidate_outside_top_zone(self):
        # جهة تسميتها أخفض من الحزام — قرب الـprior يقبلها
        priors = EntityLayoutPriors(os.devnull)
        for _ in range(3):
            priors.learn(7, 0.44, 0.44)
        t = tsv([('العدد', 400, 600, 80, 30)])   # y=0.44 خارج الحزام
        lb = NumberStripLocator(priors).find_label(t, self.W, self.H, entity_id=7)
        self.assertIsNotNone(lb)
        self.assertEqual(lb.source, 'label')

    def test_prior_fallback_when_label_unreadable(self):
        # جهات «الصفر» (ترويسة مزخرفة): لا تسمية مقروءة → منطقة الجهة المُتعلَّمة
        priors = EntityLayoutPriors(os.devnull)
        for _ in range(3):
            priors.learn(9, 0.80, 0.15)
        t = tsv([('ترويسة', 100, 60, 90, 30)])
        lb = NumberStripLocator(priors).find_label(t, self.W, self.H, entity_id=9)
        self.assertIsNotNone(lb)
        self.assertEqual(lb.source, 'prior')

    def test_prior_needs_min_samples(self):
        priors = EntityLayoutPriors(os.devnull)
        priors.learn(5, 0.5, 0.2)   # مشاهدة واحدة < الحدّ الأدنى
        t = tsv([('ترويسة', 100, 60, 90, 30)])
        self.assertIsNone(NumberStripLocator(priors).find_label(t, self.W, self.H, entity_id=5))

    def test_label_slightly_below_zone_near_prior_admitted(self):
        # تسمية شرعية أسفل الحزام (y≈0.38) لكن ضمن قطر prior الجهة — تُقبَل كتسمية.
        # حُدِّث القطر 0.14→0.09 (قياسٌ 2026-07-21: الحزام الأوسع «يُتوّج المتن»
        # مراسيَ فيضرّ الدقّة 100%→70%). فالـprior هنا ȳ≈0.31 كي يبقى المرشّح (dist≈0.07)
        # داخل 0.09 — نفس القدرة، بهندسةٍ تطابق القطر الحاليّ. وجُمل المتن (y≥0.5) خارجه.
        priors = EntityLayoutPriors(os.devnull)
        for _ in range(3):
            priors.learn(11, 0.45, 0.31)
        t = tsv([('العدد', 430, 532, 80, 30)])          # y≈0.38, x≈0.47 → dist≈0.07 < 0.09
        lb = NumberStripLocator(priors).find_label(t, self.W, self.H, entity_id=11)
        self.assertIsNotNone(lb)
        self.assertEqual(lb.source, 'label')
        # وجملة متن بعيدة عن الـprior (y=0.55) تُرفض رغم القطر المُوسَّع
        t2 = tsv([('عدد', 400, 770, 60, 30)])
        lb2 = NumberStripLocator(priors).find_label(t2, self.W, self.H, entity_id=11)
        self.assertIsNotNone(lb2)                        # يسقط لمنطقة الـprior
        self.assertEqual(lb2.source, 'prior')            # لا يلتقط نسخة المتن كتسمية


class DateFieldLocatorTests(SimpleTestCase):
    """مُرتكز v2: مرساة «التاريخ» — نفس الانضباط، تسمية مختلفة وبصمات منفصلة."""
    W, H = 1000, 1400

    def test_date_label_found_in_top_zone(self):
        t = tsv([('العدد:', 700, 180, 80, 30), ('التاريخ:', 700, 230, 90, 30)])
        lb = NumberStripLocator(field='date').find_label(t, self.W, self.H)
        self.assertIsNotNone(lb)
        self.assertEqual(lb.top, 230)          # التقط «التاريخ» لا «العدد»

    def test_citation_bitarikh_rejected(self):
        # «بتاريخ» الظرفية (إحالة متن) لا تطابق المرساة المحدودة بحدود الكلمة
        t = tsv([('بتاريخ', 700, 200, 90, 30)])
        self.assertIsNone(NumberStripLocator(field='date').find_label(t, self.W, self.H))

    def test_hamza_variant_matched(self):
        t = tsv([('التأريخ', 650, 210, 90, 30)])   # الإملاء العراقي الشائع
        lb = NumberStripLocator(field='date').find_label(t, self.W, self.H)
        self.assertIsNotNone(lb)

    def test_number_field_ignores_date_label(self):
        t = tsv([('التاريخ:', 700, 230, 90, 30)])
        self.assertIsNone(NumberStripLocator(field='number').find_label(t, self.W, self.H))


class QMSTableGuardTests(SimpleTestCase):
    """ترويسة نظام الجودة جدولٌ فيه «Date Rev» — كانت تخطف مرساة التاريخ في كل
    كتب الشركة (تدقيق بصري على 8,704 شريط: أغلب القصّات حدود جدول)."""
    W, H = 1000, 1400

    def test_table_date_cell_rejected(self):
        t = tsv([('Date', 500, 120, 60, 25), ('Rev', 570, 120, 50, 25),
                 ('التاريخ', 700, 300, 90, 30)])
        lb = NumberStripLocator(field='date').find_label(t, self.W, self.H)
        self.assertIsNotNone(lb)
        self.assertEqual(lb.top, 300)          # التسمية الحقيقية لا خليّة الجدول

    def test_rev_no_cell_rejected_for_number(self):
        t = tsv([('No.', 300, 130, 40, 25), ('Rev', 350, 130, 50, 25),
                 ('العدد', 700, 320, 80, 30)])
        lb = NumberStripLocator(field='number').find_label(t, self.W, self.H)
        self.assertIsNotNone(lb)
        self.assertEqual(lb.top, 320)

    def test_standalone_date_label_still_found(self):
        t = tsv([('Date', 700, 200, 60, 25)])   # إيميل إنكليزي بلا جدول
        lb = NumberStripLocator(field='date').find_label(t, self.W, self.H)
        self.assertIsNotNone(lb)
        self.assertEqual(lb.top, 200)


class PriorsPersistenceTests(SimpleTestCase):
    def test_running_mean_and_roundtrip(self):
        fd, path = tempfile.mkstemp(suffix='.json')
        os.close(fd)
        try:
            p = EntityLayoutPriors(path)
            p.learn(3, 0.2, 0.1)
            p.learn(3, 0.4, 0.3)
            p.learn(3, 0.3, 0.2)
            p.save()
            q = EntityLayoutPriors(path)
            got = q.get(3)
            self.assertAlmostEqual(got['x'], 0.3, places=5)
            self.assertAlmostEqual(got['y'], 0.2, places=5)
            self.assertEqual(got['n'], 3)
        finally:
            os.remove(path)


class ReaderTests(SimpleTestCase):
    """قارئ ONNX (مرحلة 3) — منطق الفكّ والثقة بجلسة محقونة، بلا نموذج فعلي."""

    class _FakeSession:
        """جلسة مزيّفة تعيد logits مُصمَّمة: إطارات (فراغ، 1، 1، فراغ، 7) ⇒ «17»."""
        def __init__(self):
            import numpy as np
            t = np.full((5, 11), -10.0, dtype=np.float32)
            t[0, 0] = 10.0            # فراغ
            t[1, 2] = 10.0            # '1' (الفهرس 2 = charset[1])
            t[2, 2] = 10.0            # '1' مكررة — تُطوى
            t[3, 0] = 10.0            # فراغ يفصل
            t[4, 8] = 10.0            # '7'
            self._out = t[None]
        def run(self, _, __):
            return [self._out]
        def get_inputs(self):
            raise AssertionError('لا يُستدعى مع جلسة محقونة')

    def _reader(self):
        from core.extraction.handwriting.reader import HandwrittenNumberReader
        return HandwrittenNumberReader(session=self._FakeSession())

    def test_ctc_collapse_and_confidence(self):
        from PIL import Image
        text, conf = self._reader().read(Image.new('L', (120, 40), 255))
        self.assertEqual(text, '17')
        self.assertGreater(conf, 0.99)         # logits حادّة ⇒ ثقة شبه كاملة

    def test_missing_model_degrades_gracefully(self):
        from core.extraction.handwriting.reader import HandwrittenNumberReader
        from PIL import Image
        r = HandwrittenNumberReader(model_path='لا/يوجد.onnx', charset_path='لا/يوجد.json')
        self.assertFalse(r.available)
        self.assertEqual(r.read(Image.new('L', (50, 20), 255)), (None, 0.0))

    def test_preprocess_contract_shape(self):
        from core.extraction.handwriting.reader import HandwrittenNumberReader
        from PIL import Image
        x = HandwrittenNumberReader.preprocess(Image.new('L', (200, 100), 255))
        self.assertEqual(x.shape[:3], (1, 1, 64))   # (دفعة، قناة، ارتفاع 64، عرض متناسب)
        self.assertEqual(x.shape[3], 128)            # 200 × 64/100

    def test_real_model_reads_refined_strip_if_present(self):
        """اختبار دخانيّ حيّ: النموذج المنشور يقرأ شريطاً حقيقياً منقّى بوسمه —
        يُتخطّى بهدوء حيث لا نموذج/شريط (بيئات CI بلا أصول)."""
        import csv
        from PIL import Image
        from core.extraction.handwriting.reader import HandwrittenNumberReader
        r = HandwrittenNumberReader()
        clean_csv = os.path.join('training', 'handwriting', 'harvest', 'labels_clean.csv')
        if not (r.available and os.path.exists(clean_csv)):
            self.skipTest('النموذج أو عدّة الحصاد غير حاضرين')
        rows = [x for x in csv.DictReader(open(clean_csv, encoding='utf-8'))
                if x['tier'] == 'A']
        if not rows:
            self.skipTest('لا شرائط فئة A بعد')
        row = rows[0]
        strip = Image.open(os.path.join('training', 'handwriting', 'harvest',
                                        'strips_refined', row['file'])).convert('L')
        text, conf = r.read(strip)
        self.assertEqual(text, row['label'])
        self.assertGreater(conf, 0.5)


class StripBboxTests(SimpleTestCase):
    def test_strip_left_of_label_rtl(self):
        from core.extraction.handwriting.localize import LabelBox
        lb = LabelBox(left=700, top=200, width=80, height=30, text='العدد', source='label')
        x0, y0, x1, y1 = NumberStripLocator.strip_bbox(lb, 1000, 1400)
        self.assertLess(x1, 701)          # الشريط يسار التسمية
        self.assertLess(x0, x1)
        self.assertLess(y0, 200)          # هامش فوق التسمية
        self.assertGreater(y1, 230)       # وتحتها
