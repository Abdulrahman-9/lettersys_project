from django.urls import path, include
from django.views.generic import RedirectView
from . import views
from . import logging_views
from . import api as api_views
from . import reservation_api
from . import network_views
from django.conf import settings
from django.conf.urls.static import static
from rest_framework.routers import DefaultRouter
from .merge_api import AttachmentMergeViewSet
from .messaging.api.urls import email_urlpatterns, mail_urlpatterns

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

    path("unified/", views.book_unified, name="book_unified"),
    path("api/unified/data/", views.api_unified_data, name="api_unified_data"),
    path("api/unified/export/csv/", views.api_export_csv, name="api_export_csv"),
    path("", RedirectView.as_view(pattern_name='book_unified', permanent=True), name="book_list"),
    path("new/incoming/", views.book_create_incoming, name="book_create_incoming"),
    path("new/outgoing/", views.book_create_outgoing, name="book_create_outgoing"),
    path("reports/", views.reports, name="reports"),
    path("reports/export/", views.reports_export, name="reports_export"),
    path("reports/followup-activity/", views.followup_activity_report, name="followup_activity_report"),
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
    path("<int:pk>/report/", views.book_report, name="book_report"),
    path("<int:pk>/edit/", views.book_edit, name="book_edit"),
    path("<int:pk>/status/", views.book_change_status, name="book_change_status"),
    path("users/", views.user_roles, name="user_roles"),
    path("api/user-password/<int:user_id>/", views.get_user_password, name="get_user_password"),
    path("api/book-notes/<int:book_id>/", views.update_book_notes, name="update_book_notes"),
    path("api/attachment/<int:att_id>/ocr/", views.attachment_ocr_text, name="attachment_ocr_text"),
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
    path("restore-data/", views.data_restore, name="data_restore"),
    path("restore-data/browse/", views.bak_browse, name="bak_browse"),
    path("legacy-import/", views.legacy_import_page, name="legacy_import"),
    path("legacy-import/run/", views.legacy_import_run, name="legacy_import_run"),
    path("legacy-import/status/", views.legacy_import_status, name="legacy_import_status"),
    path("settings/", views.settings_hub, name="settings_hub"),
    path("settings/general/save/", views.settings_general_save, name="settings_general_save"),
    path("settings/notifications/save/", views.settings_notifications_save, name="settings_notifications_save"),
    path("settings/security/save/", views.settings_security_save, name="settings_security_save"),
    path("settings/backup/save/", views.settings_backup_save, name="settings_backup_save"),
    path("settings/sequences/", views.sequence_settings, name="sequence_settings"),

    # ─── إعدادات الماسح الضوئي ────────────────────────────────────────────────
    # ── المسح عبر وكيل NAPS2 المحلي (التدفّق الوحيد المدعوم) ──
    path("settings/scan/",                views.scan_settings_page,    name="scan_settings"),
    path("api/scan/serve/<str:token>/",   views.scan_file_serve,       name="scan_file_serve"),
    path("api/scan/preview/<str:token>/", views.scan_preview_page,     name="scan_preview_page"),
    path("api/scan/manifest/<str:token>/", views.scan_manifest,        name="scan_manifest"),
    path("api/scan/edit/<str:token>/",    views.scan_edit_page,        name="scan_edit_page"),
    path("api/scan/stage-attachment/<int:attachment_id>/", views.scan_stage_attachment, name="scan_stage_attachment"),
    path("api/scan/process-upload/",      views.scan_process_upload,   name="scan_process_upload"),
    path("api/scan/agent-token/",         views.scan_agent_token,      name="scan_agent_token"),

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
    path("entities/merge/", views.entity_merge, name="entity_merge"),
    path("entities/<int:pk>/", views.entity_detail, name="entity_detail"),
    path("entities/new/", views.entity_create, name="entity_create"),
    path("entities/<int:pk>/edit/", views.entity_edit, name="entity_edit"),
    path("entities/<int:pk>/delete/", views.entity_delete, name="entity_delete"),
    path("entities/bulk-delete/", views.entity_bulk_delete, name="entity_bulk_delete"),
    path("entities/<int:pk>/restore/", views.entity_restore, name="entity_restore"),
    path("entities/bulk-restore/", views.entity_bulk_restore, name="entity_bulk_restore"),
    # ── الأضابير (مجلّدات مراسلات الأقسام) ──
    path("dossiers/", views.dossier_list, name="dossier_list"),
    path("dossiers/<int:pk>/", views.dossier_detail, name="dossier_detail"),
    path("dossiers/<int:pk>/report/", views.dossier_report, name="dossier_report"),
    path("notifications/", views.notifications_page, name="notifications"),
    path("notifications/<int:pk>/read/", views.notification_mark_read, name="notification_mark_read"),

    # Smart Merge System APIs
    path('api/', include(router.urls)),

    # AI Extraction — UI Pages
    path('extract/', include('core.extraction.views.urls')),

    # AI Extraction — REST APIs
    path('api/', include('core.extraction.api.urls')),

    path('api/book/save/', views.save_book_api, name='save-book-api'),
    path('api/book/update/', views.update_book_api, name='update-book-api'),
    path('api/next-number/', views.next_number_api, name='next-number-api'),
    path('api/entity-list/', views.entity_list_api, name='entity-list-api'),

    # Reservation APIs (حجز أرقام القيود)
    path('api/reservation/reserve/',    reservation_api.reserve_number,       name='reservation-reserve'),
    path('api/reservation/void/',       reservation_api.void_reservation,      name='reservation-void'),
    path('api/reservation/reactivate/', reservation_api.reactivate_reservation, name='reservation-reactivate'),
    path('api/reservation/status/',     reservation_api.reservation_status,    name='reservation-status'),

    # Logging & Monitoring APIs
    path('api/logs/', logging_views.log_client_event, name='log_client_event'),
    path('api/logs/batch/', logging_views.log_client_batch, name='log_client_batch'),

    # Continuous Learning APIs
    path('api/ocr/feedback/', views.record_ocr_feedback, name='ocr_feedback'),
    path('api/ocr/training/statistics/', views.ocr_training_statistics, name='ocr_training_statistics'),
    path('api/ocr/training/trigger/', views.trigger_ocr_training, name='trigger_ocr_training'),

    # ─── Email APIs ───────────────────────────────────────────────────────────
    path('api/email/', include(email_urlpatterns)),

    # ─── قسم البريد — Mail UI & APIs ─────────────────────────────────────────
    path('mail/', include('core.messaging.views.urls')),
    path('mail/api/', include(mail_urlpatterns)),
]
