# -*- coding: utf-8 -*-
"""مسارات WebSocket — تُوصَل من lettersys/asgi.py عند تفعيل channels (دورمانت افتراضياً)."""
from django.urls import re_path

from . import consumers

websocket_urlpatterns = [
    re_path(r'^ws/reservation/presence/$', consumers.ReservationPresenceConsumer.as_asgi()),
]
