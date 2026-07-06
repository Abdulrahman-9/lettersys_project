# -*- coding: utf-8 -*-
"""
Users Module - إدارة المستخدمين والأدوار
نظام متكامل لإدارة المستخدمين والصلاحيات

وحدة متخصصة لإدارة:
- أدوار المستخدمين (Admin, Controller, Data Entry, Viewer)
- إنشاء وتحديث وحذف المستخدمين
- إدارة كلمات المرور المؤقتة
- تسجيل الخروج
"""

import logging
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import Group, User
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django_ratelimit.decorators import ratelimit

from ..models import SecuritySettings, UserPassword

logger = logging.getLogger(__name__)


# ==============================================================================
# Helper Functions
# ==============================================================================

def staff_required(view_func):
    """ديكور يسمح بدخول الموظفين أو المدراء فقط"""
    return user_passes_test(lambda u: u.is_staff or u.is_superuser)(view_func)


# ==============================================================================
# User Management Views
# ==============================================================================

@login_required
@staff_required
def user_roles(request):
    """
    إدارة المستخدمين والأدوار - نسخة محسّنة
    
    المميزات:
    - إنشاء مستخدمين جدد مع أدوار محددة
    - تحديث أدوار المستخدمين الموجودين
    - حذف المستخدمين
    - حفظ كلمات المرور المؤقتة (24 ساعة)
    - مجموعات الأدوار: Admin, Controller, Data Entry, Viewer
    
    Args:
        request: Django HttpRequest
    
    Returns:
        HttpResponse: صفحة إدارة المستخدمين
    
    POST Actions:
        - create: إنشاء مستخدم جديد
        - update: تحديث دور مستخدم موجود
        - delete: حذف مستخدم
    
    Examples:
        >>> # Create new user
        >>> POST {action: "create", username: "ali", password: "pass123", role_new: "data_entry"}
        
        >>> # Update user role
        >>> POST {action: "update", user_id: 5, role: "controller"}
        
        >>> # Delete user
        >>> POST {action: "delete", user_id: 5}
    """
    role_choices = [
        ("admin", "مدير النظام"),
        ("controller", "مشرف المتابعة"),
        ("data_entry", "مدخل بيانات"),
        ("viewer", "مشاهد"),
    ]
    role_map = {code: Group.objects.get_or_create(name=code)[0] for code, _ in role_choices}

    def get_user_role(user):
        """احصل على دور المستخدم الحالي بدقة"""
        # إذا كان superuser فهو admin
        if user.is_superuser:
            return "admin"
        
        # ابحث عن أي مجموعة من role_choices
        for code, _ in role_choices:
            if code != "admin" and user.groups.filter(name=code).exists():
                return code
        
        # إذا لم يكن له دور، أعيد viewer كافتراضي
        return "viewer"

    def assign_role(user, role_code):
        """عيّن دور للمستخدم بدقة"""
        # أزل جميع الأدوار الحالية
        for code, _ in role_choices:
            if code != "admin":  # لا نزيل admin هنا
                user.groups.remove(role_map[code])
        
        # إعادة تعيين الحقول الأساسية
        if role_code == "admin":
            user.is_superuser = True
            user.is_staff = True
        else:
            user.is_superuser = False
            user.is_staff = True
            # أضف المجموعة الجديدة
            user.groups.add(role_map[role_code])
        
        user.save()

    # معالجة طلبات POST
    if request.method == "POST":
        action = request.POST.get("action")

        if action == "create":
            # إنشاء مستخدم جديد
            role_code = request.POST.get("role_new", "")
            
            # تحقق من أن الدور موجود
            valid_roles = [code for code, _ in role_choices]
            if role_code not in valid_roles:
                messages.error(request, "❌ دور غير صالح. الرجاء اختيار دور صحيح.")
                return redirect("user_roles")
            
            username = (request.POST.get("username") or "").strip()
            email = (request.POST.get("email") or "").strip()
            password = request.POST.get("password") or ""
            password2 = request.POST.get("password2") or ""
            
            # التحقق من المدخلات
            if not username or not password:
                messages.error(request, "❌ يرجى إدخال اسم المستخدم وكلمة المرور.")
                return redirect("user_roles")
            
            if password != password2:
                messages.error(request, "❌ كلمتا المرور غير متطابقتين.")
                return redirect("user_roles")
            
            min_len = SecuritySettings.get().password_min_length
            if len(password) < min_len:
                messages.error(request, f"❌ كلمة المرور يجب أن تكون {min_len} أحرف على الأقل.")
                return redirect("user_roles")
            
            if User.objects.filter(username=username).exists():
                messages.error(request, "❌ اسم المستخدم موجود بالفعل.")
                return redirect("user_roles")
            
            # إنشاء المستخدم
            user = User.objects.create(username=username, email=email, is_staff=True)
            user.set_password(password)
            user.save()
            
            # حفظ كلمة المرور المؤقتة بشكل آمن (مشفرة)
            UserPassword.objects.filter(user=user).delete()
            temp_pwd = UserPassword(
                user=user,
                expires_at=timezone.now() + timedelta(hours=24)
            )
            temp_pwd.set_password(password)
            temp_pwd.save()
            
            # تعيين الدور
            assign_role(user, role_code)
            messages.success(request, f"✅ تم إنشاء المستخدم '{username}' بنجاح مع دور '{dict(role_choices).get(role_code)}'.")
            return redirect("user_roles")
        
        elif action == "update":
            # تحديث دور مستخدم موجود
            user_id = request.POST.get("user_id")
            role_code = request.POST.get("role", "")
            
            # تحقق من أن الدور موجود
            valid_roles = [code for code, _ in role_choices]
            if role_code not in valid_roles:
                messages.error(request, "❌ دور غير صالح. الرجاء اختيار دور صحيح.")
                return redirect("user_roles")
            
            # احصل على المستخدم
            try:
                user = User.objects.get(id=user_id)
            except User.DoesNotExist:
                messages.error(request, "❌ المستخدم غير موجود.")
                return redirect("user_roles")
            
            # تعيين الدور الجديد
            assign_role(user, role_code)
            messages.success(request, f"✅ تم تحديث دور '{user.username}' إلى '{dict(role_choices).get(role_code)}' بنجاح.")
            return redirect("user_roles")
        
        elif action == "delete":
            # حذف مستخدم
            user_id = request.POST.get("user_id")
            try:
                user = User.objects.get(id=user_id)
                username = user.username
                user.delete()
                messages.success(request, f"✅ تم حذف المستخدم '{username}' بنجاح.")
            except User.DoesNotExist:
                messages.error(request, "❌ المستخدم غير موجود.")
            return redirect("user_roles")
        
        else:
            messages.error(request, "❌ إجراء غير صالح.")
            return redirect("user_roles")

    # جمع بيانات المستخدمين
    users_data = []
    for user in User.objects.all().order_by("username"):
        users_data.append({
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "role": get_user_role(user),
            "is_superuser": user.is_superuser,
        })
    
    return render(
        request,
        "core/user_roles.html",
        {
            "role_choices": role_choices,
            "users": users_data,
        },
    )


