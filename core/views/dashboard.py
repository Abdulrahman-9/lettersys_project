# -*- coding: utf-8 -*-
"""
Dashboard & Reports Views - لوحة التحكم والتقارير
إحصائيات النظام، التقارير، النسخ الاحتياطي، سلة المهملات
"""

import logging
import os
from datetime import timedelta
from subprocess import CalledProcessError

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Min, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.html import format_html
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..backup_service import create_encrypted_pg_backup, default_backup_dir, list_db_backups
from ..extraction.kinds import get_kind_label
from ..models import (Attachment, AttachmentVersion, Book, BookHistory, Entity,
                      RestoreJob)
from .filter_helpers import (_FOLLOWUP_STATES, FOLLOWUP_LABELS, days_ar, followup_phrase,
                             followup_q)
from .helpers import staff_required
from core.scoping import (STUB_TITLE, books_in_scope, can_edit_book, can_view_reports,
                          is_privileged, report_departments, restricted_flag_sql,
                          subtree_ids)

logger = logging.getLogger(__name__)


class _NoJob:
    """بديل فارغ كي يبقى القالب بسيطاً (id = None ⇒ لا مهمّة حيّة)."""
    id = None


@login_required
def dashboard(request):
    """لوحةُ التحكّم — **لكلّ دورٍ لوحتُه**.

    الأقسامُ تُبنى من `core/dashboard_sections.py`: مسجّلٌ واحدٌ فيه لكلّ قسمٍ
    بوّابتُه وبانيه، فما يراه المستخدمُ حاصلُ صلاحيّاته لا قائمةٌ مكتوبةٌ في
    القالب. موظّفُ الوحدة يرى «ما يخصّني» و«أضبارتَنا»؛ ومختصُّ البريد يرى
    معهما «طاولةَ الوارد» و«البريد»؛ ومديرُ النظام يرى «الإدارة» فوقها.

    **والنظرةُ العامّة صارت على المصدر الوحيد**: كانت هنا نسخةٌ خاصّةٌ من قاعدة
    الرؤية («المشرف الكلّ، وغيرُه كتبَه فقط») سبقت بُعدَ القسم ولم تلحق به —
    فلوحةُ موظّفِ الوحدة كانت تُظهر أصفاراً وهو يعمل كلَّ يوم.

    **والحيُّ وحدَه** (``books_in_scope``، قرارُ المالك 2026‑10‑06): كلُّ رقمٍ هنا
    رابطٌ إلى القائمة، والقائمةُ تعرض الحيَّ افتراضاً — فالرقمُ عددُ ما يفتحه.
    """
    books = books_in_scope(request.user)
    today = timezone.localdate()

    # «جارية» من المصدر الوحيد: الرقمُ هنا والقائمةُ التي يفتحها (`followup=active`)
    # يقرآن القاعدةَ نفسَها فلا ينحرفان.
    active_q = followup_q('active')
    archived_q = followup_q('archived')

    stats = books.aggregate(
        total=Count('id'),
        today_count=Count('id', filter=Q(date=today)),
        # «الأسبوع» = الرابطُ الذي يفتحه (من قبل 7 أيّام إلى اليوم) — كان بلا حدٍّ أعلى فيعدّ
        # الكتبَ المؤرَّخة في المستقبل (خطأ سنةٍ في الإدخال) ولا تُظهرها القائمة
        week_count=Count('id', filter=Q(date__range=(today - timedelta(days=7), today))),
        incoming_total=Count('id', filter=Q(kind__startswith='incoming')),
        outgoing_total=Count('id', filter=Q(kind__startswith='outgoing')),
        incoming_active=Count('id', filter=Q(kind__startswith='incoming') & active_q),
        incoming_archived=Count('id', filter=Q(kind__startswith='incoming') & archived_q),
        outgoing_active=Count('id', filter=Q(kind__startswith='outgoing') & active_q),
        outgoing_archived=Count('id', filter=Q(kind__startswith='outgoing') & archived_q),
        overdue=Count('id', filter=followup_q('overdue', today)),
    )

    from core.dashboard_sections import sections_for
    from core.roles import ROLE_DEFINITIONS, get_user_role

    role = get_user_role(request.user)
    profile = getattr(request.user, 'profile', None)
    sections = sections_for(request.user)

    ctx = {
        "sections":         sections,
        "has_quiet":        any(s['quiet'] for s in sections),
        "today":            today,
        "week_ago":         today - timedelta(days=7),
        "now":              timezone.localtime(),
        "role_label":       ROLE_DEFINITIONS.get(role, {}).get('label', role),
        "my_department":    profile.department if profile else None,
        "total":            stats['total'],
        "today_count":      stats['today_count'],
        "week_count":       stats['week_count'],
        "overdue":          stats['overdue'],
        "active_label":     FOLLOWUP_LABELS['active'],
        "incoming_total":   stats['incoming_total'],
        "outgoing_total":   stats['outgoing_total'],
        "incoming_pending": stats['incoming_active'],
        "incoming_done":    stats['incoming_archived'],
        "outgoing_pending": stats['outgoing_active'],
        "outgoing_done":    stats['outgoing_archived'],
    }
    return render(request, "core/dashboard.html", ctx)


#: دلاءُ التقارير — **مفاتيحُ فلتر المتابعة في القائمة نفسُها** (``_FOLLOWUP_TABS``)
#: و«الكلّ»، بترتيب العرض. كانت للصفحة مفرداتُها الخاصّة (today/upcoming/completed/
#: today_overdue) فلا يطابق رقمُها رقمَ القائمة ولا اللوحة.
REPORT_BUCKETS = ('all', 'active', *_FOLLOWUP_STATES)
#: المفاتيحُ القديمة ⟵ الموحَّدة: روابطُ محفوظةٌ لا تنكسر. «المستحقّ الآن»
#: (``today_overdue``) صار «متابعة جارية» = رقمُ اللوحة، وجزآه ظاهران في
#: بطاقتي «متأخر» و«مستحق اليوم».
_LEGACY_BUCKETS = {'today': 'due_today', 'upcoming': 'pending',
                   'completed': 'archived', 'today_overdue': 'active'}
