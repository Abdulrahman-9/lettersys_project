# -*- coding: utf-8 -*-
"""اختبارات core/extraction/matchers/pattern.py — استخراج البيانات بالأنماط.

دوال نقية (بلا DB): رقم الكتاب، التاريخ (عربي/رقمي)، السرية، النوع، التاريخ المرن.
"""
from datetime import datetime

from django.test import SimpleTestCase

from core.extraction.matchers.pattern import (
    PatternMatcher, DateParser, extract_structured_data, parse_date_flexible,
)


class ExtractBookNumberTests(SimpleTestCase):
    def setUp(self):
        self.m = PatternMatcher()

    def test_labeled_number(self):
        num, conf = self.m.extract_book_number('رقم الكتاب: 123')
        self.assertEqual(num, '123')
        self.assertGreater(conf, 0)

    def test_kitab_raqm(self):
        num, _ = self.m.extract_book_number('كتاب رقم 456')
        self.assertEqual(num, '456')

    def test_bare_number(self):
        num, _ = self.m.extract_book_number('12345')
        self.assertEqual(num, '12345')

    def test_no_number(self):
        self.assertEqual(self.m.extract_book_number('نص بلا أرقام'), (None, 0.0))

    def test_labeled_has_higher_confidence_than_bare(self):
        _, labeled = self.m.extract_book_number('رقم الكتاب: 123')
        _, bare = self.m.extract_book_number('45678')
        self.assertGreater(labeled, bare)   # المعنون أوثق من رقم مجرّد


class ExtractDateTests(SimpleTestCase):
    def setUp(self):
        self.m = PatternMatcher()

    def test_arabic_month(self):
        d, conf = self.m.extract_date('بتاريخ 15 من يناير 2024')
        self.assertEqual((d.year, d.month, d.day), (2024, 1, 15))
        self.assertGreater(conf, 0.9)

    def test_numeric_dmy(self):
        d, _ = self.m.extract_date('التاريخ 15-01-2024')
        self.assertEqual((d.year, d.month, d.day), (2024, 1, 15))

    def test_iso_fallback(self):
        d, _ = self.m.extract_date('Created 2024-03-10 by user')
        self.assertEqual((d.year, d.month, d.day), (2024, 3, 10))

    def test_no_date(self):
        self.assertEqual(self.m.extract_date('بلا تاريخ هنا'), (None, 0.0))

    def test_impossible_date_rejected(self):
        self.assertEqual(self.m.extract_date('45-13-2024'), (None, 0.0))


