# -*- coding: utf-8 -*-
"""حساباتُ المستخدمين — الإنشاءُ والحذفُ وإعادةُ تعيين كلمة المرور والخروج.

**والصفحةُ لمدير النظام وحدَه** (``can_manage_accounts`` — قرارُ المالك 2026‑10‑07):
بوّابةُ لوحة الإدارة نفسُها، فمَن يُنشئ الحسابَ هو مَن يُسند قسمَه ودورَه.

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
from django.db import transaction
from django.db.models import ProtectedError
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from core.logging_models import UserActivityLog
from core.roles import ROLE_DEFINITIONS, get_user_role

from ..models import SecuritySettings, UserPassword
from .helpers import privileged_required

logger = logging.getLogger(__name__)

#: وجهةُ إسناد الأدوار — تُعرض للمدير بدل حقلِ دورٍ لا أثرَ له.
ROLE_ADMIN_URL = '/books/admin/?tab=users'

#: فعلُ «إعادة تعيين كلمة المرور» في سجلّ الحركات. رمزٌ بلا تسميةٍ في
#: ``UserActivityLog.ACTION_CHOICES`` بعد — كأخيه ``DELETE_GROUP``: التسميةُ
#: تغييرُ اختياراتٍ يستتبع هجرةً، وهذه الدفعةُ بلا هجرة.
PASSWORD_RESET_ACTION = 'PASSWORD_RESET'


# ==============================================================================
# User Management Views
# ==============================================================================

@login_required
@privileged_required
def user_roles(request):
    """حساباتُ المستخدمين: إنشاءٌ وحذفٌ وإعادةُ تعيين كلمة المرور — **بلا إسنادِ دور**.

    الأفعالُ ثلاثة: ``create`` و``delete`` و``reset_password``. وكان فعلٌ اسمُه
    ``update`` يُبدّل «الدور» في مجموعاتٍ إنكليزيّةٍ لا تقرؤها بوّابة، فأُزيل مع
    نظامه كلِّه؛ والدورُ الظاهرُ في الجدول يُقرأ الآن من ``core.roles.get_user_role``
    — المصدرِ الذي تسأله البوّابات — عرضاً لا تحريراً.
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

            problem = _password_problem(password, password2)
            if problem:
                messages.error(request, problem)
                return redirect("user_roles")

            # مُدقِّقُ Django نفسُه (حروفٌ — والعربيّةُ منها — وأرقامٌ و@ . + - _): `create()` لا يستدعيه،
            # فكان يمرّ اسمٌ بمسافةٍ أو علامةِ اقتباسٍ أو وسم — يكسر الدخولَ ويصير نصّاً في صفحاتٍ أخرى
            if len(username) > 150 or not _username_ok(username):
                messages.error(request, "❌ اسمُ المستخدم حروفٌ وأرقامٌ و@ . + - _ فقط، بلا مسافات (150 حرفاً على الأكثر).")
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
            _store_temp_password(user, password)

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

        elif action == "reset_password":
            return _reset_password(request)

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
            # حسابُك أنت يُغيَّر من صفحتك بكلمتك الحاليّة — فصفُّه يدلّ عليها لا على نموذج الإعادة
            "is_self": user.pk == request.user.pk,
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


def _username_ok(username):
    """مُدقِّقُ اسم المستخدم في نموذج Django (``UnicodeUsernameValidator``)."""
    from django.core.exceptions import ValidationError

    try:
        User.username_validator(username)
    except ValidationError:
        return False
    return True


def _password_problem(password, password2):
    """سببُ رفض كلمة المرور بلغة الكاتب، أو ``None`` — **قاعدةٌ واحدةٌ للإنشاء
    وإعادة التعيين**: الحدُّ الأدنى من ``SecuritySettings`` (وقد يُضبط صفراً، فالفراغُ
    يُرفض صراحةً لا بالطول)."""
    if not password:
        return "❌ يرجى إدخال كلمة المرور."
    if password != password2:
        return "❌ كلمتا المرور غير متطابقتين."
    min_len = SecuritySettings.get().password_min_length
    if len(password) < min_len:
        return f"❌ كلمة المرور يجب أن تكون {min_len} أحرف على الأقل."
    return None


def _store_temp_password(user, password):
    """كلمةُ المرور المؤقّتة: **مُجزَّأةً** وصالحةً 24 ساعة، وصفٌّ واحدٌ لكلّ حسابٍ
    يُستبدَل ولا يُراكَم — الإنشاءُ وإعادةُ التعيين يمرّان من هنا معاً."""
    UserPassword.objects.filter(user=user).delete()
    temp_pwd = UserPassword(user=user, expires_at=timezone.now() + timedelta(hours=24))
    temp_pwd.set_password(password)
    temp_pwd.save()


def _reset_password(request):
    """كلمةُ مرورٍ جديدةٌ لحسابٍ **غيرِ حسابك** (قرارُ المالك 2026‑10‑07، البند 4).

    * المديرُ كتبها بيده، فلا تُعرض بعد الحفظ في رسالةٍ ولا صفحة — الرسائلُ تُحفظ
      في الـcookie عند المتصفّح، ولا تحمل كلمةَ مرور.
    * ``set_password`` يُبدّل بصمةَ الجلسة (``get_session_auth_hash``) فتسقط جلساتُ
      صاحب الحساب المفتوحة عند طلبها التالي — والمقصودُ ذلك: حسابٌ يُعاد تعيينُه
      يُغلق على كلّ جهاز.
    * **حسابُك أنت** يُغيَّر من صفحة «تغيير كلمة المرور» بكلمتك الحاليّة: إعادتُه من
      هنا تُسقط جلستَك نفسَها، ولا تسأل عمّا يُثبت أنّك صاحبُه.
    * والواقعةُ صفٌّ في سجلّ الحركات **باسم الحساب وحدَه** — والكتابتان في معاملةٍ
      واحدة: لا إعادةَ تعيينٍ بلا أثرها.
    """
    try:
        target = User.objects.get(pk=request.POST.get("user_id"))
    except (User.DoesNotExist, ValueError):
        messages.error(request, "❌ المستخدم غير موجود.")
        return redirect("user_roles")

    if target.pk == request.user.pk:
        messages.info(request, "كلمةُ مرورك أنت تُغيَّر من هنا — بكلمتك الحاليّة.")
        return redirect("password_change")

    password = request.POST.get("password") or ""
    problem = _password_problem(password, request.POST.get("password2") or "")
    if problem:
        messages.error(request, problem)
        return redirect("user_roles")

    actor = request.user
    with transaction.atomic():
        target.set_password(password)
        target.save(update_fields=["password"])
        _store_temp_password(target, password)
        UserActivityLog.objects.create(
            user=actor, action=PASSWORD_RESET_ACTION,
            username_snapshot=actor.get_username()[:150],
            department=getattr(getattr(actor, "profile", None), "department", None),
            metadata={"user": target.get_username()},
        )

    messages.success(
        request,
        f"✅ تغيّرت كلمةُ مرور «{target.get_username()}». أبلِغه بها بنفسك — "
        f"وسيُطلب منه الدخولُ بها من جديد على كلّ جهازٍ كان داخلاً منه.")
    return redirect("user_roles")


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
