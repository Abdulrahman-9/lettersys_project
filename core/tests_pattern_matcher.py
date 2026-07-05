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
