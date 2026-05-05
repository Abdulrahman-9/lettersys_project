# -*- coding: utf-8 -*-
"""
mail_views.py  ← SHIM
========================
الكود انتقل إلى: core.messaging.views.ui

هذا الملف يعيد تصدير الدوال فقط للحفاظ على التوافق مع الاستيرادات القديمة.
استخدم الحزمة الجديدة مباشرةً في الكود الجديد:

    from core.messaging.views.ui import mail_hub, mail_inbox
"""

from core.messaging.views.ui import (  # noqa: F401 — re-export
    mail_hub,
    mail_sent,
    mail_inbox,
    mail_compose,
    mail_thread,
    mail_settings,
    mail_templates,
    mail_template_edit,
    mail_template_delete,
)

__all__ = [
    'mail_hub',
    'mail_sent',
    'mail_inbox',
    'mail_compose',
    'mail_thread',
    'mail_settings',
    'mail_templates',
    'mail_template_edit',
    'mail_template_delete',
]
