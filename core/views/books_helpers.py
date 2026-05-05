# -*- coding: utf-8 -*-
"""
Internal helper functions for book views.
"""

from django.db.models import Case, CharField, Value, When
from django.utils import timezone

from ..models import Entity


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


def annotate_time_state(queryset):
    """
    Annotate QuerySet with time_state using ORM.
    """
    today = timezone.localdate()
    return queryset.annotate(
        time_state=Case(
            When(final_status__in=("done", "hold"), then=Value("normal")),
            When(due_date__isnull=True, then=Value("normal")),
            When(due_date=today, then=Value("today")),
            When(due_date__gt=today, then=Value("future")),
            When(due_date__lt=today, then=Value("danger")),
            default=Value("normal"),
            output_field=CharField(),
        )
    )


def compute_time_state(book):
    """
    Calculate due-date state and delay days.
    """
    state = "normal"
    delay_days = 0

    if book.final_status in ("done", "hold"):
        return state, delay_days

    if not book.due_date:
        return state, delay_days

    today = timezone.localdate()
    delay_days = (today - book.due_date).days

    if delay_days == 0:
        return "today", delay_days
    if delay_days < 0:
        return "future", abs(delay_days)

    return "danger", delay_days


def validate_sort_parameters(sort_by, sort_dir):
    """
    Validate sorting parameters to avoid invalid fields.
    """
    valid_sorts = {
        'id': 'id',
        'book_number': 'our_number',
        'our_number': 'our_number',
        'title': 'title',
        'date': 'date',
        'final_status': 'final_status',
        'kind': 'kind',
    }

    if sort_by not in valid_sorts:
        sort_by = 'date'
    if sort_dir not in ('asc', 'desc'):
        sort_dir = 'desc'

    return valid_sorts[sort_by], sort_dir
