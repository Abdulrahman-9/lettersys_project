# -*- coding: utf-8 -*-
"""
email_service.py  ← SHIM
========================
الكود انتقل إلى: core.messaging.engines.smtp (SMTPEngine)

هذا الملف يعيد تصدير الدوال فقط للحفاظ على التوافق مع الاستيرادات القديمة.
استخدم الحزمة الجديدة مباشرةً في الكود الجديد:

    from core.messaging.engines.smtp import SMTPEngine
    engine = SMTPEngine()
    engine.send_book_saved_notification(book, sent_by=user)
"""

from core.messaging.engines.smtp import (  # noqa: F401 — re-export
    SMTPEngine,
    send_book_notification,
    send_book_saved_notification,
    send_manual_email,
    test_smtp_connection,
)

__all__ = [
    'SMTPEngine',
    'send_book_notification',
    'send_book_saved_notification',
    'send_manual_email',
    'test_smtp_connection',
]
