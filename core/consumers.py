# -*- coding: utf-8 -*-
"""
WebSocket حضور الحجز — كشف لحظيّ للانقطاع القسريّ (إغلاق تبويب/شبكة/جهاز).

**موصولٌ فعلاً** منذ ضبط `lettersys/asgi.py` (daphne + `SameOriginWebsocketValidator`).
التوثيق السابق كان يقول «دورمانت افتراضياً» وهو انجرافٌ عن الكود — والفارق مهمّ:
من يقرأ «دورمانت» يظنّ المسار غير معرَّضٍ للشبكة.
(انظر WEBSOCKET_PRESENCE_SETUP.md). النظام صحيحٌ تماماً بدونه عبر heartbeat + المهمة
الدورية (تدهور رشيق) — الـWS يُسرّع كشف الانقطاع من ~دقيقة إلى ثوانٍ فقط.

عند disconnect → تحويل حجوزات المستخدم النشطة إلى cooldown فوراً (فترة سماح لصاحبه
ثم تُعاد تدويرها) — يطابق منطق reservation_service المستخدَم في كل المسارات.
"""
import json

from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async


class ReservationPresenceConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope.get('user')
        if not user or not user.is_authenticated:
            await self.close()
            return
        self.user = user
        await self.accept()
        await self._touch()

    async def receive(self, text_data=None, bytes_data=None):
        # أيّ رسالة = نبضة حضور (تُبقي الحجز حيّاً)
        await self._touch()
        await self.send(text_data=json.dumps({'type': 'pong'}))

    async def disconnect(self, code):
        # انقطاع قسريّ → cooldown فوريّ (لا يُسقط الرقم؛ يبقى لصاحبه 15د ثم يُدوَّر)
        if getattr(self, 'user', None):
            await self._cooldown()

    @database_sync_to_async
    def _touch(self):
        from django.utils import timezone
        from .models import BookNumberReservation as R
        R.objects.filter(
            user=self.user,
            status__in=[R.STATUS_ACTIVE, R.STATUS_REACTIVATED],
            book__isnull=True,
        ).update(last_heartbeat=timezone.now())

    @database_sync_to_async
    def _cooldown(self):
        from .reservation_service import force_cooldown_for_user
        try:
            force_cooldown_for_user(self.user)
        except Exception:
            pass
