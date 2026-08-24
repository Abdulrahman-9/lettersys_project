# -*- coding: utf-8 -*-
"""حرزُ تعيين عمودَي التاريخ في الاستيراد — لا يعود الانقلاب من بابٍ خلفيّ.

الانقلاب المقيس (2026-08-23، مؤكَّدٌ عدائيّاً — سجلّ التقييم قسم D): في سجلّات
الوارد `DATE` حبرُ الجهة و`CND` تاريخُ قيدنا. التعيين القديم عكسهما فسمّم 11,048
صفّاً (أصلحتها هجرة 0060). هذا الاختبار يقفل التعيين على دلالته الصحيحة.
"""
import datetime

from django.test import SimpleTestCase

from core.legacy_restore import _legacy_dates


class LegacyDateMappingTests(SimpleTestCase):
    def test_incoming_cnd_is_ours_and_date_is_senders_ink(self):
        rd = {'IIDATE': '2025-03-06', 'IICND': '2025-03-09'}
        bdate, sdate = _legacy_dates(rd, 'II', is_out=False)
        self.assertEqual(bdate, datetime.date(2025, 3, 9))    # قيدُنا ⟵ CND
        self.assertEqual(sdate, datetime.date(2025, 3, 6))    # حبرُ الجهة ⟵ DATE

    def test_outgoing_date_is_ours_and_no_sender_date(self):
        rd = {'IODATE': '2025-05-01', 'IOCND': '2025-07-01'}
        bdate, sdate = _legacy_dates(rd, 'IO', is_out=True)
        self.assertEqual(bdate, datetime.date(2025, 5, 1))
        self.assertIsNone(sdate)

    def test_missing_columns_degrade_to_none(self):
        self.assertEqual(_legacy_dates({}, 'II', is_out=False), (None, None))
