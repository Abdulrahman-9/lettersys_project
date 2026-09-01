# -*- coding: utf-8 -*-
"""حرزُ المطابقة الصارمة — كلُّ اختبارٍ هنا نصٌّ **حقيقيٌّ** من ماسحةٍ، لا مُختلَق.

القانونُ الذي تحرسه: «الخطأُ المكتوب أسوأ من الفراغ». فما لا يجتاز الصرامةَ
يُترك للمسار البصريّ صامتاً، ولا يُكتب في حقلٍ يراه الكاتبُ صحيحاً.

وكلُّ سطرٍ هنا مأخوذٌ من مستندٍ رُئي بالعين — لأنّ regex مضبوطاً على نصٍّ مُتخيَّل
ينجح في الاختبار ويسقط في الإنتاج (وهذا ما حدث في النسخة الأولى: اشترطت
«Ref. No.» فأخطأت كلَّ كتب NK التي تكتب «Ref:» وحدَها).
"""
from django.test import SimpleTestCase

from core.extraction.matchers.strict_ref import (
    APPROVED_PREFIXES, canonical_sender_number, digits_of, strict_ref_match)


class ApprovedPrefixTests(SimpleTestCase):
    def test_scanner_mangled_prefix_is_rejected(self):
        """`llK` تشويهُ ماسحةٍ لـ`NK` — والقائمةُ وحدَها تقتله (كتاب 11237)."""
        self.assertIsNone(strict_ref_match('NK Petroleum Company Limited\n'
                                           'Ref: llK-20260257\nTo : MdOC\n'))

    def test_unknown_sender_is_silent_not_guessed(self):
        """جهةٌ خارج القائمة تصمت حتّى تُضاف — صمتٌ لا خطأ."""
        self.assertIsNone(strict_ref_match('Ref: XYZ-20260233\nTo: MdOC\n'))

    def test_prefix_list_is_the_single_source(self):
        self.assertIn('NK', APPROVED_PREFIXES)
        self.assertIn('ADO', APPROVED_PREFIXES)


class RealScannerLayoutTests(SimpleTestCase):
    """التخطيطاتُ الثلاثةُ المقيسة — كلٌّ منها كسر النسخةَ السابقة."""

    def test_nk_ref_without_the_word_no(self):
        got = strict_ref_match('Date: June 18, 2026\nRef: NK-20260233\nTo : MdOC\n')
        self.assertEqual(canonical_sender_number(got), '20260233')

    def test_ado_anchor_is_no_with_value_on_the_next_line(self):
        """`No.:` ثمّ سطرٌ تالٍ — وبلا هذه المرساة كان ADO كلُّه صامتاً."""
        got = strict_ref_match('From: ADO Digital Energy DMCC\nNo.:\nADO-361\n'
                               'Subject: Monthly Procurement Report\n')
        self.assertEqual(canonical_sender_number(got), '361')

    def test_ocr_split_inside_the_value_is_stripped(self):
        got = strict_ref_match('LETTER\nNo.\nEBS- MdOC-20250916\nRemarks: Urgent\n')
        self.assertEqual(canonical_sender_number(got), '20250916')

    def test_missing_hyphen_after_prefix_still_matches(self):
        """طبقةُ ماسحٍ أسقطت الشرطة (كتاب 11291: `ADO627`)."""
        got = strict_ref_match('From: ADO Digital Energy FZCO\nNo.:\nADO627\n')
        self.assertEqual(canonical_sender_number(got), '627')


class CandidateSetTests(SimpleTestCase):
    """تكوينُ مجموعة المرشَّحين — أثقلُ بندٍ في التفكيك، وبلا حرزٍ ينجرف صامتاً.

    التفكيكُ المقيس (2026-08-30، نفسُ المجموعتين): إسقاطُ طبقة «القيمةُ تستغرق
    سطرَها» يهبط بالإطلاق **32 ⟵ 26**؛ وإسقاطُ حدَّي المرساة **معاً** يُعيد
    الخطأين بعينهما (11125 ⟵ `403` و13134 ⟵ `25`). فالثلاثةُ هنا تفشل صاخبةً
    عند أيّ ترخيصٍ لـ`_PRE_ANCHOR_MAX` أو `_TAIL_MAX` أو حدِّ السطر المستغرَق.
    """

    def test_prose_reference_loses_to_the_value_column(self):
        """كتاب 11125: إحالةُ متنٍ `(Ref No.ADO-403)` والقيمةُ `ADO-432` سطراً وحدَها."""
        got = strict_ref_match(
            'ADO Digital Energy DMCC\n'
            'Kindly refer to our earlier correspondence (Ref No.ADO-403) in this regard.\n'
            'ADO-432\n'
            'Subject: Supply of spare parts\n')
        self.assertEqual(canonical_sender_number(got), '432')

    def test_contract_number_is_not_a_reference(self):
        """كتاب 13134: `Contract No.ADo-25-Sc-019` كان يُقرأ `25` — وحدُّ الذيل يقتله."""
        got = strict_ref_match(
            'Tender Committee\n'
            'Contract No.ADo-25-Sc-019\n'
            'ADO-507\n')
        self.assertEqual(canonical_sender_number(got), '507')

    def test_value_alone_on_its_line_fires_without_any_anchor(self):
        """النموذجُ ذو العمودين: عمودُ التسميات كتلةٌ وعمودُ القيم كتلةٌ أخرى."""
        got = strict_ref_match('NK Petroleum Company Limited\n'
                               'Head Office\n'
                               'NK-20260233\n'
                               'Attention: MdOC\n')
        self.assertEqual(canonical_sender_number(got), '20260233')


