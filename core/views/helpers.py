# -*- coding: utf-8 -*-
"""
Helper Functions - دوال مساعدة للمعالجات

دوال مساعدة مشتركة بين معالجات الكتب والجهات والمرفقات
"""

from functools import wraps

from django.conf import settings
from django.db.models import Q, Value
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied

from ..scoping import can_manage_accounts, can_manage_mail


def apply_search_filters(queryset, search_text):
    """
    تطبيق فلاتر البحث على QuerySet الكتب.
    PostgreSQL: بحث نص كامل (FTS) + تشابه Trigram مرتّب حسب الصلة
    SQLite (اختبارات): icontains بسيط
    """
    if not search_text:
        return queryset

    # ── بحث مباشر بالمعرف الرقمي ──
    if search_text.isdigit():
        id_match = queryset.filter(id=int(search_text))
        if id_match.exists():
            return id_match

    from django.db import connection
    if connection.vendor != 'postgresql':
        return queryset.filter(
            Q(our_number__icontains=search_text)
            | Q(sender_number__icontains=search_text)
            | Q(title__icontains=search_text)
            | Q(margin__icontains=search_text)
        ).distinct()

    return _pg_search(queryset, search_text)


def _pg_search(queryset, search_text):
    """PostgreSQL Full-Text Search + Trigram Similarity."""
    from django.contrib.postgres.search import (
        SearchQuery, SearchRank, SearchVector, TrigramSimilarity,
    )

    vector = (
        SearchVector('our_number', weight='A', config='simple')
        + SearchVector('sender_number', weight='A', config='simple')
        + SearchVector('director_general_number', weight='A', config='simple')
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
            | Q(director_general_number__icontains=search_text)
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


def privileged_required(view_func):
    """Require account-management access while preserving the app's 403 behavior."""
    return _guarded(view_func, can_manage_accounts, 'هذه الصفحةُ لمدير النظام.')


def mail_manager_required(view_func):
    """Require the mail-management access policy."""
    return _guarded(view_func, can_manage_mail, 'هذه الصفحةُ لمسؤول البريد.')


def _guarded(view_func, allowed, denial):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        user = getattr(request, 'user', None)
        if user is None or not user.is_authenticated:
            return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)
        if not allowed(user):
            raise PermissionDenied(denial)
        return view_func(request, *args, **kwargs)
    return _wrapped
