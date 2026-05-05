# -*- coding: utf-8 -*-
"""
Helper Functions - دوال مساعدة للمعالجات

دوال مساعدة مشتركة بين معالجات الكتب والجهات والمرفقات
"""

from django.db.models import Q, Value
from django.contrib.auth.decorators import user_passes_test


def apply_search_filters(queryset, search_text):
    """
    تطبيق فلاتر البحث على QuerySet الكتب.
    PostgreSQL: بحث نص كامل (FTS) + تشابه Trigram مرتّب حسب الصلة
    SQLite/fallback: بحث بسيط بـ icontains
    """
    if not search_text:
        return queryset

    # ── بحث مباشر بالمعرف الرقمي ──
    if search_text.isdigit():
        id_match = queryset.filter(id=int(search_text))
        if id_match.exists():
            return id_match

    from django.db import connection
    if connection.vendor == 'postgresql':
        return _pg_search(queryset, search_text)
    return _simple_search(queryset, search_text)


def _simple_search(queryset, search_text):
    """Fallback search for SQLite and other non-PostgreSQL backends."""
    from django.db.models import Q
    return (
        queryset.filter(
            Q(our_number__icontains=search_text)
            | Q(sender_number__icontains=search_text)
            | Q(title__icontains=search_text)
            | Q(margin__icontains=search_text)
            | Q(issuing_entities__name__icontains=search_text)
            | Q(receiving_entities__name__icontains=search_text)
        )
        .distinct()
    )


def _pg_search(queryset, search_text):
    """PostgreSQL Full-Text Search + Trigram Similarity."""
    from django.contrib.postgres.search import (
        SearchQuery, SearchRank, SearchVector, TrigramSimilarity,
    )

    vector = (
        SearchVector('our_number', weight='A', config='simple')
        + SearchVector('sender_number', weight='A', config='simple')
        + SearchVector('title', weight='B', config='simple')
        + SearchVector('margin', weight='C', config='simple')
    )
    search_query = SearchQuery(search_text, config='simple')

    return (
        queryset
        .annotate(
            fts_rank=SearchRank(vector, search_query),
            title_sim=TrigramSimilarity('title', search_text),
        )
        .filter(
            Q(fts_rank__gt=0)
            | Q(title_sim__gt=0.15)
            | Q(our_number__icontains=search_text)
            | Q(sender_number__icontains=search_text)
            | Q(issuing_entities__name__icontains=search_text)
            | Q(receiving_entities__name__icontains=search_text)
        )
        .distinct()
        .order_by('-fts_rank', '-title_sim')
    )


def validate_sort_parameters(sort_by, sort_dir):
    """
    التحقق من معاملات الفرز لمنع SQL injection
    
    Args:
        sort_by: حقل الفرز المطلوب
        sort_dir: اتجاه الفرز (asc/desc)
    
    Returns:
        tuple: (حقل_الفرز_الصحيح، الاتجاه_الصحيح)
    """
    valid_sorts = {
        'id': 'id',
        'book_number': 'our_number',
        'our_number': 'our_number',
        'title': 'title',
        'date': 'date',
        'final_status': 'final_status',
        'kind': 'kind'
    }
    
    if sort_by not in valid_sorts:
        sort_by = 'date'
    if sort_dir not in ('asc', 'desc'):
        sort_dir = 'desc'
    
    return valid_sorts[sort_by], sort_dir


def compute_time_state(book):
    """
    حساب حالة الوقت للكتاب (متأخر/قريب من الاستحقاق/آمن)
    
    Returns:
        str: حالة الوقت ('overdue'/'critical'/'warning'/'safe')
    """
    from datetime import timedelta
    from django.utils import timezone
    
    if book.final_status == 'done':
        return 'done'
    
    if not book.due_date:
        return 'safe'
    
    today = timezone.localdate()
    days_left = (book.due_date - today).days
    
    if days_left < 0:
        return 'overdue'
    elif days_left == 0:
        return 'critical'
    elif days_left <= 2:
        return 'warning'
    else:
        return 'safe'


def is_ajax(request):
    """
    دالة مساعدة للتحقق من طلبات AJAX
    
    Returns:
        bool: True إذا كان الطلب AJAX
    """
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


def staff_required(view_func):
    """
    ديكور يسمح بدخول الموظفين أو المدراء فقط
    
    Args:
        view_func: دالة المعالج المراد حمايتها
    
    Returns:
        decorated_func: دالة المعالج المحمية
    """
    return user_passes_test(lambda u: u.is_staff or u.is_superuser)(view_func)
