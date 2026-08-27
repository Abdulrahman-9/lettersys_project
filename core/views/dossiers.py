# -*- coding: utf-8 -*-
"""
الأضابير (Dossiers) — مجلّدات مراسلات الأقسام.

طبقة عرض/استعلام فوق النماذج القائمة:
  - "القسم" = Entity.
  - كتب القسم = اتحاد issuing_entities/receiving_entities (M2M).
  - التقسيم = Book.document_type (مع كتالوج document_types.py + سلّة "متفرقة").

المستوى 1: شبكة الأقسام التي لها كتب مع أعداد صادر/وارد.
المستوى 2: كتب القسم مفلترة (نوع/تاريخ/متابعة/سرية/بحث) + تقسيم بالاتجاه ثم بالنوع
           + إجراءات لكل كتاب.
التقرير: نسخة مطبوعة احترافية للنتائج المفلترة (أو كتاب مفرد).

الأمن: كل الاستعلامات مشتقّة من _visible_books (المشرف/الموظّف يرى الكل؛
المستخدم العادي يرى created_by فقط).

الأداء (8GB): العدّ الدقيق عبر GROUP BY واحد لكل اتجاه؛ صفوف العرض تُمسَح دفعةً
واحدة (.only بلا prefetch) ثم تُقسَّم بايثونياً، ويُجلب prefetch الجهات للمعروض فقط —
بدل استعلام مقطوع لكل نوع (كان يتوسّع خطّياً مع عدد الأنواع).
"""
import logging
from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db.models import Count, F, IntegerField, OuterRef, Q, Subquery, Sum, prefetch_related_objects
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from ..document_types import get_document_type_options, normalize_document_type_value
from ..models import Book, Entity
from .filter_helpers import FOLLOWUP_LABELS, BookFilterEngine, BookSortEngine
from core.scoping import can_view_book, is_privileged

logger = logging.getLogger(__name__)

_MISC_LABEL = "متفرقة"          # سلّة النوع الفارغ
_GROUP_ROW_LIMIT = 12          # أحدث صفوف معروضة لكل مجموعة نوع (الباقي عبر "عرض الكل")
_SUBFILE_ROW_LIMIT = 200       # داخل الملف الثانوي (نوع واحد مفتوح) نعرض أكثر بكثير
_DETAIL_SCAN_CAP = 3000        # سقف مسح صفوف العرض لكل اتجاه (الأحدث) — حماية ذاكرة 8GB
_REPORT_CAP = 2000            # سقف صفوف التقرير لكل اتجاه

_SECRET_LABELS = dict(Book.SECRET_CHOICES)   # مصدر واحد (يتّحد مع get_secret_level_display)

# حقول العرض الدنيا (.only) — تتجنّب جلب أعمدة ثقيلة لا تُعرض
_DETAIL_FIELDS = ("our_number", "title", "document_type", "date",
                  "secret_level", "due_date", "is_archived")
_REPORT_FIELDS = _DETAIL_FIELDS + ("margin",)


# ════════════ أساس مؤمَّن (هزيل — الـprefetch يُضاف عند العرض فقط) ════════════
def _book_base_filter(user):
    """قاعدة الرؤية المؤمَّنة: المشرف/الموظّف = الكل؛ غيرهما = كتبه فقط."""
    f = Q(is_deleted=False)
    if not is_privileged(user):
        f &= Q(created_by=user)
    return f


def _visible_books(request):
    return Book.objects.filter(_book_base_filter(request.user))


def _direction_bases(base, pk):
    """قاعدتا اتجاه الإضبارة: (صادر = الجهة مُصدِرة، وارد = الجهة مستقبِلة) —
    تعبير M2M+distinct بمصدر واحد يخدم التفصيل والتقرير."""
    return (base.filter(issuing_entities__id=pk).distinct(),
            base.filter(receiving_entities__id=pk).distinct())


