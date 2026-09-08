# -*- coding: utf-8 -*-
"""مسارات WebSocket — موصولةٌ فعلاً من ``lettersys/asgi.py`` (لا دورمانت)."""
from django.urls import re_path

from . import consumers

websocket_urlpatterns = [
    re_path(r'^ws/reservation/presence/$', consumers.ReservationPresenceConsumer.as_asgi()),
]
