"""
جدولة النسخ الاحتياطي — ساعةُ الإعداد أوّلُ وقتٍ للتنفيذ لا وقتُه الوحيد.

المهمّة الساعيّة كانت تشترط مطابقة الساعة، والجهاز الحيّ لا يكون شغّالاً عندها
في أيّام كثيرة: نسخ «يوميّ» صار 10-22 · 10-27 · 11-01 · 11-02، وكلُّ تخطٍّ ينتهي
بـrc=0. هذه الاختبارات تثبت التعويض ولا تُفرط فيه (لا نسختين في يوم، ولا تقديمَ
الموعد لمن نُسخ أمس).
"""

import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from core.models import BackupSettings
from core.tasks import _backup_is_due, scheduled_backup

BAGHDAD = ZoneInfo('Asia/Baghdad')


def at(year, month, day, hour=0, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=BAGHDAD)


class _DueCase(SimpleTestCase):
    def due(self, now, last, frequency=BackupSettings.FREQ_DAILY, hour=9, enabled=True):
        cfg = BackupSettings(enabled=enabled, frequency=frequency, hour=hour, last_run_at=last)
        with timezone.override(BAGHDAD):
            return _backup_is_due(cfg, now)


class GeneralRuleTests(_DueCase):
    def test_disabled_never_runs_however_overdue(self):
        self.assertFalse(self.due(at(2026, 11, 3, 10), at(2026, 1, 1), enabled=False))

    def test_never_run_is_due_even_before_the_hour(self):
        self.assertTrue(self.due(at(2026, 11, 3, 8), None))

    def test_second_run_on_the_same_day_is_refused(self):
        self.assertFalse(self.due(at(2026, 11, 3, 15), at(2026, 11, 3, 9, 5)))

    def test_same_day_is_measured_on_the_local_clock(self):
        # 22:30 UTC يوم 11-02 هي 01:30 بتوقيت بغداد يوم 11-03: نُفِّذ «اليوم» لا «أمس».
        last = datetime(2026, 11, 2, 22, 30, tzinfo=ZoneInfo('UTC'))
        self.assertFalse(self.due(at(2026, 11, 3, 15), last))

    def test_unknown_frequency_is_never_due(self):
        self.assertFalse(self.due(at(2026, 11, 3, 15), at(2026, 10, 1), frequency='hourly'))


class DailyTests(_DueCase):
    def test_runs_at_the_exact_hour(self):
        self.assertTrue(self.due(at(2026, 11, 3, 9), at(2026, 11, 2, 9, 5)))

    def test_catches_up_after_the_hour_was_missed(self):
        # الحادثة نفسها: الساعة 13 فاتت والجهاز اشتغل في الرابعة عصراً.
        self.assertTrue(self.due(at(2026, 11, 3, 16), at(2026, 11, 2, 13), hour=13))

    def test_yesterdays_backup_waits_for_todays_hour(self):
        self.assertFalse(self.due(at(2026, 11, 3, 8), at(2026, 11, 2, 9, 5)))

    def test_two_days_without_a_backup_does_not_wait_for_the_hour(self):
        self.assertTrue(self.due(at(2026, 11, 3, 8), at(2026, 11, 1, 9, 5)))

    def test_a_machine_off_at_the_hour_still_backs_up_every_other_day(self):
        """إعادةُ الحادثة: الساعة 13 والجهاز يعمل صباحاً فقط — لم يكن يُنسخ أبداً."""
        cfg = BackupSettings(enabled=True, frequency=BackupSettings.FREQ_DAILY, hour=13,
                             last_run_at=at(2026, 10, 31, 13))
        runs = []
        with timezone.override(BAGHDAD):
            for offset in range(8):
                day = at(2026, 11, 1) + timedelta(days=offset)
                for hour in range(8, 13):
                    now = day.replace(hour=hour)
                    if _backup_is_due(cfg, now):
                        runs.append(now)
                        cfg.last_run_at = now
        self.assertEqual([r.day for r in runs], [2, 4, 6, 8])
        self.assertEqual({r.hour for r in runs}, {8})


