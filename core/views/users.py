# -*- coding: utf-8 -*-
"""تسجيلُ الخروج.

**وإدارةُ الحسابات ليست هنا**: بابُها الوحيد ``/books/admin/?tab=users``، وكلُّ كتابةٍ
فيه تمرّ من ``core/admin_service.py`` فتترك أثراً في سجلّ الحركات. كانت في هذا الملفّ
صفحةٌ ثانية تُنشئ حساباتٍ بلا أثرٍ ولا تدويرِ كلمة مرور — لا يُعاد بناؤها.
"""

from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.views.decorators.http import require_http_methods


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
