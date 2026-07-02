# -*- coding: utf-8 -*-
"""
API Module - واجهات برمجية إضافية
مجموعة APIs متنوعة لتحسين وظائف النظام

وحدة متخصصة لـ:
- خدمة Service Worker للـ PWA
- تحديث ملاحظات الكتب
- تسجيل تصحيحات OCR للتعلم المستمر
- إحصائيات التدريب
- تشغيل التدريب يدوياً
"""

import json
import logging
import os

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from ..models import Attachment, Book, BookHistory

logger = logging.getLogger(__name__)

# استيراد نظام التعلم المستمر
try:
    from .continuous_learning import continuous_learning
except ImportError:
    continuous_learning = None


# ==============================================================================
# PWA Service Worker View
# ==============================================================================

def serve_service_worker(request):
    """
    خدمة ملف service-worker.js مباشرة بدون redirect لتجنب خطأ PWA
    'script resource is behind a redirect, which is disallowed'
    
    المميزات:
    - خدمة مباشرة بدون إعادة توجيه
    - دعم PWA كامل
    - محاولة عدة مسارات (static/, root)
    - معالجة الأخطاء
    
    Args:
        request: Django HttpRequest
    
    Returns:
        HttpResponse: محتوى service-worker.js مع Content-Type صحيح
    
    Status Codes:
        - 200: Service worker file served
        - 404: Service worker file not found
        - 500: Error reading service worker file
    
    Examples:
        >>> GET /service-worker.js
        >>> # Returns JavaScript content
    """
    sw_path = os.path.join(settings.BASE_DIR, 'static', 'service-worker.js')
    
    if not os.path.exists(sw_path):
        # Fallback to the file in root if not in static folder
        sw_path = os.path.join(settings.BASE_DIR, 'service-worker.js')
    
    if os.path.exists(sw_path):
        try:
            with open(sw_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return HttpResponse(content, content_type='application/javascript; charset=utf-8')
        except Exception as e:
            logger.error(f"Error serving service-worker.js: {e}")
            return HttpResponse('// Service Worker error', content_type='application/javascript', status=500)
    
    return HttpResponse('// Service Worker not found', content_type='application/javascript', status=404)


# ==============================================================================
# Book Notes API
# ==============================================================================

@login_required
@require_http_methods(["POST"])
def update_book_notes(request, book_id):
    """
    API endpoint لتحديث ملاحظات الكتاب مع validation محسّن
    
    المميزات:
    - صلاحيات محسّنة (superuser, staff, owner)
    - validation على طول النص (حد أقصى 10000 حرف)
    - تسجيل في BookHistory
    - معالجة شاملة للأخطاء
    - logging كامل
    
    Args:
        request: Django HttpRequest
        book_id: معرف الكتاب
    
    POST Data:
        {
            "margin": "النص الجديد للملاحظات"
        }
    
    Returns:
        JsonResponse: نتيجة العملية
    
    Status Codes:
        - 200: Success - تم التحديث بنجاح
        - 400: Validation error - بيانات JSON غير صحيحة أو نص طويل جداً
        - 403: Permission denied - لا توجد صلاحية
        - 404: Not found - الكتاب غير موجود
        - 500: Server error - خطأ في الخادم
    
    Examples:
        >>> POST /api/books/123/notes/
        >>> {"margin": "ملاحظات جديدة"}
        >>> # Returns: {"status": "ok", "message": "تم حفظ الملاحظات بنجاح"}
    """
    try:
        book = Book.objects.select_related('created_by').get(id=book_id, is_deleted=False)
        
        # Enhanced permission check
        has_permission = (
            request.user.is_superuser or
            request.user.is_staff or
            book.created_by == request.user
        )
        
        if not has_permission:
            logger.warning(
                f"Unauthorized notes update attempt: user_id={request.user.id} "
                f"book_id={book_id}"
            )
            return JsonResponse({
                "status": "error",
                "message": "ليس لديك صلاحية تعديل ملاحظات هذا الكتاب"
            }, status=403)
        
        # Parse JSON data
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({
                "status": "error",
                "message": "بيانات JSON غير صحيحة"
            }, status=400)
        
        margin = data.get('margin', '').strip()
        
        # Validation: Maximum 10000 characters
        if len(margin) > 10000:
            return JsonResponse({
                "status": "error",
                "message": f"الملاحظات طويلة جداً (الحد الأقصى 10000 حرف، أنت أدخلت {len(margin)} حرف)"
            }, status=400)
        
        # Update notes
        book.margin = margin
        book.save(update_fields=['margin', 'updated_at'])
        
        # Log history
        BookHistory.objects.create(
            book=book,
            action='update_notes',
            by=request.user,
            notes='تحديث الملاحظات'
        )
        
        logger.info(
            f"Book notes updated: user_id={request.user.id} book_id={book_id} "
            f"notes_length={len(margin)}"
        )
        
        return JsonResponse({
            "status": "ok",
            "message": "تم حفظ الملاحظات بنجاح",
            "margin": book.margin
        })
    
    except Book.DoesNotExist:
        return JsonResponse({
            "status": "error",
            "message": "الكتاب غير موجود أو تم حذفه"
        }, status=404)
    except Exception as e:
        logger.error(f"Unexpected error in save_book_notes: {e}", exc_info=True)
        return JsonResponse({
            "success": False,
            "message": "حدث خطأ في الخادم. يرجى المحاولة لاحقاً."
        }, status=500)


@login_required
@require_http_methods(["GET"])
def attachment_ocr_text(request, att_id):
    """
    إرجاع النص المستخرج (OCR) لمرفقٍ ما — للعرض بجانب المسح (وصولية + بحث).
    يُحمَّل كسولاً عند الطلب. النص المنظّف مفضَّل على الخام.
    """
    att = get_object_or_404(
        Attachment.objects.select_related('book', 'ocr_result'),
        pk=att_id,
        is_deleted=False,
    )
    book = att.book
    has_permission = (
        request.user.is_superuser
        or request.user.is_staff
        or (book and book.created_by_id == request.user.id)
    )
    if not has_permission:
        return JsonResponse({"status": "error", "message": "ليس لديك صلاحية"}, status=403)

    ocr = getattr(att, 'ocr_result', None)
    text = ''
    confidence = 0.0
    if ocr is not None:
        text = (ocr.cleaned_text or ocr.raw_text or '').strip()
        confidence = round(ocr.confidence_score or 0.0, 1)

    return JsonResponse({
        "status": "ok",
        "has_text": bool(text),
        "text": text,
        "confidence": confidence,
    })


# ==============================================================================
# Continuous Learning / OCR Training Views
# ==============================================================================

@login_required
@require_http_methods(["POST"])
def record_ocr_feedback(request):
    """
    تسجيل تصحيح يدوي لنص OCR - يستخدم لتحسين النموذج مستقبلاً
    
    المميزات:
    - تسجيل التصحيحات اليدوية للنصوص
    - دعم اللغتين (عربي/انجليزي)
    - تخزين metadata كامل (user, book, timestamp)
    - تشغيل تلقائي للتدريب عند الوصول للحد المطلوب
    
    Args:
        request: Django HttpRequest
    
    POST Data:
        {
            "image_path": "path/to/image.jpg",
            "original_text": "النص الأصلي من OCR",
            "corrected_text": "النص المصحح",
            "language": "ar",
            "book_id": 123,
            "confidence": 0.85
        }
    
    Returns:
        JsonResponse: نتيجة التسجيل
    
    Status Codes:
        - 200: Success - تم التسجيل بنجاح
        - 400: Validation error - بيانات ناقصة أو خطأ في التسجيل
        - 500: Server error - خطأ في الخادم
        - 501: Not implemented - نظام التعلم غير متوفر
    
    Examples:
        >>> POST /api/ocr/feedback/
        >>> {"image_path": "...", "corrected_text": "نص صحيح"}
        >>> # Returns: {"status": "ok", "data": {"feedback_id": 1, ...}}
    """
    if not continuous_learning:
        return JsonResponse({"status": "error", "message": "نظام التعلم غير متوفر"}, status=501)
    
    try:
        data = json.loads(request.body)
        
        # البيانات المطلوبة
        image_path = data.get('image_path')
        original_text = data.get('original_text', '')
        corrected_text = data.get('corrected_text', '').strip()
        language = data.get('language', 'ar')
        book_id = data.get('book_id')
        
        # تحقق من البيانات
        if not image_path:
            return JsonResponse({
                "status": "error",
                "message": "مسار الصورة مطلوب"
            }, status=400)
        
        if not corrected_text:
            return JsonResponse({
                "status": "error",
                "message": "النص المصحح مطلوب"
            }, status=400)
        
        # سجل التصحيح
        result = continuous_learning.record_feedback(
            image_path=image_path,
            original_text=original_text,
            corrected_text=corrected_text,
            language=language,
            confidence=data.get('confidence', 0.0),
            metadata={
                'book_id': book_id,
                'user_id': request.user.id,
                'username': request.user.username,
                'timestamp': timezone.now().isoformat()
            }
        )
        
        if result['success']:
            logger.info(
                f"OCR feedback recorded: user_id={request.user.id} "
                f"correction_type={result.get('correction_type')} "
                f"book_id={book_id}"
            )
            
            return JsonResponse({
                "status": "ok",
                "message": "تم تسجيل التصحيح بنجاح",
                "data": {
                    "feedback_id": result.get('feedback_id'),
                    "correction_type": result.get('correction_type'),
                    "training_triggered": result.get('training_triggered', False)
                }
            })
        else:
            return JsonResponse({
                "status": "error",
                "message": result.get('error', 'فشل تسجيل التصحيح')
            }, status=400)
    
    except Exception as e:
        logger.error(f"Error recording OCR feedback: {e}", exc_info=True)
        return JsonResponse({
            "status": "error",
            "message": "حدث خطأ أثناء تسجيل التصحيح"
        }, status=500)


@login_required
@require_http_methods(["GET"])
def ocr_training_statistics(request):
    """
    عرض إحصائيات التدريب والتعلم المستمر
    
    المميزات:
    - عدد العينات المسجلة
    - عدد النماذج المدربة
    - آخر وقت تدريب
    - دقة النماذج
    - معدل التصحيحات
    
    Args:
        request: Django HttpRequest
    
    Returns:
        JsonResponse: إحصائيات التدريب
    
    Status Codes:
        - 200: Success - الإحصائيات
        - 500: Server error - خطأ في الخادم
        - 501: Not implemented - نظام التعلم غير متوفر
    
    Examples:
        >>> GET /api/ocr/statistics/
        >>> # Returns: {"status": "ok", "data": {"total_samples": 150, ...}}
    """
    if not continuous_learning:
        return JsonResponse({"status": "error", "message": "نظام التعلم غير متوفر"}, status=501)
    
    try:
        stats = continuous_learning.get_training_statistics()
        
        return JsonResponse({
            "status": "ok",
            "data": stats
        })
    
    except Exception as e:
        logger.error(f"Error getting training statistics: {e}", exc_info=True)
        return JsonResponse({
            "status": "error",
            "message": "حدث خطأ أثناء جلب الإحصائيات"
        }, status=500)


@login_required
@require_http_methods(["POST"])
def trigger_ocr_training(request):
    """
    تشغيل عملية التدريب يدوياً - يتطلب صلاحيات المشرف
    
    المميزات:
    - تشغيل يدوي للتدريب
    - التحقق من وجود عينات كافية
    - صلاحيات محدودة للمديرين فقط
    - تسجيل كامل للعملية
    
    Args:
        request: Django HttpRequest
    
    Returns:
        JsonResponse: نتيجة التدريب
    
    Status Codes:
        - 200: Success - تم بدء التدريب بنجاح
        - 400: Validation error - عدد العينات غير كافي
        - 403: Permission denied - لا توجد صلاحية
        - 500: Server error - خطأ في الخادم
        - 501: Not implemented - نظام التعلم غير متوفر
    
    Examples:
        >>> POST /api/ocr/train/
        >>> # Returns: {"status": "ok", "message": "تم بدء عملية التدريب بنجاح"}
    """
    if not request.user.is_superuser:
        return JsonResponse({
            "status": "error",
            "message": "ليس لديك صلاحية لهذا الإجراء"
        }, status=403)
    
    if not continuous_learning:
        return JsonResponse({"status": "error", "message": "نظام التعلم غير متوفر"}, status=501)
    
    try:
        # تحقق من وجود عينات كافية
        result = continuous_learning.check_and_trigger_training(force=True)
        
        if result['success']:
            logger.info(
                f"OCR training triggered manually: user_id={request.user.id}"
            )
            
            return JsonResponse({
                "status": "ok",
                "message": "تم بدء عملية التدريب بنجاح",
                "data": result
            })
        else:
            return JsonResponse({
                "status": "error",
                "message": result.get('error', 'فشل تشغيل التدريب')
            }, status=400)
    
    except Exception as e:
        logger.error(f"Error triggering OCR training: {e}", exc_info=True)
        return JsonResponse({
            "status": "error",
            "message": "حدث خطأ أثناء تشغيل التدريب"
        }, status=500)
