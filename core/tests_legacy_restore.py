# -*- coding: utf-8 -*-
"""اختبارات الدوال النقية في core/legacy_restore.py (محرّك الاستعادة من SQL Server).

نختبر المنطق المستقل عن pyodbc: تطبيع الحالة، تحليل التاريخ، فصل أسماء
الجهات، والتسلسل لـ JSON — حيث تختبئ عيوب التحويل.
"""
from datetime import date, datetime

from django.test import SimpleTestCase

from .legacy_restore import (
    _norm_status, _parse_date, _parse_entity_names, serialize_for_json,
)


class NormStatusTests(SimpleTestCase):
    def test_mapped_values(self):
        self.assertEqual(_norm_status('حفظ'), 'archived')
        self.assertEqual(_norm_status('تمت الاجابة'), 'done')
        self.assertEqual(_norm_status('تمت الإجابة'), 'done')
        self.assertEqual(_norm_status('منجز'), 'done')
        self.assertEqual(_norm_status('قيد المتابعة'), 'pending')

    def test_empty_maps_to_pending(self):
        self.assertEqual(_norm_status(''), 'pending')
        self.assertEqual(_norm_status('   '), 'pending')   # whitespace → ''

    def test_unknown_recent_date_is_pending(self):
        self.assertEqual(_norm_status('حالة غريبة', date(2026, 6, 1)), 'pending')

    def test_unknown_old_date_is_archived(self):
        self.assertEqual(_norm_status('حالة غريبة', date(2020, 1, 1)), 'archived')

    def test_unknown_no_date_is_archived(self):
        self.assertEqual(_norm_status('حالة غريبة'), 'archived')

    def test_unknown_accepts_datetime(self):
        self.assertEqual(_norm_status('حالة غريبة', datetime(2026, 6, 1, 9, 0)), 'pending')


class ParseDateTests(SimpleTestCase):
    def test_iso(self):
        self.assertEqual(_parse_date('2024-01-15'), date(2024, 1, 15))

    def test_dmy_slash(self):
        self.assertEqual(_parse_date('15/01/2024'), date(2024, 1, 15))

    def test_ymd_slash(self):
        self.assertEqual(_parse_date('2024/01/15'), date(2024, 1, 15))

    def test_iso_datetime_string_truncated(self):
        self.assertEqual(_parse_date('2024-01-15T10:30:00'), date(2024, 1, 15))

    def test_datetime_object_to_date(self):
        self.assertEqual(_parse_date(datetime(2024, 1, 15, 8, 0)), date(2024, 1, 15))

    def test_date_passthrough(self):
        self.assertEqual(_parse_date(date(2024, 1, 15)), date(2024, 1, 15))

    def test_empty_and_invalid_return_none(self):
        self.assertIsNone(_parse_date(''))
        self.assertIsNone(_parse_date(None))
        self.assertIsNone(_parse_date('xx'))


class ParseEntityNamesTests(SimpleTestCase):
    def test_plus_split(self):
        self.assertEqual(_parse_entity_names('شعبة الحاسبة + سارة'), ['شعبة الحاسبة', 'سارة'])

    def test_arabic_comma_split(self):
        self.assertEqual(_parse_entity_names('وزارة أ، وزارة ب'), ['وزارة أ', 'وزارة ب'])

    def test_latin_comma_split(self):
        self.assertEqual(_parse_entity_names('A, B'), ['A', 'B'])

    def test_does_not_split_on_waw(self):
        # ' و ' ليست فاصلاً (قد تكون جزءاً من الاسم)
        self.assertEqual(_parse_entity_names('الفحص و التدقيق'), ['الفحص و التدقيق'])

    def test_expands_wahda_abbreviation(self):
        self.assertEqual(_parse_entity_names('و.التقارير'), ['وحدة التقارير'])
        self.assertEqual(_parse_entity_names('و. اللجان'), ['وحدة اللجان'])

    def test_filters_garbage(self):
        self.assertEqual(_parse_entity_names('123'), [])
        self.assertEqual(_parse_entity_names('كوم'), [])
        self.assertEqual(_parse_entity_names('اا'), [])

    def test_empty_returns_empty_list(self):
        self.assertEqual(_parse_entity_names(''), [])
        self.assertEqual(_parse_entity_names(None), [])

    def test_mixed_valid_and_garbage(self):
        self.assertEqual(_parse_entity_names('وزارة الصحة + 123'), ['وزارة الصحة'])


class SerializeForJsonTests(SimpleTestCase):
    def test_date_to_isoformat(self):
        self.assertEqual(serialize_for_json(date(2024, 1, 15)), '2024-01-15')

    def test_datetime_to_isoformat(self):
        self.assertEqual(serialize_for_json(datetime(2024, 1, 15, 10, 30)), '2024-01-15T10:30:00')

    def test_none_passthrough(self):
        self.assertIsNone(serialize_for_json(None))

    def test_other_to_str(self):
        self.assertEqual(serialize_for_json(123), '123')
