# -*- coding: utf-8 -*-
"""
imap_service.py  ← SHIM
========================
الكود انتقل إلى: core.messaging.engines.imap (IMAPEngine)

هذا الملف يعيد تصدير الدوال فقط للحفاظ على التوافق مع الاستيرادات القديمة.
استخدم الحزمة الجديدة مباشرةً في الكود الجديد:

    from core.messaging.engines.imap import IMAPEngine
    engine = IMAPEngine(cfg)
    engine.sync_inbox()
"""

from core.messaging.engines.imap import (  # noqa: F401 — re-export
    IMAPEngine,
    sync_inbox,
    test_imap_connection,
    mark_as_read_on_server,
)

__all__ = [
    'IMAPEngine',
    'sync_inbox',
    'test_imap_connection',
    'mark_as_read_on_server',
]