REPORT_DEFAULT_BUCKET = 'active'
#: التسمياتُ من ``FOLLOWUP_LABELS`` وحدَها — و«مؤرشف» كلمةُ الورق لا المتابعة (``models.py``).
BUCKET_LABELS = {'all': 'كل الحالات', **FOLLOWUP_LABELS}


def _reports_qs(request):
    """يبني queryset التقارير المفلتر والمرتّب حسب فلاتر الصفحة (kind/entity/date/bucket).
    مصدر تصفية واحد مشترك بين عرض التقارير والتصدير (DRY). يُعيد (qs, meta).

    **النطاقُ من المصدر الوحيد** (``scope_books_for``) كاللوحة تماماً: كانت هنا
    نسخةٌ خاصّة («المشرف الكلّ، وغيرُه كتبَه فقط») فيرى موظّفُ القسم في لوحته
    رقمَ قسمه وفي التقارير كتبَه هو. و``restricted`` علَمُ الحجب من SQL
    (``restricted_flag_sql``) تقرؤه ``_shape`` للعرض والتصدير.

    ``meta['base']`` هي المجموعةُ **قبل** دلو الحالة: عدّاداتُ الحالات تُحسب
    عليها (كالقائمة) — وإلّا صار كلُّ ما خارج الدلو صفراً بنائيّاً.

    **والحيُّ وحدَه افتراضاً** (``Book.objects.live()``، قاعدةُ §7.2 وقرارُ المالك
    2026‑09‑29): المنقولُ من الورق بلا استحقاقٍ ولا متابعة، فيُضخّم «مُنجَز»
    ودائرةَ النوع. ``?legacy=1`` يُدخله صراحةً — للصفحة والإحصاء والـCSV معاً.
    """
    user = request.user
    legacy = request.GET.get("legacy") == "1"
    qs = books_in_scope(user, legacy=legacy)
    qs = (qs.select_related("created_by", "department", "current_custody__to_holder_user",
                            "current_custody__to_holder_department")
            .prefetch_related("issuing_entities", "receiving_entities")
            .annotate(restricted=restricted_flag_sql(user)))
    kind = request.GET.get("kind", "all")
    if kind == "incoming":
        qs = qs.filter(kind__startswith="incoming")
    elif kind == "outgoing":
        qs = qs.filter(kind__startswith="outgoing")
    elif kind in ("outgoing_internal", "outgoing_external", "incoming_internal", "incoming_external"):
        qs = qs.filter(kind=kind)

    if kind == "all":
        kind_label = "كل الأنواع"
    elif kind == "incoming":
        kind_label = "كل الوارد"
    elif kind == "outgoing":
        kind_label = "كل الصادر"
    else:
        kind_label = get_kind_label(kind)

    entity_id = request.GET.get("entity")
    if entity_id and entity_id.isdigit():
        # السرّيُّ «لا يُطابَق بجهةٍ» لمن لا يملك محتواه (``guard_secret_text_search``):
        # جهتاه محجوبتان في الصفّ، فإعادتُه بفلترها تكشفهما.
        qs = (qs.filter(Q(issuing_entities__id=entity_id) | Q(receiving_entities__id=entity_id))
                .filter(restricted=False).distinct())

    # القسم: المسموحُ شجرةُ القارئ (``report_departments``)، وما خارجها «غيرُ موجود»
    # لا «ممنوع». والفلترُ يسيل نزولاً كالنطاق: القسمُ يشمل شُعبَه.
    departments = list(report_departments(user).order_by("code"))
    dept = None
    dept_id = request.GET.get("dept", "")
    if dept_id.isdigit():
        dept = next((d for d in departments if d.pk == int(dept_id)), None)
        if dept is None:
            raise Http404("لا قسم بهذا الرقم")
        qs = qs.filter(department_id__in=subtree_ids(dept.pk))

    today = timezone.localdate()
    due_start = request.GET.get("due_start")
    due_end = request.GET.get("due_end")
    start_date = None
    end_date = None
    try:
        if due_start:
            start_date = timezone.datetime.fromisoformat(due_start).date()
        if due_end:
            end_date = timezone.datetime.fromisoformat(due_end).date()
    except ValueError:
        start_date = end_date = None

    if start_date and end_date:
        if start_date > end_date:
            start_date, end_date = end_date, start_date
        qs = qs.filter(due_date__range=(start_date, end_date))
    elif start_date:
        qs = qs.filter(due_date__gte=start_date)
    elif end_date:
        qs = qs.filter(due_date__lte=end_date)

    base = qs
    bucket = request.GET.get("bucket", "")
    bucket = _LEGACY_BUCKETS.get(bucket, bucket)
    if bucket not in REPORT_BUCKETS:
        bucket = REPORT_DEFAULT_BUCKET
    if bucket != "all":
        # المصدرُ الوحيد لقاعدة المتابعة — العدّادُ والقائمةُ واللوحةُ تقرأ من هنا.
        qs = qs.filter(followup_q(bucket, today))

    qs = qs.order_by("due_date", "-date", "-id")
    return qs, {
        "kind": kind, "kind_label": kind_label,
        "entity_id": entity_id or "", "bucket": bucket,
        "due_start": due_start or "", "due_end": due_end or "", "today": today,
        "due_range": (start_date, end_date),
        "base": base,
        "legacy": legacy,
        "departments": departments,
        "dept": str(dept.pk) if dept else "",
        "dept_label": dept.name if dept else "",
        "dept_obj": dept,
    }


