from django.urls import path, include
from django.views.generic import RedirectView
from . import views
from . import logging_views
from . import extraction_views
from . import extraction_ui_views
from .extraction.api import endpoints as ext_api_ep
from .extraction.views import ui as ext_ui
from . import api as api_views
from . import reservation_api
from . import network_views
from .messaging.api import email_endpoints as msg_email_ep
from .messaging.api import mail_endpoints as msg_mail_ep
from .messaging.views import ui as msg_ui
from django.conf import settings
from django.conf.urls.static import static
from rest_framework.routers import DefaultRouter
from .merge_api import AttachmentMergeViewSet

# إنشاء router للـ APIs
router = DefaultRouter()
router.register('attachments', AttachmentMergeViewSet, basename='attachment-merge')

urlpatterns = [
    # API البحث والإتمام التلقائي (Autocomplete API)
    path("api/search/entities/", api_views.search_entities, name="search_entities"),
    path("api/search/titles/", api_views.search_titles, name="search_titles"),
    path("api/title-autocomplete/", api_views.title_autocomplete, name="title_autocomplete"),
    path("api/title-words/",        api_views.title_words_api,    name="title_words_api"),
    path("api/entity/add/", api_views.add_new_entity, name="add_new_entity"),
    path("api/stats/", api_views.get_entity_stats, name="entity_stats"),
    
    # API لتشغيل الماسح الضوئي
    path("api/scan-capture/", views.scan_capture_api, name="scan_capture_api"),
    path("unified/", views.book_unified, name="book_unified"),
    path("api/unified/data/", views.api_unified_data, name="api_unified_data"),
    path("", RedirectView.as_view(pattern_name='book_unified', permanent=True), name="book_list"),
    path("new/incoming/", views.book_create_incoming, name="book_create_incoming"),
    path("new/outgoing/", views.book_create_outgoing, name="book_create_outgoing"),
    path("reports/", views.reports, name="reports"),
    path("trash/", views.trash_list, name="trash_list"),
    path("trash/book/<int:pk>/restore/", views.restore_book, name="restore_book"),
    path("trash/book/<int:pk>/purge/", views.purge_book, name="purge_book"),
    path("trash/attachment/<int:attachment_id>/restore/", views.restore_attachment, name="restore_attachment"),
    path("trash/attachment/<int:attachment_id>/purge/", views.purge_attachment, name="purge_attachment"),
    path("attachment/<int:pk>/delete/", views.attachment_delete, name="attachment_delete"),
    path("attachment/<int:pk>/replace/", views.attachment_replace, name="attachment_replace"),
    path("attachment/<int:pk>/merge/", views.attachment_merge_pages, name="attachment_merge_pages"),
    path("attachment/<int:pk>/remove-pages/", views.attachment_remove_pages, name="attachment_remove_pages"),
    path("<int:pk>/", views.book_detail, name="book_detail"),
    path("<int:pk>/edit/", views.book_edit, name="book_edit"),
    path("<int:pk>/status/", views.book_change_status, name="book_change_status"),
    path("users/", views.user_roles, name="user_roles"),
    path("api/user-password/<int:user_id>/", views.get_user_password, name="get_user_password"),
    path("api/book-notes/<int:book_id>/", views.update_book_notes, name="update_book_notes"),
    path("api/book-comments/<int:book_id>/add/", views.add_book_comment, name="add_book_comment"),
    path("api/book-comments/<int:comment_id>/edit/", views.edit_book_comment, name="edit_book_comment"),
    path("api/book-comments/<int:comment_id>/delete/", views.delete_book_comment, name="delete_book_comment"),
    path("api/book/<int:book_id>/delete/", views.api_delete_book, name="api_delete_book"),
    path("api/book/<int:pk>/status-inline/", views.api_book_inline_status, name="api_book_inline_status"),
    path("api/books/bulk-delete/", views.api_bulk_delete_books, name="api_bulk_delete_books"),
    path("api/books/bulk-status/", views.api_bulk_update_status_books, name="api_bulk_update_status_books"),
    path("api/book/<int:book_id>/undo-delete/", views.api_undo_delete_book, name="api_undo_delete_book"),
    path("api/book/<int:pk>/preview/", views.api_book_detail_json, name="api_book_detail_json"),
    path("backup/", views.backup_database, name="backup_database"),
    path("legacy-import/", views.legacy_import_page, name="legacy_import"),
    path("legacy-import/run/", views.legacy_import_run, name="legacy_import_run"),
    path("legacy-import/status/", views.legacy_import_status, name="legacy_import_status"),
    path("settings/sequences/", views.sequence_settings, name="sequence_settings"),

    # ─── الربط الشبكي — Network Binding ────────────────────────────────────────
    path("settings/network/",                    network_views.network_settings_page,  name="network_settings"),
    path("api/network/ping/",                    network_views.network_ping,           name="network-ping"),
    path("api/network/save-config/",             network_views.network_save_config,    name="network-save-config"),
    path("api/network/test-db/",                 network_views.network_test_db,        name="network-test-db"),
    path("api/network/test-ping/",               network_views.network_test_ping,      name="network-test-ping"),
    path("api/network/scan-subnet/",             network_views.network_scan_subnet,    name="network-scan-subnet"),
    path("api/network/devices/",                 network_views.network_devices,        name="network-devices"),
    path("api/network/ping-all/",                network_views.network_ping_all,       name="network-ping-all"),
    path("api/network/device/<int:pk>/delete/",  network_views.network_delete_device,  name="network-delete-device"),
    path("api/network/local-ip/",                network_views.network_get_local_ip,   name="network-local-ip"),
    path("api/network/devices/stream/",          network_views.network_devices_stream, name="network-devices-stream"),
    path("entities/", views.entity_list, name="entity_list"),
    path("entities/<int:pk>/", views.entity_detail, name="entity_detail"),
    path("entities/new/", views.entity_create, name="entity_create"),
    path("entities/<int:pk>/edit/", views.entity_edit, name="entity_edit"),
    path("entities/<int:pk>/delete/", views.entity_delete, name="entity_delete"),
    path("entities/bulk-delete/", views.entity_bulk_delete, name="entity_bulk_delete"),
    path("notifications/", views.notifications_page, name="notifications"),
    path("notifications/<int:pk>/read/", views.notification_mark_read, name="notification_mark_read"),
    
    # Smart Merge System APIs
    path('api/', include(router.urls)),

    # AI Extraction - UI Pages (now served from core.extraction)
    path('extract/quick-start/', ext_ui.extraction_quick_start, name='extraction-quick-start'),
    path('extract/wizard/', ext_ui.extraction_wizard, name='extraction-wizard'),
    path('extract/smart-desktop/', ext_ui.extraction_smart_desktop, name='extraction-smart-desktop'),
    path('extract/results/<int:extraction_id>/', ext_ui.extraction_results, name='extraction-results-ui'),
    
    # AI Extraction APIs
    path('api/book/save/', views.save_book_api, name='save-book-api'),
    path('api/next-number/', views.next_number_api, name='next-number-api'),
    path('api/entity-list/', views.entity_list_api, name='entity-list-api'),

    # Reservation APIs (حجز أرقام القيود)
    path('api/reservation/reserve/',    reservation_api.reserve_number,       name='reservation-reserve'),
    path('api/reservation/void/',       reservation_api.void_reservation,      name='reservation-void'),
    path('api/reservation/reactivate/', reservation_api.reactivate_reservation, name='reservation-reactivate'),
    path('api/reservation/status/',     reservation_api.reservation_status,    name='reservation-status'),
    path('api/extract/smart/', ext_api_ep.smart_extract_direct, name='ai_smart_extract'),
    path('api/suggestions/', ext_api_ep.suggestions_api, name='ai_suggestions'),
    path('api/extract/', ext_api_ep.start_extraction, name='ai_start_extraction'),
    path('api/extract/<int:attachment_id>/', ext_api_ep.get_extraction_result, name='ai_get_extraction'),
    path('api/extract/<int:extraction_id>/feedback/', ext_api_ep.submit_feedback, name='ai_submit_feedback'),
    path('api/extract/<int:extraction_id>/review/', ext_api_ep.review_extraction, name='ai_review_extraction'),
    path('api/extract/statistics/', ext_api_ep.extraction_statistics, name='ai_extraction_statistics'),
    
    # Logging & Monitoring APIs
    path('api/logs/', logging_views.log_client_event, name='log_client_event'),
    path('api/logs/batch/', logging_views.log_client_batch, name='log_client_batch'),
    
    # Continuous Learning APIs
    path('api/ocr/feedback/', views.record_ocr_feedback, name='ocr_feedback'),
    path('api/ocr/training/statistics/', views.ocr_training_statistics, name='ocr_training_statistics'),
    path('api/ocr/training/trigger/', views.trigger_ocr_training, name='trigger_ocr_training'),

    # Email APIs — now served from core.messaging (old email_api kept as shim)
    path('api/email/send/',                  msg_email_ep.send_email,          name='email-send'),
    path('api/email/logs/<int:book_id>/',     msg_email_ep.book_email_logs,     name='email-logs'),
    path('api/email/test-smtp/',             msg_email_ep.test_smtp,           name='email-test-smtp'),
    path('api/email/settings/',              msg_email_ep.email_settings,      name='email-settings'),
    path('api/email/entity/<int:entity_id>/',         msg_email_ep.entity_email_info,    name='entity-email-info'),
    path('api/email/entity/<int:entity_id>/update/',  msg_email_ep.update_entity_email,  name='entity-email-update'),

    # ─── قسم البريد ───────────────────────────────────────────────
    path('mail/',                               msg_ui.mail_hub,           name='mail_hub'),
    path('mail/sent/',                          msg_ui.mail_sent,          name='mail_sent'),
    path('mail/inbox/',                         msg_ui.mail_inbox,         name='mail_inbox'),
    path('mail/compose/',                       msg_ui.mail_compose,       name='mail_compose'),
    path('mail/compose/<int:book_id>/',         msg_ui.mail_compose,       name='mail_compose_book'),
    path('mail/thread/<int:thread_id>/',        msg_ui.mail_thread,        name='mail_thread'),
    path('mail/settings/',                      msg_ui.mail_settings,      name='mail_settings'),
    path('mail/templates/',                     msg_ui.mail_templates,     name='mail_templates'),
    path('mail/templates/new/',                 msg_ui.mail_template_edit, name='mail_template_new'),
    path('mail/templates/<int:template_id>/edit/', msg_ui.mail_template_edit,   name='mail_template_edit'),
    path('mail/templates/<int:template_id>/delete/', msg_ui.mail_template_delete, name='mail_template_delete'),

    # Mail API endpoints — now served from core.messaging (old mail_api kept as shim)
    path('mail/api/compose/',           msg_mail_ep.api_compose,          name='mail-api-compose'),
    path('mail/api/inbox/sync/',        msg_mail_ep.api_inbox_sync,       name='mail-api-inbox-sync'),
    path('mail/api/inbox/<int:pk>/read/', msg_mail_ep.api_mark_read,      name='mail-api-mark-read'),
    path('mail/api/thread/<int:pk>/',   msg_mail_ep.api_thread_detail,    name='mail-api-thread'),
    path('mail/api/thread/<int:pk>/status/', msg_mail_ep.api_thread_status, name='mail-api-thread-status'),
    path('mail/api/bulk-send/',         msg_mail_ep.api_bulk_send,        name='mail-api-bulk-send'),
    path('mail/api/template/<int:pk>/preview/', msg_mail_ep.api_template_preview, name='mail-api-template-preview'),
    path('mail/api/settings/test-smtp/', msg_mail_ep.api_test_smtp,       name='mail-api-test-smtp'),
    path('mail/api/settings/test-imap/', msg_mail_ep.api_test_imap,       name='mail-api-test-imap'),
    path('mail/api/stats/',             msg_mail_ep.api_mail_stats,       name='mail-api-stats'),
]

