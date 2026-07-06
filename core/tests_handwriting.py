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


class StripBboxTests(SimpleTestCase):
    def test_strip_left_of_label_rtl(self):
        from core.extraction.handwriting.localize import LabelBox
        lb = LabelBox(left=700, top=200, width=80, height=30, text='العدد', source='label')
        x0, y0, x1, y1 = NumberStripLocator.strip_bbox(lb, 1000, 1400)
        self.assertLess(x1, 701)          # الشريط يسار التسمية
        self.assertLess(x0, x1)
        self.assertLess(y0, 200)          # هامش فوق التسمية
        self.assertGreater(y1, 230)       # وتحتها