class ExtractSenderDateTests(SimpleTestCase):
    def setUp(self):
        self.m = PatternMatcher()

    def test_header_date_extracted(self):
        d, _c = self.m.extract_sender_date(
            'جمهورية العراق\nالعدد: 123\nالتاريخ: 2026/6/9\nالموضوع: كذا')
        self.assertIsNotNone(d)
        self.assertEqual((d.year, d.month, d.day), (2026, 6, 9))

    def test_arabic_indic_digits(self):
        d, _c = self.m.extract_sender_date('التاريخ: ٢٠٢٦/٦/٩')
        self.assertIsNotNone(d)
        self.assertEqual(d.year, 2026)

    def test_no_header_date(self):
        self.assertEqual(self.m.extract_sender_date('لا تاريخ ترويسة'), (None, 0.0))

    def test_english_date_month_name(self):
        # إيميل إنجليزي: Date: June 20, 2026
        d, _c = self.m.extract_sender_date('NK Petroleum\nDate: June 20, 2026 Ref: NK-1\nTo: x')
        self.assertIsNotNone(d)
        self.assertEqual((d.year, d.month, d.day), (2026, 6, 20))

    def test_english_date_day_first(self):
        d, _c = self.m.extract_sender_date('Dated: 20 June 2026')
        self.assertIsNotNone(d)
        self.assertEqual((d.year, d.month, d.day), (2026, 6, 20))

    def test_english_date_numeric(self):
        d, _c = self.m.extract_sender_date('Date: 20/06/2026')
        self.assertIsNotNone(d)
        self.assertEqual((d.year, d.month, d.day), (2026, 6, 20))

    def test_garbled_layer_date_recovered(self):
        # طبقة مسح مشوَّهة: «Jul 2, 2026» → «lul 22026» (J→l + فاصلة ساقطة) —
        # حالة حقيقية من إيميل QPC ممرَّر عبر ماسحة مكتب
        d, _c = self.m.extract_sender_date('Ref. No. QPC-1\nDate: lul 22026\nSubject: x')
        self.assertIsNotNone(d)
        self.assertEqual((d.year, d.month, d.day), (2026, 7, 2))

    def test_garbled_month_sibling(self):
        d, _c = self.m.extract_sender_date('Date: Ian 5, 2026')   # Jan بحرف I
        self.assertIsNotNone(d)
        self.assertEqual((d.year, d.month, d.day), (2026, 1, 5))

    def test_degarble_confined_to_date_zone(self):
        # «lul» خارج نافذة التاريخ لا يُمَسّ — التصحيح محصور بعد العلامة
        d, _c = self.m.extract_sender_date('lul 22026 بلا علامة تاريخ')
        self.assertIsNone(d)

    def test_body_citation_date_ignored(self):
        # حالة #11222 الحقيقية: تاريخ الكتاب فارغ (يدوي) وإحالة «بتأريخ» في المتن —
        # يجب None لا تاريخ الإحالة (تاريخ خاطئ أسوأ من فراغ)
        text = ('جمهورية العراق\nوزارة النفط\nالتاريخ: / /\nإلى / المقاولين كافة\n'
                'م / تجهيز أنابيب النفط والغاز من شركة\nعمران التركية\n'
                'نرافق لكم نسخة من كتاب الوزارة المرقم 11\nبتأريخ 2026/5/3 المتضمن الدراسة')
        self.assertIsNone(self.m.extract_sender_date(text)[0])

    def test_ba_prefixed_date_label_rejected(self):
        # «بتأريخ/بالتاريخ» ظرف إحالة لا تسمية حقل — تُرفض حتى في الرأس
        self.assertIsNone(self.m.extract_sender_date('العدد: 5\nبتأريخ 2026/5/3\nإلى فلان')[0])

    def test_header_date_beyond_cap_ignored(self):
        # علامة تاريخ بعد سقف منطقة الرأس (15 سطراً) لا تُلتقط
        filler = '\n'.join(f'سطر حشو {i}' for i in range(16))
        self.assertIsNone(self.m.extract_sender_date(filler + '\nالتاريخ: 2026/6/9')[0])

    def test_bare_date_line_in_header(self):
        # قالب Slb الغربي: التاريخ سطرٌ عارٍ أول الرسالة بلا «Date:» (حالة حيّة)
        d, _c = self.m.extract_sender_date('July 6 , 2026\nLetter Reference 135\nTo: MdOC')
        self.assertIsNotNone(d)
        self.assertEqual((d.year, d.month, d.day), (2026, 7, 6))

    def test_bare_date_only_when_whole_line(self):
        # تاريخٌ داخل جملة (إحالة) ليس سطرَ تاريخٍ عارياً — لا يُلتقط
        self.assertIsNone(self.m.extract_sender_date(
            'نشير الى كتابكم المؤرخ 2026/5/3 بخصوص التعيينات')[0])


