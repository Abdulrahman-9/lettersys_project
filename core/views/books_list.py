# -*- coding: utf-8 -*-
"""
Book list/unified/trash views.
"""

import json
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from ..models import Attachment, Book, Entity
from .books_helpers import annotate_time_state

logger = logging.getLogger(__name__)

_KIND_DISPLAY = {
    'outgoing_internal': ('صادر داخلي', 'cyan'),
    'outgoing_external': ('صادر خارجي', 'cyan-dark'),
    'incoming_internal': ('وارد داخلي', 'purple'),
    'incoming_external': ('وارد خارجي', 'purple-dark'),
}

_STATUS_DISPLAY = {
    'pending':  ('قيد الإجراء', 'warning'),
    'hold':     ('معلّق',       'secondary'),
    'done':     ('منجز',        'success'),
    'archived': ('مؤرشف',       'info'),
}


def _serialize_book(book):
    """تحويل كائن Book إلى dict مناسب لإعادة JSON في AJAX endpoint."""
    kind_label, kind_color = _KIND_DISPLAY.get(book.kind, (book.kind, 'secondary'))
    status_label, status_color = _STATUS_DISPLAY.get(book.final_status, (book.final_status, 'secondary'))

    issuing = [{'id': e.id, 'name': e.name} for e in book.issuing_entities.all()]
    receiving = [{'id': e.id, 'name': e.name} for e in book.receiving_entities.all()]

    return {
        'id': book.id,
        'our_number': book.our_number or '',
        'title': book.title,
        'kind': book.kind,
        'kind_label': kind_label,
        'kind_color': kind_color,
        'date': book.date.isoformat() if book.date else '',
        'status': book.final_status,
        'status_label': status_label,
        'status_color': status_color,
        'issuing_entities': issuing,
        'receiving_entities': receiving,
        'needs_followup': book.needs_followup,
        'due_date': book.due_date.isoformat() if book.due_date else None,
        'delay_days': getattr(book, 'delay_days', 0),
        'time_state': getattr(book, 'time_state', 'normal'),
        'urls': {
            'detail': reverse('book_detail', args=[book.id]),
            'edit':   reverse('book_edit',   args=[book.id]),
        },
    }


