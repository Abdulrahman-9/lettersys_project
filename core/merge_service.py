"""
خدمة الدمج الذكية - Smart Merge Service
تدعم دمج PDFs، الصور، والملفات المختلطة بطرق ذكية
"""

import os
import mimetypes
from pathlib import Path
from datetime import datetime
from django.utils import timezone
from io import BytesIO

# استيراد المكتبات المطلوبة
try:
    from PyPDF2 import PdfMerger, PdfReader
except ImportError:
    PdfMerger = None
    PdfReader = None

try:
    from PIL import Image
except ImportError:
    Image = None

from django.core.files.base import ContentFile
from django.conf import settings
from .models import AttachmentVersion, MergeLog


class SmartMergeService:
    """
    خدمة دمج ذكية تدعم:
    - PDF + PDF = دمج الصفحات
    - Image + Image = دمج الصور (أفقياً أو رأسياً)
    - PDF + Image = تحويل وتجميع
    """
    
    # أنواع الملفات المدعومة
    PDF_TYPES = {'application/pdf', 'application/x-pdf'}
    IMAGE_TYPES = {'image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/bmp', 'image/webp'}
    
    def __init__(self, attachment, user):
        self.attachment = attachment
        self.user = user
        self.merge_log = None
    
    def get_file_type(self, file_obj):
        """تحديد نوع الملف"""
        if hasattr(file_obj, 'name'):
            mime_type, _ = mimetypes.guess_type(file_obj.name)
        else:
            mime_type = None
        
        if mime_type in self.PDF_TYPES:
            return 'pdf'
        elif mime_type in self.IMAGE_TYPES:
            return 'image'
        else:
            return 'unknown'
    
    def merge_pdfs(self, source_file, target_file):
        """دمج ملفات PDF"""
        if not PdfMerger:
            raise ImportError("PyPDF2 غير مثبت. تثبيت: pip install PyPDF2")
        
        try:
            merger = PdfMerger()
            
            # قراءة الملفات
            source_file.seek(0)
            target_file.seek(0)
            
            # دمج الملفات
            merger.append(PdfReader(target_file))
            merger.append(PdfReader(source_file))
            
            # حفظ الملف المدمج
            output = BytesIO()
            merger.write(output)
            merger.close()
            
            output.seek(0)
            return output
        
        except Exception as e:
            raise ValueError(f"خطأ في دمج ملفات PDF: {str(e)}")
    
    def merge_images(self, source_file, target_file, orientation='vertical'):
        """
        دمج الصور
        orientation: 'vertical' أو 'horizontal'
        """
        if not Image:
            raise ImportError("Pillow غير مثبت. تثبيت: pip install Pillow")
        
        try:
            source_file.seek(0)
            target_file.seek(0)
            
            # فتح الصور
            img_source = Image.open(source_file)
            img_target = Image.open(target_file)
            
            # تحويل إلى RGB إذا كانت PNG مع Alpha
            if img_source.mode == 'RGBA':
                img_source = img_source.convert('RGB')
            if img_target.mode == 'RGBA':
                img_target = img_target.convert('RGB')
            
            # دمج حسب الاتجاه
            if orientation == 'vertical':
                # دمج عمودي (الصورة الجديدة تحت القديمة)
                max_width = max(img_target.width, img_source.width)
                total_height = img_target.height + img_source.height
                
                merged = Image.new('RGB', (max_width, total_height), color='white')
                merged.paste(img_target, (0, 0))
                merged.paste(img_source, (0, img_target.height))
            else:
                # دمج أفقي (الصورة الجديدة بجانب القديمة)
                max_height = max(img_target.height, img_source.height)
                total_width = img_target.width + img_source.width
                
                merged = Image.new('RGB', (total_width, max_height), color='white')
                merged.paste(img_target, (0, 0))
                merged.paste(img_source, (img_target.width, 0))
            
            # حفظ الصورة المدمجة
            output = BytesIO()
            merged.save(output, format='PNG', quality=95)
            output.seek(0)
            return output
        
        except Exception as e:
            raise ValueError(f"خطأ في دمج الصور: {str(e)}")
    
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
        دمج ملف جديد مع الملف الحالي
        merge_type: 'smart' (تلقائي), 'pdf', 'image'
        """
        try:
            # الحصول على الإصدار الحالي
            current_version = self.attachment.versions.latest('version_number')
            current_file = current_version.file
            
            # تحديد نوع الملفات
            source_type = self.get_file_type(new_file)
            target_type = self.get_file_type(current_file)
            
            # تحديد نوع الدمج
            if merge_type == 'smart':
                if source_type == 'pdf' and target_type == 'pdf':
                    merge_type = 'pdf'
                elif source_type == 'image' and target_type == 'image':
                    merge_type = 'image'
                else:
                    # حالة مختلطة - تحتاج معالجة خاصة
                    merge_type = 'mixed'
            
            # إنشاء سجل الدمج
            self.create_merge_log(
                action='merge',
                source_version=None,  # سيتم تحديثه بعد الدمج
                target_version=current_version,
                description=f"دمج ملف جديد: {new_file.name}"
            )
            
            # تنفيذ الدمج
            if merge_type == 'pdf':
                merged_file = self.merge_pdfs(new_file, current_file)
                filename = f"merged_{timezone.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            elif merge_type == 'image':
                merged_file = self.merge_images(new_file, current_file, orientation='vertical')
                filename = f"merged_{timezone.now().strftime('%Y%m%d_%H%M%S')}.png"
            else:
                raise ValueError("نوع الملفات غير متوافق للدمج")
            
            # حفظ النسخة الجديدة
            new_version = AttachmentVersion.objects.create(
                attachment=self.attachment,
                version_number=current_version.version_number + 1,
                created_by=self.user,
                note=f"دمج الملف: {new_file.name}",
                merge_type=merge_type,
                merged_from_version=current_version,
                is_merged=True,
                merge_metadata={
                    'source_filename': str(new_file.name),
                    'target_filename': str(current_file.name),
                    'merge_type': merge_type,
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
            
            # تحديث الملف الأساسي
            self.attachment.is_deleted = True
            self.attachment.deleted_at = timezone.now()
            self.attachment.deleted_by = self.user
            self.attachment.file = None
            self.attachment.save()
            
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
            
            # تحديث الملف الأساسي
            self.attachment.file = version.file
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
