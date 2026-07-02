# -*- coding: utf-8 -*-
"""
اختبارات تعديل PDF المسح المؤقت قبل الحفظ (دفعة 2أ): تدوير/حذف/إعادة ترتيب.
"""

import json
import os
import tempfile
import uuid

import fitz  # PyMuPDF
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from core.tests_attachment_pdf import _png_bytes, _pdf_mixed_blank


def _make_pdf(pages=3):
    """ينشئ PDF حقيقياً على القرص ويعيد مساره."""
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page()
    fd, path = tempfile.mkstemp(suffix=".pdf", prefix="scan_test_")
    os.close(fd)
    doc.save(path)
    doc.close()
    return path


class ScanEditPageTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user("u", password="p")
        self.client.login(username="u", password="p")
        self._paths = []

    def tearDown(self):
        for p in self._paths:
            try:
                os.unlink(p)
            except OSError:
                pass

    def _token_for(self, pages=3):
        path = _make_pdf(pages)
        self._paths.append(path)
        token = uuid.uuid4().hex
        cache.set(f"scan_token:{token}", {"processed_path": path, "page_count": pages}, timeout=300)
        return token, path

    def _post(self, token, payload):
        return self.client.post(
            reverse("scan_edit_page", args=[token]),
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_rotate_single_page(self):
        token, path = self._token_for(3)
        resp = self._post(token, {"op": "rotate", "page": 1, "angle": 90})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["page_count"], 3)

        doc = fitz.open(path)
        self.assertEqual(doc[0].rotation, 90)
        self.assertEqual(doc[1].rotation, 0)
        doc.close()

    def test_rotate_all_pages(self):
        token, path = self._token_for(2)
        resp = self._post(token, {"op": "rotate", "page": "all", "angle": 180})
        self.assertEqual(resp.status_code, 200)
        doc = fitz.open(path)
        self.assertEqual(doc[0].rotation, 180)
        self.assertEqual(doc[1].rotation, 180)
        doc.close()

    def test_delete_page(self):
        token, path = self._token_for(3)
        resp = self._post(token, {"op": "delete", "page": 2})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["page_count"], 2)
        doc = fitz.open(path)
        self.assertEqual(doc.page_count, 2)
        doc.close()
        # الكاش يعكس العدد الجديد
        self.assertEqual(cache.get(f"scan_token:{token}")["page_count"], 2)

    def test_cannot_delete_only_page(self):
        token, _ = self._token_for(1)
        resp = self._post(token, {"op": "delete", "page": 1})
        self.assertEqual(resp.status_code, 400)

    def test_reorder_pages(self):
        token, path = self._token_for(3)
        resp = self._post(token, {"op": "reorder", "order": [3, 1, 2]})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["page_count"], 3)

    def test_reorder_must_cover_all_pages(self):
        token, _ = self._token_for(3)
        resp = self._post(token, {"op": "reorder", "order": [1, 2]})  # ناقص ⇒ مرفوض
        self.assertEqual(resp.status_code, 400)

    def test_insert_appends_source_at_end(self):
        """op=insert يُلحق صفحات المصدر بنهاية الملف ويعيد مدى الصفحات الجديدة (للتمييز البصري)."""
        token, path = self._token_for(3)
        src_token, _ = self._token_for(2)
        resp = self._post(token, {"op": "insert", "source_token": src_token})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["page_count"], 5)
        self.assertEqual(body["inserted_from"], 4)   # 1-based: أول صفحة مُلحقة
        self.assertEqual(body["inserted_count"], 2)
        doc = fitz.open(path)
        self.assertEqual(doc.page_count, 5)
        doc.close()
        self.assertEqual(cache.get(f"scan_token:{token}")["page_count"], 5)

    def test_insert_at_position(self):
        token, _ = self._token_for(3)
        src_token, _ = self._token_for(1)
        resp = self._post(token, {"op": "insert", "source_token": src_token, "at": 0})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["page_count"], 4)
        self.assertEqual(body["inserted_from"], 1)   # أُدرج في البداية
        self.assertEqual(body["inserted_count"], 1)

    def test_insert_missing_source_returns_404(self):
        token, _ = self._token_for(2)
        resp = self._post(token, {"op": "insert", "source_token": "deadbeef" * 4})
        self.assertEqual(resp.status_code, 404)

    def test_insert_from_process_uploaded_source(self):
        """المسار الواقعي الذي تسلكه الواجهة (رفع/مسح وإلحاق): مصدرٌ يُهيَّأ عبر
        process-upload ثمّ يُلحق بالهدف المُرحَّل عبر op=insert."""
        token, path = self._token_for(3)
        up = self.client.post(
            reverse("scan_process_upload"),
            data={"file": SimpleUploadedFile("annex.pdf", _make_pdf2(2), content_type="application/pdf")},
        )
        self.assertEqual(up.status_code, 200)
        src_token = up.json()["token"]
        resp = self._post(token, {"op": "insert", "source_token": src_token})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["page_count"], 5)         # 3 قديمة + 2 مُلحقة
        self.assertEqual(body["inserted_from"], 4)      # أول صفحة جديدة
        self.assertEqual(body["inserted_count"], 2)
        doc = fitz.open(path)
        self.assertEqual(doc.page_count, 5)
        doc.close()

    def test_page_out_of_range(self):
        token, _ = self._token_for(2)
        resp = self._post(token, {"op": "rotate", "page": 9, "angle": 90})
        self.assertEqual(resp.status_code, 400)

    def test_bad_angle(self):
        token, _ = self._token_for(2)
        resp = self._post(token, {"op": "rotate", "page": 1, "angle": 45})
        self.assertEqual(resp.status_code, 400)

    def test_unknown_op(self):
        token, _ = self._token_for(2)
        resp = self._post(token, {"op": "frobnicate"})
        self.assertEqual(resp.status_code, 400)

    def test_expired_token(self):
        resp = self._post("deadbeef" * 4, {"op": "delete", "page": 1})
        self.assertEqual(resp.status_code, 404)

    def test_requires_login(self):
        token, _ = self._token_for(2)
        self.client.logout()
        resp = self._post(token, {"op": "rotate", "page": 1, "angle": 90})
        self.assertIn(resp.status_code, (302, 403))


