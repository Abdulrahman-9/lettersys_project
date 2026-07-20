# -*- coding: utf-8 -*-
"""
Views Package - معالجات التطبيق الرئيسية

جميع المعالجات مستوردة من modules متخصصة
"""

# استيراد helpers المنقول إلى ملف منفصل
from .helpers import (
    apply_search_filters,
    validate_sort_parameters,
    is_ajax,
    staff_required,
)

# استيراد معالجات الكتب (Phase 8)
from .books import (
    save_book_api,
    update_book_api,
    next_number_api,
    sequence_settings,
    book_unified,
    api_unified_data,
    api_export_csv,
    trash_list,
    book_create_incoming,
    book_create_outgoing,
    api_delete_book,
    api_bulk_delete_books,
    api_bulk_update_status_books,
    api_undo_delete_book,
    api_book_detail_json,
    book_detail,
    book_edit,
    book_change_status,
    book_report,
    api_book_inline_status,
)

# استيراد معالجات التعليقات
from .comments import (
    add_book_comment,
    edit_book_comment,
    delete_book_comment,
)

# استيراد معالجات الإشعارات
from .notifications import (
    notifications_page,
    notification_mark_read,
)

# استيراد معالجات الجهات
from .entities import (
    entity_list_api,
    entity_list,
    entity_detail,
    entity_create,
    entity_edit,
    entity_delete,
    entity_bulk_delete,
    entity_restore,
    entity_bulk_restore,
    entity_merge,
)

# الأضابير (مجلّدات مراسلات الأقسام)
from .dossiers import (
    dossier_list,
    dossier_detail,
    dossier_report,
)

# استيراد معالجات لوحة التحكم والتقارير
from .dashboard import (
    dashboard,
    reports,
    reports_export,
    followup_activity_report,
    restore_book,
    purge_book,
    restore_attachment,
    purge_attachment,
    backup_database,
    data_restore,
    bak_browse,
    legacy_import_page,
    legacy_import_run,
    legacy_import_status,
)

# استيراد معالجات المرفقات
from .attachments import (
    attachment_delete,
    attachment_replace,
    attachment_merge_pages,
    attachment_remove_pages,
    serve_shared_attachment,
)


# استيراد معالجات المستخدمين (Phase 9)
from .users import (
    user_roles,
    get_user_password,
    custom_logout,
)

# استيراد APIs إضافية (Phase 9)
from .api import (
    serve_service_worker,
    update_book_notes,
    attachment_ocr_text,
)

# مركز الإعدادات الموحّد
from .settings_hub import (
    settings_hub,
    settings_general_save,
    settings_notifications_save,
    settings_security_save,
    settings_backup_save,
)

# إعدادات الماسح الضوئي (وكيل NAPS2 المحلي)
from .scan_settings import (
    scan_settings_page,
    scan_file_serve,
    scan_preview_page,
    scan_manifest,
    scan_edit_page,
    scan_stage_attachment,
    scan_process_upload,
    scan_agent_token,
    scan_agent_start,
)
