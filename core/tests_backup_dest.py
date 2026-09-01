# -*- coding: utf-8 -*-
"""حرّاسُ وجهة النسخ وأداتِه — عيبٌ لا يظهر إلّا يوم الحاجة."""

import os
from pathlib import Path
from unittest import mock

from django.test import TestCase

from core import backup_service


class PgDumpDiscoveryTests(TestCase):
    def test_explicit_env_wins(self):
        with mock.patch.dict(os.environ, {'PG_DUMP_BIN': __file__}):
            self.assertEqual(backup_service._find_pg_dump(), __file__)

    def test_path_is_used_when_no_env(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch.object(backup_service.shutil, 'which',
                               return_value='/usr/bin/pg_dump'):
            self.assertEqual(backup_service._find_pg_dump(), '/usr/bin/pg_dump')

    def test_windows_install_is_found_when_path_is_empty(self):
        """مقيسٌ على هذا الجهاز: pg_dump ليس في PATH — وكانت كلُّ نسخةٍ ترمي خطأً."""
        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch.object(backup_service.shutil, 'which', return_value=None):
            found = backup_service._find_pg_dump()

        self.assertIsNotNone(found, 'لم يُعثر على pg_dump — النسخُ معطَّل')
        self.assertTrue(Path(found).exists())

    def test_newest_install_wins_numerically(self):
        """«9» أكبرُ من «16» نصّيّاً — والأقدمُ يرفض قاعدةً أحدثَ منه."""
        found = backup_service._find_pg_dump()

        if found and 'PostgreSQL' in found:
            versions = [int(p.name) for p in Path(found).parents
                        if p.name.isdigit()]
            self.assertTrue(versions)


class BackupDirTests(TestCase):
    def test_env_overrides_the_default(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {'BACKUP_DIR': tmp}):
                self.assertEqual(backup_service.default_backup_dir(), Path(tmp))

    def test_default_is_a_separate_disk(self):
        """قرصُ النظام على حافّة الامتلاء — الوجهةُ منفصلةٌ بقرار المالك."""
        self.assertEqual(backup_service.DEFAULT_BACKUP_DIR, Path('D:/trackbackup'))

    def test_fallback_to_system_disk_is_logged_not_silent(self):
        """نسخةٌ تُكتب بهدوءٍ على قرصٍ ممتلئ أسوأ من فشلٍ صريح."""
        with mock.patch.dict(os.environ, {'BACKUP_DIR': 'Q:/no/such/place'}), \
             mock.patch.object(backup_service.Path, 'mkdir',
                               side_effect=[OSError('no disk'), None]), \
             self.assertLogs(backup_service.logger, level='ERROR') as logs:
            backup_service.default_backup_dir()

        self.assertTrue(any('السقوط' in line for line in logs.output))
