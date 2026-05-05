# -*- coding: utf-8 -*-
"""
Book Filtering Helpers - مساعدات فلترة الكتب الموحدة
يوحد منطق فلترة الصادر والوارد والأحوال والتواريخ
"""

from django.db.models import Q, Case, When, Value, Count, CharField
from django.utils import timezone


class BookFilterEngine:
    """
    محرك فلترة الكتب الموحد - يدعم جميع أنواع الفلترة
    """
    
    @staticmethod
    def apply_tab_filter(queryset, tab):
        """
        تطبيق فلتر التبويب الرئيسي
        
        Args:
            queryset: QuerySet للكتب
            tab: الاختيار الحالي (all, incoming, outgoing, done, overdue, today, upcoming)
        
        Returns:
            QuerySet مفلتر
        """
        if not tab or tab == "all":
            return queryset
        
        today = timezone.localdate()
        
        # Tabs based on kind — supports both 2-type and 4-type values
        EXACT_KINDS = {"incoming_internal", "incoming_external", "outgoing_internal", "outgoing_external"}
        if tab in EXACT_KINDS:
            return queryset.filter(kind=tab)
        elif tab == "incoming":
            return queryset.filter(kind__startswith="incoming")
        elif tab == "outgoing":
            return queryset.filter(kind__startswith="outgoing")
        
        # Tabs based on final_status
        elif tab == "done":
            return queryset.filter(final_status="done")
        
        # Tabs based on due_date and final_status
        elif tab == "overdue":
            return queryset.filter(
                due_date__lt=today,
                final_status__in=("pending", "hold")
            )
        elif tab == "today":
            return queryset.filter(
                due_date=today,
                final_status__in=("pending", "hold")
            )
        elif tab == "upcoming":
            return queryset.filter(
                due_date__gt=today,
                final_status__in=("pending", "hold")
            )
        
        return queryset
    
    @staticmethod
    def apply_search_filter(queryset, search_text):
        """
        تطبيق فلتر البحث النصي — يفوَّض إلى helpers.apply_search_filters
        (مصدر واحد للمنطق يدعم FTS على PostgreSQL)
        """
        from .helpers import apply_search_filters
        return apply_search_filters(queryset, search_text)
    
    @staticmethod
    def apply_date_filter(queryset, date_from=None, date_to=None):
        """
        تطبيق فلتر نطاق التاريخ
        
        Args:
            queryset: QuerySet
            date_from: بداية النطاق (YYYY-MM-DD)
            date_to: نهاية النطاق (YYYY-MM-DD)
        
        Returns:
            QuerySet مفلتر
        """
        if date_from:
            queryset = queryset.filter(date__gte=date_from)
        if date_to:
            queryset = queryset.filter(date__lte=date_to)
        return queryset
    
    @staticmethod
    def apply_entity_filter(queryset, entity_id=None):
        """
        تطبيق فلتر الجهة
        
        Args:
            queryset: QuerySet
            entity_id: معرف الجهة
        
        Returns:
            QuerySet مفلتر
        """
        if entity_id and str(entity_id).isdigit():
            eid = int(entity_id)
            return queryset.filter(
                Q(issuing_entities__id=eid) | Q(receiving_entities__id=eid)
            ).distinct()
        return queryset
    
    @staticmethod
    def apply_status_filter(queryset, status=None):
        """
        تطبيق فلتر الحالة الفردية
        
        Args:
            queryset: QuerySet
            status: الحالة (pending, hold, done)
        
        Returns:
            QuerySet مفلتر
        """
        if status and status in ("pending", "hold", "done"):
            return queryset.filter(final_status=status)
        return queryset
    
    @staticmethod
    def apply_all_filters(queryset, **filters):
        """
        تطبيق جميع الفلاتر مرة واحدة - دالة موحدة
        
        Args:
            queryset: QuerySet
            tab: int التبويب الحالي
            search_text: نص البحث
            date_from: تاريخ البداية
            date_to: تاريخ النهاية
            entity_id: معرف الجهة
            status: الحالة
        
        Returns:
            QuerySet مفلتر
        """
        # Apply tab filter (highest priority)
        tab = filters.get('tab', 'all')
        queryset = BookFilterEngine.apply_tab_filter(queryset, tab)
        
        # Apply search filter
        search_text = filters.get('search_text', '')
        queryset = BookFilterEngine.apply_search_filter(queryset, search_text)
        
        # Apply date range filter
        queryset = BookFilterEngine.apply_date_filter(
            queryset,
            filters.get('date_from'),
            filters.get('date_to')
        )
        
        # Apply entity filter
        queryset = BookFilterEngine.apply_entity_filter(
            queryset,
            filters.get('entity_id')
        )
        
        # Apply status filter (but not if tab already handles it)
        if tab not in ("done", "overdue", "today", "upcoming"):
            status = filters.get('status')
            queryset = BookFilterEngine.apply_status_filter(queryset, status)
        
        return queryset
    
    @staticmethod
    def get_counter_badges(queryset):
        """
        حساب عدادات التبويبات بـ query واحد (Phase 3 optimized)
        
        Args:
            queryset: QuerySet الأساسي (بدون فلاتر)
        
        Returns:
            dict مع عدادات: all, incoming, outgoing, done, overdue, today, upcoming
        """
        from django.db.models import F
        
        today = timezone.localdate()
        
        # تصنيف الحالة الزمنية
        annotated_qs = queryset.annotate(
            time_state=Case(
                When(final_status__in=("done", "hold"), then=Value("normal")),
                When(due_date__isnull=True, then=Value("normal")),
                When(due_date=today, then=Value("today")),
                When(due_date__gt=today, then=Value("future")),
                When(due_date__lt=today, then=Value("danger")),
                default=Value("normal"),
                output_field=CharField()
            )
        )
        
        # عد جميع الفئات بـ query واحد
        counts = annotated_qs.aggregate(
            all=Count('id'),
            incoming=Count('id', filter=Q(kind__startswith="incoming")),
            outgoing=Count('id', filter=Q(kind__startswith="outgoing")),
            done=Count('id', filter=Q(final_status="done")),
            overdue=Count('id', filter=Q(time_state="danger", final_status__in=("pending", "hold"))),
            today=Count('id', filter=Q(time_state="today", final_status__in=("pending", "hold"))),
            upcoming=Count('id', filter=Q(time_state="future", final_status__in=("pending", "hold"))),
        )
        
        return {
            'all': counts.get('all', 0),
            'incoming': counts.get('incoming', 0),
            'outgoing': counts.get('outgoing', 0),
            'done': counts.get('done', 0),
            'overdue': counts.get('overdue', 0),
            'today': counts.get('today', 0),
            'upcoming': counts.get('upcoming', 0),
        }

    @staticmethod
    def active_filters_summary(**filters):
        """
        يُعيد ملخصاً وصفياً للفلاتر النشطة — يُستخدَم في AJAX JSON endpoint.

        Returns:
            dict: {'count': int, 'labels': [str, ...]}
        """
        labels = []
        tab = filters.get('tab', 'all')
        TAB_LABELS = {
            'all': None,
            'incoming': 'وارد',
            'outgoing': 'صادر',
            'incoming_internal': 'وارد داخلي',
            'incoming_external': 'وارد خارجي',
            'outgoing_internal': 'صادر داخلي',
            'outgoing_external': 'صادر خارجي',
            'done': 'منجز',
            'overdue': 'متأخر',
            'today': 'اليوم',
            'upcoming': 'قريب',
        }
        tab_label = TAB_LABELS.get(tab)
        if tab_label:
            labels.append(tab_label)

        if filters.get('search_text'):
            labels.append(f'بحث: {filters["search_text"]}')
        if filters.get('date_from'):
            labels.append(f'من: {filters["date_from"]}')
        if filters.get('date_to'):
            labels.append(f'إلى: {filters["date_to"]}')
        if filters.get('entity_id'):
            labels.append('جهة محددة')
        if filters.get('status') and tab not in ('done', 'overdue', 'today', 'upcoming'):
            STATUS_LABELS = {'pending': 'قيد الإجراء', 'hold': 'معلّق', 'done': 'منجز', 'archived': 'مؤرشف'}
            labels.append(STATUS_LABELS.get(filters['status'], filters['status']))

        return {'count': len(labels), 'labels': labels}


class BookSortEngine:
    """
    محرك الفرز الموحد
    """
    
    VALID_SORTS = {
        'date': 'date',
        '-date': '-date',
        'our_number': 'our_number',
        '-our_number': '-our_number',
        'book_number': 'our_number',
        '-book_number': '-our_number',
        'title': 'title',
        '-title': '-title',
        'due_date': 'due_date',
        '-due_date': '-due_date',
    }
    
    @staticmethod
    def apply_sort(queryset, sort_field='-date'):
        """
        تطبيق الفرز مع التحقق من الصحة
        
        Args:
            queryset: QuerySet
            sort_field: حقل الفرز
        
        Returns:
            QuerySet مرتب
        """
        sort_field = (sort_field or '-date').strip()
        
        if sort_field not in BookSortEngine.VALID_SORTS:
            sort_field = '-date'
        
        return queryset.order_by(sort_field, '-id')
