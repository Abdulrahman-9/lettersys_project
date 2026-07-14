"""
core.messaging.api.urls
========================
URL routing for all messaging REST API endpoints.

Mounts under:
  /books/api/email/*   — email_urlpatterns (via core/urls.py include)
  /books/mail/api/*    — mail_urlpatterns  (via core/urls.py include)
"""

from django.urls import path
from . import email_endpoints, mail_endpoints

# ────────────────────────────────────────────────────
# Book/entity-scoped email endpoints
# Prefix: books/api/email/
# ────────────────────────────────────────────────────
email_urlpatterns = [
    path('send/',                email_endpoints.send_email,          name='email-send'),
    path('logs/<int:book_id>/',  email_endpoints.book_email_logs,     name='email-logs'),
    path('test-smtp/',           email_endpoints.test_smtp,           name='email-test-smtp'),
    path('settings/',            email_endpoints.email_settings,      name='email-settings'),
    path('entity/<int:entity_id>/',        email_endpoints.entity_email_info,    name='entity-email-info'),
    path('entity/<int:entity_id>/update/', email_endpoints.update_entity_email,  name='entity-email-update'),
    # إرسال الكتاب بمرفقاته إلى جهته المعنيّة (معاينة ثم إرسال)
    path('book/<int:book_id>/preview/',    email_endpoints.book_email_preview,   name='book-email-preview'),
    path('book/<int:book_id>/send/',       email_endpoints.send_book_to_entity,  name='book-email-send'),
]

# ────────────────────────────────────────────────────
# Thread-based mail endpoints
# Prefix: mail/api/
# ────────────────────────────────────────────────────
mail_urlpatterns = [
    path('compose/',                      mail_endpoints.api_compose,          name='mail-api-compose'),
    path('inbox/sync/',                   mail_endpoints.api_inbox_sync,       name='mail-api-inbox-sync'),
    path('inbox/<int:pk>/read/',          mail_endpoints.api_mark_read,        name='mail-api-mark-read'),
    path('thread/<int:pk>/',              mail_endpoints.api_thread_detail,    name='mail-api-thread'),
    path('thread/<int:pk>/status/',       mail_endpoints.api_thread_status,    name='mail-api-thread-status'),
    path('bulk-send/',                    mail_endpoints.api_bulk_send,        name='mail-api-bulk-send'),
    path('template/<int:pk>/preview/',    mail_endpoints.api_template_preview, name='mail-api-template-preview'),
    path('settings/test-smtp/',           mail_endpoints.api_test_smtp,        name='mail-api-test-smtp'),
    path('settings/test-imap/',           mail_endpoints.api_test_imap,        name='mail-api-test-imap'),
    path('stats/',                        mail_endpoints.api_mail_stats,       name='mail-api-stats'),
]
