# -*- coding: utf-8 -*-
"""
Book list/unified/trash views.
"""

import csv
import io
import json
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from ..models import Attachment, Book, Entity
from core.scoping import (books_in_scope, can_edit_book, is_privileged, present_book_payload,
                          scope_books_for)

logger = logging.getLogger(__name__)

_KIND_DISPLAY = {
    'outgoing_internal': ('صادر داخلي', 'cyan'),
    'outgoing_external': ('صادر خارجي', 'cyan-dark'),
    'incoming_internal': ('وارد داخلي', 'purple'),
    'incoming_external': ('وارد خارجي', 'purple-dark'),
}

# حالات المتابعة الأربع الموحَّدة: state → (label, color-token)
_STATUS_DISPLAY = {
    'pending':   ('قيد المتابعة', 'pending'),
    'due_today': ('مستحق اليوم',  'due_today'),
    'overdue':   ('متأخر',         'overdue'),
    'archived':  ('مُنجَز / بلا متابعة', 'archived'),
}

# توافق رجعي مع URLs قديمة (bookmarks خارجية، CSV exports قديم، إلخ)
_LEGACY_FOLLOWUP_MAP = {
    'today':    'due_today',
    'upcoming': 'pending',
    'done':     'archived',
    'hold':     'archived',
}


def _resolve_followup_param(request):
    """يستخرج معامل حالة المتابعة من الطلب مع دعم الأسماء القديمة."""
    raw = (
        request.GET.get('followup')
        or request.GET.get('status')
        or request.GET.get('due_status')
        or ''
    ).strip()
    return _LEGACY_FOLLOWUP_MAP.get(raw, raw)


def _serialize_book(book):
    """تحويل كائن Book إلى dict مناسب لإعادة JSON في AJAX endpoint."""
    kind_label, kind_color = _KIND_DISPLAY.get(book.kind, (book.kind, 'secondary'))
    state = book.followup_state
    status_label, status_color = _STATUS_DISPLAY.get(state, (state, 'secondary'))

    issuing = [{'id': e.id, 'name': e.name} for e in book.issuing_entities.all()]
    receiving = [{'id': e.id, 'name': e.name} for e in book.receiving_entities.all()]

    att = book.attachment
    try:
        attachment_url = att.file.url if att and att.file else None
    except Exception:
        attachment_url = None

    created_by_name = ''
    if book.created_by_id:
        created_by_name = book.created_by.get_full_name() or book.created_by.username

    return {
        'id': book.id,
        'our_number': book.our_number or '',
        'our_number_display': book.our_number_display,
        'our_number_year': book.our_number_year,
        'our_number_sequence': book.our_number_sequence,
        'our_number_is_compound': book.our_number_is_compound,
        'our_number_is_numberless': book.our_number_is_numberless,
        'series_no': book.series_no,
        'version': book.version,
        'legacy_number': book.legacy_number or '',
        'sender_number': book.sender_number or '',
        'date_display': book.date.strftime('%d/%m/%Y') if book.date else '—',
        'sender_date_display': book.sender_date.strftime('%d/%m/%Y') if book.sender_date else '',
        'title': book.title,
        'kind': book.kind,
        'kind_label': kind_label,
        'kind_color': kind_color,
        'date': book.date.isoformat() if book.date else '',
        'status': state,
        'status_label': status_label,
        'status_color': status_color,
        'is_archived': book.is_archived,
        'followup_state': state,
        'followup_label': status_label,
        'issuing_entities': issuing,
        'receiving_entities': receiving,
        'due_date': book.due_date.isoformat() if book.due_date else None,
        'due_date_display': book.due_date.strftime('%d/%m/%Y') if book.due_date else '',
        'delay_days': book.delay_days,
        'attachment_url': attachment_url,
        # ─── expansion panel data ───
        'margin': book.margin or '',
        'sender_date': book.sender_date.strftime('%d/%m/%Y') if book.sender_date else '',
        'document_type': book.document_type or '',
        'secret_level': book.secret_level,
        'secret_label': book.get_secret_level_display(),
        'created_by_name': created_by_name,
        'created_at': timezone.localtime(book.created_at).strftime('%d/%m/%Y %H:%M') if book.created_at else '',
        'updated_at': timezone.localtime(book.updated_at).strftime('%d/%m/%Y %H:%M') if book.updated_at else '',
        'urls': {
            'detail': reverse('book_detail', args=[book.id]),
            'edit':   reverse('book_edit',   args=[book.id]),
            'delete': reverse('api_delete_book', args=[book.id]),
        },
    }