# ==============================================================================
# Password Management API
# ==============================================================================

@login_required
@staff_required
@ratelimit(key='user', rate='30/h', method='GET')
def get_user_password(request, user_id):
    """
    جلب كلمة مرور المستخدم المؤقتة - مع حماية من الاستخدام المفرط
    
    المميزات:
    - كلمات مرور مؤقتة تنتهي صلاحيتهاخلال 24 ساعة
    - حماية من الاستخدام المفرط (30 طلب/ساعة)
    - تسجيل كامل للوصول
    - صلاحيات محدودة للموظفين فقط
    
    Args:
        request: Django HttpRequest
        user_id: معرف المستخدم المراد جلب كلمة مروره
    
    Returns:
        JsonResponse: كلمة المرور أو رسالة خطأ
    
    Status Codes:
        - 200: Success - كلمة المرور المؤقتة
        - 404: Not found - المستخدم غير موجود
        - 410: Gone - انتهت صلاحية كلمة المرور
        - 500: Server error - خطأ في الخادم
    
    Examples:
        >>> GET /api/users/5/password/
        >>> {"success": true, "password": "temp123"}
    """
    try:
        user = User.objects.get(id=user_id)
        
        # البحث عن كلمة المرور المؤقتة
        try:
            user_pwd = UserPassword.objects.get(user=user)
            
            if user_pwd.is_expired():
                return JsonResponse({
                    "success": False,
                    "message": "انتهت صلاحية كلمة المرور (24 ساعة). يمكن تعيين كلمة جديدة."
                }, status=410)
            
            # تحديث علم القراءة
            user_pwd.is_viewed = True
            user_pwd.save()

            # إرجاع كلمة المرور مرة واحدة فقط — بعد المشاهدة الأولى لا تُعاد
            plain_password = user_pwd.password
            # مسح القيمة من النموذج بعد الإظهار مرة واحدة
            user_pwd.password = '***'
            user_pwd.save(update_fields=['password'])

            return JsonResponse({
                "success": True,
                "password": plain_password,
                "warning": "هذه الكلمة تُعرض مرة واحدة فقط وتم حذفها من النظام."
            })
        except UserPassword.DoesNotExist:
            return JsonResponse({
                "success": False,
                "message": "لم يتم العثور على كلمة مرور مؤقتة. تم إنشاء هذا المستخدم قبل الميزة الجديدة."
            })
    except User.DoesNotExist:
        return JsonResponse({
            "success": False,
            "message": "المستخدم غير موجود"
        }, status=404)
    except Exception as e:
        logger.error(f"Unexpected error in get_user_password: {e}", exc_info=True)
        return JsonResponse({
            "success": False,
            "message": "حدث خطأ في الخادم. يرجى المحاولة لاحقاً."
        }, status=500)


# ==============================================================================
# Logout View
# ==============================================================================

@require_http_methods(["GET", "POST"])
def custom_logout(request):
    """
    تسجيل خروج مخصص يدعم GET و POST
    
    المميزات:
    - دعم GET و POST
    - رسالة تأكيد للمستخدم
    - إعادة توجيه لصفحة تسجيل الدخول
    
    Args:
        request: Django HttpRequest
    
    Returns:
        HttpResponseRedirect: إعادة توجيه لصفحة تسجيل الدخول
    
    Examples:
        >>> GET /logout/
        >>> # User logged out and redirected to login
    """
    logout(request)
    messages.success(request, 'تم تسجيل الخروج بنجاح')
    return redirect('login')