class ProcessUploadPipelineTests(TestCase):
    """رفع موحّد: صورة→PDF، وإزالة الصفحات الفارغة في مسار المسح."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user("u", password="p")
        self.client.login(username="u", password="p")

    def _upload(self, name, content, ctype, **extra):
        return self.client.post(
            reverse("scan_process_upload"),
            data={"file": SimpleUploadedFile(name, content, content_type=ctype), **extra},
        )

    def test_image_upload_is_staged_as_pdf(self):
        resp = self._upload("photo.png", _png_bytes(), "image/png")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["ok"])
        token = body["token"]
        # الملف المُخدَّم PDF
        serve = self.client.get(reverse("scan_file_serve", args=[token]))
        self.assertEqual(serve.status_code, 200)
        self.assertTrue(b"".join(serve.streaming_content).startswith(b"%PDF-"))

    def test_scan_path_trims_blank_back_page(self):
        resp = self._upload("scan.pdf", _pdf_mixed_blank(), "application/pdf", trim_blanks="1")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["trimmed_pages"], 1)
        self.assertEqual(body["page_count"], 1)

    def test_plain_pdf_upload_not_trimmed_without_flag(self):
        resp = self._upload("scan.pdf", _pdf_mixed_blank(), "application/pdf")  # بلا trim_blanks
        body = resp.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["trimmed_pages"], 0)
        self.assertEqual(body["page_count"], 2)

    def test_scan_token_bound_to_creator(self):
        # تراجع #12: رمز المسح مربوط بمنشئه — مستخدم آخر لا يصل للمعاينة
        token = self._upload("scan.pdf", _pdf_mixed_blank(), "application/pdf").json()["token"]
        prev_url = reverse("scan_preview_page", args=[token]) + "?page=1&dpi=72"

        intruder = Client()
        User.objects.create_user("intruder", password="p")
        intruder.login(username="intruder", password="p")
        self.assertEqual(intruder.get(prev_url).status_code, 404)        # ليس صاحبه

        self.assertEqual(self.client.get(prev_url).status_code, 200)     # المنشئ يصل


class StageAttachmentTests(TestCase):
    """وضع التعديل: تجهيز مرفق محفوظ للمعاينة (Bug 2)."""

    def setUp(self):
        from django.utils import timezone
        from core.attachment_service import create_attachment
        from core.models import Book
        self.client = Client()
        self.user = User.objects.create_user("u", password="p")
        self.client.login(username="u", password="p")
        self.book = Book.objects.create(
            our_number="2026100009", kind="incoming_internal", title="ك",
            date=timezone.now(), created_by=self.user,
        )
        # مرفق محفوظ (PDF موحّد) عبر نقطة الإنشاء
        pdf = SimpleUploadedFile("doc.pdf", _make_pdf2(2), content_type="application/pdf")
        self.att = create_attachment(self.book, pdf, user=self.user)

    def test_stage_saved_attachment_returns_token_and_serves(self):
        r = self.client.get(reverse("scan_stage_attachment", args=[self.att.id]))
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["page_count"], 2)
        token = body["token"]
        # المعاينة تعمل على المرفق المُهيّأ
        prev = self.client.get(reverse("scan_preview_page", args=[token]) + "?page=1&dpi=80")
        self.assertEqual(prev.status_code, 200)
        self.assertEqual(prev["Content-Type"], "image/png")

    def test_stage_requires_ownership(self):
        other = User.objects.create_user("other", password="p")
        c2 = Client(); c2.login(username="other", password="p")
        r = c2.get(reverse("scan_stage_attachment", args=[self.att.id]))
        self.assertEqual(r.status_code, 403)


def _make_pdf2(pages):
    import fitz
    d = fitz.open()
    for _ in range(pages):
        d.new_page()
    data = d.tobytes()
    d.close()
    return data
