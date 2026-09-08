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

from core.scoping import can_open_content


from ..models import Attachment, Book, BookHistory

logger = logging.getLogger(__name__)

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
        # قاعدةُ الرؤية من المصدر الوحيد — وهذه عمليّةُ **محتوى**
        # (تعديلٌ أو تعليقٌ أو تغييرُ حالة) لا مجرّدُ رؤيةِ صفّ:
        # فالسرّيُّ لا يُعدَّل بمن يرى سطرَه في الدفتر.
        has_permission = can_open_content(book, request.user)
        
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