def _shape(b):
    """يُلبس الصفَّ محتواه **كما يحقّ لقارئه** — للجدول والتصدير معاً.

    القرارُ علَمُ ``restricted`` من ``_reports_qs`` (``restricted_flag_sql``)؛
    والمحجوبُ ما يُفرَّغ في ``stub_book_payload``: العنوانُ ⟵ ``STUB_TITLE``،
    والجهاتُ وعددُ الجهة وتاريخُها والهامشُ فارغة. والرقمُ والتاريخُ والنوعُ
    والمتابعةُ تبقى — الدفترُ يكشفها. القالبُ والـCSV يقرآن ``shown_*`` وحدَها.

    و«بعهدة» (``current_custody``) محجوبٌ كالجهات — ``None`` للمحجوب و``""``
    لما لم تُسجَّل له عهدة، فلا يُقال عن سرّيٍّ له حاملٌ إنّه بلا عهدة. وفراغُه
    «لم تُسجَّل عهدة» لا «لم يُفرَّق»: العهدةُ تُسجَّل يدويّاً، والتفريقُ شيءٌ آخر.
    """
    r = b.restricted
    b.shown_title = STUB_TITLE if r else b.title
    b.shown_issuing = [] if r else list(b.issuing_entities.all())
    b.shown_receiving = [] if r else list(b.receiving_entities.all())
    b.shown_sender_number = "" if r else b.sender_number
    b.shown_sender_date = None if r else b.sender_date
    b.shown_margin = "" if r else b.margin
    b.shown_holder = None if r else (b.current_custody.holder_name if b.current_custody_id else "")
    b.followup_text = FOLLOWUP_LABELS[b.followup_state]
    return b


def _pct(part, whole):
    return round(100 * part / whole) if whole else 0


def _scope_label(departments, dept):
    """سطرُ النطاق فوق العنوان: القسمُ المختار، أو جذرُ شجرة القارئ، أو «كلّ الأقسام»."""
    def tree(d):
        return d.name + (" وشُعَبُه" if any(x.parent_id == d.pk for x in departments) else "")
    if dept is not None:
        return tree(dept)
    ids = {d.pk for d in departments}
    roots = [d for d in departments if d.parent_id not in ids]
    return tree(roots[0]) if len(roots) == 1 else "كلّ الأقسام"


@login_required
def reports(request):
    """
    تقارير الكتب المستحقة مع فلاتر وتصدير/طباعة
    
    الفلاتر المتاحة:
    - النوع (وارد/صادر)
    - الجهة
    - نطاق تاريخ الاستحقاق
    - حالة المتابعة (``REPORT_BUCKETS`` — مفاتيحُ القائمة وتسمياتُ ``FOLLOWUP_LABELS``)
    
    Args:
        request: HTTP request with filter parameters
    
    Returns:
        Rendered reports template with filtered books and statistics
    """
    if not can_view_reports(request.user):
        raise Http404("لا صفحة بهذا العنوان")
    qs, _m = _reports_qs(request)
    kind = _m["kind"]
    selected_kind_label = _m["kind_label"]
    entity_id = _m["entity_id"]
    bucket = _m["bucket"]
    due_start = _m["due_start"]
    due_end = _m["due_end"]
    today = _m["today"]

    # ── إحصاءات عبر تجميع DB (بلا تحميل كل الصفوف في الذاكرة) ──
    # على المجموعة **قبل** الدلو (كعدّادات القائمة)؛ و``total`` وحده عدُّ الدلو.
    agg = _m["base"].aggregate(
        incoming=Count("id", filter=Q(kind__startswith="incoming")),
        outgoing=Count("id", filter=Q(kind__startswith="outgoing")),
        **{k: Count("id", filter=followup_q(k, today)) for k in ("active", *_FOLLOWUP_STATES)},
        all=Count("id"),
        oldest_overdue=Min("due_date", filter=followup_q("overdue", today)),
        nearest_pending=Min("due_date", filter=followup_q("pending", today)),
    )
    oldest_overdue = agg.pop("oldest_overdue")
    nearest_pending = agg.pop("nearest_pending")
    stats = {k: (v or 0) for k, v in agg.items()}

    # الحفاظ على فلاتر الاستعلام عند تنقّل الصفحات
    page_params = request.GET.copy()
    page_params.pop("page", None)

    def _with(**params):
        """رابطُ الصفحة نفسِها بفلاترها كلّها إلّا ما يُستبدَل — والترقيمُ يعود إلى أوّله."""
        q = page_params.copy()
        for k, v in params.items():
            q[k] = v
        return "?" + q.urlencode()

    # ── شريطُ الحالات: البلاطاتُ هي فلترُ الحالة (رابطٌ يحفظ بقيّة الفلاتر) ──
    # الحصّةُ: «جارية» و«مُنجَز» من الكلّ، والثلاثُ الجارية من «جارية».
    active, every = stats["active"], stats["all"]
    subs = {
        "active": f"من أصل {every}",
        "overdue": (f"أقدمُها منذ {days_ar((today - oldest_overdue).days, after_preposition=True)}"
                    if oldest_overdue else "لا متأخّر"),
        "due_today": "قبل نهاية الدوام" if stats["due_today"] else "لا شيء اليوم",
        "pending": (f"أقربُها بعد {days_ar((nearest_pending - today).days, after_preposition=True)}"
                    if nearest_pending else "لا مواعيد قادمة"),
        "archived": f"{_pct(stats['archived'], every)}% من الكتب",
    }
    tiles = [{
        "key": k, "label": FOLLOWUP_LABELS[k], "num": stats[k], "sub": subs[k],
        "share": _pct(stats[k], every if k in ("active", "archived") else active),
        "url": _with(bucket=k), "on": bucket == k,
    } for k in ("active", "overdue", "due_today", "pending", "archived")]

    # ── بحسب القسم: حين تجتمع في شجرة القارئ أقسامٌ عدّة (شرطُ عددٍ لا دور) ──
    # على المجموعة قبل الدلو كالعدّادات؛ و``distinct`` لأنّ فلتر الجهة يضاعف الصفوف.
    show_department = len(_m["departments"]) > 1
    dept_rows = []
    if show_department:
        dept_rows = list(
            _m["base"].prefetch_related(None).order_by()
            .values("department_id", "department__code", "department__name")
            .annotate(total=Count("id", distinct=True),
                      **{k: Count("id", distinct=True, filter=followup_q(k, today))
                         for k in ("active", *_FOLLOWUP_STATES)})
            .order_by("department__code"))
        # الشريطُ: عرضُه جاريةُ القسم نسبةً إلى أكبرها، وقِطَعُه بحالاتها الثلاث.
        # والاسمُ رابطُ فلترٍ لما في شجرة القارئ وحدَه («بلا قسم» لا فلترَ له).
        allowed = {d.pk for d in _m["departments"]}
        widest = max((r["active"] for r in dept_rows), default=0)
        for row in dept_rows:
            row["label"] = row["department__name"] or "بلا قسم"
            row["bar"] = _pct(row["active"], widest)
            row["url"] = _with(dept=str(row["department_id"])) if row["department_id"] in allowed else ""

    # ── أقدمُ المتأخّرات: أربعٌ بأبعد استحقاق، محجوبةُ المحتوى كالجدول (``_shape``) ──
    late = [_shape(b) for b in _m["base"].filter(followup_q("overdue", today))
                                          .order_by("due_date", "id")[:4]]
    for b in late:
        b.late_days = (today - b.due_date).days

    # ── ترقيم العرض: يمنع تحميل آلاف الكتب دفعةً (مهمّ على ذاكرة محدودة) ──
    page_obj = Paginator(qs, 200).get_page(request.GET.get("page"))
    stats["total"] = page_obj.paginator.count
    books = [_shape(b) for b in page_obj.object_list]
    for b in books:
        b.followup_phrase = followup_phrase(b, today)

    # هوية المؤسسة + ملخّص الفلاتر لترويسة الطباعة الاحترافية — الاسمُ من
    # ``core.branding.org_name`` (مصدرٌ واحدٌ باحتياطيٍّ واحد)، والقسمُ والوحدةُ من الإعدادات
    from ..models import EmailSettings
    from core.branding import org_name
    org = EmailSettings.get()
    selected_entity_name = ""
    if entity_id and entity_id.isdigit():
        _e = Entity.objects.filter(pk=entity_id).only("name").first()
        selected_entity_name = _e.name if _e else ""

    return render(
        request,
        "core/reports.html",
        {
            "stats": stats,
            "books": books,
            "page_obj": page_obj,
            "total": stats["total"],
            "querystring": page_params.urlencode(),
            "entities": Entity.objects.filter(is_active=True).order_by("name"),
            "selected_kind": kind,
            "selected_kind_label": selected_kind_label,
            "selected_entity": entity_id or "",
            "selected_entity_name": selected_entity_name,
            "bucket": bucket,
            "bucket_label": BUCKET_LABELS[bucket],
            "all_buckets_url": _with(bucket="all"),
            "tiles": tiles,
            "late": late,
            "followup_labels": FOLLOWUP_LABELS,
            "due_start": due_start or "",
            "due_end": due_end or "",
            "due_from": _m["due_range"][0],
            "due_to": _m["due_range"][1],
            "today": today,
            "org": org,
            "org_name": org_name(),
            "scope_label": _scope_label(_m["departments"], _m["dept_obj"]),
            "departments": _m["departments"],
            "selected_dept": _m["dept"],
            "dept_label": _m["dept_label"],
            "show_department": show_department,
            "dept_rows": dept_rows,
            "legacy": _m["legacy"],
        },
    )


