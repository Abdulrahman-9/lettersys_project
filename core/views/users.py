# -*- coding: utf-8 -*-
"""حساباتُ المستخدمين — الإنشاءُ والحذفُ وكلمةُ المرور المؤقّتة والخروج.

**ولا دورَ يُسنَد من هنا.** كان في هذا الملفّ نظامُ أدوارٍ **موازٍ** بأسماءِ
مجموعاتٍ إنكليزيّة (``admin`` · ``controller`` · ``data_entry`` · ``viewer``)
يُنشئها ``get_or_create`` عند كلّ زيارة — **ولا تراها بوّابةٌ واحدة**: البوّاباتُ
كلُّها في ``core/scoping.py`` وتسأل مجموعاتِ ``core/roles.py`` العربيّة
(«مشرف المتابعة» · «مسؤول الأرشفة» · «أرشيف الشركة») وملفَّ المستخدم. فكان
المديرُ يختار «متابعة» فيرى رسالةَ نجاحٍ ولا يتغيّر شيءٌ في صلاحيّات الرجل.

والإسنادُ الحقيقيُّ في ``/books/admin/?tab=users`` (القسمُ ورئاستُه وطاولةُ
البريد وطاولةُ الأرشفة)، وكلُّ كتابةٍ فيه تمرّ من ``core/admin_service.py``
فتترك أثراً في سجلّ الحركات. **لا يُعاد بناءُ الإسناد هنا.**
"""

import logging
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django_ratelimit.decorators import ratelimit

from core.roles import ROLE_DEFINITIONS, get_user_role

from ..models import SecuritySettings, UserPassword
from .helpers import staff_required

logger = logging.getLogger(__name__)

#: وجهةُ إسناد الأدوار — تُعرض للمدير بدل حقلِ دورٍ لا أثرَ له.
ROLE_ADMIN_URL = '/books/admin/?tab=users'


# ==============================================================================
# User Management Views
# ==============================================================================

@login_required
@staff_required
def user_roles(request):
    """حساباتُ المستخدمين: إنشاءٌ وحذفٌ وكلمةُ مرورٍ مؤقّتة — **بلا إسنادِ دور**.

    الأفعالُ اثنان: ``create`` و``delete``. وكان ثالثٌ (``update``) يُبدّل
    «الدور» في مجموعاتٍ إنكليزيّةٍ لا تقرؤها بوّابة، فأُزيل مع نظامه كلِّه؛
    والدورُ الظاهرُ في الجدول يُقرأ الآن من ``core.roles.get_user_role`` —
    المصدرِ الذي تسأله البوّابات — عرضاً لا تحريراً.
    """
    if request.method == "POST":
        action = request.POST.get("action")

        if action == "create":
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
            # بلا ملفٍّ يسقط الموظّف الجديد إلى «كتبي أنا» بدل «كتب قسمي».
            from core.scoping import ensure_profile
            ensure_profile(user)
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

            # الحسابُ يُولد بلا قسمٍ ولا دور — والرسالةُ تقول أين يُسندان، وإلّا
            # ظنَّ المديرُ أنّ الحساب جاهزٌ فسقط صاحبُه إلى «قارئ فقط» صامتاً.
            messages.success(
                request,
                f"✅ أُنشئ الحساب «{username}». أسنِد قسمَه ودورَه من لوحة الإدارة "
                f"({ROLE_ADMIN_URL}) — فبلا ذلك يبقى قارئاً فقط.")
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

    # جمع بيانات المستخدمين — والدورُ **تسميةٌ مقروءةٌ من المصدر الوحيد**
    users_data = []
    for user in User.objects.all().order_by("username").prefetch_related("groups"):
        role = get_user_role(user)
        users_data.append({
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "role": role,
            "role_label": ROLE_DEFINITIONS.get(role, {}).get("label", "قارئ فقط"),
            "is_superuser": user.is_superuser,
        })

    return render(
        request,
        "core/user_roles.html",
        {
            "users": users_data,
            "role_definitions": ROLE_DEFINITIONS,
            "role_admin_url": ROLE_ADMIN_URL,
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
