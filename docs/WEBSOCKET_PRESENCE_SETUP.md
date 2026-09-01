# تفعيل الحضور اللحظيّ عبر WebSocket (Channels) — اختياريّ

نظام الحجز الذكي **يعمل كاملاً الآن** بدون WebSocket عبر:
- نبضة heartbeat كل 25ث (HTTP) من الواجهة.
- مهمة دورية `cleanup_expired_reservations` (تحوّل النبضة الميتة إلى cooldown).
- انتهاء الصلاحية + إعادة التدوير في `reservation_service`.

الكشف عندها خلال ~1-2 دقيقة. **WebSocket يُقلّص الكشف إلى ثوانٍ** عند إغلاق التبويب/انقطاع
الشبكة — ميزة تسريع لا شرطٌ للصحّة. الملفّات جاهزة ودورمانت (`core/consumers.py`،
`core/routing.py`). لتفعيلها **بشكل متعمّد (لا أثناء جلسة عمل حيّة)**:

## 1) التثبيت
```powershell
pip install "channels[daphne]" channels-redis
```

## 2) الإعدادات — `lettersys/settings.py`
```python
INSTALLED_APPS = [
    'daphne',            # قبل django.contrib.staticfiles ليرقّي runserver لـASGI
    ...
    'channels',
    ...
]
ASGI_APPLICATION = 'lettersys.asgi.application'

# التطوير (عملية واحدة): طبقة في الذاكرة — بلا Redis
CHANNEL_LAYERS = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}
# الإنتاج (عمّال متعددون): Redis
# CHANNEL_LAYERS = {'default': {
#     'BACKEND': 'channels_redis.core.RedisChannelLayer',
#     'CONFIG': {'hosts': [('127.0.0.1', 6379)]},
# }}
```

## 3) توصيل الـASGI — `lettersys/asgi.py`
```python
import os
from django.core.asgi import get_asgi_application
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lettersys.settings')
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from core.routing import websocket_urlpatterns

application = ProtocolTypeRouter({
    'http': django_asgi_app,
    'websocket': AuthMiddlewareStack(URLRouter(websocket_urlpatterns)),
})
```

## 4) تفعيل عميل الواجهة
أضِف السمة إلى حاوية صفحة الإدخال في `templates/core/extraction_smart_desktop.html`:
```html
<div class="extraction-container" data-ws-presence="1" ...>
```
(بدونها يبقى العميل مُطفأً ويعتمد على heartbeat فقط.)

## 5) التشغيل
- التطوير: `python manage.py runserver` (سيرقّيه daphne لـASGI تلقائياً).
- الإنتاج: `daphne lettersys.asgi:application` (أو uvicorn) + Redis channel-layer.

## التحقّق
افتح صفحة الإدخال في تبويبين لمستخدمين، أغلق تبويباً فجأة → خلال ثوانٍ يتحوّل رقمه إلى
cooldown (يبقى له 15د)، وبعدها يُدوَّر لغيره ببانر «رقم مُدوّر» برتقاليّ.

**ملاحظة جهاز 8GB:** InMemoryChannelLayer كافٍ للتطوير وخفيف؛ لا تُشغّل Redis إلا للإنتاج
متعدّد العمّال.
