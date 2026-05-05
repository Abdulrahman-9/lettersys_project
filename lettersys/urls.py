from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from core import views as core_views
from core.auth_views import CustomLoginView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('login/', CustomLoginView.as_view(template_name='core/login.html'), name='login'),  # ✅ Custom Login with Remember Me
    path('logout/', core_views.custom_logout, name='logout'),
    path('', core_views.dashboard, name='dashboard'),
    path('books/', include('core.urls')),
    # Service Worker at root scope for PWA - direct serve without redirect
    path('service-worker.js', core_views.serve_service_worker, name='service_worker_root'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