@login_required
def book_unified(request):
    """
    الصفحة الموحدة لإدارة الكتب.
    استخدام BookFilterEngine لتوحيد منطق الفلترة.
    """
    from .filter_helpers import BookFilterEngine, BookSortEngine

    base_qs = (
        Book.objects.filter(is_deleted=False)
        if request.user.is_superuser
        else Book.objects.filter(created_by=request.user, is_deleted=False)
    ).select_related("created_by").prefetch_related("issuing_entities", "receiving_entities")

    tab = (request.GET.get("tab") or "all").strip()
    search_text = (request.GET.get("q") or "").strip()
    date_from_str = (request.GET.get("date_from") or "").strip()
    date_to_str = (request.GET.get("date_to") or "").strip()
    entity_id = (request.GET.get("entity_id") or "").strip()
    status = (request.GET.get("status") or "").strip()
    sort = (request.GET.get("sort") or "-date").strip()

    date_from = None
    date_to = None
    if date_from_str:
        try:
            from datetime import datetime
            date_from = datetime.strptime(date_from_str, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            messages.warning(request, "صيغة تاريخ البداية غير صحيحة")

    if date_to_str:
        try:
            from datetime import datetime
            date_to = datetime.strptime(date_to_str, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            messages.warning(request, "صيغة تاريخ النهاية غير صحيحة")

    qs = BookFilterEngine.apply_all_filters(
        base_qs,
        tab=tab,
        search_text=search_text,
        date_from=date_from,
        date_to=date_to,
        entity_id=entity_id,
        status=status
    )
    qs = BookSortEngine.apply_sort(qs, sort)

    paginator = Paginator(qs, 12)
    page_num = request.GET.get("page", 1)

    try:
        page_obj = paginator.page(page_num)
    except (PageNotAnInteger, EmptyPage):
        page_obj = paginator.page(1)

    books = list(annotate_time_state(page_obj.object_list))
    today = timezone.localdate()
    for book in books:
        if book.due_date:
            book.delay_days = abs((book.due_date - today).days)
        else:
            book.delay_days = 0

    counter_badges = BookFilterEngine.get_counter_badges(base_qs)

    from django.core.cache import cache
    cache_key = 'active_entities_list'
    entities = cache.get(cache_key)
    if entities is None:
        entities = list(Entity.objects.filter(is_active=True).values('id', 'name').order_by('name'))
        cache.set(cache_key, entities, 3600)

    if paginator.count == 0:
        pagination_from = 0
        pagination_to = 0
    else:
        pagination_from = ((page_obj.number - 1) * paginator.per_page) + 1
        pagination_to = pagination_from + len(books) - 1

    active_filters_count = sum(
        1 for v in [search_text, date_from, date_to, entity_id, status] if v
    )

    query_copy = request.GET.copy()
    if "page" in query_copy:
        query_copy.pop("page")
    base_querystring = query_copy.urlencode()

    context = {
        "books": books,
        "page_obj": page_obj,
        "total_count": paginator.count,
        "showing_count": len(books),
        "total_pages": paginator.num_pages,
        "pagination_from": pagination_from,
        "pagination_to": pagination_to,
        "base_querystring": base_querystring,
        "current_tab": tab,
        "search_query": search_text,
        "date_from": date_from_str,
        "date_to": date_to_str,
        "entity_id": entity_id,
        "selected_entity_id": entity_id,
        "status": status,
        "sort_by": sort,
        "show_filters": active_filters_count > 0,
        "has_active_filters": active_filters_count > 0,
        "active_filters_count": active_filters_count,
        "total_books": counter_badges['all'],
        "incoming_count": counter_badges['incoming'],
        "outgoing_count": counter_badges['outgoing'],
        "done_count": counter_badges['done'],
        "overdue_count": counter_badges['overdue'],
        "today_count": counter_badges['today'],
        "upcoming_count": counter_badges['upcoming'],
        "entities": entities,
        "book_list_api_url": "/api/books/",
        "filters": json.dumps({
            "tab": tab,
            "q": search_text,
            "date_from": date_from_str,
            "date_to": date_to_str,
            "entity_id": entity_id,
            "status": status,
            "sort": sort,
        }),
    }

    return render(request, "core/book_unified.html", context)


@login_required
@require_http_methods(["GET"])
def api_unified_data(request):
    """
    JSON endpoint لتحديث جدول الكتب في book_unified بدون reload.
    """
    from .filter_helpers import BookFilterEngine, BookSortEngine

    base_qs = (
        Book.objects.filter(is_deleted=False)
        if request.user.is_superuser
        else Book.objects.filter(created_by=request.user, is_deleted=False)
    ).select_related('created_by').prefetch_related('issuing_entities', 'receiving_entities')

    tab = (request.GET.get('tab') or 'all').strip()
    search_text = (request.GET.get('q') or '').strip()
    date_from_s = (request.GET.get('date_from') or '').strip()
    date_to_s = (request.GET.get('date_to') or '').strip()
    entity_id = (request.GET.get('entity_id') or '').strip()
    status = (request.GET.get('status') or '').strip()
    sort = (request.GET.get('sort') or '-date').strip()
    per_page = 12

    date_from = date_to = None
    try:
        from datetime import datetime
        if date_from_s:
            date_from = datetime.strptime(date_from_s, '%Y-%m-%d').date()
        if date_to_s:
            date_to = datetime.strptime(date_to_s, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        pass

    qs = BookFilterEngine.apply_all_filters(
        base_qs,
        tab=tab, search_text=search_text,
        date_from=date_from, date_to=date_to,
        entity_id=entity_id, status=status,
    )
    qs = BookSortEngine.apply_sort(qs, sort)

    paginator = Paginator(qs, per_page)
    try:
        page_obj = paginator.page(request.GET.get('page', 1))
    except (PageNotAnInteger, EmptyPage):
        page_obj = paginator.page(1)

    books_qs = list(annotate_time_state(page_obj.object_list))
    today = timezone.localdate()
    for b in books_qs:
        b.delay_days = abs((b.due_date - today).days) if b.due_date else 0

    books_data = [_serialize_book(b) for b in books_qs]

    active_filters = BookFilterEngine.active_filters_summary(
        tab=tab, search_text=search_text,
        date_from=date_from_s, date_to=date_to_s,
        entity_id=entity_id, status=status,
    )

    return JsonResponse({
        'books': books_data,
        'pagination': {
            'current':  page_obj.number,
            'total':    paginator.num_pages,
            'count':    paginator.count,
            'per_page': per_page,
            'has_next': page_obj.has_next(),
            'has_prev': page_obj.has_previous(),
        },
        'active_filters': active_filters,
    })


@login_required
def trash_list(request):
    """عرض سلة المهملات - الكتب والمرفقات المحذوفة."""
    books_qs = Book.objects.filter(is_deleted=True)
    attachments_qs = Attachment.objects.filter(is_deleted=True).select_related("book")

    if not (request.user.is_superuser or request.user.is_staff):
        books_qs = books_qs.filter(created_by=request.user)
        attachments_qs = attachments_qs.filter(book__created_by=request.user)

    context = {
        "deleted_books": books_qs.order_by("-deleted_at"),
        "deleted_attachments": attachments_qs.order_by("-deleted_at"),
    }

    return render(request, "core/trash.html", context)


__all__ = [
    'book_unified',
    'api_unified_data',
    'trash_list',
    '_serialize_book',
    '_KIND_DISPLAY',
    '_STATUS_DISPLAY',
]
