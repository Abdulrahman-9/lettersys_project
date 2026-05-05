# -*- coding: utf-8 -*-
"""
Internal helper functions for books views.
These are private to the books package and not exported publicly.
"""
from django.db.models import Case, CharField, Value, When
from django.utils import timezone


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
    ✅ PHASE 3 OPTIMIZATION: Annotate QuerySet with time_state using ORM.

    Replicates compute_time_state logic at the database level for efficiency.
    Returns QuerySet with 'time_state' annotation:
        - 'normal': final_status in ['done', 'hold'] OR no due_date
        - 'today':  due_date == TODAY
        - 'future': due_date > TODAY
        - 'danger': due_date < TODAY  (overdue)

    Performance Impact:
        BEFORE: 1000 books = 1 query + 1000 compute_time_state() calls in Python
        AFTER:  1000 books = 1 query with annotation (all logic in SQL)
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
    حساب حالة الاستحقاق الزمنية والفرق بالأيام.

    Returns:
        tuple: (state, delay_days)
            state: 'normal', 'today', 'future', or 'danger'
            delay_days: number of days late/upcoming
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
    التحقق من معاملات الفرز لمنع SQL injection.

    Returns:
        tuple: (validated_field, validated_direction)
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
