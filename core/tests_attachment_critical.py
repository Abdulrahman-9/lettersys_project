"""Only critical attachment integrity, rollback and PostgreSQL race regressions."""

import time
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from threading import Event
from unittest import mock, skipUnless

from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, close_old_connections, connection, connections, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from pypdf import PdfReader, PdfWriter

from core.merge_service import SmartMergeService
from core.models import Attachment, AttachmentVersion, Book, BookHistory, BookSignature, MergeLog
from core.signature_service import sign_attachment


def pdf(pages=1):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    output = BytesIO()
    writer.write(output)
    writer.close()
    return output.getvalue()


def upload(name="new.pdf", pages=1):
    return SimpleUploadedFile(name, pdf(pages), content_type="application/pdf")


def read_file(field):
    with field.open("rb") as handle:
        return handle.read()


class AttachmentFixture:
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_superuser("critical-owner", "critical@example.test", "pw")
        self.book = Book.objects.create(
            kind="incoming_internal", our_number="91001",
            title="Critical attachment", created_by=self.user,
        )
        self.attachment = Attachment.objects.create(book=self.book, file=upload("original.pdf"))

    def media_files(self):
        return {path for path in Path(settings.MEDIA_ROOT).rglob("*") if path.is_file()}


class AttachmentIntegrityTests(AttachmentFixture, TestCase):
    def test_database_rejects_duplicate_version_numbers(self):
        AttachmentVersion.objects.create(
            attachment=self.attachment, version_number=1, file=self.attachment.file.name)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AttachmentVersion.objects.create(
                    attachment=self.attachment, version_number=1, file=self.attachment.file.name)

    def test_snapshot_failure_prevents_all_destructive_view_operations(self):
        client = Client()
        client.force_login(self.user)
        original = read_file(self.attachment.file)
        operations = (
            ("attachment_delete", {}),
            ("attachment_replace", {"file": upload()}),
            ("attachment_merge_pages", {"merge_files": [upload()]}),
            ("attachment_remove_pages", {"pages_to_remove": "1"}),
        )
        for name, data in operations:
            with self.subTest(operation=name), mock.patch(
                "django.db.models.fields.files.FieldFile.save",
                side_effect=OSError("snapshot storage unavailable"),
            ):
                response = client.post(
                    reverse(name, args=[self.attachment.pk]), data,
                    HTTP_X_REQUESTED_WITH="XMLHttpRequest",
                )
                self.assertEqual(response.status_code, 500)
                self.assertFalse(response.json()["success"])
                self.attachment.refresh_from_db()
                self.assertFalse(self.attachment.is_deleted)
                self.assertEqual(read_file(self.attachment.file), original)
                self.assertEqual(self.attachment.versions.count(), 0)
                self.assertFalse(BookHistory.objects.filter(book=self.book).exists())

    def test_merge_database_failure_rolls_back_file_and_versions(self):
        before = self.media_files()
        original = read_file(self.attachment.file)
        with mock.patch.object(Attachment, "save", side_effect=IntegrityError("injected")):
            with self.assertRaises(IntegrityError):
                SmartMergeService(self.attachment, self.user).merge_files(upload())
        self.attachment.refresh_from_db()
        self.assertEqual(read_file(self.attachment.file), original)
        self.assertEqual(self.attachment.versions.count(), 0)
        self.assertFalse(MergeLog.objects.filter(status="success", attachment=self.attachment).exists())
        self.assertEqual(self.media_files(), before)

    def test_sign_history_failure_leaves_no_version_signature_or_file(self):
        before = self.media_files()
        with mock.patch("core.signature_service._record", side_effect=IntegrityError("injected")):
            with self.assertRaises(IntegrityError):
                sign_attachment(self.attachment, by=self.user)
        self.assertEqual(self.attachment.versions.count(), 0)
        self.assertFalse(BookSignature.objects.filter(book=self.book).exists())
        self.assertEqual(self.media_files(), before)

    def test_invalid_merge_input_cannot_report_partial_success(self):
        client = Client()
        client.force_login(self.user)
        original = read_file(self.attachment.file)
        response = client.post(
            reverse("attachment_merge_pages", args=[self.attachment.pk]),
            {"merge_files": [upload(), SimpleUploadedFile("broken.pdf", b"%PDF-invalid")]},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 500)
        self.assertFalse(response.json()["success"])
        self.attachment.refresh_from_db()
        self.assertEqual(read_file(self.attachment.file), original)
        self.assertEqual(self.attachment.versions.count(), 0)

    def test_stale_attachment_cannot_be_signed_or_merged_after_delete(self):
        Attachment.all_objects.filter(pk=self.attachment.pk).update(is_deleted=True)
        with self.assertRaises(ValidationError):
            SmartMergeService(self.attachment, self.user).merge_files(upload())
        with self.assertRaises(ValidationError):
            sign_attachment(self.attachment, by=self.user)
        self.assertEqual(self.attachment.versions.count(), 0)

    def test_failed_restore_keeps_deletion_state_and_cleans_new_file(self):
        version = AttachmentVersion.objects.create(
            attachment=self.attachment, version_number=1, file=self.attachment.file.name)
        Attachment.all_objects.filter(pk=self.attachment.pk).update(is_deleted=True)
        before = self.media_files()
        with mock.patch.object(Attachment, "save", side_effect=IntegrityError("injected")):
            with self.assertRaises(IntegrityError):
                SmartMergeService(self.attachment, self.user).restore_version(version.version_number)
        self.attachment.refresh_from_db()
        self.assertTrue(self.attachment.is_deleted)
        self.assertEqual(self.media_files(), before)


