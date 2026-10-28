"""
خدمة الدمج الذكية - Smart Merge Service
تُحوّل كل المدخلات إلى PDF ثم تدمجها، فالناتج موحّد بصيغة PDF دائماً.
"""

from django.utils import timezone
from io import BytesIO

from pypdf import PdfReader, PdfWriter

from django.core.files.base import ContentFile
from .attachment_service import attachment_write, ensure_pdf_bytes, validate_attachment_file
from .models import AttachmentVersion, MergeLog


def _pdf_pages(data) -> int:
    """عددُ صفحات PDF من بايتاته — صفرٌ إن تعذّر (لا يُفشل الدمجَ بحالٍ)."""
    try:
        import fitz
        from .pdf_lock import MUPDF_LOCK
        with MUPDF_LOCK, fitz.open(stream=bytes(data), filetype='pdf') as doc:
            return doc.page_count
    except Exception:                       # noqa: BLE001
        return 0


def _file_bytes(file_obj):
    """قراءة كامل محتوى ملف (FieldFile أو ملف مرفوع) مع إعادة المؤشّر."""
    try:
        file_obj.open('rb')
    except (AttributeError, ValueError):
        pass
    try:
        file_obj.seek(0)
    except (AttributeError, ValueError):
        pass
    data = file_obj.read()
    try:
        file_obj.seek(0)
    except (AttributeError, ValueError):
        pass
    return data


class SmartMergeService:
    """
    خدمة دمج ذكية: تُحوّل كل المدخلات إلى PDF ثم تدمجها، فالناتج PDF دائماً.
    """

    def __init__(self, attachment, user):
        self.attachment = attachment
        self.user = user
        self.merge_log = None

    def merge_pdfs(self, source_file, target_file):
        """دمج ملفي PDF (الهدف أولاً ثم المصدر) عبر pypdf."""
        try:
            target_file.seek(0)
            source_file.seek(0)

            writer = PdfWriter()
            writer.append(PdfReader(target_file))
            writer.append(PdfReader(source_file))

            output = BytesIO()
            writer.write(output)
            writer.close()

            output.seek(0)
            return output

        except Exception as e:
            raise ValueError(f"خطأ في دمج ملفات PDF: {str(e)}")
    
    def create_merge_log(self, action, source_version=None, target_version=None, status='pending', description=''):
        """إنشاء سجل دمج"""
        self.merge_log = MergeLog.objects.create(
            attachment=self.attachment,
            action=action,
            performed_by=self.user,
            source_version=source_version,
            target_version=target_version,
            status=status,
            description=description
        )
        return self.merge_log
    
    def update_merge_log(self, status, error_message=''):
        """تحديث حالة سجل الدمج"""
        if self.merge_log:
            self.merge_log.status = status
            self.merge_log.error_message = error_message
            self.merge_log.save(update_fields=['status', 'error_message'])
    
    def merge_files(self, new_file, merge_type='smart'):
        """
        دمج ملف جديد مع الملف الحالي.

        التوحيد: يُحوَّل كلا الملفين إلى PDF أولاً (الصور القديمة تُلَفّ في PDF
        لحظة الدمج)، فيكون الناتج **PDF دائماً** ولا حالة «مختلط» ولا PNG.
        """
        # تحقّق موحّد من الحجم والنوع قبل أي سجل دمج أو كتابة — #12
        validate_attachment_file(new_file)
        self.create_merge_log(action='merge', description=f"دمج ملف جديد: {new_file.name}")
        try:
            with attachment_write(self.attachment) as (locked, save_file):
                self.attachment = locked
                return self._merge_files(new_file, save_file)
        except Exception as e:
            self.update_merge_log('failed', str(e))
            raise

    def _merge_files(self, new_file, save_file):
        # The live file includes edits; the latest version may be an old snapshot.
        current_version = self.attachment.versions.order_by('-version_number').first()
        live_file = self.attachment.file
        current_file = live_file if getattr(live_file, 'name', None) else (
            current_version.file if current_version else None)
        number = (current_version.version_number + 1) if current_version else 1
        new_pdf_bytes, _, _ = ensure_pdf_bytes(_file_bytes(new_file), getattr(new_file, 'name', ''))
        current_pdf_bytes, _, _ = ensure_pdf_bytes(
            _file_bytes(current_file), getattr(current_file, 'name', ''))
        merged_file = self.merge_pdfs(BytesIO(new_pdf_bytes), BytesIO(current_pdf_bytes))
        filename = f"merged_{timezone.localtime().strftime('%Y%m%d_%H%M%S')}.pdf"
        added_pages = _pdf_pages(new_pdf_bytes)
        pages_before = _pdf_pages(current_pdf_bytes)
        merged_bytes = merged_file.getbuffer().tobytes()
        total_pages = _pdf_pages(merged_bytes) or (pages_before + added_pages)
        new_version = AttachmentVersion(
            attachment=self.attachment, version_number=number, created_by=self.user,
            note=f"دمج الملف: {new_file.name}", merge_type='pdf',
            merged_from_version=current_version, is_merged=True,
            merge_metadata={
                'source_filename': str(new_file.name),
                'target_filename': str(getattr(current_file, 'name', '')),
                'merge_type': 'pdf',
                'merged_at': timezone.now().isoformat(),
                'added_pages': added_pages,
                'pages_before': pages_before,
            },
            page_count=total_pages, file_size=len(merged_bytes),
        )
        save_file(new_version.file, filename, ContentFile(merged_bytes))
        new_version.save()
        self.attachment.file = new_version.file
        self.attachment.save(update_fields=['file'])
        self.merge_log.target_version = new_version
        self.merge_log.status = 'success'
        self.merge_log.save(update_fields=['target_version', 'status'])
        return new_version

    
    def delete_current_file(self, reason=''):
        """حذف الملف الحالي (soft delete)"""
        self.create_merge_log(action='delete', description=reason)
        try:
            with attachment_write(self.attachment) as (locked, _save_file):
                self.attachment = locked
                locked.is_deleted = True
                locked.deleted_at = timezone.now()
                locked.deleted_by = self.user
                locked.save(update_fields=["is_deleted", "deleted_at", "deleted_by"])
                self.update_merge_log('success')
            return True
        
        except Exception as e:
            self.update_merge_log('failed', str(e))
            raise
    
    def restore_version(self, version_number):
        """استعادة نسخة سابقة"""
        self.create_merge_log(
            action='restore', description=f"استعادة النسخة {version_number}")
        try:
            with attachment_write(self.attachment, allow_deleted=True) as (locked, save_file):
                self.attachment = locked
                version = locked.versions.get(version_number=version_number)
                from pathlib import Path
                raw = _file_bytes(version.file)
                pdf_bytes, _, _ = ensure_pdf_bytes(raw, getattr(version.file, 'name', ''))
                base = Path(version.file.name).stem or 'restored'
                save_file(locked.file, f"{base}.pdf", ContentFile(pdf_bytes))
                locked.is_deleted = False
                locked.deleted_at = None
                locked.deleted_by = None
                locked.save(update_fields=['file', 'is_deleted', 'deleted_at', 'deleted_by'])
                self.merge_log.source_version = version
                self.merge_log.status = 'success'
                self.merge_log.save(update_fields=['source_version', 'status'])
            return version
        
        except AttachmentVersion.DoesNotExist:
            self.update_merge_log('failed', 'النسخة غير موجودة')
            raise ValueError('النسخة غير موجودة')
        except Exception as e:
            self.update_merge_log('failed', str(e))
            raise
