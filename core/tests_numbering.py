# -*- coding: utf-8 -*-
"""اختبارات قواعد رقم القيد — المصدر الوحيد (core/numbering.py)."""
from django.test import SimpleTestCase

from core import numbering as N


class ParseTests(SimpleTestCase):
    def test_blank(self):
        for v in ('', None, '   '):
            self.assertEqual(N.parse(v).kind_of, 'blank')

    def test_current_series_is_bare(self):
        p = N.parse('2433')
        self.assertEqual((p.year, p.seq, p.kind_of), (None, 2433, 'series'))

    def test_short_numbers_are_series_not_years(self):
        # '2025' وحدها تسلسل لا سنة — اشتراط الطول ≥ 8 يمنع الخلط
        p = N.parse('2025')
        self.assertEqual((p.year, p.seq, p.kind_of), (None, 2025, 'series'))

    def test_tagged_year(self):
        p = N.parse('20250825')
        self.assertEqual((p.year, p.seq, p.kind_of), (2025, 825, 'tagged'))

    def test_old_years_are_accepted(self):
        # في البيانات كتب مؤرّخة 2000 و2007 و2014 — الحدّ الأدنى 2000 لا 2020
        for y in (2000, 2007, 2014, 2025):
            p = N.parse('%d0825' % y)
            self.assertEqual(p.year, y, msg='سنة %d' % y)
            self.assertEqual(p.seq, 825)

    def test_base_year_and_later_are_never_tagged(self):
        # 2026 فما بعدها لا تُوسَم: أرقامها هي السلسلة نفسها
        p = N.parse('20260825')
        self.assertEqual(p.kind_of, 'series')
        self.assertIsNone(p.year)

    def test_training(self):
        p = N.parse('T57')
        self.assertEqual((p.seq, p.kind_of), (57, 'training'))

    def test_unknown_text_survives(self):
        p = N.parse('قديم-بلا-56')
        self.assertEqual(p.kind_of, 'unknown')
        self.assertEqual(p.raw, 'قديم-بلا-56')


class FormatTests(SimpleTestCase):
    def test_series_is_bare(self):
        self.assertEqual(N.format_series(2433), '2433')
        self.assertEqual(N.format_series('7'), '7')

    def test_tagged_pads_to_four(self):
        self.assertEqual(N.format_tagged(825, 2025), '20250825')
        self.assertEqual(N.format_tagged(5782, 2025), '20255782')

    def test_tagged_allows_five_digit_sequences(self):
        self.assertEqual(N.format_tagged(27189, 2025), '202527189')

    def test_ledger_year_decides(self):
        self.assertEqual(N.format_for_ledger_year(825, 2025), '20250825')
        self.assertEqual(N.format_for_ledger_year(1815, 2026), '1815')
        self.assertEqual(N.format_for_ledger_year(9, 2027), '9')
        self.assertEqual(N.format_for_ledger_year(9, None), '9')

    def test_round_trip(self):
        for seq, year in ((825, 2025), (1, 2000), (5782, 2025), (2433, 2026), (7, None)):
            s = N.format_for_ledger_year(seq, year)
            p = N.parse(s)
            self.assertEqual(p.seq, seq, msg=s)
            expected_year = year if (year and year < N.BASE_YEAR) else None
            self.assertEqual(p.year, expected_year, msg=s)


class DisplayTests(SimpleTestCase):
    def test_display_is_always_the_bare_stamp_number(self):
        self.assertEqual(N.display('20250825'), '825')
        self.assertEqual(N.display('2433'), '2433')
        self.assertEqual(N.display('T57'), 'T57')
        self.assertEqual(N.display(''), '')

    def test_year_tag_separate_from_the_number(self):
        self.assertEqual(N.year_tag('20250825'), '2025')
        self.assertEqual(N.year_tag('2433'), '')

    def test_unknown_displays_verbatim(self):
        self.assertEqual(N.display('قديم-بلا-56'), 'قديم-بلا-56')


class SearchTests(SimpleTestCase):
    """كتابة الرقم المجرّد يجب أن تجده في كل صيغه المخزَّنة."""

    def _matches(self, digits, stored):
        import re
        return any(re.match(p, stored) for p in N.search_patterns(digits))

    def test_finds_current_series(self):
        self.assertTrue(self._matches('825', '825'))

    def test_finds_tagged_years(self):
        self.assertTrue(self._matches('825', '20250825'))
        self.assertTrue(self._matches('825', '20070825'))

    def test_finds_training(self):
        self.assertTrue(self._matches('57', 'T57'))

    def test_does_not_match_a_longer_or_different_number(self):
        self.assertFalse(self._matches('825', '8250'))
        self.assertFalse(self._matches('825', '1825'))
        self.assertFalse(self._matches('825', '20258250'))

    def test_five_digit_sequences_are_findable(self):
        self.assertTrue(self._matches('27189', '202527189'))
        self.assertTrue(self._matches('27189', '27189'))


class ContractTests(SimpleTestCase):
    """ثوابت يعتمد عليها بقيّة النظام."""

    def test_base_year_is_the_pivot(self):
        self.assertEqual(N.BASE_YEAR, 2026)

    def test_registers_are_split_by_who_issues_the_number(self):
        self.assertIn('outgoing_external', N.MANUAL_KINDS)
        for k in ('incoming_internal', 'incoming_external', 'outgoing_internal'):
            self.assertIn(k, N.SERIES_KINDS)
        self.assertEqual(set(N.SERIES_KINDS) & set(N.MANUAL_KINDS), set())

    def test_training_numbers_can_never_collide_with_official_ones(self):
        # أول خانة غير رقمية ⇒ خارج فضاء السلسلة بنيوياً
        self.assertFalse(N.format_training(2433).isdigit())
        self.assertNotEqual(N.format_training(2433), N.format_series(2433))
