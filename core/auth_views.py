"""
✅ Custom Authentication Views with Remember Me Support
دعم نظام "تذكرني" في تسجيل الدخول
"""

from django.contrib.auth.views import LoginView
from django.urls import reverse_lazy
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
        إذا اختار "تذكرني" = session تدوم 30 يوم
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
