# -*- coding: utf-8 -*-
"""
core.netaddr
============
عناوينُ الشبكة لقراراتِ الوصول — **مصدرٌ وحيد**.

قاعدةُ الموضعين: ``REMOTE_ADDR`` وحدَه ولا ``X-Forwarded-For`` أبداً — قرارُ وصولٍ
أمنيٌّ لا يُبنى على ترويسةٍ يتحكّم بها العميل.
"""
import ipaddress

from django.conf import settings


def _remote_addr(request):
    """عنوانُ الطالب كعنوانٍ مُحلَّل، أو ``None`` إن لم يكن عنواناً صالحاً."""
    raw = (request.META.get('REMOTE_ADDR') or '').strip()
    try:
        return ipaddress.ip_address(raw)
    except ValueError:
        return None


def is_lan_peer(request) -> bool:
    """أهذا الطلب من جارٍ على شبكة خاصة (أو من الجهاز نفسه)؟

    **ليس** حارساً لعملٍ خطير: كلُّ كاتبةٍ على الشبكة تُرضي هذا الشرط. للأعمال التي
    لا تصحّ إلّا على جهاز الخادم استخدم ``request_is_loopback``.
    """
    addr = _remote_addr(request)
    return addr is not None and (addr.is_private or addr.is_loopback)


def request_is_loopback(request) -> bool:
    """أجاء هذا الطلبُ من جهاز الخادم نفسِه فعلاً؟

    خلف بروكسيٍّ عاكس (``SECURE_PROXY_SSL_HEADER`` مضبوط، أي مرحلةُ Caddy) يكون
    ``REMOTE_ADDR`` عنوانَ البروكسي، فـ«الحلقةُ المحلّيّة» لا تُثبت شيئاً عن الطالب
    ⟵ نرفض للجميع، ولو كان الكونسول. في تلك المرحلة يُشغَّل الوكيلُ من اختصار بدء
    التشغيل لا من الويب.
    """
    if getattr(settings, 'SECURE_PROXY_SSL_HEADER', None):
        return False
    addr = _remote_addr(request)
    return addr is not None and addr.is_loopback
