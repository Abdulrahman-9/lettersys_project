# -*- coding: utf-8 -*-
"""
Internal helper functions for book views.
"""

from django.db.models import Case, CharField, Q, Value, When
from django.utils import timezone

from ..models import Book, Entity


# ── كشف التكرار ──────────────────────────────────────────────────────────
# الصفات الأربع التي تُطابِق كتاباً تطابقاً تامّاً (طلب المالك):
#   1) العنوان   2) تاريخ الطرف   3) اسم جهة الطرف   4) رقم الطرف (رقم صادرهم)
# تطابق 4/4 = مكرر مؤكَّد (يُمنَع)؛ 3/4 = مشابه (تنبيه ذكي). الفراغ لا يُحتسب مطابقةً.

def _norm_ar(s):
    """تطبيع عربي خفيف لمقارنة العناوين/الأسماء — يعيد استخدام مطبِّع مطابقة الجهات (DRY)."""
    from ..extraction.matchers.entity import _normalize_ar
    return _normalize_ar(s)


def _book_party_names(book, is_incoming):
    """أسماء جهات الطرف الآخر (مطبَّعة) لكتابٍ مرشَّح — تشمل الجهات الحيّة والمؤرشفة نصّاً."""
    if is_incoming:
        live = book.issuing_entities.all()
        archived = book.archived_issuing_names or []
    else:
        live = book.receiving_entities.all()
        archived = book.archived_receiving_names or []
    names = {_norm_ar(e.name) for e in live}
    names |= {_norm_ar(n) for n in archived}
    return {n for n in names if n}


def find_duplicate_candidates(*, kind, title, cmp_date, party_number,
                              party_entities, exclude_id=None, limit=5):
    """يبحث عن كتبٍ مطابقة/مشابهة وفق الصفات الأربع، ويُعيد قائمة dict مرتّبة تنازلياً
    بعدد المطابقات (match_count ∈ {3,4} فقط — ما دونها ليس تنبيهاً).

    Args:
        kind:            نوع الكتاب (نطاق البحث — نفس النوع فقط)
        title:           عنوان الكتاب المُدخَل
        cmp_date:        تاريخ المقارنة (sender_date للوارد، date للصادر) — أو None
        party_number:    رقم الطرف (sender_number) — أو ''
        party_entities:  قائمة كائنات Entity لجهة الطرف الآخر (مُصدِرة للوارد/مُستلمة للصادر)
        exclude_id:      استثناء كتاب (للتعديل)
        limit:           أقصى عدد مرشّحين يُعادون

    Returns: list[dict] بالمفاتيح: id, our_number, title, date, match_count, matched
    """
    is_incoming = kind in ('incoming_internal', 'incoming_external')
    ntitle = _norm_ar(title)
    nnumber = (party_number or '').strip()
    nparty = {_norm_ar(e.name) for e in (party_entities or [])}
    nparty = {n for n in nparty if n}
    party_ids = [e.pk for e in (party_entities or []) if getattr(e, 'pk', None)]

    # مرشّحون أوّليّون على DB: نفس النوع + غير محذوف + أيّ إشارة قوية (تاريخ/رقم/عنوان/جهة).
    # OR-net واسع بما يكفي ليضمّ كل مطابقة حقيقية (3/4 قد لا تشمل العنوان)، ومحدود بسقف.
    base = Book.objects.filter(kind=kind, is_deleted=False)
    if exclude_id:
        base = base.exclude(pk=exclude_id)

    prelim = Q()
    if title.strip():
        prelim |= Q(title__icontains=title.strip()[:80])
    if cmp_date:
        prelim |= (Q(sender_date=cmp_date) if is_incoming else Q(date=cmp_date))
    if nnumber:
        prelim |= Q(sender_number=nnumber)
    if party_ids:
        rel = 'issuing_entities__in' if is_incoming else 'receiving_entities__in'
        prelim |= Q(**{rel: party_ids})
    if not prelim:
        return []

    candidates = (base.filter(prelim)
                      .prefetch_related('issuing_entities', 'receiving_entities')
                      .distinct()[:300])

    results = []
    for b in candidates:
        matched = []
        if ntitle and _norm_ar(b.title) == ntitle:
            matched.append('title')
        b_date = b.sender_date if is_incoming else b.date
        if cmp_date and b_date and b_date == cmp_date:
            matched.append('date')
        if nparty and (nparty & _book_party_names(b, is_incoming)):
            matched.append('entity')
        b_number = (b.sender_number or '').strip()
        if nnumber and b_number and b_number == nnumber:
            matched.append('number')

        if len(matched) >= 3:
            results.append({
                'id': b.id,
                'our_number': b.our_number,
                'our_number_display': b.our_number_display,
                'title': b.title,
                'date': (b_date.isoformat() if b_date else ''),
                'match_count': len(matched),
                'matched': matched,
            })

    results.sort(key=lambda r: r['match_count'], reverse=True)
    return results[:limit]


