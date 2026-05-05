"""
core.messaging.api.urls
========================
URL routing for all messaging REST API endpoints.

Mounts under:
  /books/api/email/*   — from email_endpoints (via core/urls.py include)
  /mail/api/*          — from mail_endpoints  (via lettersys/urls.py include)
"""

from django.urls import path
from . import email_endpoints, mail_endpoints

# ────────────────────────────────────────────────────
# Book/entity-scoped email endpoints
# Prefix: books/api/email/
# ────────────────────────────────────────────────────
email_urlpatterns = [
    path('send/',                email_endpoints.send_email,          name='msg_email_send'),
    path('logs/<int:book_id>/',  email_endpoints.book_email_logs,     name='msg_email_logs'),
    path('test-smtp/',           email_endpoints.test_smtp,           name='msg_test_smtp'),
    path('settings/',            email_endpoints.email_settings,      name='msg_email_settings'),
    path('entity/<int:entity_id>/',        email_endpoints.entity_email_info,    name='msg_entity_email_info'),
    path('entity/<int:entity_id>/update/', email_endpoints.update_entity_email,  name='msg_entity_email_update'),
]

# ────────────────────────────────────────────────────
# Thread-based mail endpoints
# Prefix: mail/api/
# ────────────────────────────────────────────────────
mail_urlpatterns = [
    path('compose/',                      mail_endpoints.api_compose,          name='msg_compose'),
    path('inbox/sync/',                   mail_endpoints.api_inbox_sync,       name='msg_inbox_sync'),
    path('inbox/<int:pk>/read/',          mail_endpoints.api_mark_read,        name='msg_mark_read'),
    path('thread/<int:pk>/',              mail_endpoints.api_thread_detail,    name='msg_thread_detail'),
    path('thread/<int:pk>/status/',       mail_endpoints.api_thread_status,    name='msg_thread_status'),
    path('bulk-send/',                    mail_endpoints.api_bulk_send,        name='msg_bulk_send'),
    path('template/<int:pk>/preview/',    mail_endpoints.api_template_preview, name='msg_template_preview'),
    path('settings/test-smtp/',           mail_endpoints.api_test_smtp,        name='msg_mail_test_smtp'),
    path('settings/test-imap/',           mail_endpoints.api_test_imap,        name='msg_mail_test_imap'),
    path('stats/',                        mail_endpoints.api_mail_stats,       name='msg_mail_stats'),
]
