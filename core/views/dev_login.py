from django.conf import settings
from django.shortcuts import render, redirect
from django.contrib.auth import get_user_model, login
from django.http import HttpResponseNotFound
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods


@require_http_methods(["GET", "POST"])
def dev_login(request):
    """Development-only login helper — **معطَّلٌ خارج DEBUG بردّ 404**.

    أداةُ تطويرٍ محليّة تُودَع مع هياكل الواجهة: تُنشئ `dev_demo` وتُدخِله بلا
    كلمة سرّ. حارسُها الوحيد `settings.DEBUG`، فلا تُفعّل DEBUG على جهازٍ
    يصل إليه أحد. المستخدَمُ المُنشأ بلا كلمة سرٍّ صالحة (`set_unusable_password`)
    فلا يُدخَل إليه من نموذج الدخول العاديّ، لكنّه **staff+superuser** فامسحه
    إن تسرّب إلى قاعدةٍ حقيقيّة.

    - Only enabled when DEBUG=True to avoid accidental exposure in production.
    - Creates a demo user (username: dev_demo) if missing, marks it staff+superuser,
      and logs the requester in without a password.
    - Redirects to `next` or to the dashboard.
    """
    if not settings.DEBUG:
        return HttpResponseNotFound("Not available")

    if request.method == 'POST':
        User = get_user_model()
        username = 'dev_demo'
        user, created = User.objects.get_or_create(
            username=username,
            defaults={'email': 'dev@local', 'is_staff': True, 'is_superuser': True},
        )
        if created:
            # ensure no usable password is set (not needed) but mark staff/super
            user.set_unusable_password()
            user.save()

        # Log in programmatically
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        # **إعادةُ توجيهٍ محروسة**: `next` يصل من الاستعلام إلى حقلٍ مخفيٍّ ثمّ
        # يُعاد إليه — وتمريرُه خامّاً إلى `redirect` إعادةُ توجيهٍ مفتوحة
        # (`?next=https://evil.example`). نفسُ حارس Django في `LoginView`.
        next_url = request.POST.get('next') or '/'
        if not url_has_allowed_host_and_scheme(next_url, {request.get_host()},
                                               require_https=request.is_secure()):
            next_url = '/'
        return redirect(next_url)

    # GET -> show a minimal template with a form
    return render(request, 'core/dev_login.html', {'next': request.GET.get('next', '/')})
