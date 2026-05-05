# -*- coding: utf-8 -*-
"""
Comments Views - معالجات التعليقات
إدارة التعليقات على الكتب (إضافة، تعديل، حذف)
"""

import json
import logging

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from ..models import Book, BookComment

logger = logging.getLogger(__name__)


@login_required
@require_http_methods(["POST"])
def add_book_comment(request, book_id):
    """
    إضافة تعليق جديد على كتاب
    
    Args:
        request: HTTP request with JSON body containing 'content'
        book_id: معرف الكتاب
    
    Returns:
        JsonResponse: حالة العملية وبيانات التعليق
    """
    try:
        data = json.loads(request.body)
        content = data.get('content', '').strip()
        
        if not content:
            return JsonResponse({
                "status": "error",
                "message": "محتوى التعليق مطلوب"
            }, status=400)
        
        if len(content) > 5000:
            return JsonResponse({
                "status": "error",
                "message": f"التعليق طويل جداً ({len(content)} حرف). الحد الأقصى 5000 حرف."
            }, status=400)
        
        # Get book
        book = Book.objects.get(pk=book_id, is_deleted=False)
        
        # Check permission
        has_permission = (
            request.user.is_superuser or
            request.user.is_staff or
            book.created_by == request.user
        )
        
        if not has_permission:
            return JsonResponse({
                "status": "error",
                "message": "ليس لديك صلاحية التعليق على هذا الكتاب"
            }, status=403)
        
        # Create comment
        comment = BookComment.objects.create(
            book=book,
            created_by=request.user,
            content=content
        )
        
        logger.info(
            f"Comment added: user_id={request.user.id} book_id={book_id} "
            f"comment_id={comment.id}"
        )
        
        return JsonResponse({
            "status": "ok",
            "message": "تم إضافة التعليق بنجاح",
            "comment": {
                "id": comment.id,
                "content": comment.content,
                "created_by": comment.created_by.username,
                "created_at": comment.created_at.strftime("%d/%m/%Y %H:%M"),
                "is_edited": comment.is_edited
            }
        })
    
    except Book.DoesNotExist:
        return JsonResponse({
            "status": "error",
            "message": "الكتاب غير موجود"
        }, status=404)
    except Exception as e:
        logger.error(f"Error adding comment: {e}", exc_info=True)
        return JsonResponse({
            "status": "error",
            "message": "حدث خطأ أثناء إضافة التعليق"
        }, status=500)


@login_required
@require_http_methods(["POST"])
def edit_book_comment(request, comment_id):
    """
    تعديل تعليق موجود
    
    Args:
        request: HTTP request with JSON body containing 'content'
        comment_id: معرف التعليق
    
    Returns:
        JsonResponse: حالة العملية وبيانات التعليق المعدل
    """
    try:
        data = json.loads(request.body)
        content = data.get('content', '').strip()
        
        if not content:
            return JsonResponse({
                "status": "error",
                "message": "محتوى التعليق مطلوب"
            }, status=400)
        
        if len(content) > 5000:
            return JsonResponse({
                "status": "error",
                "message": f"التعليق طويل جداً ({len(content)} حرف). الحد الأقصى 5000 حرف."
            }, status=400)
        
        # Get comment
        comment = BookComment.objects.select_related('book', 'created_by').get(pk=comment_id)
        
        # Check permission (only owner or superuser can edit)
        if not (request.user == comment.created_by or request.user.is_superuser):
            return JsonResponse({
                "status": "error",
                "message": "ليس لديك صلاحية تعديل هذا التعليق"
            }, status=403)
        
        # Update comment
        comment.content = content
        comment.is_edited = True
        comment.save()
        
        logger.info(
            f"Comment edited: user_id={request.user.id} comment_id={comment_id}"
        )
        
        return JsonResponse({
            "status": "ok",
            "message": "تم تعديل التعليق بنجاح",
            "comment": {
                "id": comment.id,
                "content": comment.content,
                "is_edited": comment.is_edited,
                "updated_at": comment.updated_at.strftime("%d/%m/%Y %H:%M")
            }
        })
    
    except BookComment.DoesNotExist:
        return JsonResponse({
            "status": "error",
            "message": "التعليق غير موجود"
        }, status=404)
    except Exception as e:
        logger.error(f"Error editing comment: {e}", exc_info=True)
        return JsonResponse({
            "status": "error",
            "message": "حدث خطأ أثناء تعديل التعليق"
        }, status=500)


@login_required
@require_http_methods(["POST"])
def delete_book_comment(request, comment_id):
    """
    حذف تعليق
    
    Args:
        request: HTTP request
        comment_id: معرف التعليق
    
    Returns:
        JsonResponse: حالة العملية
    """
    try:
        # Get comment
        comment = BookComment.objects.select_related('book', 'created_by').get(pk=comment_id)
        
        # Check permission (only owner or superuser can delete)
        if not (request.user == comment.created_by or request.user.is_superuser):
            return JsonResponse({
                "status": "error",
                "message": "ليس لديك صلاحية حذف هذا التعليق"
            }, status=403)
        
        comment_id_backup = comment.id
        comment.delete()
        
        logger.info(
            f"Comment deleted: user_id={request.user.id} comment_id={comment_id_backup}"
        )
        
        return JsonResponse({
            "status": "ok",
            "message": "تم حذف التعليق بنجاح"
        })
    
    except BookComment.DoesNotExist:
        return JsonResponse({
            "status": "error",
            "message": "التعليق غير موجود"
        }, status=404)
    except Exception as e:
        logger.error(f"Error deleting comment: {e}", exc_info=True)
        return JsonResponse({
            "status": "error",
            "message": "حدث خطأ أثناء حذف التعليق"
        }, status=500)
