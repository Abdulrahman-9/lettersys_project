# -*- coding: utf-8 -*-
"""
اختبارات حماية خدمة الوسائط (serve_media).

المرفقاتُ كتبٌ رسميّة. تتحقّق هذه الاختبارات من أنّ:
- الزائرَ غير المسجّل لا يحصل على الملفّ، بل يُحوَّل لتسجيل الدخول (302).
- المستخدمَ المسجّل الذي لا يملك الكتاب يُمنَع (403).
- المالكَ (والإداريّ) يحصل على الملفّ.
- في وضع الإنتاج (USE_X_ACCEL_REDIRECT) لا تُبَثّ البايتاتُ عبر Django، بل
  تصدر ترويسةُ X-Accel-Redirect إلى الموقع الداخليّ ويبقى جسمُ الردّ فارغاً
  (فلا تتسرّب بايتاتُ ملفٍّ من طبقة التطبيق).
"""

import tempfile
from pathlib import Path

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import Attachment, AttachmentVersion, Book

_MEDIA = tempfile.mkdtemp()
import atexit, shutil
atexit.register(shutil.rmtree, _MEDIA, True)
_PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\nfake-official-document-bytes\n%%EOF\n"


@override_settings(MEDIA_ROOT=_MEDIA)
class ServeMediaProtectionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("owner", password="pw-owner-123")
        cls.other = User.objects.create_user("other", password="pw-other-123")
        cls.staff = User.objects.create_user("staffer", password="pw-staff-123",
                                             is_staff=True)

    def setUp(self):
        with override_settings(MEDIA_ROOT=_MEDIA):
            self.book = Book.objects.create(
                our_number="2026100777",
                kind="incoming_internal",
                title="كتاب سرّي",
                date=timezone.now(),
                created_by=self.owner,
            )
            self.att = Attachment.objects.create(
                book=self.book,
                file=SimpleUploadedFile("secret.pdf", _PDF,
                                        content_type="application/pdf"),
            )
        self.url = "/media/" + self.att.file.name

    # ── منعُ غير المصرَّح لهم ────────────────────────────────────────────
    def test_anonymous_is_redirected_not_served(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp["Location"])
        # لم يُخدَم الملفّ
        self.assertNotIn("X-Accel-Redirect", resp)

    def test_logged_in_non_owner_forbidden(self):
        self.client.login(username="other", password="pw-other-123")
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 403)

    # ── سماحُ المالك والإداريّ ───────────────────────────────────────────
    def test_owner_receives_file_in_dev_streaming(self):
        self.client.login(username="owner", password="pw-owner-123")
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        body = b"".join(resp.streaming_content)      # FileResponse يبثّ
        self.assertEqual(body, _PDF)

    def test_staff_non_owner_is_scoped_out(self):
        """سياسةُ النطاقات (rollout, ``can_open_content``): ``is_staff`` وحدَه لا يفتح
        محتوى كتابٍ ليس في نطاقه — كان 200 قبل الدمج على السياسة القديمة."""
        self.client.login(username="staffer", password="pw-staff-123")
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 403)

    def test_superuser_non_owner_allowed(self):
        from django.contrib.auth.models import User
        User.objects.create_superuser("root_media", "r@x", "pw-root-123")
        self.client.login(username="root_media", password="pw-root-123")
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)

    # ── وضعُ الإنتاج: التفويضُ إلى nginx بلا بثٍّ من Django ──────────────
    @override_settings(USE_X_ACCEL_REDIRECT=True,
                       X_ACCEL_MEDIA_PREFIX="/protected_media/")
    def test_owner_gets_x_accel_redirect_no_body_leak(self):
        self.client.login(username="owner", password="pw-owner-123")
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["X-Accel-Redirect"],
                         "/protected_media/" + self.att.file.name)
        # لا بايتات ملفٍّ في جسم ردّ التطبيق — nginx يتولّى البثّ
        self.assertEqual(resp.content, b"")
        self.assertNotIn(b"%PDF", resp.content)

    @override_settings(USE_X_ACCEL_REDIRECT=True)
    def test_non_owner_still_forbidden_in_prod(self):
        self.client.login(username="other", password="pw-other-123")
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 403)
        self.assertNotIn("X-Accel-Redirect", resp)

    def assert_media_rejected(self, url):
        for accelerated in (False, True):
            with self.subTest(url=url, accelerated=accelerated):
                with override_settings(USE_X_ACCEL_REDIRECT=accelerated):
                    resp = self.client.get(url)
                    try:
                        self.assertIn(resp.status_code, (403, 404))
                        self.assertNotIn("X-Accel-Redirect", resp)
                        self.assertNotIn(_PDF, resp.content)
                    finally:
                        resp.close()

    def test_noncanonical_paths_never_bypass_ownership(self):
        self.client.force_login(self.other)
        parent, filename = self.att.file.name.rsplit("/", 1)
        paths = (
            parent + "/./" + filename,
            parent + "/unused/../" + filename,
            parent + "//" + filename,
            self.att.file.name.replace("/", "\\"),
            self.att.file.name.upper(),
            self.att.file.name.replace("books/", "books./", 1),
            self.att.file.name.replace("books/", "books /", 1),
            self.att.file.name + ".",
            self.att.file.name + " ",
            self.att.file.name + "::$DATA",
        )
        for path in paths:
            self.assert_media_rejected("/media/" + path)

    def test_deleted_attachment_is_not_generic_media_even_for_owner(self):
        Attachment.all_objects.filter(pk=self.att.pk).update(is_deleted=True)
        for user in (self.other, self.owner):
            self.client.force_login(user)
            self.assert_media_rejected(self.url)

    def make_version(self):
        return AttachmentVersion.objects.create(
            attachment=self.att,
            file=SimpleUploadedFile("previous.pdf", _PDF, content_type="application/pdf"),
            version_number=1,
            created_by=self.owner,
        )

    def test_version_retains_content_permissions(self):
        version = self.make_version()
        url = "/media/" + version.file.name
        self.client.force_login(self.other)
        self.assert_media_rejected(url)
        self.client.force_login(self.owner)
        resp = self.client.get(url)
        try:
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(b"".join(resp.streaming_content), _PDF)
        finally:
            resp.close()

    def test_deleted_attachment_versions_are_not_served(self):
        version = self.make_version()
        Attachment.all_objects.filter(pk=self.att.pk).update(is_deleted=True)
        for user in (self.other, self.owner):
            self.client.force_login(user)
            self.assert_media_rejected("/media/" + version.file.name)

    def test_unregistered_document_is_not_generic_media(self):
        self.client.force_login(self.other)
        path = Path(_MEDIA) / "books" / "orphan.pdf"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_PDF)
        self.addCleanup(path.unlink)
        self.assert_media_rejected("/media/books/orphan.pdf")

    def test_other_media_remains_available_to_authenticated_users(self):
        self.client.force_login(self.other)
        path = Path(_MEDIA) / "branding" / "logo.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic-branding")
        self.addCleanup(path.unlink)
        resp = self.client.get("/media/branding/logo.png")
        try:
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(b"".join(resp.streaming_content), b"synthetic-branding")
        finally:
            resp.close()
