import io
import stat
import tarfile
import tempfile
import types
import zipfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from core.legacy_restore import LegacyRestoreEngine
from core.restore_archive import UnsafeRestoreArchive, extract_backup_archive


class RestoreArchiveTests(SimpleTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.destination = self.root / "extracted"
        self.destination.mkdir()

    def make_archive(self, kind, names):
        path = self.root / ("backup.zip" if kind == "zip" else "backup.tar.gz")
        if kind == "zip":
            with zipfile.ZipFile(path, "w") as archive:
                for name in names:
                    archive.writestr(name, b"synthetic-backup")
        else:
            with tarfile.open(path, "w:gz") as archive:
                for name in names:
                    member = tarfile.TarInfo(name)
                    member.size = len(b"synthetic-backup")
                    archive.addfile(member, io.BytesIO(b"synthetic-backup"))
        return path

    def test_valid_nested_backup_in_both_formats(self):
        for kind in ("zip", "tar"):
            with self.subTest(kind=kind):
                destination = self.root / kind
                destination.mkdir()
                source = self.make_archive(kind, ["folder/backup.BAK"])
                backup = extract_backup_archive(source, destination)
                self.assertEqual(Path(backup).read_bytes(), b"synthetic-backup")
                self.assertTrue(Path(backup).is_relative_to(destination))

    def test_rejects_unsafe_names_before_writing_any_member(self):
        names = (
            "../outside.bak", "/outside.bak", "C:/outside.bak",
            r"folder\..\outside.bak", "folder/../outside.bak",
            "folder./backup.bak", "folder /backup.bak",
            "backup.bak::$DATA", "NUL.bak", "COM1/backup.bak",
        )
        for kind in ("zip", "tar"):
            for name in names:
                with self.subTest(kind=kind, name=name):
                    source = self.make_archive(kind, ["good.bak", name])
                    with self.assertRaises(UnsafeRestoreArchive):
                        extract_backup_archive(source, self.destination)
                    self.assertEqual(list(self.destination.iterdir()), [])
                    self.assertFalse((self.root / "outside.bak").exists())

    def test_rejects_tar_links_and_special_files(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE):
            with self.subTest(kind=kind):
                source = self.root / "link.tar.gz"
                with tarfile.open(source, "w:gz") as archive:
                    member = tarfile.TarInfo("link.bak")
                    member.type = kind
                    member.linkname = "../outside.bak"
                    archive.addfile(member)
                with self.assertRaises(UnsafeRestoreArchive):
                    extract_backup_archive(source, self.destination)
                self.assertEqual(list(self.destination.iterdir()), [])

    def test_rejects_zip_symlink(self):
        source = self.root / "link.zip"
        with zipfile.ZipFile(source, "w") as archive:
            member = zipfile.ZipInfo("link.bak")
            member.create_system = 3
            member.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(member, "../outside.bak")
        with self.assertRaises(UnsafeRestoreArchive):
            extract_backup_archive(source, self.destination)
        self.assertEqual(list(self.destination.iterdir()), [])

    def test_duplicate_case_alias_is_rejected_before_writing(self):
        for kind in ("zip", "tar"):
            with self.subTest(kind=kind):
                source = self.make_archive(kind, ["backup.bak", "BACKUP.BAK"])
                with self.assertRaises(UnsafeRestoreArchive):
                    extract_backup_archive(source, self.destination)
                self.assertEqual(list(self.destination.iterdir()), [])

    def test_limits_are_enforced_before_writing(self):
        for kind in ("zip", "tar"):
            source = self.make_archive(kind, ["backup.bak", "another.bak"])
            for limits in ({"max_bytes": 5}, {"max_members": 1}):
                with self.subTest(kind=kind, limits=limits):
                    with self.assertRaises(UnsafeRestoreArchive):
                        extract_backup_archive(source, self.destination, **limits)
                    self.assertEqual(list(self.destination.iterdir()), [])

    def test_missing_backup_is_reported(self):
        source = self.make_archive("zip", ["readme.txt"])
        with self.assertRaisesRegex(UnsafeRestoreArchive, "no .bak"):
            extract_backup_archive(source, self.destination)

    def test_refuses_nonempty_destination(self):
        source = self.make_archive("zip", ["backup.bak"])
        (self.destination / "existing").write_bytes(b"keep")
        with self.assertRaisesRegex(UnsafeRestoreArchive, "fresh"):
            extract_backup_archive(source, self.destination)
        self.assertEqual((self.destination / "existing").read_bytes(), b"keep")

    def test_restore_refuses_unsafe_archive_and_cleans_up_without_sql(self):
        source = self.make_archive("tar", ["../outside.bak"])
        driver = types.SimpleNamespace(connect=mock.Mock())
        with mock.patch.dict("sys.modules", {"pyodbc": driver}):
            with self.assertLogs("core.legacy_restore", level="WARNING"):
                result = LegacyRestoreEngine.restore_from_bak(str(source))
        self.assertTrue(result["aborted"])
        driver.connect.assert_not_called()
        self.assertEqual(list(self.root.glob("_legacy_restore_tmp_*")), [])
        self.assertFalse((self.root / "outside.bak").exists())

    def test_seven_zip_refused_without_loading_driver(self):
        source = self.root / "backup.7z"
        source.write_bytes(b"synthetic-7z")
        with mock.patch.dict("sys.modules", {"pyodbc": None}):
            result = LegacyRestoreEngine.restore_from_bak(str(source))
        self.assertTrue(result["aborted"])
        self.assertIn("7z", result["reason"])
