# -*- coding: utf-8 -*-
"""
Book Filtering Helpers — مساعدات فلترة الكتب الموحَّدة

منطق المتابعة الموحَّد (4 حالات حصرية متبادلة، محسوبة من due_date + is_archived):
    pending   : due_date > today  ، is_archived=False
    due_today : due_date = today  ، is_archived=False
    overdue   : due_date < today  ، is_archived=False
    archived  : is_archived=True OR due_date IS NULL
"""

from django.db.models import Q, Count
from django.utils import timezone


# تبويبات النوع (kind) — مستقلة عن حالة المتابعة
_KIND_TABS = {
    "all",
    "incoming", "outgoing",
    "incoming_internal", "incoming_external",
    "outgoing_internal", "outgoing_external",
}

# تبويبات/فلاتر حالة المتابعة الأربع
_FOLLOWUP_TABS = {"pending", "due_today", "overdue", "archived"}

# تسميات عربية للحالات (مصدر واحد للعرض في الفلاتر/الـ summaries)
FOLLOWUP_LABELS = {
    "pending":   "قيد المتابعة",
    "due_today": "مستحق اليوم",
    "overdue":   "متأخر",
    "archived":  "مؤرشف",
}


class BookFilterEngine:
    """محرّك فلترة الكتب الموحَّد."""

    # ── فلتر النوع (kind) ─────────────────────────────────────────────
    @staticmethod
    def apply_tab_filter(queryset, tab):
        if not tab or tab == "all":
            return queryset
        if tab in {"incoming_internal", "incoming_external", "outgoing_internal", "outgoing_external"}:
            return queryset.filter(kind=tab)
        if tab == "incoming":
            return queryset.filter(kind__startswith="incoming")
        if tab == "outgoing":
            return queryset.filter(kind__startswith="outgoing")
        return queryset

    # ── فلتر البحث النصي ──────────────────────────────────────────────
    @staticmethod
    def apply_search_filter(queryset, search_text):
        from .helpers import apply_search_filters
        return apply_search_filters(queryset, search_text)

    # ── فلتر نطاق التاريخ ─────────────────────────────────────────────
    @staticmethod
    def apply_date_filter(queryset, date_from=None, date_to=None):
        if date_from:
            queryset = queryset.filter(date__gte=date_from)
        if date_to:
            queryset = queryset.filter(date__lte=date_to)
        return queryset

    # ── فلتر الجهة ────────────────────────────────────────────────────
    @staticmethod
    def apply_entity_filter(queryset, entity_id=None):
        if entity_id and str(entity_id).isdigit():
            eid = int(entity_id)
            return queryset.filter(
                Q(issuing_entities__id=eid) | Q(receiving_entities__id=eid)
            ).distinct()
        return queryset

    # ── فلتر حالة المتابعة (الجوهر — مصدر حقيقة واحد) ────────────────
    @staticmethod
    def apply_followup_filter(queryset, state):
        """
        فلتر حالة المتابعة الموحَّد.
        state ∈ {'pending', 'due_today', 'overdue', 'archived', None}
        """
        if not state or state not in _FOLLOWUP_TABS:
            return queryset
        today = timezone.localdate()
        if state == "archived":
            return queryset.filter(Q(is_archived=True) | Q(due_date__isnull=True))
        # الحالات النشطة الثلاث: غير مؤرشف + due_date موجود
        active = queryset.filter(is_archived=False, due_date__isnull=False)
        if state == "overdue":
            return active.filter(due_date__lt=today)
        if state == "due_today":
            return active.filter(due_date=today)
        if state == "pending":
            return active.filter(due_date__gt=today)
        return queryset

    # ── واجهة موحَّدة لتطبيق كل الفلاتر ────────────────────────────────
    @staticmethod
    def apply_all_filters(queryset, **filters):
        """
        كل الفلاتر تعمل معاً (orthogonal):
            - tab: نوع الكتاب (incoming/outgoing/all/...)
            - followup: حالة المتابعة (pending/due_today/overdue/archived)
            - search_text / date_from / date_to / entity_id
        """
        queryset = BookFilterEngine.apply_tab_filter(queryset, filters.get("tab", "all"))
        queryset = BookFilterEngine.apply_search_filter(queryset, filters.get("search_text", ""))
        queryset = BookFilterEngine.apply_date_filter(
            queryset, filters.get("date_from"), filters.get("date_to")
        )
        queryset = BookFilterEngine.apply_entity_filter(queryset, filters.get("entity_id"))
        queryset = BookFilterEngine.apply_followup_filter(queryset, filters.get("followup"))
        return queryset

    # ── عدّادات الشرائح (badge counts) ───────────────────────────────
    @staticmethod
    def get_counter_badges(queryset):
        """
        يحسب عدّاد كل شريحة بـ query واحد (تجميع).
        Returns dict مع: all, incoming, outgoing, pending, due_today, overdue, archived.
        """
        today = timezone.localdate()
        archived_q = Q(is_archived=True) | Q(due_date__isnull=True)
        active_q = Q(is_archived=False, due_date__isnull=False)

        counts = queryset.aggregate(
            all=Count("id"),
            incoming=Count("id", filter=Q(kind__startswith="incoming")),
            outgoing=Count("id", filter=Q(kind__startswith="outgoing")),
            archived=Count("id", filter=archived_q),
            overdue=Count("id", filter=active_q & Q(due_date__lt=today)),
            due_today=Count("id", filter=active_q & Q(due_date=today)),
            pending=Count("id", filter=active_q & Q(due_date__gt=today)),
        )
        return {
            "all":       counts.get("all", 0),
            "incoming":  counts.get("incoming", 0),
            "outgoing":  counts.get("outgoing", 0),
            "pending":   counts.get("pending", 0),
            "due_today": counts.get("due_today", 0),
            "overdue":   counts.get("overdue", 0),
            "archived":  counts.get("archived", 0),
        }

    # ── ملخّص الفلاتر النشطة (للعرض في الـ AJAX) ──────────────────────
    @staticmethod
    def active_filters_summary(**filters):
        labels = []
        TAB_LABELS = {
            "incoming": "وارد", "outgoing": "صادر",
            "incoming_internal": "وارد داخلي", "incoming_external": "وارد خارجي",
            "outgoing_internal": "صادر داخلي", "outgoing_external": "صادر خارجي",
        }
        tab_label = TAB_LABELS.get(filters.get("tab"))
        if tab_label:
            labels.append(tab_label)
        if filters.get("search_text"):
            labels.append(f"بحث: {filters['search_text']}")
        if filters.get("date_from"):
            labels.append(f"من: {filters['date_from']}")
        if filters.get("date_to"):
            labels.append(f"إلى: {filters['date_to']}")
        if filters.get("entity_id"):
            labels.append("جهة محددة")
        state_label = FOLLOWUP_LABELS.get(filters.get("followup"))
        if state_label:
            labels.append(state_label)
        return {"count": len(labels), "labels": labels}


class BookSortEngine:
    """محرّك الفرز الموحَّد."""

    VALID_SORTS = {
        "date": "date", "-date": "-date",
        "our_number": "our_number", "-our_number": "-our_number",
        "book_number": "our_number", "-book_number": "-our_number",
        "title": "title", "-title": "-title",
        "due_date": "due_date", "-due_date": "-due_date",
    }

    @staticmethod
    def apply_sort(queryset, sort_field="-date"):
        sort_field = (sort_field or "-date").strip()
        if sort_field not in BookSortEngine.VALID_SORTS:
            sort_field = "-date"
        return queryset.order_by(sort_field, "-id")
