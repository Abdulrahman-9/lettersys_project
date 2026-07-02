# -*- coding: utf-8 -*-
"""
خدمة المرفقات الموحّدة — نقطة الاختناق الوحيدة لإنشاء المرفقات.

الهدف: كل مستند جديد يُحفظ بصيغة **PDF** بصرف النظر عن مصدره
(رفع يدوي، مسح، دمج). الصور (JPG/PNG) تُلَفّ في PDF صفحة‑واحدة عبر
PyMuPDF (مثبّت أصلاً، يحفظ جودة الصورة بلا إعادة ترميز خشنة).

عند تحويل صورة إلى PDF نحتفظ بالأصل كـ AttachmentVersion v1 (قرار المالك:
الاحتفاظ بالأصل + PDF). ملفات PDF تمرّ كما هي بلا تحويل ولا نسخة زائدة.
"""

import logging
from pathlib import Path

import fitz  # PyMuPDF
from django.core.files.base import ContentFile

from .models import Attachment, AttachmentVersion

logger = logging.getLogger(__name__)

# الصيغ التي نعاملها كصور قابلة للّفّ في PDF. ما عداها (وما يبدأ بـ %PDF-)
# يُعامل كـ PDF ويمرّ كما هو.
_IMAGE_EXTS = {"jpg", "jpeg", "png", "gif", "bmp", "webp", "tif", "tiff"}


def _read_bytes(django_file):
    """قراءة كامل محتوى ملف Django مع إعادة المؤشّر للبداية بأمان."""
    try:
        django_file.seek(0)
    except (AttributeError, ValueError):
        pass
    data = django_file.read()
    try:
        django_file.seek(0)
    except (AttributeError, ValueError):
        pass
    return data


def is_pdf_bytes(data):
    """هل المحتوى ملف PDF فعلاً (توقيع %PDF- في أوله)؟"""
    return bool(data) and data[:5] == b"%PDF-"


_IMG_SUFFIXES = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff")


def pick_primary_attachment(qs):
    """قاعدة موحّدة لاختيار المرفق «الأساسي» للكتاب — مصدر حقيقة واحد يستخدمه
    العرض الكبير (صفحة التعديل) وشارة «أساسي» في لوحة الإدارة، فلا يتضاربان:
    أحدث PDF ← وإلا أحدث صورة ← وإلا أحدث مرفق."""
    atts = list(qs.order_by("-uploaded_at"))

    def _is_pdf(a):
        return bool(a.file) and a.file.name.lower().endswith(".pdf")

    def _is_img(a):
        return bool(a.file) and a.file.name.lower().endswith(_IMG_SUFFIXES)

    return (next((a for a in atts if _is_pdf(a)), None)
            or next((a for a in atts if _is_img(a)), None)
            or (atts[0] if atts else None))


