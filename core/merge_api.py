"""
APIs لخدمة الدمج الذكية
"""

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404

from .models import Attachment, AttachmentVersion, MergeLog
from .merge_service import SmartMergeService


class AttachmentMergeViewSet(viewsets.GenericViewSet):
    """
    API لإدارة دمج الملفات
    
    GET /api/attachments/{id}/versions/ - قائمة النسخ
    POST /api/attachments/{id}/merge/ - دمج ملف جديد
    DELETE /api/attachments/{id}/delete_file/ - حذف الملف
    POST /api/attachments/{id}/restore/ - استعادة نسخة سابقة
    GET /api/attachments/{id}/logs/ - سجل العمليات
    """
    
    queryset = Attachment.objects.all()
    permission_classes = [IsAuthenticated]
    
    def get_attachment(self, attachment_id):
        """الحصول على الملف المرفق"""
        return get_object_or_404(Attachment, id=attachment_id)
    
    @action(detail=True, methods=['post'])
    def merge(self, request, pk=None):
        """
        دمج ملف جديد مع الملف الحالي
        
        Parameters:
        - file: الملف الجديد (multipart/form-data)
        - merge_type: 'smart', 'pdf', 'image' (optional)
        
        Returns:
        - new_version: تفاصيل النسخة الجديدة
        - merge_log: سجل الدمج
        """
        attachment = self.get_attachment(pk)
        
        # التحقق من صلاحيات المستخدم
        if attachment.book.created_by != request.user and not request.user.is_staff:
            return Response(
                {'error': 'ليس لديك صلاحية لتعديل هذا الملف'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # التحقق من وجود الملف الجديد
        if 'file' not in request.FILES:
            return Response(
                {'error': 'يجب توفير ملف'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            new_file = request.FILES['file']
            merge_type = request.data.get('merge_type', 'smart')
            
            # إنشاء خدمة الدمج
            merge_service = SmartMergeService(attachment, request.user)
            
            # تنفيذ الدمج
            new_version = merge_service.merge_files(new_file, merge_type)
            
            return Response({
                'success': True,
                'message': 'تم دمج الملف بنجاح',
                'new_version': {
                    'id': new_version.id,
                    'version_number': new_version.version_number,
                    'file_url': new_version.file.url,
                    'created_at': new_version.created_at,
                    'merge_type': new_version.merge_type
                },
                'merge_log': {
                    'id': merge_service.merge_log.id,
                    'status': merge_service.merge_log.status
                }
            }, status=status.HTTP_200_OK)
        
        except Exception as e:
            return Response(
                {'error': f'خطأ في دمج الملف: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['delete'])
    def delete_file(self, request, pk=None):
        """
        حذف الملف الحالي (soft delete)
        
        Parameters:
        - reason: سبب الحذف (optional)
        """
        attachment = self.get_attachment(pk)
        
        # التحقق من صلاحيات المستخدم
        if attachment.book.created_by != request.user and not request.user.is_staff:
            return Response(
                {'error': 'ليس لديك صلاحية لحذف هذا الملف'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            reason = request.data.get('reason', '')
            
            merge_service = SmartMergeService(attachment, request.user)
            merge_service.delete_current_file(reason)
            
            return Response({
                'success': True,
                'message': 'تم حذف الملف بنجاح',
                'delete_log': {
                    'id': merge_service.merge_log.id,
                    'status': merge_service.merge_log.status
                }
            }, status=status.HTTP_200_OK)
        
        except Exception as e:
            return Response(
                {'error': f'خطأ في حذف الملف: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['post'])
    def restore(self, request, pk=None):
        """
        استعادة نسخة سابقة
        
        Parameters:
        - version_number: رقم النسخة المراد استعادتها
        """
        attachment = self.get_attachment(pk)
        
        # التحقق من صلاحيات المستخدم
        if attachment.book.created_by != request.user and not request.user.is_staff:
            return Response(
                {'error': 'ليس لديك صلاحية لاستعادة نسخ هذا الملف'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        version_number = request.data.get('version_number')
        
        if not version_number:
            return Response(
                {'error': 'يجب تحديد رقم النسخة'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            merge_service = SmartMergeService(attachment, request.user)
            version = merge_service.restore_version(version_number)
            
            return Response({
                'success': True,
                'message': f'تم استعادة النسخة {version_number} بنجاح',
                'restored_version': {
                    'id': version.id,
                    'version_number': version.version_number,
                    'file_url': version.file.url,
                    'created_at': version.created_at
                }
            }, status=status.HTTP_200_OK)
        
        except ValueError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return Response(
                {'error': f'خطأ في استعادة النسخة: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['get'])
    def history(self, request, pk=None):
        """
        الحصول على سجل الدمج والحذف والاستعادة
        """
        attachment = self.get_attachment(pk)
        
        merge_logs = MergeLog.objects.filter(attachment=attachment).order_by('-performed_at')
        
        logs_data = [
            {
                'id': log.id,
                'action': log.get_action_display(),
                'performed_by': str(log.performed_by),
                'performed_at': log.performed_at,
                'status': log.get_status_display(),
                'description': log.description
            }
            for log in merge_logs
        ]
        
        return Response({
            'attachment_id': attachment.id,
            'logs': logs_data
        }, status=status.HTTP_200_OK)
    
    @action(detail=True, methods=['get'])
    def versions(self, request, pk=None):
        """
        الحصول على قائمة جميع النسخ
        """
        attachment = self.get_attachment(pk)
        
        versions = attachment.versions.all().order_by('version_number')
        
        versions_data = [
            {
                'id': version.id,
                'version_number': version.version_number,
                'file_url': version.file.url if version.file else None,
                'created_at': version.created_at,
                'created_by': str(version.created_by),
                'is_merged': version.is_merged,
                'merge_type': version.merge_type,
                'note': version.note
            }
            for version in versions
        ]
        
        return Response({
            'attachment_id': attachment.id,
            'total_versions': versions.count(),
            'versions': versions_data
        }, status=status.HTTP_200_OK)
