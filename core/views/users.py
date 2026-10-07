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
from django.db.models import ProtectedError
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

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
            # **بلا `is_staff`** (قرارُ المالك D‑1): هي بوّابةُ صفحات الإدارة
            # (`staff_required`: النسخُ والاستعادةُ والإعداداتُ وإدارةُ الجهات)
            # لا دورُ عمل — تُمنح عمداً من /admin/ لمن يحتاجها، لا لكلّ كاتبٍ جديد.
            user = User.objects.create(username=username, email=email)
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
            # لا حذفَ للذات ولا لآخر مدير (كان ممكناً بلا سؤال — تدقيقُ نيلسن E#3)،
            # ولا لمن أنشأ كتباً: الكتابُ يحمي مُنشئَه (PROTECT) فكان الحذفُ 500.
            user_id = request.POST.get("user_id")
            try:
                user = User.objects.get(id=user_id)
            except (User.DoesNotExist, ValueError):
                messages.error(request, "❌ المستخدم غير موجود.")
                return redirect("user_roles")
            username = user.username
            if user == request.user:
                messages.error(request, "❌ لا يمكنك حذفُ حسابك الذي تعمل به.")
            elif user.is_superuser and not User.objects.filter(
                    is_superuser=True, is_active=True).exclude(pk=user.pk).exists():
                messages.error(request, f"❌ «{username}» آخرُ مديرٍ نشط — أنشئ مديراً آخر قبل حذفه.")
            else:
                try:
                    user.delete()
                except ProtectedError:
                    messages.error(
                        request,
                        f"❌ لا يُحذف «{username}» لأنّه أنشأ كتباً — عطِّل حسابه بدل حذفه: "
                        f"أزِل علامة «نشط» في /admin/auth/user/{user.pk}/change/")
                else:
                    messages.success(request, f"✅ تم حذف المستخدم '{username}' بنجاح.")
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
            # الحدُّ الأدنى الذي يفرضه الخادم — كانت الواجهةُ تفرض 4 (تدقيقُ نيلسن F#7)
            "min_len": SecuritySettings.get().password_min_length,
        },
    )


# ==============================================================================
# Logout View
# ==============================================================================

@require_http_methods(["POST"])
def custom_logout(request):
    """
    تسجيل خروج مخصص — POST وحدَه (تدقيقُ نيلسن F، S3): الخروجُ بـGET بلا CSRF كان
    يتيح لرابطِ صورةٍ في أيّ صفحةٍ أن يُخرج المستخدم. زرُّ الشريط نموذجُ POST أصلاً.
    
    المميزات:
    - POST فقط (GET ⟵ 405)
    - رسالة تأكيد للمستخدم
    - إعادة توجيه لصفحة تسجيل الدخول
    
    Args:
        request: Django HttpRequest
    
    Returns:
        HttpResponseRedirect: إعادة توجيه لصفحة تسجيل الدخول
    
    Examples:
        >>> POST /logout/
        >>> # User logged out and redirected to login
    """
    logout(request)
    messages.success(request, 'تم تسجيل الخروج بنجاح')
    return redirect('login')
