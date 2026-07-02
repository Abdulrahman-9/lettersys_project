"""
خدمة الدمج الذكية - Smart Merge Service
تُحوّل كل المدخلات إلى PDF ثم تدمجها، فالناتج موحّد بصيغة PDF دائماً.
"""

from django.utils import timezone
from io import BytesIO

from pypdf import PdfReader, PdfWriter

from django.core.files.base import ContentFile
from .attachment_service import ensure_pdf_bytes, validate_attachment_file
from .models import AttachmentVersion, MergeLog


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
            self.merge_log.save()
    
    def merge_files(self, new_file, merge_type='smart'):
        """
        دمج ملف جديد مع الملف الحالي.

        التوحيد: يُحوَّل كلا الملفين إلى PDF أولاً (الصور القديمة تُلَفّ في PDF
        لحظة الدمج)، فيكون الناتج **PDF دائماً** ولا حالة «مختلط» ولا PNG.
        """
        # تحقّق موحّد من الحجم والنوع قبل أي سجل دمج أو كتابة — #12
        validate_attachment_file(new_file)
        try:
            # مصدر الدمج هو الملف الحيّ للمرفق (يحوي آخر التعديلات)، لا أحدث نسخة —
            # فالنسخ لقطاتٌ لِما قبل التعديل (والنسخة 1 قد تكون الأصل الصُّوري)، فاستخدامها
            # كأساس يُسقط تعديلات المستخدم أو يدمج على الصورة الأصلية بدل الـPDF.
            current_version = self.attachment.versions.order_by('-version_number').first()
            live_file = self.attachment.file
            current_file = live_file if getattr(live_file, 'name', None) else (
                current_version.file if current_version else None)
            next_version_number = (current_version.version_number + 1) if current_version else 1

            # إنشاء سجل الدمج
            self.create_merge_log(
                action='merge',
                source_version=None,  # سيتم تحديثه بعد الدمج
                target_version=current_version,
                description=f"دمج ملف جديد: {new_file.name}"
            )

            # توحيد الصيغة: حوّل كلا المدخلين إلى PDF ثم ادمجهما كـ PDF
            new_pdf_bytes, _, _ = ensure_pdf_bytes(_file_bytes(new_file), getattr(new_file, 'name', ''))
            current_pdf_bytes, _, _ = ensure_pdf_bytes(_file_bytes(current_file), getattr(current_file, 'name', ''))

            merged_file = self.merge_pdfs(BytesIO(new_pdf_bytes), BytesIO(current_pdf_bytes))
            filename = f"merged_{timezone.now().strftime('%Y%m%d_%H%M%S')}.pdf"

            # حفظ النسخة الجديدة
            new_version = AttachmentVersion.objects.create(
                attachment=self.attachment,
                version_number=next_version_number,
                created_by=self.user,
                note=f"دمج الملف: {new_file.name}",
                merge_type='pdf',
                merged_from_version=current_version,
                is_merged=True,
                merge_metadata={
                    'source_filename': str(new_file.name),
                    'target_filename': str(getattr(current_file, 'name', '')),
                    'merge_type': 'pdf',
                    'merged_at': timezone.now().isoformat()
                },
                file_size=merged_file.getbuffer().nbytes
            )
            
            # حفظ الملف المدمج
            new_version.file.save(filename, ContentFile(merged_file.read()), save=True)
            
            # تحديث الملف الأساسي
            self.attachment.file = new_version.file
            self.attachment.save()
            
            # تحديث سجل الدمج
            self.merge_log.target_version = new_version
            self.merge_log.status = 'success'
            self.merge_log.save()
            
            return new_version
        
        except Exception as e:
            self.update_merge_log('failed', str(e))
            raise
    
    def delete_current_file(self, reason=''):
        """حذف الملف الحالي (soft delete)"""
        try:
            self.create_merge_log(
                action='delete',
                status='pending',
                description=reason
            )
            
            # حذف ناعم موحّد: نُبقي الملف على القرص (كي تعمل الاستعادة restore_attachment
            # ولا يتيتّم الملف) — لا نُفرّغ FieldFile. #11
            self.attachment.is_deleted = True
            self.attachment.deleted_at = timezone.now()
            self.attachment.deleted_by = self.user
            self.attachment.save(update_fields=["is_deleted", "deleted_at", "deleted_by"])
            
            self.update_merge_log('success')
            return True
        
        except Exception as e:
            self.update_merge_log('failed', str(e))
            raise
    
    def restore_version(self, version_number):
        """استعادة نسخة سابقة"""
        try:
            version = self.attachment.versions.get(version_number=version_number)
            
            self.create_merge_log(
                action='restore',
                source_version=version,
                status='pending',
                description=f"استعادة النسخة {version_number}"
            )

            # توحيد الصيغة عند الاستعادة: النسخة 1 قد تكون الأصل الصُّوري (PNG/JPG)،
            # فنحوّل المُستعاد إلى PDF كي لا يُكسر ثبات «المرفق دائماً PDF».
            from pathlib import Path
            from .attachment_service import ensure_pdf_bytes
            raw = _file_bytes(version.file)
            pdf_bytes, _, _ = ensure_pdf_bytes(raw, getattr(version.file, 'name', ''))
            base = Path(getattr(version.file, 'name', 'restored') or 'restored').stem or 'restored'
            self.attachment.file.save(f"{base}.pdf", ContentFile(pdf_bytes), save=False)
            self.attachment.is_deleted = False
            self.attachment.deleted_at = None
            self.attachment.deleted_by = None
            self.attachment.save()
            
            self.update_merge_log('success')
            return version
        
        except AttachmentVersion.DoesNotExist:
            self.update_merge_log('failed', 'النسخة غير موجودة')
            raise ValueError('النسخة غير موجودة')
        except Exception as e:
            self.update_merge_log('failed', str(e))
            raise
