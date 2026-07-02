# -*- coding: utf-8 -*-
"""
اختبارات توحيد صيغة المرفقات إلى PDF (دفعة 1).

تتحقق من:
- ensure_pdf_bytes: تمرير PDF كما هو، وتحويل الصور إلى PDF.
- create_attachment: كل مرفق جديد يُحفظ PDF؛ والأصل الصُّوري يُحفظ كنسخة v1.
- الدمج: المخرج PDF دائماً، ويعمل حتى لو لم يحمل المرفق نسخاً (إصلاح العطل القديم).
"""

from io import BytesIO

import fitz  # PyMuPDF
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from core.attachment_service import create_attachment, ensure_pdf_bytes, remove_blank_pages
from core.merge_service import SmartMergeService
from core.models import Attachment, AttachmentVersion, Book


def _png_bytes(color="white", size=(24, 24)):
    """PNG حقيقي صغير عبر PyMuPDF (بلا اعتماد على Pillow في الاختبار)."""
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, *size))
    pix.clear_with(255 if color == "white" else 0)
    return pix.tobytes("png")


def _pdf_bytes(pages=1):
    """PDF حقيقي صغير قابل للقراءة من PyPDF2/pypdf."""
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page()
    data = doc.tobytes()
    doc.close()
    return data


def _pdf_mixed_blank():
    """PDF بصفحتين: الأولى تحمل نصاً، الثانية فارغة تماماً."""
    doc = fitz.open()
    p0 = doc.new_page()
    # نص يملأ مساحة كافية ليتجاوز عتبة الفراغ
    for y in range(60, 760, 18):
        p0.insert_text((40, y), "نص اختبار للصفحة غير الفارغة ABC 12345", fontsize=11)
    doc.new_page()           # صفحة ثانية فارغة
    data = doc.tobytes()
    doc.close()
    return data


def _read(field_file):
    field_file.open("rb")
    try:
        return field_file.read()
    finally:
        field_file.close()


class EnsurePdfBytesTests(TestCase):
    def test_pdf_passes_through_unchanged(self):
        data = _pdf_bytes()
        out, converted, original = ensure_pdf_bytes(data, "x.pdf")
        self.assertFalse(converted)
        self.assertIsNone(original)
        self.assertEqual(out, data)

    def test_png_is_converted_to_pdf(self):
        png = _png_bytes()
        out, converted, original = ensure_pdf_bytes(png, "x.png")
        self.assertTrue(converted)
        self.assertEqual(original, png)
        self.assertTrue(out.startswith(b"%PDF-"))

    def test_pdf_sniffed_even_with_wrong_extension(self):
        # المحتوى PDF لكن الاسم .png ⇒ يُمرّر كـ PDF (نعتمد التوقيع لا الامتداد)
        data = _pdf_bytes()
        out, converted, _ = ensure_pdf_bytes(data, "mislabeled.png")
        self.assertFalse(converted)
        self.assertEqual(out, data)


class CreateAttachmentTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("u", password="p")
        self.book = Book.objects.create(
            our_number="2026100001",
            kind="incoming_internal",
            title="كتاب",
            date=timezone.now(),
            created_by=self.user,
        )

    def test_image_upload_is_stored_as_pdf(self):
        upload = SimpleUploadedFile("scan.png", _png_bytes(), content_type="image/png")
        att = create_attachment(self.book, upload, user=self.user)

        self.assertTrue(att.file.name.endswith(".pdf"))
        self.assertTrue(_read(att.file).startswith(b"%PDF-"))

    def test_image_original_kept_as_version_v1(self):
        png = _png_bytes()
        upload = SimpleUploadedFile("scan.png", png, content_type="image/png")
        att = create_attachment(self.book, upload, user=self.user)

        versions = att.versions.all()
        self.assertEqual(versions.count(), 1)
        v1 = versions.first()
        self.assertEqual(v1.version_number, 1)
        self.assertFalse(v1.is_merged)
        # النسخة تحمل الصورة الأصلية كما هي
        self.assertEqual(_read(v1.file), png)

    def test_pdf_upload_stays_pdf_without_extra_version(self):
        data = _pdf_bytes()
        upload = SimpleUploadedFile("doc.pdf", data, content_type="application/pdf")
        att = create_attachment(self.book, upload, user=self.user)

        self.assertTrue(att.file.name.endswith(".pdf"))
        self.assertTrue(_read(att.file).startswith(b"%PDF-"))
        # لا تحويل ⇒ لا نحتفظ بنسخة أصل
        self.assertEqual(att.versions.count(), 0)