@skipUnless(connection.vendor == "postgresql", "Requires the deployed database backend")
class AttachmentMigrationSafetyTests(AttachmentFixture, TransactionTestCase):
    def test_duplicate_guard_refuses_upgrade_without_removing_rows(self):
        previous = [("core", "0083_alter_bookhistory_action_alter_bookreferral_status")]
        latest = [("core", "0084_attachment_version_unique")]
        MigrationExecutor(connection).migrate(previous)
        first = AttachmentVersion.objects.create(
            attachment=self.attachment, version_number=1, file=self.attachment.file.name)
        second = AttachmentVersion.objects.create(
            attachment=self.attachment, version_number=1, file=self.attachment.file.name)
        before = self.media_files()
        try:
            with self.assertRaisesMessage(RuntimeError, "no files or rows were removed"):
                MigrationExecutor(connection).migrate(latest)
            self.assertEqual(self.attachment.versions.count(), 2)
            self.assertEqual(self.media_files(), before)
        finally:
            # Only the duplicate created by this isolated test is removed.
            second.delete()
            MigrationExecutor(connection).migrate(latest)
        self.assertTrue(AttachmentVersion.objects.filter(pk=first.pk).exists())


@skipUnless(connection.vendor == "postgresql", "Real row locking requires PostgreSQL")
class AttachmentConcurrencyTests(AttachmentFixture, TransactionTestCase):
    def assert_serialized(self, second_operation):
        entered, release, second_connected = Event(), Event(), Event()
        backend = {}
        merge_pdfs = SmartMergeService.merge_pdfs

        def held_merge(service, source, target):
            entered.set()
            if not release.wait(10):
                raise TimeoutError("Critical race test did not release first writer")
            return merge_pdfs(service, source, target)

        def first():
            close_old_connections()
            try:
                att = Attachment.objects.get(pk=self.attachment.pk)
                user = User.objects.get(pk=self.user.pk)
                return SmartMergeService(att, user).merge_files(upload()).version_number
            finally:
                connections.close_all()

        def second():
            close_old_connections()
            try:
                att = Attachment.objects.get(pk=self.attachment.pk)
                user = User.objects.get(pk=self.user.pk)
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    backend["pid"] = cursor.fetchone()[0]
                second_connected.set()
                if second_operation == "merge":
                    return SmartMergeService(att, user).merge_files(upload()).version_number
                if second_operation == "sign":
                    return sign_attachment(att, by=user).version.version_number
                client = Client()
                client.force_login(user)
                response = client.post(
                    reverse("attachment_replace", args=[att.pk]), {"file": upload("replacement.pdf")},
                    HTTP_X_REQUESTED_WITH="XMLHttpRequest",
                )
                if response.status_code != 200:
                    raise AssertionError(response.content)
                return att.versions.get(note="Replaced with new file").version_number
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            with mock.patch.object(SmartMergeService, "merge_pdfs", held_merge):
                first_result = pool.submit(first)
                second_result = None
                try:
                    self.assertTrue(entered.wait(5), "First writer never reached merge")
                    second_result = pool.submit(second)
                    self.assertTrue(second_connected.wait(5))
                    blocked = False
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        with connection.cursor() as cursor:
                            cursor.execute(
                                "SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s",
                                [backend["pid"]],
                            )
                            row = cursor.fetchone()
                        if row and row[0] == "Lock":
                            blocked = True
                            break
                        if second_result.done():
                            break
                        time.sleep(0.02)
                    self.assertTrue(blocked, "Second writer bypassed the attachment row lock")
                finally:
                    release.set()
                self.assertEqual(first_result.result(timeout=10), 1)
                self.assertEqual(second_result.result(timeout=10), 2)
        self.assertEqual(list(self.attachment.versions.order_by("version_number")
                              .values_list("version_number", flat=True)), [1, 2])
        self.attachment.refresh_from_db()
        if second_operation == "merge":
            self.assertEqual(len(PdfReader(BytesIO(read_file(self.attachment.file))).pages), 3)
        elif second_operation == "sign":
            signature = BookSignature.objects.get(book=self.book)
            self.assertEqual(len(PdfReader(BytesIO(read_file(signature.version.file))).pages), 2)
        else:
            previous = self.attachment.versions.get(version_number=2)
            self.assertEqual(len(PdfReader(BytesIO(read_file(previous.file))).pages), 2)

    def test_concurrent_merges_keep_both_added_pages(self):
        self.assert_serialized("merge")

    def test_signing_waits_and_signs_the_committed_merge(self):
        self.assert_serialized("sign")

    def test_replacement_snapshots_the_committed_merge(self):
        self.assert_serialized("replace")