class WeeklyTests(_DueCase):
    FREQ = BackupSettings.FREQ_WEEKLY

    def test_six_days_is_too_soon_even_after_the_hour(self):
        self.assertFalse(self.due(at(2026, 11, 7, 15), at(2026, 11, 1, 9), self.FREQ))

    def test_seventh_day_waits_for_the_hour(self):
        self.assertFalse(self.due(at(2026, 11, 8, 8), at(2026, 11, 1, 9), self.FREQ))

    def test_seventh_day_runs_once_the_hour_passed(self):
        self.assertTrue(self.due(at(2026, 11, 8, 9), at(2026, 11, 1, 9), self.FREQ))

    def test_eighth_day_does_not_wait_for_the_hour(self):
        self.assertTrue(self.due(at(2026, 11, 9, 8), at(2026, 11, 1, 9), self.FREQ))


class MonthlyTests(_DueCase):
    FREQ = BackupSettings.FREQ_MONTHLY

    def test_same_month_is_never_due(self):
        self.assertFalse(self.due(at(2026, 11, 29, 15), at(2026, 11, 1, 9), self.FREQ))

    def test_same_month_of_another_year_is_due(self):
        self.assertTrue(self.due(at(2026, 11, 2, 8), at(2025, 11, 20, 9), self.FREQ))

    def test_the_first_waits_for_the_hour(self):
        self.assertFalse(self.due(at(2026, 11, 1, 8), at(2026, 10, 1, 9), self.FREQ))

    def test_the_first_runs_once_the_hour_passed(self):
        self.assertTrue(self.due(at(2026, 11, 1, 9), at(2026, 10, 1, 9), self.FREQ))

    def test_after_the_first_does_not_wait_for_the_hour(self):
        self.assertTrue(self.due(at(2026, 11, 2, 8), at(2026, 10, 1, 9), self.FREQ))


class ScheduledTaskTests(TestCase):
    """المهمّة نفسها: تعوّض مرّةً واحدة، ولا تُحرَّك ``last_run_at`` عند التخطّي."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for name, value in (
            ('create_encrypted_pg_backup', 'db.enc'),
            ('create_encrypted_config_backup', 'cfg.enc'),
            ('mirror_tree', {'copied': 0}),
            ('default_backup_dir', Path(tmp.name)),
            ('encryption_key_status', {'exists': True}),
            ('prune_old_backups', 0),
        ):
            patcher = patch(f'core.backup_service.{name}', return_value=value)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        self.last = at(2026, 11, 2, 13)
        BackupSettings.objects.update_or_create(singleton=1, defaults={
            'enabled': True, 'frequency': BackupSettings.FREQ_DAILY,
            'hour': 13, 'last_run_at': self.last,
        })

    def run_at(self, now):
        with timezone.override(BAGHDAD), patch('django.utils.timezone.now', return_value=now):
            return scheduled_backup()

    def test_missed_hour_is_caught_up_once_then_skipped(self):
        catch_up = at(2026, 11, 3, 16)
        report = self.run_at(catch_up)
        self.assertEqual(report['database'], 'db.enc')
        self.create_encrypted_pg_backup.assert_called_once()
        self.assertEqual(BackupSettings.get().last_run_at, catch_up)

        self.assertEqual(self.run_at(at(2026, 11, 3, 17)), {'skipped': True})
        self.create_encrypted_pg_backup.assert_called_once()
        self.assertEqual(BackupSettings.get().last_run_at, catch_up)

    def test_before_the_hour_skips_without_touching_anything(self):
        self.assertEqual(self.run_at(at(2026, 11, 3, 8)), {'skipped': True})
        self.create_encrypted_pg_backup.assert_not_called()
        self.assertEqual(BackupSettings.get().last_run_at, self.last)