# ════════════ الفلاتر (مصدر واحد للتفصيل والتقرير) ════════════
def _parse_date(value):
    value = (value or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


# اختصارات الفترة السريعة (على تاريخ الكتاب؛ بداية الأسبوع = السبت — انظر resolve_period_preset)
_PERIOD_PRESETS = [
    ("today", "اليوم"), ("week", "هذا الأسبوع"), ("month", "هذا الشهر"),
    ("quarter", "هذا الربع"), ("year", "هذه السنة"),
]

# أيقونة + مفتاح CSS (بشرطة، لموائمة fb-pill-* في book_unified) لكل حالة متابعة
_CHIP_META = {
    "pending":   ("bi-clock-history", "pending"),
    "due_today": ("bi-calendar-event", "due-today"),
    "overdue":   ("bi-exclamation-triangle", "overdue"),
    "archived":  ("bi-archive", "archived"),
}


def collect_filters(request):
    period = (request.GET.get("period") or "").strip()
    date_from = _parse_date(request.GET.get("date_from"))
    date_to = _parse_date(request.GET.get("date_to"))
    # اختصار الفترة يملأ المدى فقط إن لم يُحدَّد يدوياً (اليدوي يفوز)
    if period and not date_from and not date_to:
        date_from, date_to = BookFilterEngine.resolve_period_preset(period, timezone.localdate())
    return {
        "q": (request.GET.get("q") or "").strip(),
        "document_type": (request.GET.get("document_type") or "").strip(),
        "period": period,
        "date_from": date_from,
        "date_to": date_to,
        "followup": (request.GET.get("followup") or "").strip(),
        "secret_level": (request.GET.get("secret_level") or "").strip(),
        "sort": (request.GET.get("sort") or "-date").strip(),
    }


def _apply_filters(qs, f):
    """فلاتر الإضبارة (بلا فرز) عبر المحرّك المشترك."""
    qs = BookFilterEngine.apply_search_filter(qs, f["q"])
    qs = BookFilterEngine.apply_date_filter(qs, f["date_from"], f["date_to"])
    if f["document_type"] == _MISC_LABEL:
        # سلّة «متفرقة» = الكتب بلا نوع — تُفتح كملف ثانوي مثل بقية الأنواع
        # (نوع حقيقي مُسمّى «متفرقة» حرفياً يندمج معها عرضاً — تصادم مقبول بنفس الدلالة)
        qs = qs.filter(Q(document_type="") | Q(document_type=_MISC_LABEL))
    else:
        qs = BookFilterEngine.apply_document_type_filter(qs, f["document_type"])
    qs = BookFilterEngine.apply_secret_filter(qs, f["secret_level"])
    qs = BookFilterEngine.apply_followup_filter(qs, f["followup"])
    return qs


def _active_filter_count(f):
    return sum(1 for k in ("q", "document_type", "followup", "secret_level") if f.get(k)) \
        + (1 if f.get("date_from") else 0) + (1 if f.get("date_to") else 0)


def _filter_summary(f):
    out = []
    if f.get("q"):             out.append(f"بحث: «{f['q']}»")
    if f.get("document_type"): out.append(f"النوع: {f['document_type']}")
    if f.get("date_from"):     out.append(f"من: {f['date_from']:%Y/%m/%d}")
    if f.get("date_to"):       out.append(f"إلى: {f['date_to']:%Y/%m/%d}")
    if f.get("followup"):      out.append(f"المتابعة: {FOLLOWUP_LABELS.get(f['followup'], f['followup'])}")
    if f.get("secret_level"):  out.append(f"السرية: {_SECRET_LABELS.get(f['secret_level'], f['secret_level'])}")
    return out


# ════════════ تجميع الأنواع ════════════
def _type_meta(qs):
    """لكل نوع مستند (مطبَّع): عدده الدقيق — GROUP BY واحد DB.

    order_by() إلزامي قبل values/annotate لئلا يتسرّب ترتيب موروث إلى GROUP BY.
    """
    meta = {}
    for row in qs.order_by().values("document_type").annotate(c=Count("id", distinct=True)):
        key = normalize_document_type_value(row["document_type"])
        slot = meta.setdefault(key, {"count": 0})
        slot["count"] += row["c"]
    return meta


def _available_types(*metas):
    """قائمة الأنواع المتاحة للقائمة المنسدلة (الكتالوج أولاً ثم القيم الحرّة)."""
    merged = {}
    for meta in metas:
        for key, m in meta.items():
            if key:
                merged[key] = merged.get(key, 0) + m["count"]
    options, seen = [], set()
    for label in get_document_type_options():
        key = normalize_document_type_value(label)
        if key in merged and key not in seen:
            options.append({"value": label, "count": merged[key]})
            seen.add(key)
    for key in sorted(k for k in merged if k not in seen):
        options.append({"value": key, "count": merged[key]})
        seen.add(key)
    return options


def _ordered_type_groups(scan_books, meta, row_limit=_GROUP_ROW_LIMIT):
    """مجموعات الأنواع مرتّبة (كتالوج ← حرّة ← متفرقة).

    العدّ من meta (دقيق DB)؛ صفوف العرض من scan_books (المُقسَّمة بايثونياً، أحدث أولاً).
    كل نوع في meta يظهر ولو بلا صفوف معروضة (نوع قديم خارج نطاق المسح) مع "عرض الكل".
    """
    sampled = {}
    for b in scan_books:
        sampled.setdefault(normalize_document_type_value(b.document_type), []).append(b)

    ordered, seen = [], set()

    def emit(key, label):
        if key in seen or key not in meta:
            return
        seen.add(key)
        rows = sampled.get(key, [])[:row_limit]
        total = meta[key]["count"]
        ordered.append({"type": label, "count": total, "books": rows,
                        "truncated": total > len(rows)})

    for label in get_document_type_options():
        emit(normalize_document_type_value(label), label)
    for key in sorted(k for k in meta if k and k not in seen):
        emit(key, key)
    emit("", _MISC_LABEL)
    return ordered


# ════════════ العروض ════════════
@login_required
@require_http_methods(["GET"])
def dossier_list(request):
    """المستوى 1: الأقسام التي لها كتب (مع أعداد صادر/وارد)، مرتّبة بالأكثر."""
    search_q = (request.GET.get("q") or "").strip()
    base_filter = _book_base_filter(request.user)

    issued_sq = (
        Book.objects.filter(base_filter, issuing_entities=OuterRef("pk"))
        .order_by().values("issuing_entities").annotate(c=Count("id")).values("c")
    )
    received_sq = (
        Book.objects.filter(base_filter, receiving_entities=OuterRef("pk"))
        .order_by().values("receiving_entities").annotate(c=Count("id")).values("c")
    )
    qs = (
        Entity.objects.filter(is_active=True)
        .annotate(
            issued_count=Coalesce(Subquery(issued_sq, output_field=IntegerField()), 0),
            received_count=Coalesce(Subquery(received_sq, output_field=IntegerField()), 0),
        )
        .filter(Q(issued_count__gt=0) | Q(received_count__gt=0))
    )
    if search_q:
        qs = qs.filter(Q(name__icontains=search_q) | Q(code__icontains=search_q))

    # الفرز في DB (لا تجسيد كامل في الذاكرة) + Paginator يطبّق LIMIT/OFFSET
    qs = qs.annotate(total_count=F("issued_count") + F("received_count")).order_by("-total_count", "name")

    paginator = Paginator(qs, 24)
    try:
        page = paginator.page(request.GET.get("page"))
    except PageNotAnInteger:
        page = paginator.page(1)
    except EmptyPage:
        page = paginator.page(paginator.num_pages)

    # الإجماليات: تجميع DB واحد (بلا بثّ صفوف الأقسام إلى بايثون ولا حلقة مُفسَّرة)
    agg = qs.aggregate(
        departments=Count("id"),
        issued=Coalesce(Sum("issued_count"), 0),
        received=Coalesce(Sum("received_count"), 0),
    )

    return render(request, "core/dossier_list.html", {
        "page_obj": page, "paginator": paginator, "search_q": search_q,
        "totals": {"departments": agg["departments"], "issued": agg["issued"], "received": agg["received"]},
    })


@login_required
@require_http_methods(["GET"])
def dossier_detail(request, pk):
    """المستوى 2: كتب القسم مفلترة، مقسّمة بالاتجاه ثم بنوع المستند."""
    entity = get_object_or_404(Entity, pk=pk, is_active=True)
    f = collect_filters(request)
    base = _visible_books(request)

    out_base, in_base = _direction_bases(base, pk)
    outgoing_qs = _apply_filters(out_base, f)
    incoming_qs = _apply_filters(in_base, f)
    out_types = _type_meta(outgoing_qs)
    in_types = _type_meta(incoming_qs)

    # الأنواع المتاحة للقائمة المنسدلة: عند غياب فلتر النوع نعيد استخدام out/in_types
    # (توفير استعلامَي GROUP BY)؛ وإلا نستعلم القائمة الكاملة (بكل الفلاتر عدا النوع).
    if f["document_type"]:
        fnt = {**f, "document_type": ""}
        available_types = _available_types(
            _type_meta(_apply_filters(out_base, fnt)),
            _type_meta(_apply_filters(in_base, fnt)),
        )
    else:
        available_types = _available_types(out_types, in_types)

    # مسح صفوف العرض دفعة واحدة لكل اتجاه (.only بلا prefetch) ثم تقسيم بايثوني.
    # داخل الملف الثانوي (نوع مُنتقى) نرفع سقف الصفوف — إنه العرض المخصّص لذلك النوع.
    row_limit = _SUBFILE_ROW_LIMIT if f["document_type"] else _GROUP_ROW_LIMIT
    out_scan = list(BookSortEngine.apply_sort(outgoing_qs.only(*_DETAIL_FIELDS), f["sort"])[:_DETAIL_SCAN_CAP])
    in_scan = list(BookSortEngine.apply_sort(incoming_qs.only(*_DETAIL_FIELDS), f["sort"])[:_DETAIL_SCAN_CAP])
    outgoing_groups = _ordered_type_groups(out_scan, out_types, row_limit)
    incoming_groups = _ordered_type_groups(in_scan, in_types, row_limit)

    # prefetch الجهات للمعروض فقط (≤ 12×أنواع×اتجاهين) بدل كل المسح
    displayed = [b for g in outgoing_groups for b in g["books"]] \
        + [b for g in incoming_groups for b in g["books"]]
    prefetch_related_objects(displayed, "issuing_entities", "receiving_entities")

    out_count = sum(m["count"] for m in out_types.values())
    in_count = sum(m["count"] for m in in_types.values())

    # ── عدّادات المتابعة (شريط الرقائق): تُحسب بلا فلتر المتابعة كي تعكس كل الحالات،
    #    بحساب آمن ضدّ fan-out (aggregate لكل اتجاه، Count distinct). ──
    if f["followup"]:
        _cf = {**f, "followup": ""}
        out_for_cnt = _apply_filters(out_base, _cf)
        in_for_cnt = _apply_filters(in_base, _cf)
    else:
        out_for_cnt, in_for_cnt = outgoing_qs, incoming_qs
    counters = BookFilterEngine.get_dossier_counter_badges(out_for_cnt, in_for_cnt)
    counter_chips = [
        {"key": k, "label": FOLLOWUP_LABELS[k], "count": counters[k], "active": f["followup"] == k,
         "icon": _CHIP_META[k][0], "css": _CHIP_META[k][1]}
        for k in ("pending", "due_today", "overdue", "archived")
    ]
    period_presets = [{"key": k, "label": lbl, "active": f["period"] == k} for k, lbl in _PERIOD_PRESETS]

    params = request.GET.copy()
    params.pop("page", None)
    # querystring بلا followup (لروابط رقائق العدّادات — كل رقاقة تستبدل followup)
    _qp = params.copy()
    _qp.pop("followup", None)
    qs_no_followup = _qp.urlencode()
    # querystring بلا period/التواريخ (لروابط رقائق الفترة — كل رقاقة تُعيّن period وتُصفّر المدى؛ الـpreset يفوز)
    _qpp = params.copy()
    for _k in ("period", "date_from", "date_to"):
        _qpp.pop(_k, None)
    qs_no_period = _qpp.urlencode()
    # querystring بلا document_type — لروابط بطاقات الملفات الثانوية وكسرة «كل الملفات»
    _qpt = params.copy()
    _qpt.pop("document_type", None)
    qs_no_type = _qpt.urlencode()

    return render(request, "core/dossier_detail.html", {
        "entity": entity,
        "filters": f,
        "available_types": available_types,
        "active_filter_count": _active_filter_count(f),
        "filter_summary": _filter_summary(f),
        "outgoing_groups": outgoing_groups,
        "incoming_groups": incoming_groups,
        "outgoing_count": out_count,
        "incoming_count": in_count,
        "total_count": out_count + in_count,
        "counter_chips": counter_chips,
        "qs_no_followup": qs_no_followup,
        "qs_no_period": qs_no_period,
        "qs_no_type": qs_no_type,
        "period_presets": period_presets,
        "querystring": params.urlencode(),
        "secret_labels": _SECRET_LABELS,
        "followup_labels": FOLLOWUP_LABELS,
    })


@login_required
@require_http_methods(["GET"])
def dossier_report(request, pk):
    """تقرير احترافي مطبوع للنتائج المفلترة (أو كتاب مفرد عبر book_id)."""
    entity = get_object_or_404(Entity, pk=pk, is_active=True)
    f = collect_filters(request)
    base = _visible_books(request)
    out_base, in_base = _direction_bases(base, pk)
    outgoing_qs = _apply_filters(out_base, f)
    incoming_qs = _apply_filters(in_base, f)

    book_id = (request.GET.get("book_id") or "").strip()
    single = book_id.isdigit()
    if single:
        outgoing_qs = outgoing_qs.filter(id=book_id)
        incoming_qs = incoming_qs.filter(id=book_id)

    # نجلب CAP+1 لكشف التجاوز بدقّة (لا off-by-one) ثم نقتطع للعرض
    sort = f["sort"]
    out_raw = list(BookSortEngine.apply_sort(outgoing_qs.only(*_REPORT_FIELDS), sort)[:_REPORT_CAP + 1])
    in_raw = list(BookSortEngine.apply_sort(incoming_qs.only(*_REPORT_FIELDS), sort)[:_REPORT_CAP + 1])
    capped = (len(out_raw) > _REPORT_CAP or len(in_raw) > _REPORT_CAP) and not single
    outgoing = out_raw[:_REPORT_CAP]
    incoming = in_raw[:_REPORT_CAP]
    prefetch_related_objects(outgoing + incoming, "issuing_entities", "receiving_entities")

    report_book = None
    if single:
        report_book = next(iter(outgoing + incoming), None)

    from ..models import EmailSettings
    org = EmailSettings.get()   # هوية المؤسسة لترويسة التقرير (شركة/قسم/وحدة)

    return render(request, "core/dossier_report.html", {
        "entity": entity,
        "org": org,
        "filters": f,
        "filter_summary": _filter_summary(f),
        "outgoing": outgoing,
        "incoming": incoming,
        "outgoing_count": len(outgoing),
        "incoming_count": len(incoming),
        "total_count": len(outgoing) + len(incoming),
        "single_book": single,
        "report_book": report_book,
        "capped": capped,
        "report_cap": _REPORT_CAP,
        "generated_at": timezone.localtime(),
        "user": request.user,
    })
