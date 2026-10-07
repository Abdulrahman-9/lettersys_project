# -*- coding: utf-8 -*-
"""
Book Filtering Helpers — مساعدات فلترة الكتب الموحَّدة

منطق المتابعة الموحَّد (4 حالات حصريّة + فلترُ «جارية»، من due_date + is_archived — المصدرُ `followup_q`):
    pending   : due_date > today  ، is_archived=False
    due_today : due_date = today  ، is_archived=False
    overdue   : due_date < today  ، is_archived=False
    archived  : is_archived=True OR due_date IS NULL
    active    : is_archived=False AND due_date IS NOT NULL  (= pending ∪ due_today ∪ overdue)
الأربعُ الأولى حصريّةٌ متبادلة؛ و`active` اتّحادُ الثلاث الجارية لا حالةٌ خامسةٌ للصفّ.
"""

from datetime import timedelta

from django.db.models import Q, Count
from django.utils import timezone

from .. import numbering


# تبويبات النوع (kind) — مستقلة عن حالة المتابعة
_KIND_TABS = {
    "all", "all_internal", "all_external",
    "incoming", "outgoing",
    "incoming_internal", "incoming_external",
    "outgoing_internal", "outgoing_external",
}

# حالاتُ الصفّ الأربع الحصريّة — لكلٍّ منها رقاقةٌ بعدّاد (القائمة والأضبارة)
_FOLLOWUP_STATES = ("pending", "due_today", "overdue", "archived")
# فلاتر حالة المتابعة: الأربعُ + «جارية» (اتّحادُ الثلاث الجارية؛ فلترٌ بلا عدّاد رقاقة)
_FOLLOWUP_TABS = {"active", *_FOLLOWUP_STATES}

# تسميات عربية للحالات (مصدر واحد للعرض في الفلاتر/الـ summaries)
FOLLOWUP_LABELS = {
    "pending":   "قيد المتابعة",
    "due_today": "مستحق اليوم",
    "overdue":   "متأخر",
    # المعنى هنا «انتهت المتابعة» لا «حُفظت الورقة» — والثانيةُ حدثُ عهدةٍ
    # في `core/archive_service.py`. كلمةٌ واحدةٌ لمعنيين تُربك الكاتبَ يوميّاً.
    "archived":  "مُنجَز / بلا متابعة",
    # ≠ «قيد المتابعة» (المستقبليّ وحده) ≠ «مُنجَز / بلا متابعة».
    "active":    "متابعة جارية",
}


def followup_q(state, today=None):
    """كائنُ Q لحالةٍ واحدة — المصدرُ الوحيد: العدّادُ والقائمةُ التي يفتحها يقرآن من هنا فلا ينحرفان.

    «جارية» = غيرُ مؤرشفٍ وله استحقاق = pending ∪ due_today ∪ overdue.
    قيمةٌ مجهولة ⟵ KeyError صادق.
    """
    today = today or timezone.localdate()
    active = Q(is_archived=False, due_date__isnull=False)
    return {
        "active":    active,
        "archived":  Q(is_archived=True) | Q(due_date__isnull=True),
        "overdue":   active & Q(due_date__lt=today),
        "due_today": active & Q(due_date=today),
        "pending":   active & Q(due_date__gt=today),
    }[state]


def day_unit_ar(n):
    """تمييزُ العدد «يوم» بقاعدة العربيّة: 1 يوم · 2 يومان · 3–10 أيّام · 11–99 يوماً · 100+ يوم."""
    if n == 1:
        return "يوم"
    if n == 2:
        return "يومان"
    if 3 <= n % 100 <= 10:
        return "أيّام"
    if 11 <= n % 100 <= 99:
        return "يوماً"
    return "يوم"


def days_ar(n, *, after_preposition=False):
    """«N أيّام» عبارةً تامّة: «يوم واحد»/«يومان» بلا رقم، وما بعدهما بالرقم.
    بعد حرف الجرّ («بعد»/«منذ») يصير المثنّى «يومين» والمفردُ «يوم»."""
    if n == 1:
        return "يوم" if after_preposition else "يوم واحد"
    if n == 2:
        return "يومين" if after_preposition else "يومان"
    return f"{n} {day_unit_ar(n)}"


def followup_phrase(book, today=None):
    """نصُّ رقاقة المتابعة في سطر الكتاب — من ``followup_state`` و``FOLLOWUP_LABELS``
    وحدهما: «متأخر · 9 أيّام» · «مستحق اليوم» · «بعد 3 أيّام» · «مُنجَز / بلا متابعة»."""
    state = book.followup_state
    if state in ("archived", "due_today"):
        return FOLLOWUP_LABELS[state]
    gap = (book.due_date - (today or timezone.localdate())).days
    if state == "overdue":
        return f"{FOLLOWUP_LABELS['overdue']} · {days_ar(-gap)}"
    return f"بعد {days_ar(gap, after_preposition=True)}"


