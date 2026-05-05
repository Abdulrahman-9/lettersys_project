# -*- coding: utf-8 -*-
"""
email_api.py  ← SHIM
====================
الكود انتقل إلى: core.messaging.api.email_endpoints

هذا الملف يعيد تصدير الدوال فقط للحفاظ على التوافق مع الاستيرادات القديمة.
استخدم الحزمة الجديدة مباشرةً في الكود الجديد:

    from core.messaging.api.email_endpoints import send_email, email_settings
"""

from core.messaging.api.email_endpoints import (  # noqa: F401 — re-export
    send_email,
    book_email_logs,
    test_smtp,
    email_settings,
    entity_email_info,
    update_entity_email,
)

__all__ = [
    'send_email',
    'book_email_logs',
    'test_smtp',
    'email_settings',
    'entity_email_info',
    'update_entity_email',
]