# الحدّ الأقصى الموحّد لحجم الرفع (يطابق مسار المسح؛ يُتجاوز عبر إعداد ATTACHMENT_MAX_UPLOAD_BYTES)
_DEFAULT_MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def _sniff_document_kind(head):
    """كشف نوع المستند عبر توقيع البايتات (لا يعتمد على الامتداد ولا على python-magic غير المتوفّر)."""
    if head[:5] == b"%PDF-":
        return "pdf"
    if head[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if head[:2] == b"BM":
        return "bmp"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    return None


def validate_attachment_file(uploaded_file, *, max_bytes=None):
    """
    تحقّق موحّد من أي ملف مرفوع قبل الحفظ — نقطة الحقيقة الوحيدة للحجم والنوع.

    - الحجم ≤ ATTACHMENT_MAX_UPLOAD_BYTES (افتراضياً 50MB، يطابق مسار المسح).
    - النوع الفعلي عبر توقيع البايتات: PDF أو صورة مستند (JPEG/PNG/GIF/BMP/WEBP/TIFF)
      — وهي الأنواع التي يحوّلها ensure_pdf؛ يُرفض ما عداها (تنفيذيات/سكربتات…).

    يرفع django.core.exceptions.ValidationError (فئة فرعية يلتقطها clean_* في النماذج،
    وتُترجَم في عروض JSON إلى 400). لا يعتمد python-magic لأنه غير متوفّر في هذه البيئة.
    """
    from django.conf import settings
    from django.core.exceptions import ValidationError

    if not uploaded_file:
        return

    if max_bytes is None:
        max_bytes = getattr(settings, "ATTACHMENT_MAX_UPLOAD_BYTES", _DEFAULT_MAX_UPLOAD_BYTES)

    size = getattr(uploaded_file, "size", None)
    if size is not None and size > max_bytes:
        raise ValidationError(f"حجم الملف يتجاوز الحد الأقصى {max_bytes // (1024 * 1024)}MB.")

    try:
        uploaded_file.seek(0)
        head = uploaded_file.read(16)
        uploaded_file.seek(0)
    except Exception:
        raise ValidationError("تعذّر قراءة الملف للتحقّق منه.")

    if _sniff_document_kind(head) is None:
        raise ValidationError("نوع الملف غير مسموح. المسموح: PDF أو صورة (JPG/PNG/GIF/BMP/WEBP/TIFF).")


def ensure_pdf_bytes(data, name=""):
    """
    يضمن أن تكون البايتات PDF.

    يُعيد ثلاثية: (pdf_bytes, was_converted, original_bytes_or_None)
      - إن كان المحتوى PDF أصلاً: (نفس المحتوى، False، None).
      - إن كان صورة: (PDF ناتج، True، بايتات الأصل) — لنحفظ الأصل كنسخة.

    عند تعذّر التحويل يرفع ValueError ليتعامل المتصل معه (يحفظ الأصل احتياطاً).
    """
    if is_pdf_bytes(data):
        return data, False, None

    # صورة → PDF صفحة‑واحدة. نمرّر filetype من الامتداد لمساعدة PyMuPDF،
    # وإن غاب نتركه يكتشفه من المحتوى.
    ext = Path(name or "").suffix.lower().lstrip(".")
    open_kwargs = {"stream": data}
    if ext in _IMAGE_EXTS:
        open_kwargs["filetype"] = ext

    try:
        with fitz.open(**open_kwargs) as imgdoc:
            pdf_bytes = imgdoc.convert_to_pdf()
    except Exception as exc:  # noqa: BLE001 — نريد التقاط أي فشل في فك الصورة
        raise ValueError(f"تعذّر تحويل الصورة إلى PDF: {exc}") from exc

    if not is_pdf_bytes(pdf_bytes):
        raise ValueError("ناتج التحويل ليس PDF صالحاً.")

    return pdf_bytes, True, data


def ensure_pdf(django_file):
    """
    مثل ensure_pdf_bytes لكن يأخذ ملف Django (يقرأ محتواه ويستخدم اسمه).
    """
    data = _read_bytes(django_file)
    name = getattr(django_file, "name", "") or ""
    return ensure_pdf_bytes(data, name)


def _page_is_blank(page, max_dark_px, sample_dpi):
    """فارغة فعلاً؟ نعدّ **العدد المطلق** للبكسلات الداكنة (لا نسبتها من المساحة).

    نسبة المساحة خاطئة هنا: رقم صفحة أو ختم صغير يشغل جزءاً ضئيلاً جداً من A4
    فيقع تحت أي نسبة معقولة ويُحذف خطأً. العدّ المطلق عند دقّة كافية يميّز العلامة
    الصغيرة (~20 بكسل عند 72DPI) عن ضجيج الماسح (أقل من العتبة)، فلا تُفقد صفحة
    فيها أي محتوى حقيقي.
    """
    pix = page.get_pixmap(dpi=sample_dpi, colorspace=fitz.csGRAY, alpha=False)
    data = pix.samples
    if not data:
        return False
    dark = sum(1 for b in data if b < 190)     # نص/علامة = بكسلات داكنة
    return dark < max_dark_px


def remove_blank_pages(pdf_bytes, max_dark_px=10, sample_dpi=72):
    """يزيل الصفحات الفارغة فعلاً فقط من PDF (ظهور المسح المزدوج تلقائياً).

    يُعيد (out_bytes, removed_count). لا يُنقص العدد دون صفحة واحدة، ولا يلمس
    ملفات الصفحة الواحدة.

    محافِظ جداً عمداً (نظام مستندات رسمية): تُحذف فقط الصفحات شبه الخالية تماماً
    (داكن < ~10 بكسل عند 72DPI)؛ أي صفحة فيها محتوى حقيقي — حتى رقم صفحة أو ختم
    صغير (~20+ بكسل) — تُبقى. إبقاء صفحة فارغة أرحم من حذف صفحة فيها محتوى.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        total = doc.page_count
        if total <= 1:
            return pdf_bytes, 0
        keep = [i for i in range(total) if not _page_is_blank(doc[i], max_dark_px, sample_dpi)]
        if not keep:                  # لا نحذف كل شيء — أبقِ الأولى على الأقل
            keep = [0]
        if len(keep) == total:
            return pdf_bytes, 0
        doc.select(keep)
        return doc.tobytes(garbage=3, deflate=True), total - len(keep)
    finally:
        doc.close()


def _pdf_name(original_name):
    """اسم PDF مشتقّ من الاسم الأصلي (يستبدل الامتداد بـ .pdf)."""
    stem = Path(original_name or "document").stem or "document"
    return f"{stem}.pdf"


def create_attachment(book, uploaded_file, user=None, note=""):
    """
    نقطة الإنشاء الموحّدة لكل المرفقات.

    - يحوّل الصور إلى PDF، ويمرّر PDF كما هو.
    - عند التحويل يحفظ الأصل (الصورة) كـ AttachmentVersion v1.
    - عند فشل التحويل يحفظ الأصل كما هو (لا نفقد المستند) ويسجّل تحذيراً.

    يُعيد كائن Attachment المُنشأ.
    """
    # نقطة الاختناق: تحقّق موحّد من الحجم والنوع قبل أي معالجة أو حفظ (#12).
    # يرفع ValidationError (ليست ValueError) فلا يلتقطها fallback ensure_pdf أدناه.
    validate_attachment_file(uploaded_file)

    original_name = getattr(uploaded_file, "name", "") or "document"

    try:
        pdf_bytes, was_converted, original_bytes = ensure_pdf(uploaded_file)
    except ValueError as exc:
        # شبكة أمان: لا نفقد المستند إن فشل التحويل — نحفظ الأصل كما هو.
        logger.warning(
            "ensure_pdf failed for %r (book=%s); saving original as-is: %s",
            original_name, getattr(book, "pk", None), exc,
        )
        att = Attachment(book=book)
        att.file.save(original_name, uploaded_file, save=True)
        return att

    att = Attachment(book=book)
    att.file.save(_pdf_name(original_name), ContentFile(pdf_bytes), save=True)

    # الاحتفاظ بالأصل الصُّوري كنسخة سابقة (v1) عند حدوث تحويل فعلي.
    if was_converted and original_bytes is not None:
        try:
            version = AttachmentVersion(
                attachment=att,
                version_number=1,
                created_by=user,
                note=note or "الأصل (صورة) قبل التحويل إلى PDF",
                merge_type="none",
                is_merged=False,
                file_size=len(original_bytes),
            )
            version.file.save(original_name, ContentFile(original_bytes), save=True)
        except Exception as exc:  # noqa: BLE001 — حفظ الأصل مساعد لا حرج
            logger.warning(
                "Could not keep original image as version for attachment %s: %s",
                att.pk, exc,
            )

    return att