class BookFilterEngine:
    """محرّك فلترة الكتب الموحَّد."""

    # ── فلتر النوع (kind) ─────────────────────────────────────────────
    @staticmethod
    def apply_tab_filter(queryset, tab):
        if not tab or tab == "all":
            return queryset
        if tab in {"incoming_internal", "incoming_external", "outgoing_internal", "outgoing_external"}:
            return queryset.filter(kind=tab)
        # «الكلّ» حالةٌ صريحة بنطاقها (تدقيقُ نيلسن A#6): داخليُّ الاتّجاهين أو خارجيُّهما —
        # كانت أوّلُ نقرةِ نطاقٍ من tab=all تضيّق إلى الوارد صامتةً.
        if tab == "all_internal":
            return queryset.filter(kind__endswith="_internal")
        if tab == "all_external":
            return queryset.filter(kind__endswith="_external")
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
        state ∈ {'active', 'pending', 'due_today', 'overdue', 'archived', None}
        """
        if not state or state not in _FOLLOWUP_TABS:
            return queryset
        return queryset.filter(followup_q(state))

    # ── واجهة موحَّدة لتطبيق كل الفلاتر ────────────────────────────────
    @staticmethod
    def apply_all_filters(queryset, user=None, **filters):
        """
        كل الفلاتر تعمل معاً (orthogonal):
            - tab: نوع الكتاب (incoming/outgoing/all/...)
            - followup: حالة المتابعة (active/pending/due_today/overdue/archived)
            - search_text / date_from / date_to / entity_id

        ``user`` يلزم لحارس البحث السرّي: البحث النصّي لا يكشف كتاباً سرّياً
        لمن لا يملك محتواه (``core.scoping.guard_secret_text_search``). تركُه
        فارغاً يعني «بلا حارس» — ولا يجوز إلّا في مسارٍ لا مستخدمَ فيه.
        """
        search_text = filters.get("search_text", "")
        queryset = BookFilterEngine.apply_tab_filter(queryset, filters.get("tab", "all"))
        queryset = BookFilterEngine.apply_search_filter(queryset, search_text)
        if user is not None:
            from core.scoping import guard_secret_text_search
            queryset = guard_secret_text_search(queryset, user, search_text)
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

        counts = queryset.aggregate(
            all=Count("id"),
            incoming=Count("id", filter=Q(kind__startswith="incoming")),
            outgoing=Count("id", filter=Q(kind__startswith="outgoing")),
            **{k: Count("id", filter=followup_q(k, today)) for k in _FOLLOWUP_STATES},
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
        spec = {
            k: Count("id", distinct=True, filter=followup_q(k, today))
            for k in _FOLLOWUP_STATES
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
            "all_internal": "داخلي", "all_external": "خارجي",
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
        if filters.get("legacy"):
            labels.append("يشمل الورق القديم")
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
    def apply_sort(queryset, sort_field="-date", user=None):
        """``user`` لفرز العنوان وحده: يُفرز على العنوان **كما يراه** (انظر أدناه)،
        وبلا مستخدمٍ يُحجب كلُّ سرّيٍّ مقيَّد — فشلٌ مغلق لا مفتوح."""
        sort_field = (sort_field or "-date").strip()
        # «relevance»: لا نُعيد الترتيب — نحافظ على أولوية صلة البحث القادمة من
        # apply_search_filters (_exact ثم _num_pri: قيدنا قبل رقم الجهة). بدونه كان
        # فرز -date الافتراضي يطمس الأولوية فتظهر مطابقات رقم الجهة فوق مطابقات قيدنا.
        if sort_field == "relevance":
            return queryset
        if sort_field not in BookSortEngine.VALID_SORTS:
            sort_field = "-date"
        resolved = BookSortEngine.VALID_SORTS[sort_field]

        # الفرز بالرقم **رقميّ لا نصّيّ**: نصّياً يأتي '10' قبل '9'، ويعلو
        # الموسوم '20250825' على كل أرقام السلسلة الجارية لأنّ '2' > '1'.
        # نفرز على (السنة الفعّالة، التسلسل) — والسلسلة الجارية تُعامَل بسنة
        # الأساس فتأتي بعد الموسوم بسنته، وهو الترتيب الزمني الصحيح.
        if resolved.lstrip('-') == 'our_number':
            desc = resolved.startswith('-')
            keys = ('-_num_year', '-_num_seq') if desc else ('_num_year', '_num_seq')
            return queryset.annotate(**numbering.sort_key_sql()).order_by(*keys, "-id")

        # الفرز بالعنوان على العنوان **كما يراه القارئ**: الصفُّ المحجوب يُطبع
        # «— سرّي —» لكنّ فرزَه بعنوانه الحقيقيّ يضعه بين جارَين يكشفان بادئتَه،
        # ومن يعدّل عنوانَ كتابٍ يملكه يستخرجه حرفاً حرفاً بالبحث الثنائيّ.
        if resolved.lstrip('-') == 'title':
            from core.scoping import STUB_TITLE, shown_field_sql
            key = '-_shown_title' if resolved.startswith('-') else '_shown_title'
            return (queryset.annotate(_shown_title=shown_field_sql(user, 'title', STUB_TITLE))
                    .order_by(key, "-id"))

        return queryset.order_by(resolved, "-id")
