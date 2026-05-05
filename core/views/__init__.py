# -*- coding: utf-8 -*-
"""
Views Package - معالجات التطبيق الرئيسية

جميع المعالجات مستوردة من modules متخصصة
"""

# استيراد helpers المنقول إلى ملف منفصل
from .helpers import (
    apply_search_filters,
    validate_sort_parameters,
    compute_time_state,
    is_ajax,
    staff_required,
)

# استيراد معالجات الكتب (Phase 8)
from .books import (
    save_book_api,
    next_number_api,
    sequence_settings,
    book_unified,
    api_unified_data,
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
)

# استيراد معالجات لوحة التحكم والتقارير
from .dashboard import (
    dashboard,
    reports,
    restore_book,
    purge_book,
    restore_attachment,
    purge_attachment,
    backup_database,
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
)

# استيراد معالجات المسح الضوئي (Phase 9)
from .scanner import (
    scan_capture_api,
    _validate_scanned_file,
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
    record_ocr_feedback,
    ocr_training_statistics,
    trigger_ocr_training,
)