class CanonicalFormTests(SimpleTestCase):
    """الإصدارُ خاناتٌ وحدَها — بلاغُ المالك: الكاتب يُسقط البادئةَ عمداً.

    والقاعدةُ تؤكّده: 12 وسماً ببادئة من 235 (5%)، وADO 88 عارياً مقابل 2.
    """

    def test_prefix_is_stripped_for_every_shape(self):
        self.assertEqual(canonical_sender_number('NK-20260233'), '20260233')
        self.assertEqual(canonical_sender_number('ADO-361'), '361')
        self.assertEqual(canonical_sender_number('EBS-MdOC-20250916'), '20250916')

    def test_canonical_is_the_only_normaliser(self):
        """توحيدُ المخرَج مع البصريّ (يقرأ خاناتٍ فقط) يجعل التصادقَ مطابقةً ساذجة."""
        self.assertEqual(canonical_sender_number('NK-2025144'), digits_of('2025144'))


class TruncationGuardTests(SimpleTestCase):
    """حارزُ تمام الأرقام — وحدُّه مقيسٌ لا مُقدَّر."""

    def test_bare_year_is_rejected_as_line_break_truncation(self):
        """كتاب 13277: طرفُ سطرٍ قطع `NK-20260233` إلى `NK-2026`."""
        self.assertIsNone(strict_ref_match('Ref: NK-2026\nTo: MdOC\n'))

    def test_seven_digit_year_form_is_legitimate(self):
        """نُقض تشديدُ «ثمانٍ بالضبط» بدليلٍ صوريّ: 6596 و6638 يطبعان سبعاً."""
        self.assertEqual(canonical_sender_number(
            strict_ref_match('Date: August 23, 2025\nRef: NK-2025144\n')), '2025144')

    def test_year_out_of_range_is_rejected(self):
        self.assertIsNone(strict_ref_match('Ref: NK-19990233\n'))


class HeadZoneTests(SimpleTestCase):
    def test_reference_quoted_in_the_body_does_not_fire(self):
        """المراسلاتُ تقتبس مراجعَ بعضها — والمرساةُ في الرأس هي الفارق."""
        body = 'X\n' * 400 + 'With reference to your letter Ref: NK-20260233\n'
        self.assertIsNone(strict_ref_match(body))

    def test_empty_text_is_silent(self):
        for bad in ('', None):
            self.assertIsNone(strict_ref_match(bad))


class PipelineWiringTests(SimpleTestCase):
    """حرزُ «النصّ يسبق البصريّ» — والفخُّ الذي يقفله أخطرُ من الميزة نفسها.

    فخُّ المرآة (تحذيرُ فيبل 2026-08-26): `_sender_number_survives_emission`
    تحرس **محاولةَ** المسار البصريّ. لو عُدّ منشأٌ نصّيٌّ ناجياً فيها لصار الشرطُ
    `not _survives` كاذباً، فامتنعت المحاولةُ البصريّة على كلّ المستندات
    و**انتُقض S3′ صامتاً** بلا خطأٍ ولا اختبارٍ أحمر. ولذلك التخطّي شرطٌ منفصلٌ
    (`_strict_ref_skips_visual`) لا تعديلٌ للمرآة.
    """

    def _r(self, **kw):
        from core.extraction.pipeline import AIExtractionResult
        r = AIExtractionResult()
        for k, v in kw.items():
            setattr(r, k, v)
        return r

    def test_strict_ref_survives_emission(self):
        from core.extraction.pipeline import _suppress_sender_number_emission
        r = self._r(sender_number='20260233', sender_number_confidence=0.85,
                    sender_number_source='strict_ref')
        _suppress_sender_number_emission(r)
        self.assertEqual(r.sender_number, '20260233')

    def test_strict_ref_never_survives_the_mirror(self):
        """**الحرزُ الأهمّ** — وإلّا مُنعت المحاولةُ البصريّة على كلّ مستند."""
        from core.extraction.pipeline import _sender_number_survives_emission
        r = self._r(sender_number='20260233', sender_number_source='strict_ref')
        self.assertFalse(_sender_number_survives_emission(r),
                         'المنشأُ النصّيُّ نجا في المرآة ⟵ البصريُّ لن يُحاوَل أبداً')

    def test_skip_needs_both_a_strict_value_and_a_date(self):
        """التخطّي بلا تاريخٍ يقتل قصاصةَ التاريخ واقتراحَه — ثمنٌ لا يُدفع."""
        from core.extraction.pipeline import _strict_ref_skips_visual
        both = self._r(sender_number='20260233', sender_number_source='strict_ref',
                       sender_date='2026-06-18')
        no_date = self._r(sender_number='20260233', sender_number_source='strict_ref')
        other = self._r(sender_number='20260233', sender_number_source='printed_anchor',
                        sender_date='2026-06-18')
        self.assertTrue(_strict_ref_skips_visual(both))
        self.assertFalse(_strict_ref_skips_visual(no_date))
        self.assertFalse(_strict_ref_skips_visual(other))

    def test_strict_confidence_stays_below_the_confident_wrong_threshold(self):
        """0.85 دون 0.90 بنائيّاً: الأدلّةُ كلُّها من مجموعةِ تطويرٍ حتّى تُبنى e2e-F."""
        from core.extraction.handwriting.reader import CONF_GATE
        self.assertLess(0.85, CONF_GATE)

    def test_other_text_writers_are_still_silenced(self):
        """فتحُ منشأٍ واحد لا يفتح الباب: احتياطُ ref_num يبقى مكتوماً."""
        from core.extraction.pipeline import _suppress_sender_number_emission
        r = self._r(sender_number='1942', sender_number_confidence=0.65,
                    sender_number_source='ref_num')
        _suppress_sender_number_emission(r)
        self.assertFalse(r.sender_number)
