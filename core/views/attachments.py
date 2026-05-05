# -*- coding: utf-8 -*-
"""
Attachments Views - معالجات المرفقات
إدارة ملفات المرفقات: حذف، استبدال، دمج صفحات، حذف صفحات
"""

import logging
import mimetypes
from io import BytesIO
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files import File
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from pypdf import PdfReader, PdfWriter

from ..models import Attachment, AttachmentVersion, BookHistory

logger = logging.getLogger(__name__)


def _save_attachment_version(attachment, user, note="", merge_type="none", page_count=None):
    """
    حفظ نسخة من الملف قبل عمليات التعديل (حذف صفحات، دمج، إلخ)
    
    Args:
        attachment: كائن الملف المرفق
        user: المستخدم الذي قام بالعملية
        note: ملاحظة حول التعديل
        merge_type: نوع الدمج (pdf, image, none)
        page_count: عدد الصفحات بعد التعديل
    
    Returns:
        AttachmentVersion: النسخة المحفوظة أو None عند الفشل
    """
    try:
        last_version = attachment.versions.order_by("-version_number").first()
        next_version = (last_version.version_number + 1) if last_version else 1
        base = Path(attachment.file.name).stem
        ext = Path(attachment.file.name).suffix
        version_name = f"{base}_v{next_version}{ext}"

        with attachment.file.open("rb") as fh:
            version = AttachmentVersion(
                attachment=attachment,
                version_number=next_version,
                created_by=user,
                note=note,
                merge_type=merge_type,
                merged_from_version=last_version,
                file_size=attachment.file.size or 0,
                page_count=page_count,
                is_merged=merge_type != "none",
            )
            version.file.save(version_name, File(fh), save=True)
        return version
    except Exception as exc:
        logger.warning("Could not save attachment version: %s", exc, exc_info=True)
        return None


@login_required
def attachment_delete(request, pk):
    """
    نقل مرفق إلى سلة المهملات (حذف ناعم)
    
    Args:
        request: HTTP request (POST)
        pk: معرف المرفق
    
    Returns:
        Redirect to book detail page
    """
    att = get_object_or_404(Attachment, id=pk, is_deleted=False)
    book = att.book
    
    # فحص الصلاحيات: صاحب المستند أو الموظف
    if not (request.user.is_superuser or request.user.is_staff or book.created_by == request.user):
        messages.error(request, "غير مصرح بحذف هذا المرفق.")
        return redirect("book_detail", pk=book.pk)
    
    if request.method == "POST":
        # حفظ نسخة قبل الحذف
        _save_attachment_version(att, request.user, note="Deleted from book_detail")
        
        # حذف ناعم
        att.is_deleted = True
        att.deleted_at = timezone.now()
        att.deleted_by = request.user
        att.save(update_fields=["is_deleted", "deleted_at", "deleted_by"])
        
        # تسجيل العملية
        BookHistory.objects.create(
            book=att.book,
            action='delete-attachment',
            by=request.user,
            attachment=att,
            notes=f"Deleted attachment: {att.file.name}"
        )
        
        messages.success(request, "تم نقل المرفق إلى سلة المهملات.")
    
    # الرجوع إلى تفاصيل الكتاب
    return redirect("book_detail", pk=book.pk)


@login_required
def attachment_replace(request, pk):
    """
    استبدال ملف مرفق بملف جديد
    
    Args:
        request: HTTP POST request مع ملف جديد
        pk: معرف المرفق
    
    Returns:
        Redirect to book detail page
    """
    att = get_object_or_404(Attachment, id=pk, is_deleted=False)
    book = att.book
    
    # فحص الصلاحيات
    if not (request.user.is_superuser or request.user.is_staff or book.created_by == request.user):
        messages.error(request, "غير مصرح باستبدال هذا المرفق.")
        return redirect("book_detail", pk=book.pk)
    
    if request.method == "POST" and request.FILES.get("file"):
        # حفظ نسخة من الملف القديم
        _save_attachment_version(att, request.user, note="Replaced with new file")
        
        # الحصول على الملف الجديد
        new_file = request.FILES["file"]
        
        # تحديث المرفق بالملف الجديد
        att.file.save(new_file.name, new_file, save=True)
        att.file_size = att.file.size or 0
        att.file_type = mimetypes.guess_type(new_file.name)[0] or "application/octet-stream"
        att.save()
        
        # تسجيل العملية
        BookHistory.objects.create(
            book=book,
            action="replace-attachment",
            by=request.user,
            attachment=att,
            notes=f"Replaced attachment: {new_file.name}"
        )
        
        messages.success(request, "تم استبدال المرفق بنجاح.")
    
    return redirect("book_detail", pk=book.pk)