def _list_scope(request):
    """أساسُ القائمة — **قاعدةٌ واحدة** للصفحة وتحديثها والتصدير (قرارُ المالك 2026‑10‑06).

    الحيُّ وحدَه افتراضاً كاللوحة والتقارير (``books_in_scope``)، فرقمُ كلِّ بلاطةٍ
    في اللوحة هو عددُ ما تفتحه هنا؛ و``?legacy=1`` يُدخل الورقَ القديم.
    **والبحثُ يجد الكلّ**: أرقامُ الدفتر القديم («825» ⟵ ``20250825``، «قديم-544»)
    أوّلُ ما يُبحث عنه، وإخضاعُها للمفتاح يُفشل البحثَ بلا رسالة — فنصُّ البحث
    يوسّع **الصفوفَ وحدَها**، والعدّاداتُ تتبع المفتاحَ لا النصّ (وإلّا قفزت
    الشاراتُ من المئات إلى الآلاف مع كلّ حرف).

    يُعيد ``(rows, counters, legacy, widened)``: ``widened`` = بحثٌ وسّع الصفوفَ
    إلى الورق القديم والمفتاحُ مطفأ — والواجهةُ تقوله للكاتب.
    """
    legacy = request.GET.get('legacy') == '1'
    widened = bool((request.GET.get('q') or '').strip()) and not legacy
    counters = books_in_scope(request.user, legacy=legacy)
    rows = books_in_scope(request.user, legacy=True) if widened else counters
    return rows, counters, legacy, widened


