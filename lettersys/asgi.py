import os
# حدّ خيوط OpenBLAS/OMP قبل استيراد numpy/scipy/sklearn — يمنع OOM على 8GB.
os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
os.environ.setdefault('OMP_NUM_THREADS', '1')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lettersys.settings')

from django.core.asgi import get_asgi_application

# تُهيَّأ تطبيقة Django (HTTP) أولاً قبل استيراد أي شيء يمسّ النماذج.
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from core.routing import websocket_urlpatterns
from core.ws_security import SameOriginWebsocketValidator

# حارس الأصل إلزامي: بدونه يفتح أي موقع خارجي WebSocket إلى
# /ws/reservation/presence/ بكوكي جلسة الموظّف، وقطعُه يُدخل حجوزات أرقامه في
# فترة السماح. لا نستعمل AllowedHostsOriginValidator لأن ALLOWED_HOSTS هنا '*'
# (شبكة محلية بعناوين متغيّرة) فيقبل كل شيء — انظر core/ws_security.py.
application = ProtocolTypeRouter({
    'http': django_asgi_app,
    'websocket': SameOriginWebsocketValidator(
        AuthMiddlewareStack(URLRouter(websocket_urlpatterns))
    ),
})