@login_required
def attachment_merge_pages(request, pk):
    """
    دمج ملفات PDF متعددة في مرفق واحد
    
    المميزات:
    - فحص أن الملف الأساسي PDF
    - دمج عدة ملفات PDF
    - حفظ نسخة من الملف قبل الدمج
    - تسجيل العملية
    
    Args:
        request: HTTP POST request مع ملفات PDF للدمج
        pk: معرف المرفق الأساسي
    
    Returns:
        Redirect to book detail page
    """
    att = get_object_or_404(Attachment, id=pk, is_deleted=False)
    book = att.book
    
    # فحص الصلاحيات
    if not (request.user.is_superuser or request.user.is_staff or book.created_by == request.user):
        messages.error(request, "غير مصرح بدمج الملفات.")
        return redirect("book_detail", pk=book.pk)
    
    # التحقق من أن الملف PDF
    if not att.file_type or "pdf" not in att.file_type.lower():
        messages.error(request, "يمكن دمج الملفات فقط مع ملفات PDF.")
        return redirect("book_detail", pk=book.pk)
    
    if request.method == "POST" and request.FILES.getlist("merge_files"):
        try:
            # حفظ نسخة قبل الدمج
            _save_attachment_version(att, request.user, note="Merged with other PDFs", merge_type="pdf")
            
            # قراءة ملف PDF الرئيسي
            att.file.open("rb")
            writer = PdfWriter()
            main_reader = PdfReader(att.file)
            
            # إضافة جميع الصفحات من ملف PDF الرئيسي
            for page in main_reader.pages:
                writer.add_page(page)
            
            # إضافة صفحات من ملفات الدمج
            merge_files = request.FILES.getlist("merge_files")
            for merge_file in merge_files:
                try:
                    merge_reader = PdfReader(merge_file)
                    for page in merge_reader.pages:
                        writer.add_page(page)
                except Exception as e:
                    logger.warning("Could not read merge file: %s", e)
            
            # حفظ ملف PDF المدمج
            buffer = BytesIO()
            writer.write(buffer)
            buffer.seek(0)
            
            att.file.save(att.file.name, File(buffer), save=True)
            
            # تسجيل العملية
            BookHistory.objects.create(
                book=book,
                action="merge-pages",
                by=request.user,
                attachment=att,
                notes=f"Merged {len(merge_files)} PDFs"
            )
            
            messages.success(request, f"تم دمج {len(merge_files)} ملفات بنجاح.")
        except Exception as e:
            logger.error("PDF merge failed: %s", e, exc_info=True)
            messages.error(request, f"فشل دمج الملفات: {e}")
    
    return redirect("book_detail", pk=book.pk)


@login_required
def attachment_remove_pages(request, pk):
    """
    حذف صفحات محددة من ملف PDF
    
    المميزات:
    - تحديد الصفحات بصيغة: 1,3,5-7 (صفحات فردية ونطاقات)
    - فحص أن الملف PDF
    - حفظ نسخة قبل التحرير
    - تسجيل العملية
    
    Args:
        request: HTTP POST request مع قائمة الصفحات المراد حذفها
        pk: معرف المرفق
    
    Returns:
        Redirect to book detail page
    """
    att = get_object_or_404(Attachment, id=pk, is_deleted=False)
    book = att.book
    
    # فحص الصلاحيات
    if not (request.user.is_superuser or request.user.is_staff or book.created_by == request.user):
        messages.error(request, "غير مصرح بحذف الصفحات.")
        return redirect("book_detail", pk=book.pk)
    
    # التحقق من أن الملف PDF
    if not att.file_type or "pdf" not in att.file_type.lower():
        messages.error(request, "يمكن حذف الصفحات فقط من ملفات PDF.")
        return redirect("book_detail", pk=book.pk)
    
    if request.method == "POST":
        try:
            pages_to_remove = request.POST.get("pages_to_remove", "")
            if not pages_to_remove.strip():
                messages.error(request, "يرجى تحديد الصفحات المراد حذفها.")
                return redirect("book_detail", pk=book.pk)
            
            # تحليل أرقام الصفحات
            page_numbers = []
            for part in pages_to_remove.split(","):
                part = part.strip()
                if "-" in part:
                    start, end = part.split("-")
                    page_numbers.extend(range(int(start.strip())-1, int(end.strip())))
                else:
                    page_numbers.append(int(part)-1)
            
            # حفظ نسخة قبل التعديل
            _save_attachment_version(att, request.user, note=f"Removed pages: {pages_to_remove}")
            
            # قراءة ملف PDF وحذف الصفحات
            att.file.open("rb")
            reader = PdfReader(att.file)
            writer = PdfWriter()
            
            for idx, page in enumerate(reader.pages):
                if idx not in page_numbers:
                    writer.add_page(page)
            
            # حفظ ملف PDF المعدل
            buffer = BytesIO()
            writer.write(buffer)
            buffer.seek(0)
            
            att.file.save(att.file.name, File(buffer), save=True)
            
            # تسجيل العملية
            BookHistory.objects.create(
                book=book,
                action="remove-pages",
                by=request.user,
                attachment=att,
                notes=f"Removed pages: {pages_to_remove}"
            )
            
            messages.success(request, "تم حذف الصفحات بنجاح.")
        except Exception as e:
            logger.error("Page removal failed: %s", e, exc_info=True)
            messages.error(request, f"فشل حذف الصفحات: {e}")
    
    return redirect("book_detail", pk=book.pk)