class TitleWrapJoinTests(SimpleTestCase):
    """ضمّ تتمّة الموضوع الملتفّ — حالة #11222 + الموانع (توصية استشارية)."""

    def setUp(self):
        self.m = PatternMatcher()

    def test_wrapped_arabic_subject_joined(self):
        text = ('وزارة النفط\nإلى / المقاولين كافة\n'
                'م / تجهيز أنابيب النفط والغاز من شركة\nعمران التركية\nنرافق لكم نسخة')
        t = self.m.extract_title_keywords(text)
        self.assertIn('عمران', t)
        self.assertIn('التركية', t)

    def test_body_opener_never_joined(self):
        text = 'م / تعميم ضوابط الدوام الرسمي للموظفين\nنرافق لكم نسخة من الضوابط'
        self.assertNotIn('نرافق', self.m.extract_title_keywords(text))

    def test_english_salutation_not_joined(self):
        text = 'Subject: Coordination on Gas Pipeline Hot Tapping Activities\nDear Sir,'
        self.assertNotIn('Dear', self.m.extract_title_keywords(text))

    def test_short_complete_subject_not_joined(self):
        # موضوع قصير مكتمل (<20 محرفاً، لا ينتهي بكلمة ربط) — لا ضمّ
        self.assertEqual(self.m.extract_title_keywords('م / الإجازات\nكافة الأقسام مدعوة'),
                         'الإجازات')

    def test_wrapped_english_subject_joined(self):
        # حالة 195 الحقيقية: Subject ملتفّ لسطر ثانٍ
        text = ('Subject: Request Meeting with Ministerial Cost Team (MCT) to Discuss\n'
                'Estimate for MF Drilling Project\nDear Mr. Hassan,')
        t = self.m.extract_title_keywords(text)
        self.assertIn('Estimate', t)

    def test_m_marker_with_invisible_mark_beats_ila_line(self):
        # بلاغ المالك: «م‏/» (بعلامة RTL خفية) كانت تفشل فيُلتقط سطر «إلى/» موضوعاً —
        # م/ هي الدلالة الأقوى دائماً ويجب أن تفوز
        text = ('وزارة النفط\nإلى/ الجهات كافة\nم‏/ ضوابط منح الإجازات الدراسية\nتحية طيبة')
        t = self.m.extract_title_keywords(text)
        self.assertIn('ضوابط', t)
        self.assertNotIn('الجهات', t)

    def test_ila_line_never_title_even_without_m(self):
        # حتى بلا م/ إطلاقاً: سطر المُرسَل إليه يُتخطّى لأول سطر جوهري بعده
        text = 'إلى / المقاولين المشغلين كافة\nتعليمات الصرف للموازنة التشغيلية المحدثة'
        t = self.m.extract_title_keywords(text)
        self.assertNotIn('المقاولين', t)
        self.assertIn('تعليمات', t)

    def test_bilingual_columns_arabic_wins_regardless_of_order(self):
        # كتب بعمودين (عربي + ترجمة إنكليزية): OCR قد يُخرج Subject قبل م/ —
        # العربية (الأصل المعتمد) تفوز دائماً (توجيه مالك)
        text = ('Subject: Approval of the Operational Budget Instructions\n'
                'م/ تعليمات الموازنة التشغيلية\nتحية طيبة')
        t = self.m.extract_title_keywords(text)
        self.assertIn('الموازنة', t)
        self.assertNotIn('Approval', t)

    def test_english_only_doc_still_uses_subject(self):
        # مستند إنكليزي صرف (لا علامة عربية): Subject يعمل كما كان
        t = self.m.extract_title_keywords('NK Petroleum\nSubject: Gas Pipeline Coordination\nDear Sir')
        self.assertIn('Pipeline', t)

    def test_full_width_body_line_not_joined(self):
        # بلاغ مالك حيّ: بعد م/ سليمة، سطرُ متنٍ كامل العرض («حرصاً على…») ضُمّ خطأً —
        # بوّابة الطول (>45) تصدّه حتى لو غابت افتتاحيته من القائمة
        text = ('م/ معوقات عمل قسم الرقابة والتدقيق الداخلي\n'
                'سعياً الى تحقيق افضل النتائج في تقويم الاداء وتطوير اجراءات العمل النافذة')
        t = self.m.extract_title_keywords(text)
        self.assertIn('معوقات', t)
        self.assertNotIn('تقويم', t)