@login_required
def book_unified(request):
    """
    الصفحة الموحدة لإدارة الكتب.
    استخدام BookFilterEngine لتوحيد منطق الفلترة.
    """
    from .filter_helpers import FOLLOWUP_LABELS, BookFilterEngine, BookSortEngine

    rows_qs, counters_qs, legacy, widened = _list_scope(request)
    base_qs = rows_qs.select_related("created_by").prefetch_related("issuing_entities", "receiving_entities", "attachments")

    tab = (request.GET.get("tab") or "incoming").strip()
    search_text = (request.GET.get("q") or "").strip()
    date_from_str = (request.GET.get("date_from") or "").strip()
    date_to_str = (request.GET.get("date_to") or "").strip()
    entity_id = (request.GET.get("entity_id") or "").strip()
    followup = _resolve_followup_param(request)
    # عند وجود بحث ولم يختر المستخدم عموداً: افتراضٌ «relevance» يحفظ أولوية الصلة
    # (قيدنا قبل رقم الجهة). الواجهة لا تُرسل sort إلا عند اختيار عمود صراحةً.
    sort = (request.GET.get("sort") or ("relevance" if search_text else "-date")).strip()

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
        user=request.user,
        tab=tab,
        search_text=search_text,
        date_from=date_from,
        date_to=date_to,
        entity_id=entity_id,
        followup=followup,
    )
    qs = BookSortEngine.apply_sort(qs, sort, user=request.user)

    paginator = Paginator(qs, 12)
    page_num = request.GET.get("page", 1)

    try:
        page_obj = paginator.page(page_num)
    except (PageNotAnInteger, EmptyPage):
        page_obj = paginator.page(1)

    books = list(page_obj.object_list)

    counter_badges = BookFilterEngine.get_counter_badges(counters_qs)

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
        1 for v in [search_text, date_from, date_to, entity_id, followup, legacy] if v
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
        "followup": followup,
        "current_filter": followup,
        "sort_by": sort,
        "legacy": legacy,
        "search_widened": widened,
        "show_filters": active_filters_count > 0,
        "has_active_filters": active_filters_count > 0,
        "active_filters_count": active_filters_count,
        "total_books": counter_badges['all'],
        "incoming_count": counter_badges['incoming'],
        "outgoing_count": counter_badges['outgoing'],
        "pending_count": counter_badges['pending'],
        "due_today_count": counter_badges['due_today'],
        "overdue_count": counter_badges['overdue'],
        "archived_count": counter_badges['archived'],
        # رقاقةُ «متابعة جارية» تُرسَم عند الوصول من اللوحة وحدَه (followup=active)،
        # بلا عدّاد: `counter_badges` عبر التبويبات كلّها ورقمُ اللوحة للوارد وحدَه.
        "active_label": FOLLOWUP_LABELS['active'],
        "entities": entities,
        "book_list_api_url": "/api/books/",
        "filters": json.dumps({
            "tab": tab,
            "q": search_text,
            "date_from": date_from_str,
            "date_to": date_to_str,
            "entity_id": entity_id,
            "followup": followup,
            "sort": sort,
            "legacy": "1" if legacy else "",
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

    rows_qs, counters_qs, legacy, widened = _list_scope(request)
    base_qs = rows_qs.select_related('created_by').prefetch_related('issuing_entities', 'receiving_entities', 'attachments')

    tab = (request.GET.get('tab') or 'incoming').strip()
    search_text = (request.GET.get('q') or '').strip()
    date_from_s = (request.GET.get('date_from') or '').strip()
    date_to_s = (request.GET.get('date_to') or '').strip()
    entity_id = (request.GET.get('entity_id') or '').strip()
    followup = _resolve_followup_param(request)
    # عند وجود بحث ولم يختر المستخدم عموداً: «relevance» يحفظ أولوية الصلة (قيدنا قبل رقم الجهة)
    sort = (request.GET.get('sort') or ('relevance' if search_text else '-date')).strip()
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
        user=request.user,
        tab=tab, search_text=search_text,
        date_from=date_from, date_to=date_to,
        entity_id=entity_id, followup=followup,
    )
    qs = BookSortEngine.apply_sort(qs, sort, user=request.user)

    paginator = Paginator(qs, per_page)
    try:
        page_obj = paginator.page(request.GET.get('page', 1))
    except (PageNotAnInteger, EmptyPage):
        page_obj = paginator.page(1)

    books_qs = list(page_obj.object_list)
    # المُقدِّم بعد المُسلسِل: نقطةُ اختناقٍ واحدة يمرّ منها كلُّ حقلٍ يُضاف
    # مستقبلاً، فلا يتسرّب محتوى كتابٍ سرّيّ من حقلٍ نُسي (سجلّ العيوب ح1).
    books_data = [present_book_payload(_serialize_book(b), b, request.user)
                  for b in books_qs]

    # رسم صفوف الجدول من القالب نفسه المستخدَم في الرسم الأولي (book_unified_row.html) —
    # مصدر حقيقة واحد للصف بدل إعادة بنائه في JS (buildRow)، فلا يتباعد المساران. #13
    from django.template.loader import render_to_string
    rows_html = ''.join(
        render_to_string('core/partials/book_unified_row.html', {'book': b}, request=request)
        for b in books_qs
    )

    active_filters = BookFilterEngine.active_filters_summary(
        tab=tab, search_text=search_text,
        date_from=date_from_s, date_to=date_to_s,
        entity_id=entity_id, followup=followup, legacy=legacy,
    )

    counter_badges = BookFilterEngine.get_counter_badges(counters_qs)

    return JsonResponse({
        'books': books_data,
        'rows_html': rows_html,
        'pagination': {
            'current':  page_obj.number,
            'total':    paginator.num_pages,
            'count':    paginator.count,
            'per_page': per_page,
            'has_next': page_obj.has_next(),
            'has_prev': page_obj.has_previous(),
        },
        'active_filters': active_filters,
        'badges': counter_badges,
        'legacy': legacy,
        'search_widened': widened,
    })


@login_required
def trash_list(request):
    """عرض سلة المهملات - الكتب والمرفقات المحذوفة."""
    # ‏all_objects: المدير الافتراضي لا يرى المحذوف — والسلّة كلّها محذوف.
    books_qs = Book.all_objects.filter(is_deleted=True)
    attachments_qs = Attachment.all_objects.filter(is_deleted=True).select_related("book")

    if not is_privileged(request.user):
        books_qs = scope_books_for(request.user, books_qs)
        attachments_qs = attachments_qs.filter(book__in=scope_books_for(
            request.user, Book.all_objects.all()))

    # لا زرَّ يُعرض ليُرفض: «استعادة» لمن يكتب على الكتاب (Q1‑ج، ``can_edit_book``)
    # — الوحدةُ المُحالُ إليها ترى كتابَ المالك المحذوف ولا تستعيده — و«حذفٌ نهائيّ»
    # لمدير النظام وحده كما يحرسه ``purge_book``.
    privileged = is_privileged(request.user)
    deleted_books = list(books_qs.order_by("-deleted_at"))
    deleted_attachments = list(attachments_qs.order_by("-deleted_at"))
    for b in deleted_books:
        b.can_restore = privileged or can_edit_book(b, request.user)
    for a in deleted_attachments:
        a.can_restore = privileged or can_edit_book(a.book, request.user)

    context = {
        "deleted_books": deleted_books,
        "deleted_attachments": deleted_attachments,
        "can_purge": privileged,
    }

    return render(request, "core/trash.html", context)


@login_required
def api_export_csv(request):
    """تصدير الكتب المفلترة كـ CSV — يستخدم نفس فلاتر api_unified_data."""
    from .filter_helpers import BookFilterEngine, BookSortEngine

    rows_qs, _counters, _legacy, _widened = _list_scope(request)
    base_qs = rows_qs.prefetch_related("issuing_entities", "receiving_entities")

    from datetime import datetime as _dt
    # `incoming` كالصفحة والنقطة تماماً: زرُّ التصدير ينسخ `window.location.search`
    # وأوّلُ تحميلٍ بلا `tab` — فافتراضُ «الكلّ» هنا كان يُصدّر أكثرَ ممّا يُرى.
    tab = (request.GET.get("tab") or "incoming").strip()
    search_text = (request.GET.get("q") or "").strip()
    entity_id = (request.GET.get("entity_id") or "").strip()
    followup = _resolve_followup_param(request)
    # عند وجود بحث ولم يختر المستخدم عموداً: افتراضٌ «relevance» يحفظ أولوية الصلة
    # (قيدنا قبل رقم الجهة). الواجهة لا تُرسل sort إلا عند اختيار عمود صراحةً.
    sort = (request.GET.get("sort") or ("relevance" if search_text else "-date")).strip()
    date_from = date_to = None
    try:
        if request.GET.get("date_from"):
            date_from = _dt.strptime(request.GET["date_from"], "%Y-%m-%d").date()
        if request.GET.get("date_to"):
            date_to = _dt.strptime(request.GET["date_to"], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        pass

    qs = BookFilterEngine.apply_all_filters(
        base_qs,
        user=request.user,
        tab=tab, search_text=search_text,
        date_from=date_from, date_to=date_to,
        entity_id=entity_id, followup=followup,
    )
    qs = BookSortEngine.apply_sort(qs, sort, user=request.user)

    # ملفٌّ يخرج من الجهاز بصفوفٍ كثيرة — أثقلُ واقعةِ إخراجٍ في النظام
    from core.audit_service import record_event
    record_event(request, 'EXPORT_DATA', metadata={'tab': tab, 'q': bool(search_text)})

    HEADERS = ["رقم الكتاب", "التاريخ", "الموضوع", "النوع", "الحالة", "الجهات", "تاريخ الاستحقاق"]

    def _rows():
        # القرارُ من المصدر الوحيد (`secret_access`)؛ وأعمدةُ المحتوى هنا
        # هي العنوانُ والجهات — كما تُفرَّغ في `stub_book_payload` للقائمة.
        from core.scoping import ACCESS_STUB, STUB_TITLE, secret_access

        buf = io.StringIO()
        # BOM مرّةً واحدة صراحةً (كتصدير التقارير): ``charset=utf-8-sig`` في الترويسة
        # كان يُرمِّز **كلَّ دفعةٍ** وحدَها فيُلصق BOM ببداية كلّ صفّ — محرفٌ خفيٌّ أوّلَ
        # خانةٍ في كلّ سطرٍ من Excel.
        buf.write("﻿")
        writer = csv.writer(buf)
        writer.writerow(HEADERS)
        yield buf.getvalue()
        for book in qs.iterator(chunk_size=500):
            buf = io.StringIO()
            writer = csv.writer(buf)
            kind_label = _KIND_DISPLAY.get(book.kind, (book.kind,))[0]
            status_label = _STATUS_DISPLAY.get(book.followup_state, (book.followup_state,))[0]
            restricted = secret_access(request.user, book) == ACCESS_STUB
            entities = "" if restricted else ", ".join(
                e.name for e in list(book.issuing_entities.all()) + list(book.receiving_entities.all())
            )
            writer.writerow([
                book.our_number or "",
                book.date.isoformat() if book.date else "",
                STUB_TITLE if restricted else book.title,
                kind_label,
                status_label,
                entities,
                book.due_date.isoformat() if book.due_date else "",
            ])
            yield buf.getvalue()

    response = StreamingHttpResponse(_rows(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="books_export.csv"'
    return response


__all__ = [
    'book_unified',
    'api_unified_data',
    'api_export_csv',
    'trash_list',
    '_serialize_book',
    '_KIND_DISPLAY',
    '_STATUS_DISPLAY',
]