def _resolve_entities(ids_list, new_names_list, default_etype):
    """
    Convert lists of IDs and new names into Entity objects for M2M assignment.
    - Fetches existing entities via in_bulk (single query)
    - Creates new entities via get_or_create
    - Activates inactive entities
    - Deduplicates while preserving order
    """
    clean_ids = []
    for eid in (ids_list or []):
        eid = str(eid).strip()
        if not eid:
            continue
        try:
            clean_ids.append(int(eid))
        except (TypeError, ValueError):
            continue

    entities = []
    inactive_to_activate = []

    if clean_ids:
        fetched = Entity.objects.in_bulk(clean_ids)
        for pk in clean_ids:
            e = fetched.get(pk)
            if not e:
                continue
            if not e.is_active:
                inactive_to_activate.append(e.pk)
                e.is_active = True
            entities.append(e)

    for name in (new_names_list or []):
        name = str(name).strip()
        if not name:
            continue
        e, _ = Entity.objects.get_or_create(
            name__iexact=name,
            defaults={'name': name, 'etype': default_etype, 'is_active': True}
        )
        if not e.is_active:
            inactive_to_activate.append(e.pk)
            e.is_active = True
        entities.append(e)

    if inactive_to_activate:
        Entity.objects.filter(pk__in=inactive_to_activate).update(is_active=True)

    seen_ids = set()
    unique = []
    for e in entities:
        if e.pk in seen_ids:
            continue
        seen_ids.add(e.pk)
        unique.append(e)
    return unique


def _normalize_secret_level_value(value):
    normalized = (value or 'normal').strip().lower()
    aliases = {
        '': 'normal',
        'normal': 'normal',
        'confidential': 'secret',
        'secret': 'secret',
        'top_secret': 'topsecret',
        'topsecret': 'topsecret',
    }
    return aliases.get(normalized, 'normal')


def annotate_followup_state(queryset):
    """
    يلحق بكل صف حقل followup_state بإحدى القيم الأربع:
        'archived' | 'overdue' | 'due_today' | 'pending'
    منطق محسوب بالكامل على مستوى DB — مصدر حقيقة واحد للفلترة والعرض.
    """
    today = timezone.localdate()
    return queryset.annotate(
        followup_state=Case(
            When(is_archived=True, then=Value("archived")),
            When(due_date__isnull=True, then=Value("archived")),
            When(due_date__lt=today, then=Value("overdue")),
            When(due_date=today, then=Value("due_today")),
            When(due_date__gt=today, then=Value("pending")),
            default=Value("archived"),
            output_field=CharField(),
        )
    )


def compute_followup_state(book):
    """
    حالة المتابعة + عدد الأيام (موجب دائماً).
    يفوّض إلى الـ properties في الـ Model — مصدر حقيقة واحد.
    Returns: (state, delay_days)
    """
    return book.followup_state, book.delay_days


def validate_sort_parameters(sort_by, sort_dir):
    """التحقق من معاملات الفرز لمنع SQL injection."""
    valid_sorts = {
        'id': 'id',
        'book_number': 'our_number',
        'our_number': 'our_number',
        'title': 'title',
        'date': 'date',
        'kind': 'kind',
    }

    if sort_by not in valid_sorts:
        sort_by = 'date'
    if sort_dir not in ('asc', 'desc'):
        sort_dir = 'desc'

    return valid_sorts[sort_by], sort_dir