@login_required
def reports_export(request):
    """تصدير نتائج التقرير المفلترة كملف CSV (يفتح مباشرة في Excel) — نفس فلاتر صفحة التقارير.
    يبثّ الصفوف تدريجياً فيبقى خفيفاً على الذاكرة مهما كبر العدد."""
    import csv
    import io
    from django.http import StreamingHttpResponse

    if not can_view_reports(request.user):
        raise Http404("لا صفحة بهذا العنوان")
    qs, meta = _reports_qs(request)
    # ملفٌّ يخرج من الجهاز بصفوفٍ كثيرة — واقعةُ إخراجٍ لا تُطوى (كتصدير القائمة)
    from core.audit_service import record_event
    record_event(request, 'EXPORT_DATA', metadata={
        'report': 'followup', 'kind': meta['kind'], 'bucket': meta['bucket']})
    # أعمدة تطابق جدول الصفحة الرسمي: تاريخا الكتاب (قيدنا + كتاب الجهة رقماً
    # وتاريخاً) حاضران، ولا معرّفات قاعدة بيانات داخلية في مخرجات رسمية.
    HEADERS = ["رقم القيد", "تاريخ القيد", "العنوان", "النوع",
               "الجهة المُصدِرة", "الجهة المستقبِلة",
               "رقم كتاب الجهة", "تاريخ كتاب الجهة", "تاريخ الإدخال",
               "تاريخ الاستحقاق", "الحالة", "الملاحظات",
               # الجديدُ في الذيل: فهارسُ الأعمدة السابقة يعتمدها مَن يستورد الملفّ
               "القسم", "بعهدة"]

    def _rows():
        buf = io.StringIO()
        buf.write("﻿")  # BOM (يُكتب صراحةً) كي يعرض Excel العربية بلا تشويش
        csv.writer(buf).writerow(HEADERS)
        yield buf.getvalue()
        for b in qs.iterator(chunk_size=500):
            _shape(b)
            buf = io.StringIO()
            csv.writer(buf).writerow([
                # الرقمُ كما يُعرض ويُطبع («825/2025») — ``core/numbering.py`` لا المخزَّنُ الخام
                b.our_number_display,
                b.date.isoformat() if b.date else "",
                b.shown_title or "",
                b.kind_label,
                "، ".join(e.name for e in b.shown_issuing),
                "، ".join(e.name for e in b.shown_receiving),
                b.shown_sender_number or "",
                b.shown_sender_date.isoformat() if b.shown_sender_date else "",
                # يومُ الإدخال **ببغداد** لا بـUTC: كتابٌ أُدخل بعد منتصف الليل
                # محلّيّاً كان يُكتب بتاريخ الأمس.
                timezone.localdate(b.created_at).isoformat() if b.created_at else "",
                b.due_date.isoformat() if b.due_date else "",
                b.followup_text,
                b.shown_margin or "",
                b.department.name if b.department_id else "",
                b.shown_holder or "",
            ])
            yield buf.getvalue()

    resp = StreamingHttpResponse(_rows(), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = 'attachment; filename="report_%s.csv"' % meta["today"].isoformat()
    return resp


@login_required
@require_POST
def restore_book(request, pk):
    """
    استعادة كتاب محذوف من سلة المهملات (POST فقط — يُعدّل الحالة فلا يُسمح بـ GET)
    
    Args:
        request: HTTP request
        pk: معرف الكتاب
    
    Returns:
        Redirect to trash list with success message
    """
    book = get_object_or_404(Book.all_objects, pk=pk, is_deleted=True)
    # الاستعادةُ عكسُ الحذف — للقسم المالك وطاولته والمدير (Q1‑ج)
    if not can_edit_book(book, request.user):
        messages.error(request, "غير مصرح بالاستعادة.")
        return redirect("trash_list")
    book.is_deleted = False
    book.deleted_at = None
    book.deleted_by = None
    book.save(update_fields=["is_deleted", "deleted_at", "deleted_by"])
    Attachment.all_objects.filter(book=book, is_deleted=True).update(is_deleted=False, deleted_at=None, deleted_by=None)
    BookHistory.objects.create(book=book, action="restore", by=request.user)
    messages.success(request, format_html(
        'تمت استعادة الكتاب من سلة المهملات. <a class="alert-link" href="{}">افتحه</a>',
        reverse("book_detail", args=[book.pk])))
    return redirect("trash_list")


@login_required
def purge_book(request, pk):
    """
    حذف كتاب نهائياً من قاعدة البيانات (لا يمكن الاستعادة)
    
    Args:
        request: HTTP POST request
        pk: معرف الكتاب
    
    Returns:
        Redirect to trash list with success message
    """
    # من السلّة وحدَها: المديرُ الافتراضيُّ يُسقط المحذوف، فكان «حذف نهائي» يلقى 404
    # دائماً (تدقيقُ نيلسن 2026‑10‑07، D#1). ومرفقاتُه كلُّها — والمحذوفةُ منها
    # ناعماً — كي لا تبقى ملفّاتُها يتيمةً على القرص.
    book = get_object_or_404(Book.all_objects, pk=pk, is_deleted=True)
    if not is_privileged(request.user):
        messages.error(request, "غير مصرح بالحذف النهائي.")
        return redirect("trash_list")
    if request.method != "POST":
        return redirect("trash_list")
    for att in Attachment.all_objects.filter(book=book):
        for v in att.versions.all():
            try:
                v.file.delete(save=False)
            except Exception:
                pass
            v.delete()
        try:
            att.file.delete(save=False)
        except Exception:
            pass
        att.delete()
    book.delete()
    messages.success(request, "تم حذف الكتاب نهائياً.")
    return redirect("trash_list")


@login_required
@require_POST
def restore_attachment(request, attachment_id):
    """
    استعادة مرفق محذوف (POST فقط — يُعدّل الحالة فلا يُسمح بـ GET)
    
    Args:
        request: HTTP request
        attachment_id: معرف المرفق
    
    Returns:
        Redirect to trash list with success message
    """
    att = get_object_or_404(Attachment.all_objects, id=attachment_id, is_deleted=True)
    if att.book.is_deleted:
        messages.error(request, "لا يمكن استعادة مرفق لكتاب محذوف.")
        return redirect("trash_list")
    if not can_edit_book(att.book, request.user):
        messages.error(request, "غير مصرح بالاستعادة.")
        return redirect("trash_list")
    att.is_deleted = False
    att.deleted_at = None
    att.deleted_by = None
    att.save(update_fields=["is_deleted", "deleted_at", "deleted_by"])
    BookHistory.objects.create(book=att.book, action="restore-attachment", by=request.user, attachment=att)
    messages.success(request, "تمت استعادة المرفق.")
    return redirect("trash_list")


@login_required
def purge_attachment(request, attachment_id):
    """
    حذف مرفق نهائياً من قاعدة البيانات
    
    Args:
        request: HTTP POST request
        attachment_id: معرف المرفق
    
    Returns:
        Redirect to trash list with success message
    """
    # من السلّة وحدَها (المديرُ الافتراضيُّ يُسقط المحذوف — كان 404 دائماً)
    att = get_object_or_404(Attachment.all_objects, id=attachment_id, is_deleted=True)
    if not is_privileged(request.user):
        messages.error(request, "غير مصرح بالحذف النهائي.")
        return redirect("trash_list")
    if request.method != "POST":
        return redirect("trash_list")
    for v in att.versions.all():
        try:
            v.file.delete(save=False)
        except Exception:
            pass
        v.delete()
    try:
        att.file.delete(save=False)
    except Exception:
        pass
    att.delete()
    messages.success(request, "تم حذف المرفق نهائياً.")
    return redirect("trash_list")


@staff_required
def backup_database(request):
    """
    تنفيذ نسخة احتياطية من PostgreSQL باستخدام pg_dump مع التشفير
    
    المميزات:
    - إنشاء dump منطقي من PostgreSQL
    - تشفير النسخة الاحتياطية لحماية البيانات
    - عرض النسخ الاحتياطية الموجودة
    
    Args:
        request: HTTP request (GET or POST)
    
    Returns:
        Rendered backup template or redirect after backup creation
    """
    db_config = settings.DATABASES["default"]
    default_dir = default_backup_dir()
    suggested_name = f"pg_backup_{timezone.now().strftime('%Y%m%d_%H%M')}.dump"

    if request.method == "POST":
        target_directory = request.POST.get("target_directory") or default_dir
        file_name = request.POST.get("file_name") or suggested_name
        try:
            encrypted_path = create_encrypted_pg_backup(target_directory, file_name)
            messages.success(request, f"تم إنشاء نسخة PostgreSQL احتياطية مشفرة: {encrypted_path}")
        except FileNotFoundError as exc:
            logger.error("pg_dump executable is unavailable: %s", exc, exc_info=True)
            messages.error(request, "تعذر العثور على pg_dump. ثبّت أدوات PostgreSQL أو عيّن PG_DUMP_BIN.")
        except CalledProcessError as exc:
            logger.error("pg_dump failed: %s", exc.stderr, exc_info=True)
            messages.error(request, "فشل pg_dump أثناء إنشاء النسخة الاحتياطية. راجع إعدادات اتصال PostgreSQL.")
        except OSError as exc:
            logger.error("Backup file operation failed: %s", exc, exc_info=True)
            messages.error(request, "تعذر كتابة أو تشفير النسخة الاحتياطية في المسار المحدد.")
        return redirect("backup_database")

    backups = list_db_backups(default_dir)

    return render(
        request,
            "core/backup.html",
        {
            "database_name": db_config["NAME"],
            "database_host": db_config.get("HOST") or "localhost",
            "database_port": db_config.get("PORT") or "5432",
            "default_directory": default_dir,
            "suggested_name": suggested_name,
            "existing_backups": backups,
        },
    )


# ══════════════════════════════════════════════════════════════════
#  استعادة البيانات من قاعدة قديمة (SQL Server نوع ARCHMDOC)
# ══════════════════════════════════════════════════════════════════

@staff_required
def data_restore(request):
    """
    استعادة البيانات من قاعدة بريد قديمة عبر اتصال SQL Server.
    GET: نموذج الإدخال.
    POST action=discover: يتصل ويعرض جداول البريد وأعدادها.
    POST action=import:   ينفّذ الاستعادة الكاملة (كتب + جهات + مرفقات) بالتطبيع الصحيح.
    """
    from ..legacy_restore import LegacyRestoreEngine

    # الاعتماد لا يُكتب في القالب ولا يُعاد للمتصفّح. يُقرأ من البيئة، وحقل النموذج
    # يبقى متاحاً لمن يفضّل إدخاله يدوياً.
    saved_password = os.environ.get('LEGACY_SQL_PASSWORD', '')

    ctx = {
        'form': {
            'server': request.POST.get('server', 'localhost'),
            'database': request.POST.get('database', ''),
            'username': request.POST.get('username', 'sa'),
        },
        'has_saved_password': bool(saved_password),
        'state': _restore_state(),
        # مهمّة دمج حيّة (إن وُجدت) — تُلتقط عند فتح الصفحة فيرى المستخدم تقدّمها
        # حتى لو بدأها قبل ساعة ثم أغلق المتصفّح.
        'live_job_id': (RestoreJob.running() or _NoJob).id,
    }

    if request.method == 'POST':
        action = request.POST.get('action', '')

        # ── طريقة 2: استعادة من ملف باكاب (.bak أو مضغوط) ──
        if action == 'restore_from_bak':
            bak_path = (request.POST.get('bak_path') or '').strip()
            bak_server = (request.POST.get('bak_server') or 'localhost').strip()
            bak_user = (request.POST.get('bak_user') or 'sa').strip()
            bak_pass = request.POST.get('bak_password') or saved_password
            bak_work_dir = (request.POST.get('bak_work_dir') or '').strip()
            restore_files = request.POST.get('restore_files') == 'on'
            mode = request.POST.get('merge_mode') or 'skip_existing'
            if mode not in ('fresh', 'skip_existing', 'update_existing'):
                mode = 'skip_existing'
            ctx['form']['bak_path'] = bak_path
            ctx['form']['bak_server'] = bak_server
            ctx['form']['bak_user'] = bak_user
            ctx['form']['bak_work_dir'] = bak_work_dir
            if not bak_path:
                messages.error(request, 'مسار ملف الباكاب مطلوب.')
                return render(request, 'core/data_restore.html', ctx)
            try:
                summary = LegacyRestoreEngine.restore_from_bak(
                    bak_path, sql_server=bak_server, admin_user=bak_user, admin_password=bak_pass,
                    created_by=request.user, restore_files=restore_files, mode=mode,
                    work_dir=bak_work_dir or None,
                )
                if summary.get('aborted'):
                    messages.warning(request, summary.get('reason', 'تم الإيقاف.'))
                else:
                    ctx['summary'] = summary
                    parts = []
                    if summary.get('books'):   parts.append(f"{summary['books']:,} كتاب جديد")
                    if summary.get('updated'): parts.append(f"{summary['updated']:,} مُحدَّث")
                    if summary.get('skipped'): parts.append(f"{summary['skipped']:,} متخطّى")
                    if restore_files and summary.get('files'): parts.append(f"{summary['files']:,} مرفق")
                    if summary.get('dedup_fixed'): parts.append(f"فُكّ {summary['dedup_fixed']} تكرار")
                    messages.success(request, "تمت الاستعادة من الملف: " + ("، ".join(parts) if parts else "لا تغييرات"))
                    _reseed_book_sequences()
            except Exception as e:
                logger.exception('restore_from_bak failed')
                messages.error(request, f'فشل أثناء الاستعادة من الملف: {e}')
            ctx['state'] = _restore_state()
            return render(request, 'core/data_restore.html', ctx)

        # ── طريقة 1: اتصال مباشر بقاعدة حية ──
        server = (request.POST.get('server') or 'localhost').strip()
        database = (request.POST.get('database') or '').strip()
        username = (request.POST.get('username') or 'sa').strip()
        password = request.POST.get('password') or saved_password

        if not database:
            messages.error(request, 'اسم قاعدة البيانات مطلوب.')
            return render(request, 'core/data_restore.html', ctx)

        engine = LegacyRestoreEngine(server, database, username, password)

        if action == 'discover':
            try:
                info = engine.discover()
                ctx['discovery'] = info
                if not info['tables']:
                    messages.warning(request, 'لم يُعثر على جداول بريد (IIMAIL_YYYY ...) في هذه القاعدة.')
                else:
                    total = sum(t['rows'] for t in info['tables'])
                    messages.success(request, f"اتصال ناجح — {len(info['tables'])} جدول، {total:,} سجل، السنوات: {', '.join(info['years'])}")
            except Exception as e:
                logger.exception('data_restore discover failed')
                messages.error(request, f'فشل الاتصال أو الاكتشاف: {e}')
            return render(request, 'core/data_restore.html', ctx)

        if action == 'import':
            # المسار المتزامن أُلغي: الدمج قد يستغرق ساعات، وتشغيلُه داخل الطلب
            # كان ينهي مهلة المتصفّح فيظنّ المستخدم أنه فشل بينما هو ماضٍ.
            # البديل: restore_start ينشئ RestoreJob ويشغّله كعمليةٍ مستقلّة.
            messages.info(request, 'استعمل زرّ «ابدأ الدمج الآن» في الخطوة ٤ — يعمل بالخلفية بمؤشّر تقدّم.')
            ctx['state'] = _restore_state()
            return render(request, 'core/data_restore.html', ctx)

    return render(request, 'core/data_restore.html', ctx)


# ── واجهات JSON لصفحة الاستعادة (كلها قراءة رخيصة عدا reconcile بـ apply) ──

def _restore_engine(request):
    """يبني المحرّك من حقول النموذج، والاعتماد من البيئة إن تُرك الحقل فارغاً."""
    from ..legacy_restore import LegacyRestoreEngine
    return LegacyRestoreEngine(
        (request.POST.get('server') or 'localhost').strip(),
        (request.POST.get('database') or 'ARCHMDOC').strip(),
        (request.POST.get('username') or 'sa').strip(),
        request.POST.get('password') or os.environ.get('LEGACY_SQL_PASSWORD', ''),
    )


def _restore_state():
    """حالة النظام التي تحكم أي خطوة متاحة الآن."""
    total = Book.objects.count()
    stamped = Book.objects.exclude(source_ref='').count()
    return {
        'books': total,
        'stamped': stamped,
        'unstamped': total - stamped,
        'attachments': Attachment.objects.count(),
        'entities': Entity.objects.count(),
    }


@staff_required
@require_POST
def restore_probe(request):
    """يتحقّق من الاتصال ويعرض جداول المصدر وأعدادها — قراءة فقط."""
    try:
        info = _restore_engine(request).discover()
    except Exception as exc:
        logger.warning('restore_probe failed: %s', exc)
        return JsonResponse({'ok': False, 'error': str(exc)}, status=200)
    total = sum(t['rows'] for t in info['tables'])
    return JsonResponse({
        'ok': True, 'years': info['years'], 'tables': info['tables'],
        'total_rows': total, 'state': _restore_state(),
    })


@staff_required
@require_POST
def restore_reconcile(request):
    """
    يربط الكتب الحالية بصفوفها في المصدر ويختم source_ref.
    apply=0 (الافتراضي) معاينة لا تكتب شيئاً.
    """
    apply_it = request.POST.get('apply') == '1'
    try:
        verify = int(request.POST.get('verify_bytes') or 40)
    except ValueError:
        verify = 40
    try:
        report = _restore_engine(request).reconcile(
            apply=apply_it, verify_bytes=max(0, min(verify, 300)))
    except Exception as exc:
        logger.warning('restore_reconcile failed: %s', exc)
        return JsonResponse({'ok': False, 'error': str(exc)}, status=200)
    report['ok'] = True
    report['state'] = _restore_state()
    report['verify_mismatches'] = [list(m) for m in report.get('verify_mismatches', [])]
    return JsonResponse(report)


@staff_required
@require_POST
def restore_start(request):
    """
    يبدأ الدمج كعمليةٍ مستقلّة ويعود فوراً.

    الطلب لا ينفّذ شيئاً: يتحقّق، يُنشئ صفّ مهمّة، يُشغّل الأمر، ويردّ بمعرّفها.
    قبل هذا كان الدمج يعمل داخل الطلب نفسه — فتنتهي مهلة المتصفّح ويظنّ المستخدم
    أنه فشل بينما هو ماضٍ، ولا يبقى منه أثر إن أُغلقت الصفحة.
    """
    import subprocess
    import sys

    from ..models import RestoreJob

    live = RestoreJob.running()
    if live:
        return JsonResponse({'ok': False, 'job_id': live.id,
                             'error': f'توجد مهمّة دمج قيد التنفيذ (#{live.id}). '
                                      'انتظر انتهاءها أو ألغِها قبل بدء أخرى.'})

    mode = request.POST.get('merge_mode') or 'skip_existing'
    if mode not in ('fresh', 'skip_existing', 'update_existing'):
        mode = 'skip_existing'

    password = request.POST.get('password') or os.environ.get('LEGACY_SQL_PASSWORD', '')
    if not password:
        return JsonResponse({'ok': False, 'error': 'كلمة سرّ المصدر مطلوبة.'})

    job = RestoreJob.objects.create(
        created_by=request.user,
        params={
            'server': (request.POST.get('server') or 'localhost').strip(),
            'database': (request.POST.get('database') or 'ARCHMDOC').strip(),
            'username': (request.POST.get('username') or 'sa').strip(),
            'mode': mode,
            'restore_files': request.POST.get('restore_files') == 'on',
            'include_held': request.POST.get('include_held') == 'on',
        },
    )

    # الاعتماد يُمرَّر في بيئة العملية الابنة فقط — لا في صفّ المهمّة ولا في سطر الأوامر.
    env = dict(os.environ, LEGACY_SQL_PASSWORD=password, PYTHONIOENCODING='utf-8')
    creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    try:
        subprocess.Popen(
            [sys.executable, 'manage.py', 'run_restore_job', '--job', str(job.id)],
            cwd=str(settings.BASE_DIR), env=env, creationflags=creationflags,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        job.status = RestoreJob.STATUS_FAILED
        job.error_message = f'تعذّر تشغيل العملية: {exc}'
        job.finished_at = timezone.now()
        job.save(update_fields=['status', 'error_message', 'finished_at'])
        return JsonResponse({'ok': False, 'error': job.error_message})

    return JsonResponse({'ok': True, 'job_id': job.id})


@staff_required
def restore_job_status(request, job_id):
    """حالة مهمّة الدمج — تُستطلَع من الصفحة كل ثانيتين."""
    from ..models import RestoreJob

    job = RestoreJob.objects.filter(pk=job_id).first()
    if not job:
        return JsonResponse({'ok': False, 'error': 'المهمّة غير موجودة.'}, status=404)
    return JsonResponse({
        'ok': True, 'id': job.id, 'status': job.status, 'phase': job.phase,
        'done': job.done_count, 'total': job.total_count, 'percent': job.percent,
        'is_live': job.is_live, 'summary': job.summary, 'error': job.error_message,
        'cancel_requested': job.cancel_requested,
        'state': _restore_state(),
    })


@staff_required
@require_POST
def restore_job_cancel(request, job_id):
    """يطلب الإلغاء — يُفحَص بين الدفعات فلا يُترك مرفقٌ نصفه."""
    from ..models import RestoreJob

    updated = RestoreJob.objects.filter(pk=job_id, status__in=RestoreJob.LIVE_STATUSES) \
                                .update(cancel_requested=True)
    return JsonResponse({'ok': bool(updated),
                         'error': '' if updated else 'المهمّة غير حيّة.'})


@staff_required
@require_POST
def restore_delta(request):
    """يعرض ما الجديد في المصدر مقارنةً بما عندنا — بلا نقل مرفقات."""
    try:
        info = _restore_engine(request).delta()
    except Exception as exc:
        logger.warning('restore_delta failed: %s', exc)
        return JsonResponse({'ok': False, 'error': str(exc)}, status=200)
    info['ok'] = True
    info['state'] = _restore_state()
    return JsonResponse(info)


@staff_required
def bak_browse(request):
    """
    متصفّح ملفات على جهاز الخادم لاختيار ملف باكاب — للقراءة فقط، يعرض المجلدات
    وملفات النسخ الاحتياطي فقط (.bak / .zip / .7z / .tar.gz). يُستخدَم من صفحة الاستعادة.
    """
    import os
    BACKUP_EXTS = ('.bak', '.zip', '.7z', '.tar.gz', '.tgz', '.gz')
    raw = (request.GET.get('path') or '').strip()

    # المستوى الأعلى: الأقراص + مجلدات سريعة
    if not raw or raw in ('/', '\\'):
        roots = []
        for letter in 'CDEFGHIJ':
            d = f"{letter}:\\"
            if os.path.isdir(d):
                roots.append(d)
        quick = []
        # المجلّداتُ السريعة من الإعداد ``BACKUP_BROWSE_QUICK`` (قائمة) — لا مساراتٌ شخصيّة
        # مكتوبةٌ في مستودعٍ عامّ (تدقيقُ نيلسن F، S2)؛ والأقراصُ أعلاه تبلغ أيَّ مجلّدٍ آخر.
        defaults = ('D:\\trackbackup', 'D:\\backups', str(settings.BASE_DIR / 'backups'),
                    os.path.expanduser('~\\Desktop'), os.path.expanduser('~\\Downloads'))
        for q in getattr(settings, 'BACKUP_BROWSE_QUICK', None) or defaults:
            if os.path.isdir(q):
                quick.append(q)
        return JsonResponse({'is_root': True, 'path': '', 'parent': None, 'dirs': roots, 'quick': quick, 'files': []})

    path = os.path.abspath(raw)
    if not os.path.isdir(path):
        return JsonResponse({'error': 'المسار ليس مجلداً موجوداً.'}, status=400)
    try:
        entries = list(os.scandir(path))
    except PermissionError:
        return JsonResponse({'error': 'لا صلاحية وصول لهذا المجلد.'}, status=403)
    except OSError as e:
        return JsonResponse({'error': f'تعذّر الوصول: {e}'}, status=400)

    dirs, files = [], []
    for e in entries:
        try:
            if e.is_dir():
                dirs.append(e.name)
            elif e.is_file() and e.name.lower().endswith(BACKUP_EXTS):
                files.append({'name': e.name, 'size_mb': round(e.stat().st_size / (1024 * 1024), 1)})
        except OSError:
            continue
    dirs.sort(key=str.lower)
    files.sort(key=lambda x: x['name'].lower())

    # الأب: لو كنا في جذر قرص (مثل D:\) فالأب هو قائمة الأقراص
    norm = path.rstrip('\\/')
    if len(norm) == 2 and norm[1] == ':':       # "D:" → جذر القرص
        parent = ''
    else:
        parent = os.path.dirname(norm)
        if len(parent) == 2 and parent[1] == ':':
            parent = parent + '\\'
    return JsonResponse({'is_root': False, 'path': path, 'parent': parent, 'dirs': dirs, 'files': files})


def _reseed_book_sequences():
    """
    يرفع BookSequence.next_number لكل سجلّ إلى ما يضمن ألّا يتكرّر رقم — **ولا يُنزله أبداً**.

    السلسلة لا نهائية بلا تصفير سنوي، فيُحتسب أساسها من أرقام **السلسلة الجارية**
    وحدها (المجرّدة). الموسوم بسنته وكتب التدريب خارج فضائها: لو حُسب '20255782'
    تسلسلاً لقفز العدّاد إلى عشرين مليوناً. والصادر الخارجي لا عدّاد له أصلاً —
    رقمه من مكتب السيد المدير العام.

    العدّاد لا ينزل لأن الرقم قد يكون **محجوزاً الآن** لمستخدم يكتب كتاباً لم يُحفظ بعد
    (BookNumberReservation نشط)، أو قد يكون في حجزٍ ينتظر. إنزال العدّاد كان يمنح
    ذلك الرقم لشخصٍ آخر فيتصادمان. لذا: الجديد = أكبر (العدّاد الحالي، أكبر رقم كتاب،
    أكبر رقم محجوز) + ١. الفجوات مقبولة؛ تكرار الأرقام ليس كذلك.
    """
    from django.db.models import Max

    from .. import numbering
    from ..models import BookNumberReservation, BookSequence

    live = (BookNumberReservation.STATUS_ACTIVE,
            BookNumberReservation.STATUS_REACTIVATED,
            BookNumberReservation.STATUS_COOLDOWN,
            BookNumberReservation.STATUS_USED)

    # مسحة واحدة على الأرقام كلها بدل مسحةٍ لكل سجلّ تُحمّلها في الذاكرة مراراً.
    max_seq = {kind: 0 for kind in numbering.SERIES_KINDS}
    for kind, onum in (Book.objects.exclude(our_number='')
                       .filter(kind__in=numbering.SERIES_KINDS)
                       .values_list('kind', 'our_number').iterator(chunk_size=2000)):
        p = numbering.parse(onum)
        if p.kind_of == 'series' and p.seq:
            max_seq[kind] = max(max_seq[kind], p.seq)

    reserved = dict(BookNumberReservation.objects.filter(status__in=live)
                    .values_list('kind').annotate(m=Max('number')))

    for kind in numbering.SERIES_KINDS:
        obj, _c = BookSequence.objects.get_or_create(
            kind=kind, defaults={'next_number': 1, 'year': timezone.now().year}
        )
        target = max(obj.next_number, max_seq[kind] + 1, (reserved.get(kind) or 0) + 1, 1)
        if target != obj.next_number:
            obj.next_number = target
            obj.save(update_fields=['next_number', 'updated_at'])