class ExtractSenderNumberTests(SimpleTestCase):
    """رقم صادر الجهة المطبوع (إيميلات/مكتوب): كودٌ مركّب بعد العدد/ref، لا الفاكس."""
    def setUp(self):
        self.m = PatternMatcher()

    def test_compound_code_after_aladad(self):
        n, c = self.m.extract_sender_number('شركة النفط\nالعدد: KHL/25/32\nالموضوع: كذا')
        self.assertEqual(n, 'KHL/25/32')
        self.assertGreater(c, 0)

    def test_english_ref_marker(self):
        n, _c = self.m.extract_sender_number('From: x\nRef: EMDOC-2025-043\nBody')
        self.assertEqual(n, 'EMDOC-2025-043')

    def test_bare_number_after_ref(self):
        # رقمٌ مجرّد بعد علامة صريحة (بلا بادئة) — يُلتقط أيضاً
        n, _c = self.m.extract_sender_number('Date: June 20\nRef: 20260237\nTo: x')
        self.assertEqual(n, '20260237')

    def test_prefix_compound_preferred(self):
        # حين توجد بادئة، يُلتقط الكود المركّب كاملاً (NK-...) لا الرقم المجرّد
        n, _c = self.m.extract_sender_number('Ref: NK-20260237')
        self.assertEqual(n, 'NK-20260237')

    def test_arabic_indic_digits_normalized(self):
        n, _c = self.m.extract_sender_number('العدد: هغ/٨٨١')
        self.assertIsNotNone(n)
        self.assertTrue(n.endswith('881'))

    def test_fax_number_ignored(self):
        # رقمٌ بعد «فاكس» ليس رقم صادر — يجب تجاهله
        self.assertEqual(self.m.extract_sender_number('فاكس: 00964-1/2345'), (None, 0.0))

    def test_no_number(self):
        self.assertEqual(self.m.extract_sender_number('نصّ بلا رقم مرجعي'), (None, 0.0))

    def test_arabic_digits_slash_letter(self):
        # صيغة عربية شائعة: رقم ثم حرف سجلّ (و=وارد، ص=صادر) — «241/و»
        self.assertEqual(self.m.extract_sender_number('العدد: 241/و')[0], '241/و')
        self.assertEqual(self.m.extract_sender_number('الرقم 12/ص')[0], '12/ص')

    def test_reference_number_marker(self):
        # «Reference Number» علامة كاملة — لا «ref» فقط (الذي يفشل داخل «Reference»)
        n, _c = self.m.extract_sender_number('Reference Number: MF-2026-195')
        self.assertEqual(n, 'MF-2026-195')

    def test_body_citation_number_ignored(self):
        # 41/45 إيجابية كاذبة مقيسة: «العدد» في إحالة متن تحت سطر الموضوع — تُرفض
        text = ('جمهورية العراق\nالعدد: \nالموضوع: متابعة\n'
                'اشارة الى الامر الوزاري العدد 5978 في 2025/1/3 نرجو الاطلاع')
        self.assertIsNone(self.m.extract_sender_number(text)[0])

    def test_ba_prefixed_adad_rejected(self):
        # «بالعدد» ظرف إحالة لا تسمية حقل — تُرفض حتى في الرأس
        self.assertIsNone(self.m.extract_sender_number('كتاب الشركة بالعدد 26910 المؤرخ')[0])

    def test_header_adad_beyond_cap_ignored(self):
        filler = '\n'.join(f'سطر حشو {i}' for i in range(16))
        self.assertIsNone(self.m.extract_sender_number(filler + '\nالعدد: 1234')[0])

    def test_dotted_ref_no_and_two_segment_code(self):
        # حالة EBS الحيّة: «Ref. No.» بنقطة + كود بمقطعين حرفيين وأرقام ملتصقة
        n, _c = self.m.extract_sender_number('EBSPetroleum\nRef. No. EBS-MdOC20260594\nDate: July 3')
        self.assertEqual(n, 'EBS-MdOC20260594')

    def test_two_segment_code_with_spaces(self):
        # حالة QPC الحيّة: مسافة بعد الشرطة الأولى
        n, _c = self.m.extract_sender_number('Ref. No. QPC- MdOC-20260083\nSubject: x')
        self.assertEqual(n, 'QPC-MdOC-20260083')

    def test_reference_to_prose_still_ignored(self):
        # «reference to …» النثرية لا تُلتقط (لا كود بعدها)
        self.assertIsNone(self.m.extract_sender_number(
            'With reference to single source tender discussions held earlier')[0])


