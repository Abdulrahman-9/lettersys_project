# -*- coding: utf-8 -*-
"""
mail_api.py  ← SHIM
====================
الكود انتقل إلى: core.messaging.api.mail_endpoints

هذا الملف يعيد تصدير الدوال فقط للحفاظ على التوافق مع الاستيرادات القديمة.
استخدم الحزمة الجديدة مباشرةً في الكود الجديد:

    from core.messaging.api.mail_endpoints import api_compose, api_inbox_sync
"""

from core.messaging.api.mail_endpoints import (  # noqa: F401 — re-export
    api_compose,
    api_inbox_sync,
    api_mark_read,
    api_thread_detail,
    api_thread_status,
    api_bulk_send,
    api_template_preview,
    api_test_smtp,
    api_test_imap,
    api_mail_stats,
)

__all__ = [
    'api_compose',
    'api_inbox_sync',
    'api_mark_read',
    'api_thread_detail',
    'api_thread_status',
    'api_bulk_send',
    'api_template_preview',
    'api_test_smtp',
    'api_test_imap',
    'api_mail_stats',
]