class RemoveBlankPagesTests(TestCase):
    def test_blank_back_page_is_removed(self):
        out, removed = remove_blank_pages(_pdf_mixed_blank())
        self.assertEqual(removed, 1)
        doc = fitz.open(stream=out, filetype="pdf")
        self.assertEqual(doc.page_count, 1)
        doc.close()

    def test_single_page_untouched(self):
        data = _pdf_bytes(1)
        out, removed = remove_blank_pages(data)
        self.assertEqual(removed, 0)
        self.assertEqual(out, data)

    def test_never_removes_all_pages(self):
        # كل الصفحات فارغة ⇒ نُبقي واحدة على الأقل
        out, removed = remove_blank_pages(_pdf_bytes(3))
        doc = fitz.open(stream=out, filetype="pdf")
        self.assertGreaterEqual(doc.page_count, 1)
        doc.close()

    def test_page_number_only_back_is_kept(self):
        # تراجع #2: ظهر يحمل رقم صفحة فقط ليس فارغاً — يجب ألا يُحذف
        doc = fitz.open()
        p0 = doc.new_page(width=595, height=842)
        for y in range(120, 760, 22):
            p0.insert_text((60, y), "سطر محتوى حقيقي في الصفحة الأولى ABC 123", fontsize=11)
        p1 = doc.new_page(width=595, height=842)
        p1.insert_text((285, 800), "- 2 -", fontsize=11)     # رقم صفحة فقط
        data = doc.tobytes()
        doc.close()
        out, removed = remove_blank_pages(data)
        self.assertEqual(removed, 0)                          # لا حذف
        kept = fitz.open(stream=out, filetype="pdf")
        self.assertEqual(kept.page_count, 2)
        kept.close()

    def test_sparse_first_page_is_kept(self):
        # تراجع Bug 1: صفحة فيها سطر عنوان واحد فقط يجب ألا تُحذف كفارغة
        doc = fitz.open()
        p0 = doc.new_page(width=595, height=842)
        p0.insert_text((60, 90), "Memo No. 12 / 2026", fontsize=14)   # محتوى قليل
        doc.new_page(width=595, height=842)                            # فارغة فعلاً
        data = doc.tobytes()
        doc.close()
        out, removed = remove_blank_pages(data)   # العتبة الافتراضية المحافِظة
        self.assertEqual(removed, 1)               # تُحذف الفارغة فقط
        kept = fitz.open(stream=out, filetype="pdf")
        self.assertEqual(kept.page_count, 1)
        # الصفحة الباقية هي صفحة العنوان (فيها بكسلات داكنة)
        pix = kept[0].get_pixmap(dpi=36, colorspace=fitz.csGRAY, alpha=False)
        dark = sum(1 for b in pix.samples if b < 200)
        self.assertGreater(dark, 0)
        kept.close()


class MergeAlwaysPdfTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("u", password="p")
        self.book = Book.objects.create(
            our_number="2026100002",
            kind="incoming_internal",
            title="كتاب",
            date=timezone.now(),
            created_by=self.user,
        )

    def test_merge_image_into_pdf_attachment_outputs_pdf(self):
        # مرفق PDF بلا نسخ (يحاكي العطل القديم: versions.latest كان يرمي استثناءً)
        att = Attachment.objects.create(
            book=self.book,
            file=SimpleUploadedFile("base.pdf", _pdf_bytes(), content_type="application/pdf"),
        )
        self.assertEqual(att.versions.count(), 0)

        new_img = SimpleUploadedFile("page2.png", _png_bytes(), content_type="image/png")
        service = SmartMergeService(att, self.user)
        version = service.merge_files(new_img, merge_type="smart")

        self.assertEqual(version.merge_type, "pdf")
        self.assertTrue(version.file.name.endswith(".pdf"))
        self.assertTrue(_read(version.file).startswith(b"%PDF-"))

        # الناتج المدمج صفحتان (صفحة الأساس + الصورة الملفوفة)
        merged = fitz.open(stream=_read(version.file), filetype="pdf")
        self.assertEqual(merged.page_count, 2)
        merged.close()

    def test_merge_uses_live_file_not_stale_version(self):
        # تراجع #1: الأساس هو att.file الحيّ (صفحتان)، لا أحدث نسخة قديمة (صفحة)
        att = Attachment.objects.create(
            book=self.book,
            file=SimpleUploadedFile("live.pdf", _pdf_bytes(2), content_type="application/pdf"),
        )
        stale = AttachmentVersion(attachment=att, version_number=1, is_merged=False)
        stale.file.save("stale.pdf", ContentFile(_pdf_bytes(1)), save=True)   # نسخة قديمة صفحة واحدة

        service = SmartMergeService(att, self.user)
        version = service.merge_files(
            SimpleUploadedFile("new.pdf", _pdf_bytes(1), content_type="application/pdf"))
        merged = fitz.open(stream=_read(version.file), filetype="pdf")
        self.assertEqual(merged.page_count, 3)   # live(2)+new(1)=3 ؛ العطل القديم=stale(1)+new(1)=2
        merged.close()

    def test_restore_version_yields_pdf_not_raw_image(self):
        # تراجع #3: استعادة النسخة 1 (الأصل الصُّوري) يجب أن تُعيد PDF لا صورة خام
        att = create_attachment(
            self.book, SimpleUploadedFile("scan.png", _png_bytes(), content_type="image/png"),
            user=self.user)
        self.assertEqual(att.versions.count(), 1)             # v1 = الأصل الصُّوري
        SmartMergeService(att, self.user).restore_version(1)
        att.refresh_from_db()
        self.assertTrue(_read(att.file).startswith(b"%PDF-"))  # موحّد PDF، لا PNG خام
