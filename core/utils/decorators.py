# -*- coding: utf-8 -*-
"""
Enhanced Decorators - Decorators محسّنة موحدة
للتعامل الموحد مع الصلاحيات والأخطاء و AJAX
"""

import json
import logging
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required as django_login_required
from django.http import JsonResponse
from django.shortcuts import redirect

from .notifications import notify_error, notify_success
from .exceptions import AppException, PermissionError, ServerError

logger = logging.getLogger(__name__)


def json_view(view_func):
    """
    Decorator لتحويل استجابة JSON تلقائياً
    يتعامل مع الأخطاء تلقائياً ويحولها إلى JSON
    
    مثال:
        @json_view
        def my_api(request):
            return {'status': 'ok', 'data': [...]}
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        try:
            result = view_func(request, *args, **kwargs)
            
            # إذا كانت النتيجة dict، حولها إلى JSON
            if isinstance(result, dict):
                return JsonResponse(result)
            
            # إذا كانت JsonResponse، أرجعها كما هي
            if isinstance(result, JsonResponse):
                return result
            
            return result
        
        except AppException as e:
            logger.warning(f"{e.code}: {e.message}")
            return JsonResponse({
                'success': False,
                'error': e.message,
                'code': e.code,
            }, status=e.status_code)
        
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return JsonResponse({
                'success': False,
                'error': 'حدث خطأ غير متوقع',
                'code': 'SERVER_ERROR',
            }, status=500)
    
    return wrapper


def handle_errors(view_func):
    """
    Decorator للتعامل مع الأخطاء بشكل موحد
    يحول الاستثناءات إلى رسائل للمستخدم
    
    مثال:
        @handle_errors
        def my_view(request):
            # الأخطاء ستُحول تلقائياً إلى رسائل
            ...
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        try:
            return view_func(request, *args, **kwargs)
        
        except AppException as e:
            logger.warning(f"{e.code}: {e.message}")
            notify_error(request, e.message)
            
            # إرجاع الصفحة السابقة أو الصفحة الرئيسية
            return redirect(request.META.get('HTTP_REFERER', 'home'))
        
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            notify_error(request, "حدث خطأ غير متوقع", exception=e)
            return redirect(request.META.get('HTTP_REFERER', 'home'))
    
    return wrapper


def require_permission(permission_name):
    """
    Decorator للتحقق من صلاحية محددة
    
    مثال:
        @require_permission('can_edit_book')
        def edit_book(request, pk):
            ...
    
    Args:
        permission_name: اسم الصلاحية (مثل: 'core.change_book')
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                messages.error(request, "يجب تسجيل الدخول أولاً")
                return redirect('login')
            
            # التحقق من الصلاحية
            if not request.user.has_perm(permission_name):
                logger.warning(f"Permission denied for {request.user.id}: {permission_name}")
                raise PermissionError()
            
            return view_func(request, *args, **kwargs)
        
        return wrapper
    
    return decorator


def staff_only(view_func):
    """
    Decorator للسماح فقط للموظفين والمسؤولين
    
    مثال:
        @staff_only
        def admin_panel(request):
            ...
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.error(request, "يجب تسجيل الدخول أولاً")
            return redirect('login')
        
        if not (request.user.is_staff or request.user.is_superuser):
            logger.warning(f"Staff access denied for {request.user.id}")
            raise PermissionError("هذه الصفحة متاحة فقط للموظفين")
        
        return view_func(request, *args, **kwargs)
    
    return wrapper


def superuser_only(view_func):
    """
    Decorator للسماح فقط للمسؤولين
    
    مثال:
        @superuser_only
        def super_admin_panel(request):
            ...
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.error(request, "يجب تسجيل الدخول أولاً")
            return redirect('login')
        
        if not request.user.is_superuser:
            logger.warning(f"Superuser access denied for {request.user.id}")
            raise PermissionError("هذه الصفحة متاحة فقط للمسؤولين")
        
        return view_func(request, *args, **kwargs)
    
    return wrapper


def owner_or_staff(get_object_func):
    """
    Decorator للتحقق من أن المستخدم هو صاحب الكائن أو موظف
    
    مثال:
        def get_book(book_id):
            return Book.objects.get(id=book_id)
        
        @owner_or_staff(get_book)
        def edit_book(request, book_id):
            ...
    
    Args:
        get_object_func: دالة لاسترجاع الكائن
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                messages.error(request, "يجب تسجيل الدخول أولاً")
                return redirect('login')
            
            try:
                obj = get_object_func(*args, **kwargs)
            except Exception as e:
                logger.error(f"Error getting object: {e}")
                raise ServerError("الكائن المطلوب غير موجود")
            
            # التحقق من الملكية أو الموظفية
            is_owner = hasattr(obj, 'created_by') and obj.created_by == request.user
            is_staff = request.user.is_staff or request.user.is_superuser
            
            if not (is_owner or is_staff):
                logger.warning(f"Access denied for {request.user.id} on object {type(obj).__name__}#{getattr(obj, 'id', '?')}")
                raise PermissionError()
            
            return view_func(request, *args, **kwargs)
        
        return wrapper
    
    return decorator
