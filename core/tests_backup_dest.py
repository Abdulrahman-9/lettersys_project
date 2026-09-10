# -*- coding: utf-8 -*-
"""حرّاسُ وجهة النسخ وأداتِه — عيبٌ لا يظهر إلّا يوم الحاجة."""

import os
import tempfile
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

    def _install(self, root, *versions):
        """هيكلُ تنصيبٍ مصنوع: ``<root>/<نسخة>/bin/pg_dump.exe``."""
        for version in versions:
            binary = Path(root) / version / 'bin' / 'pg_dump.exe'
            binary.parent.mkdir(parents=True)
            binary.write_text('')

    def test_windows_install_is_found_when_path_is_empty(self):
        """مقيسٌ على جهاز المالك: pg_dump ليس في PATH — وكانت كلُّ نسخةٍ ترمي خطأً.

        الجذورُ تُرقَّع على ``tempfile``: الاختبارُ القديم كان يقرأ
        ``C:/Program Files/PostgreSQL`` الحقيقيّ فيقيس **الجهازَ لا الكود**،
        ويحمرّ على لينكس (الفشلُ الوحيد في حزمة كاغل الكاملة) — N11.
        """
        with tempfile.TemporaryDirectory() as tmp:
            self._install(tmp, '16')
            with mock.patch.dict(os.environ, {}, clear=True), \
                 mock.patch.object(backup_service.shutil, 'which', return_value=None), \
                 mock.patch.object(backup_service, 'WINDOWS_PG_ROOTS', (Path(tmp),)):
                found = backup_service._find_pg_dump()

            self.assertEqual(found, str(Path(tmp) / '16' / 'bin' / 'pg_dump.exe'))

    def test_newest_install_wins_numerically(self):
        """«9» أكبرُ من «16» نصّيّاً — والأقدمُ يرفض قاعدةً أحدثَ منه.

        وهذا ليس فرضاً: الإصدارُ 16 هو الذي يُنتج نسخةَ الشحن على هذا الجهاز.
        """
        with tempfile.TemporaryDirectory() as tmp:
            self._install(tmp, '9', '16')
            with mock.patch.dict(os.environ, {}, clear=True), \
                 mock.patch.object(backup_service.shutil, 'which', return_value=None), \
                 mock.patch.object(backup_service, 'WINDOWS_PG_ROOTS', (Path(tmp),)):
                found = backup_service._find_pg_dump()

            self.assertEqual(found, str(Path(tmp) / '16' / 'bin' / 'pg_dump.exe'))

    def test_none_when_nothing_is_installed(self):
        """الغيابُ يُعيد ``None`` — والمُستدعي يرمي رسالةً واضحةً لا يصمت."""
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {}, clear=True), \
                 mock.patch.object(backup_service.shutil, 'which', return_value=None), \
                 mock.patch.object(backup_service, 'WINDOWS_PG_ROOTS', (Path(tmp),)):
                self.assertIsNone(backup_service._find_pg_dump())

    def test_the_real_roots_are_the_windows_ones(self):
        """الترقيعُ لا يُخفي الحقيقة: الثابتُ نفسُه يبقى مقيساً."""
        self.assertEqual(backup_service.WINDOWS_PG_ROOTS,
                         (Path('C:/Program Files/PostgreSQL'),
                          Path('C:/Program Files (x86)/PostgreSQL')))

    def test_pg_restore_shares_the_same_discovery(self):
        """فرعان بالمنطق نفسِه كانا سينحرفان — مصدرٌ واحدٌ للأداتين."""
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / '16' / 'bin' / 'pg_restore.exe'
            binary.parent.mkdir(parents=True)
            binary.write_text('')
            with mock.patch.dict(os.environ, {}, clear=True), \
                 mock.patch.object(backup_service.shutil, 'which', return_value=None), \
                 mock.patch.object(backup_service, 'WINDOWS_PG_ROOTS', (Path(tmp),)):
                self.assertEqual(backup_service.find_pg_restore(), str(binary))


class BackupDirTests(TestCase):
    def test_env_overrides_the_default(self):
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