class SplitRefFromTitleTests(SimpleTestCase):
    """نمط Slb: رقم الصادر داخل سطر الموضوع («Ref-135, Akkas…») — يُقتطع ويُنظَّف."""

    def setUp(self):
        self.m = PatternMatcher()

    def test_slb_real_saved_titles(self):
        # عناوين محفوظة حرفياً من كتب المالك (#11238، #11188)
        n, t = self.m.split_ref_from_title('Ref-135 Akkas-8 Abandonment and Sidetrack Program, MdOC-F-25069')
        self.assertEqual(n, '135')
        self.assertTrue(t.startswith('Akkas-8'))
        n2, t2 = self.m.split_ref_from_title('ref-129, Akkas tubing requirements , mdoc -F-25069')
        self.assertEqual(n2, '129')
        self.assertTrue(t2.startswith('Akkas'))

    def test_plain_title_untouched(self):
        n, t = self.m.split_ref_from_title('Submission of Weekly Report No 11')
        self.assertIsNone(n)
        self.assertEqual(t, 'Submission of Weekly Report No 11')

    def test_reference_prose_not_split(self):
        # «Reference is made…» نثرٌ لا كود — لا اقتطاع
        n, _t = self.m.split_ref_from_title('Reference is made to your letter regarding the pipeline')
        self.assertIsNone(n)


class ExtractSecretLevelTests(SimpleTestCase):
    def setUp(self):
        self.m = PatternMatcher()

    def test_topsecret_wins_over_secret(self):
        lvl, _ = self.m.extract_secret_level('وثيقة سري للغاية')
        self.assertEqual(lvl, 'topsecret')

    def test_secret(self):
        self.assertEqual(self.m.extract_secret_level('ملف سري')[0], 'secret')

    def test_normal(self):
        self.assertEqual(self.m.extract_secret_level('كتاب اعتيادي')[0], 'normal')

    def test_none(self):
        self.assertEqual(self.m.extract_secret_level('بلا تصنيف'), (None, 0.0))


class ExtractBookKindTests(SimpleTestCase):
    def setUp(self):
        self.m = PatternMatcher()

    def test_incoming_arabic(self):
        self.assertEqual(self.m.extract_book_kind('كتاب وارد')[0], 'incoming')

    def test_outgoing_arabic(self):
        self.assertEqual(self.m.extract_book_kind('كتاب صادر')[0], 'outgoing')

    def test_incoming_english(self):
        self.assertEqual(self.m.extract_book_kind('INCOMING letter')[0], 'incoming')

    def test_none(self):
        self.assertEqual(self.m.extract_book_kind('نص محايد'), (None, 0.0))


class DateParserTests(SimpleTestCase):
    def test_iso(self):
        self.assertEqual(DateParser.parse('2024-01-15').date().isoformat(), '2024-01-15')

    def test_arabic_month_name(self):
        d = DateParser.parse('15 آذار 2024')
        self.assertEqual((d.year, d.month, d.day), (2024, 3, 15))

    def test_invalid_returns_none(self):
        self.assertIsNone(DateParser.parse('ليس تاريخاً'))
        self.assertIsNone(DateParser.parse(''))
        self.assertIsNone(DateParser.parse(None))

    def test_format_date(self):
        self.assertEqual(DateParser.format_date(datetime(2024, 1, 15)), '2024-01-15')


class HelpersTests(SimpleTestCase):
    def test_extract_structured_data_keys(self):
        data = extract_structured_data('كتاب وارد سري رقم الكتاب: 99 بتاريخ 15-01-2024')
        for key in ('book_number', 'date', 'secret_level', 'book_kind', 'entities', 'title'):
            self.assertIn(key, data)
        self.assertEqual(data['book_kind'], 'incoming')
        self.assertEqual(data['secret_level'], 'secret')

    def test_parse_date_flexible(self):
        self.assertEqual(parse_date_flexible('2024-01-15').date().isoformat(), '2024-01-15')
