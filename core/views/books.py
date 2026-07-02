# -*- coding: utf-8 -*-
"""
Book Management Views — thin coordinator.

Real implementations live in the books_* sub-modules.
This file re-exports everything for backwards compatibility
(views/__init__.py and any direct imports continue to work unchanged).
"""

from .books_helpers import (
    _normalize_secret_level_value,
    _resolve_entities,
    annotate_followup_state,
    compute_followup_state,
    validate_sort_parameters,
)
from .books_sequence import (
    next_number_api,
    sequence_settings,
)
from .books_api import (
    save_book_api,
    update_book_api,
    api_delete_book,
    api_bulk_delete_books,
    api_bulk_update_status_books,
    api_undo_delete_book,
    api_book_detail_json,
    api_book_inline_status,
)
from .books_list import (
    book_unified,
    api_unified_data,
    api_export_csv,
    trash_list,
    _KIND_DISPLAY,
    _STATUS_DISPLAY,
    _serialize_book,
)
from .books_forms import (
    book_create_incoming,
    book_create_outgoing,
)
from .books_detail import (
    book_detail,
    book_edit,
    book_change_status,
    book_report,
)

__all__ = [
    # helpers
    '_normalize_secret_level_value',
    '_resolve_entities',
    'annotate_followup_state',
    'compute_followup_state',
    'validate_sort_parameters',
    # sequence
    'next_number_api',
    'sequence_settings',
    # API mutations
    'save_book_api',
    'update_book_api',
    'api_delete_book',
    'api_bulk_delete_books',
    'api_bulk_update_status_books',
    'api_undo_delete_book',
    'api_book_detail_json',
    'api_book_inline_status',
    # list/unified
    'book_unified',
    'api_unified_data',
    'api_export_csv',
    'trash_list',
    # forms/create
    'book_create_incoming',
    'book_create_outgoing',
    # detail/edit/status
    'book_detail',
    'book_edit',
    'book_change_status',
    'book_report',
]
