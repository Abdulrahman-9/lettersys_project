# -*- coding: utf-8 -*-
"""
حارس أصل اتصالات WebSocket.

لماذا لا يكفي `AllowedHostsOriginValidator` هنا: النظام يعمل عبر شبكة محلية بعناوين
IP متغيّرة، فـ`ALLOWED_HOSTS` مضبوط على `*` — وعندها يقبل ذلك الحارس **كل** أصل،
فيصير بلا أثر.

المتصفّح لا يطبّق سياسة same-origin على WebSocket: أي صفحة على الإنترنت تستطيع فتح
`ws://<خادمك>/ws/reservation/presence/` وسيُرسل المتصفّح كوكي جلسة الموظّف معها.
قطعُ ذلك الاتصال يُدخل حجوزات أرقامه في فترة السماح — تعطيلٌ عن بعد بلا مصادقة.

الحلّ: نقبل الأصل إن طابق **المضيف الذي يخدم الصفحة نفسها** (فتعمل الشبكة المحلية
بأي عنوان دون إعداد)، أو إن كان مضيفاً مذكوراً صراحةً في `ALLOWED_HOSTS`
(حين لا تكون `*`). ما عدا ذلك يُرفض.
"""
from urllib.parse import urlparse

from django.conf import settings


def _header(scope, name):
    want = name.lower().encode()
    for key, value in scope.get('headers') or ():
        if key.lower() == want:
            return value.decode('latin1')
    return ''


def _host_only(value):
    """ينزع المنفذ من 'host:port' (ويتعامل مع IPv6 بين قوسين)."""
    value = (value or '').strip().lower()
    if value.startswith('['):                       # [::1]:8000
        end = value.find(']')
        return value[:end + 1] if end != -1 else value
    return value.split(':', 1)[0]


class SameOriginWebsocketValidator:
    """يمرّر الاتصال إلى `app` إن كان أصله مقبولاً، وإلا يُغلقه برمز 403."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get('type') == 'websocket' and not self._allowed(scope):
            await send({'type': 'websocket.close', 'code': 4003})
            return
        return await self.app(scope, receive, send)

    @staticmethod
    def _allowed(scope):
        origin = _header(scope, 'origin')
        if not origin:
            # المتصفّحات ترسل Origin دائماً مع WebSocket؛ غيابه يعني عميلاً غير متصفّح.
            # لا عميل كهذا في النظام، والرفض هو الجانب الآمن.
            return False

        origin_host = _host_only(urlparse(origin).netloc or origin)
        if not origin_host:
            return False

        # نفس المضيف الذي يخدم الصفحة — يغطّي localhost وكل عناوين الشبكة المحلية
        if origin_host == _host_only(_header(scope, 'host')):
            return True

        allowed = {_host_only(h) for h in getattr(settings, 'ALLOWED_HOSTS', []) if h != '*'}
        return origin_host in allowed
