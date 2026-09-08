"""
تغطية النسخ الاحتياطي — اختبارات انحدار لسجلّ العيوب ح8.

كان النسخ يغطّي `pg_dump` وحده. وقياسٌ على التنصيب الحيّ: **15.8 غيغا في
14,041 ملفاً** من المرفقات بلا أيّ حماية — فاستعادةٌ «ناجحة» كانت تُعيد نظاماً
بكتبٍ بلا مستنداتها، وبلا `.env` فلا تقوم على جهازٍ نظيف أصلاً.
"""

import os
import tarfile
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase

from core.backup_service import (
    PRUNABLE_PATTERNS,
    create_encrypted_config_backup,
    encryption_key_status,
    mirror_tree,
    prune_old_backups,
)


class MirrorTreeTests(TestCase):
    """المرآة تدريجيّة: تنسخ الجديد والمتغيّر فقط — 15.8 غيغا لا تُنسخ كلّ ساعة."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src = Path(self.tmp.name) / 'src'
        self.dst = Path(self.tmp.name) / 'dst'
        (self.src / 'sub').mkdir(parents=True)
        (self.src / 'a.pdf').write_bytes(b'A' * 100)
        (self.src / 'sub' / 'b.pdf').write_bytes(b'B' * 50)
        self.addCleanup(self.tmp.cleanup)

    def test_first_run_copies_everything_preserving_layout(self):
        stats = mirror_tree(self.src, self.dst)
        self.assertEqual(stats['copied'], 2)
        self.assertEqual(stats['bytes'], 150)
        self.assertTrue((self.dst / 'sub' / 'b.pdf').exists())

    def test_second_run_copies_nothing(self):
        mirror_tree(self.src, self.dst)
        stats = mirror_tree(self.src, self.dst)
        self.assertEqual(stats['copied'], 0, 'المرآة أعادت نسخ ما لم يتغيّر')
        self.assertEqual(stats['scanned'], 2)

    def test_new_file_is_picked_up(self):
        mirror_tree(self.src, self.dst)
        (self.src / 'c.pdf').write_bytes(b'C' * 10)
        stats = mirror_tree(self.src, self.dst)
        self.assertEqual(stats['copied'], 1)
        self.assertTrue((self.dst / 'c.pdf').exists())

    def test_changed_size_is_recopied(self):
        mirror_tree(self.src, self.dst)
        (self.src / 'a.pdf').write_bytes(b'A' * 200)
        stats = mirror_tree(self.src, self.dst)
        self.assertEqual(stats['copied'], 1)
        self.assertEqual((self.dst / 'a.pdf').stat().st_size, 200)

    def test_missing_source_is_reported_not_raised(self):
        """مسارٌ غير موجود لا يُسقط دورة النسخ كلّها."""
        stats = mirror_tree(Path(self.tmp.name) / 'ghost', self.dst)
        self.assertTrue(stats['skipped_missing_src'])
        self.assertEqual(stats['copied'], 0)

    def test_dry_run_touches_nothing(self):
        stats = mirror_tree(self.src, self.dst, dry_run=True)
        self.assertEqual(stats['copied'], 2)
        self.assertFalse(self.dst.exists())


class ConfigBackupTests(TestCase):
    """`.env` يحمل اعتماد القاعدة — بدونه لا تقوم استعادةٌ على جهازٍ نظيف."""

    def test_env_is_archived_and_encrypted(self):
        with tempfile.TemporaryDirectory() as base, tempfile.TemporaryDirectory() as dest:
            env_path = Path(base) / '.env'
            env_path.write_text('DB_PASSWORD=secret\n', encoding='utf-8')

            with patch('core.backup_service.settings') as fake:
                fake.BASE_DIR = Path(base)
                path = create_encrypted_config_backup(target_dir=dest)

            self.assertIsNotNone(path)
            self.assertTrue(str(path).endswith('.tar.enc'))
            # المعمّى لا يكشف السرّ.
            self.assertNotIn(b'secret', Path(path).read_bytes())

    def test_archive_round_trips(self):
        from core.encryption import decrypt_file

        with tempfile.TemporaryDirectory() as base, tempfile.TemporaryDirectory() as dest:
            (Path(base) / '.env').write_text('DB_PASSWORD=secret\n', encoding='utf-8')
            with patch('core.backup_service.settings') as fake:
                fake.BASE_DIR = Path(base)
                enc = create_encrypted_config_backup(target_dir=dest)

            plain = decrypt_file(enc)
            with tarfile.open(plain) as tar:
                self.assertIn('.env', tar.getnames())

    def test_missing_env_returns_none_without_raising(self):
        with tempfile.TemporaryDirectory() as base, tempfile.TemporaryDirectory() as dest:
            with patch('core.backup_service.settings') as fake:
                fake.BASE_DIR = Path(base)
                self.assertIsNone(create_encrypted_config_backup(target_dir=dest))


class EncryptionKeyStatusTests(TestCase):
    """المفتاح نقطةُ الفشل الواحدة — ولا يُنسخ تلقائيّاً بجانب ما يفتحه."""

    def test_reports_fingerprint(self):
        with tempfile.TemporaryDirectory() as dest:
            status = encryption_key_status(dest)
            self.assertTrue(status['exists'])
            self.assertEqual(len(status['fingerprint']), 16)
            self.assertFalse(status['leaked_into_backup_dir'])

    def test_detects_key_left_inside_backup_dir(self):
        """مفتاحٌ بجانب المعمّى الذي يفتحه = لا تشفير أصلاً."""
        with tempfile.TemporaryDirectory() as dest:
            (Path(dest) / '.encryption_key').write_bytes(b'x')
            self.assertTrue(encryption_key_status(dest)['leaked_into_backup_dir'])


class PruneTests(TestCase):

    def test_prunes_both_archive_kinds_but_never_the_mirror(self):
        with tempfile.TemporaryDirectory() as dest:
            d = Path(dest)
            old = 40 * 86400
            for name in ('a.dump.enc', 'b.tar.enc'):
                f = d / name
                f.write_bytes(b'x')
                os.utime(f, (f.stat().st_atime - old, f.stat().st_mtime - old))

            mirror_file = d / 'media_mirror' / 'keep.pdf'
            mirror_file.parent.mkdir()
            mirror_file.write_bytes(b'x')
            os.utime(mirror_file, (mirror_file.stat().st_atime - old,
                                   mirror_file.stat().st_mtime - old))

            self.assertEqual(prune_old_backups(d, retention_days=30), 2)
            self.assertTrue(mirror_file.exists(), 'التشذيب حذف مرفقاً حيّاً من المرآة')

    def test_patterns_are_explicit(self):
        self.assertEqual(PRUNABLE_PATTERNS, ('*.dump.enc', '*.tar.enc'))
