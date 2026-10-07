"""
✅ Custom Authentication Views with Remember Me Support
دعم نظام "تذكرني" في تسجيل الدخول
"""

from django.contrib.auth.views import LoginView
from django.http import HttpResponse, JsonResponse
from django.conf import settings
from django.utils.decorators import method_decorator

from .decorators import rate_limit


@method_decorator(rate_limit('login', max_attempts=10, window_seconds=300, by='ip'), name='post')
class CustomLoginView(LoginView):
    """
    Custom Login View مع دعم Remember Me
    تحويل مدة الـ session حسب الـ checkbox
    """
    
    template_name = 'core/login.html'
    redirect_authenticated_user = True
    
    def form_valid(self, form):
        """
        معالجة النموذج بعد التحقق من صحته
        إذا اختار "تذكرني" = session تدوم 7 أيّام (نصُّ الصفحة يقول المدّةَ نفسَها)
        """
        remember_me = self.request.POST.get('remember_me', False)
        
        if remember_me:
            # تعيين مدة الـ session لـ 7 أيام (604800 ثانية)
            self.request.session.set_expiry(604800)  # 7 days
        else:
            # تنتهي عند إغلاق المتصفح (0 = عند الإغلاق)
            self.request.session.set_expiry(0)
        
        # تحديث ال session cookie
        self.request.session.modified = True
        
        # استدعاء الـ parent method
        response = super().form_valid(form)
        
        return response


# ─── تغييرُ كلمة المرور (تدقيقُ نيلسن F#2) ─────────────────────────────────────
# لم يكن في النظام كلِّه مسارٌ لتغيير كلمة المرور، والصفحةُ تَعِد به. الحدُّ الأدنى من
# SecuritySettings — القاعدةُ نفسُها التي يفرضها إنشاءُ الحساب في users.py.
from django.contrib import messages as _messages
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.views import PasswordChangeView
from django.core.exceptions import ValidationError
from django.urls import reverse_lazy


class LetterSysPasswordChangeForm(PasswordChangeForm):

    def clean_new_password1(self):
        from .models import SecuritySettings

        password = self.cleaned_data.get('new_password1') or ''
        min_len = SecuritySettings.get().password_min_length
        if len(password) < min_len:
            raise ValidationError(f'كلمة المرور يجب أن تكون {min_len} أحرف على الأقل.')
        return password


class LetterSysPasswordChangeView(PasswordChangeView):
    template_name = 'core/password_change.html'
    form_class = LetterSysPasswordChangeForm
    success_url = reverse_lazy('dashboard')

    def get_context_data(self, **kwargs):
        from .models import SecuritySettings

        ctx = super().get_context_data(**kwargs)
        ctx['min_len'] = SecuritySettings.get().password_min_length
        return ctx

    def form_valid(self, form):
        response = super().form_valid(form)   # يحدّث بصمةَ الجلسة فلا يُخرَج المستخدم
        _messages.success(self.request, 'تمّ تغيير كلمة المرور.')
        return response
