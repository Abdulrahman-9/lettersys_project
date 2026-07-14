# -*- coding: utf-8 -*-
"""
Book Filtering Helpers — مساعدات فلترة الكتب الموحَّدة

منطق المتابعة الموحَّد (4 حالات حصرية متبادلة، محسوبة من due_date + is_archived):
    pending   : due_date > today  ، is_archived=False
    due_today : due_date = today  ، is_archived=False
    overdue   : due_date < today  ، is_archived=False
    archived  : is_archived=True OR due_date IS NULL
"""

from datetime import timedelta

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

    # ── فلتر نوع المستند (اعمام/أمر إداري/مذكرة...) ────────────────────
    @staticmethod
    def apply_document_type_filter(queryset, document_type=None):
        dt = (document_type or "").strip()
        return queryset.filter(document_type=dt) if dt else queryset

    # ── فلتر مستوى السرية ─────────────────────────────────────────────
    @staticmethod
    def apply_secret_filter(queryset, secret_level=None):
        sl = (secret_level or "").strip()
        return queryset.filter(secret_level=sl) if sl in {"normal", "secret", "topsecret"} else queryset

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
        queryset = BookFilterEngine.apply_document_type_filter(queryset, filters.get("document_type"))
        queryset = BookFilterEngine.apply_secret_filter(queryset, filters.get("secret_level"))
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

    @staticmethod
    def get_dossier_counter_badges(out_qs, in_qs):
        """عدّادات الأضبارة: aggregate واحد لكل اتجاه (على القائمتين المنفصلتين، بلا اتحاد
        M2M) ثم جمع الرقمين لكل حالة. Count(distinct=True) يتفادى fan-out الكارتيزي للكتب
        متعددة الجهات (distinct على مستوى الـqueryset تُتجاهَل داخل aggregate)."""
        today = timezone.localdate()
        archived_q = Q(is_archived=True) | Q(due_date__isnull=True)
        active_q = Q(is_archived=False, due_date__isnull=False)
        spec = {
            "archived":  Count("id", distinct=True, filter=archived_q),
            "overdue":   Count("id", distinct=True, filter=active_q & Q(due_date__lt=today)),
            "due_today": Count("id", distinct=True, filter=active_q & Q(due_date=today)),
            "pending":   Count("id", distinct=True, filter=active_q & Q(due_date__gt=today)),
        }
        o = out_qs.aggregate(**spec)
        i = in_qs.aggregate(**spec)
        return {k: (o.get(k) or 0) + (i.get(k) or 0) for k in spec}

    @staticmethod
    def resolve_period_preset(period, today):
        """يُعيد (date_from, date_to) لاختصار فترة على تاريخ الكتاب. بداية الأسبوع = السبت
        (تقويم إداري عربي). المدى من بداية الفترة حتى اليوم (لا تواريخ مستقبلية)."""
        if period == "today":
            return today, today
        if period == "week":
            # weekday(): الإثنين=0 … الأحد=6؛ السبت=5. أيام منذ آخر سبت:
            offset = (today.weekday() - 5) % 7
            return today - timedelta(days=offset), today
        if period == "month":
            return today.replace(day=1), today
        if period == "quarter":
            q_first_month = 3 * ((today.month - 1) // 3) + 1
            return today.replace(month=q_first_month, day=1), today
        if period == "year":
            return today.replace(month=1, day=1), today
        return None, None

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
        # «relevance»: لا نُعيد الترتيب — نحافظ على أولوية صلة البحث القادمة من
        # apply_search_filters (_exact ثم _num_pri: قيدنا قبل رقم الجهة). بدونه كان
        # فرز -date الافتراضي يطمس الأولوية فتظهر مطابقات رقم الجهة فوق مطابقات قيدنا.
        if sort_field == "relevance":
            return queryset
        if sort_field not in BookSortEngine.VALID_SORTS:
            sort_field = "-date"
        return queryset.order_by(sort_field, "-id")
