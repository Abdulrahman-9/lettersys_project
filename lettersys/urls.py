from django.contrib import admin
from django.urls import path, include, re_path
from core import views as core_views
from core.auth_views import CustomLoginView
from core.views.dev_login import dev_login
from core.views.attachments import serve_media, serve_shared_attachment

urlpatterns = [
    path('admin/', admin.site.urls),
    path('login/', CustomLoginView.as_view(template_name='core/login.html'), name='login'),  # ✅ Custom Login with Remember Me
    path('logout/', core_views.custom_logout, name='logout'),
    path('', core_views.dashboard, name='dashboard'),
    path('dev-login/', dev_login, name='dev_login'),
    path('books/', include('core.urls')),
    # Service Worker at root scope for PWA - direct serve without redirect
    path('service-worker.js', core_views.serve_service_worker, name='service_worker_root'),
    # خدمة MEDIA خلف مصادقة + فحص ملكية (يحلّ محلّ static(MEDIA_URL) المفتوح) — C1
    re_path(r'^media/(?P<path>.*)$', serve_media, name='media'),
    # المسار الوحيد المفتوح على المرفقات: رابط موقّع محدود المدة يفتح مرفقاً واحداً
    # بعينه — لأن الجهة الخارجية التي نراسلها لا حساب لها، والملفات الكبيرة لا
    # تُرفَق بالبريد. الرمز موقّع بـSECRET_KEY فلا يُزوَّر ولا يُخمَّن.
    path('share/attachment/<str:token>/', serve_shared_attachment, name='attachment_share'),
]
