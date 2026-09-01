# -*- coding: utf-8 -*-
"""ثقةُ القارئ = احتماليّةُ **السلسلة** لا متوسّطُ الرموز.

العطب المُقاس (2026-08-19، استشارة فيبل): الصيغة السابقة متوسّطٌ على الأطر المُصدَّرة
وحدها، والحذفُ غيرُ مرئيٍّ لها **بالبناء** عبر ثلاث قنوات — أطرُ الفراغ · أطرُ الامتداد
(`k != prev`) · وانهيارُ المكرّر (لا إطارَ يحمل دليلَه). المعرض: «٧٠٩٩» تُقرأ «799»
بثقة 1.000 (كتاب 11305).

مقيسٌ على 1,781 زوجاً: فصلُ الصحيح عن الحذف **AUROC 0.903 [0.883, 0.921]** مقابل
**0.734 [0.696, 0.764]** للسابقة — ومجالاهما متباينان.
"""
import numpy as np
from django.test import SimpleTestCase

from core.extraction.handwriting.reader import HandwrittenNumberReader


def _frames(seq, mass=1.0, T=14, C=11):
    """أطرٌ اصطناعيّة: فراغٌ في كلّ مكانٍ إلا مواضع الرموز المطلوبة."""
    p = np.full((T, C), 1e-6)
    p[:, 0] = 1.0
    for t, k in seq:
        p[t, 0] = 1.0 - mass
        p[t, k] = mass
    return p / p.sum(axis=1, keepdims=True)


class SequenceConfidenceTests(SimpleTestCase):
    def setUp(self):
        self.r = HandwrittenNumberReader()

    def test_certain_sequence_scores_one(self):
        p = _frames([(3, 8), (8, 10)])          # 7 ثمّ 9
        self.assertGreater(self.r._sequence_confidence(p, '79'), 0.99)

    def test_split_mass_lowers_confidence_geometrically(self):
        """نصفُ الكتلة على رمزٍ من رمزين ⟵ الجذر التربيعيّ لـ0.5 = 0.707.

        المتوسّطُ الحسابيّ القديم كان يعطي 0.75 — أي يُخفي نصفَ الشكّ."""
        p = _frames([(3, 8)])
        p[8, 0] = 0.5
        p[8, 10] = 0.5
        p = p / p.sum(axis=1, keepdims=True)
        got = self.r._sequence_confidence(p, '79')
        self.assertLess(got, 0.75)
        self.assertAlmostEqual(got, 0.707, delta=0.02)

    def test_confidence_is_length_normalised(self):
        """رمزٌ واحدٌ لا يتفوّق على أربعةٍ بالبناء (انحيازُ القراءة القصيرة)."""
        one = self.r._sequence_confidence(_frames([(3, 8)]), '7')
        four = self.r._sequence_confidence(_frames([(2, 8), (5, 1), (8, 10), (11, 10)]), '7099')
        self.assertAlmostEqual(one, four, delta=0.02)

    def test_failure_degrades_to_silence_not_to_the_old_formula(self):
        """الارتداد إلى المتوسّط كان سيُعيد العمى عن الحذف من بابٍ خلفيّ."""
        self.assertEqual(self.r._sequence_confidence(None, '79'), 0.0)

    def test_repeated_digits_are_representable(self):
        """«99» تحتاج فراغاً بين الرمزين — شرطُ CTC للمكرّر، وهو مُنفَّذٌ هنا."""
        p = _frames([(3, 10), (9, 10)])
        self.assertGreater(self.r._sequence_confidence(p, '99'), 0.9)


class _NamedInput:
    def __init__(self, name):
        self.name = name


class _FakeSession:
    """جلسةٌ باسم مُدخَلٍ غير `image` — تُخفق إن نُودي عليها بالاسم الخطأ."""

    def __init__(self, name='input'):
        self._name = name
        self.fed_names = []

    def get_inputs(self):
        return [_NamedInput(self._name)]

    def run(self, _out, feed):
        self.fed_names += list(feed)
        if self._name not in feed:
            raise ValueError('invalid input name')
        T, C = 14, 11
        logits = np.full((1, T, C), -10.0, dtype=np.float32)
        logits[0, :, 0] = 10.0
        return [logits]


class InjectedSessionInputNameTests(SimpleTestCase):
    """العطب الخامس من صنف «مسارَي بناءٍ أحدهما يتخطّى اللازم» (2026-08-23).

    الاشتقاق كان في مسار التحميل من الملفّ وحده؛ الجلسة المحقونة تبقى على
    الافتراضيّ `'image'` بينما مُدخَل T2.4 اسمه `'input'` ⟵ ValueError على كلّ
    قراءةٍ ومسحُ عتبةٍ كاملٌ صفريّ النتائج (0/393) قبل الإصلاح."""

    def test_injected_session_input_name_is_honoured(self):
        from PIL import Image
        sess = _FakeSession('input')
        r = HandwrittenNumberReader(session=sess)
        text, conf = r.read(Image.new('L', (100, 40), 255))
        self.assertEqual(sess.fed_names, ['input'])
        self.assertIsNone(text)            # كلّها فراغٌ ⟵ امتناعٌ صامت
        self.assertEqual(conf, 0.0)
