# -*- coding: utf-8 -*-
"""
Helper Functions - دوال مساعدة للمعالجات

دوال مساعدة مشتركة بين معالجات الكتب والجهات والمرفقات
"""

import re

from django.db.models import Case, IntegerField, Q, Value, When
from django.contrib.auth.decorators import user_passes_test


def apply_search_filters(queryset, search_text):
    """
    تطبيق فلاتر البحث على QuerySet الكتب.
    - مدخل رقمي محض: يبحث في حقول الأرقام (our_number, sender_number).
      الصيغة: YYYYRNNNN (جديد، 9 خانات) أو YYYYNNNN (قديم، 8 خانات).
      في كلتا الصيغتين آخر 4 خانات = NNNN (التسلسل المكمّل بأصفار).
    - مدخل نصي: PostgreSQL FTS أو SQLite icontains.
    """
    if not search_text:
        return queryset

    search_text = search_text.strip()

    # ── بحث برقم مركّب: "X-Y" أو "X/Y" (مثل 2-15 أو 1304/3) ──
    compound_m = re.match(r'^(\d+)[-/](\d+)$', search_text)
    if compound_m:
        x, y = int(compound_m.group(1)), int(compound_m.group(2))
        return queryset.filter(
            Q(series_no=x, version=y)
            | Q(legacy_number__icontains=f"{x}-{y}")
        ).distinct().order_by('-our_number', '-date')

    # ── البحث الرقمي ──
    if search_text.isdigit():
        n = len(search_text)
        ival = int(search_text)
        q = Q()

        if n <= 4:
            # التسلسل قد يكون في صيغتين:
            #  • تاريخي: YYYYNNNN (8) أو YYYYRNNNN (9) — آخر 4 خانات = التسلسل.
            #    نمط مُرسّى بطول كلّي 8-9 يستبعد المركّب (11) فلا يتسرّب زائفاً.
            #  • دائم: {R}{NNNN} (رمز سجل 0-4 ثم التسلسل بلا سنة) — نطابق
            #    "رمز + أصفار بادئة اختيارية + الرقم" حتى النهاية.
            padded = search_text.zfill(4)
            q |= Q(our_number__regex=r'^[0-9]{4,5}' + padded + r'$')          # تاريخي
            q |= Q(our_number__regex=r'^[0-4]0*' + str(ival) + r'$')          # دائم

            # الأرقام المركّبة (series_no)
            q |= Q(series_no=ival)

            # سنة: 4 خانات ضمن نطاق YYYY → ابحث بالبادئة أيضاً
            if n == 4 and 2020 <= ival <= 2099:
                q |= Q(our_number__startswith=search_text)

            # رقم الجهة المرسلة: رقم مستقل (لا يُطابَق كجزء من رقم أطول)
            _sn_pat = r'(^|[^0-9])' + re.escape(search_text) + r'([^0-9]|$)'
            q |= Q(sender_number__iregex=_sn_pat)

            # الأرقام القديمة (legacy) — icontains للمرونة
            q |= Q(legacy_number__icontains=search_text)

            # العنوان والملاحظات — يدعم البحث بالكلمة حتى عند إدخال رقم
            q |= Q(title__icontains=search_text)
            q |= Q(margin__icontains=search_text)
        else:
            # ≥5 خانات: رقم طويل أو جزء من our_number
            q |= Q(our_number__icontains=search_text)
            q |= Q(legacy_number__icontains=search_text)
            q |= Q(sender_number__icontains=search_text)
            q |= Q(title__icontains=search_text)
            q |= Q(margin__icontains=search_text)

        # الترتيب (تحت الترقيم الدائم، حيث يتكرّر التسلسل عبر السجلّات والسنوات):
        #   1) _exact   : مطابقة رقم القيد الكامل حرفياً (مثل كتابة 10089) تتصدّر.
        #   2) _num_pri : مطابقات حقول الأرقام (0-1) قبل ضوضاء العنوان/الهامش (2).
        #   3) -date    : الأحدث أولاً — يضع الكتاب الدائم الحالي فوق التاريخي لنفس
        #                 التسلسل (يُصحّح فرز -our_number النصّي الذي كان يرفع '2025…'
        #                 فوق '10089' لأنّ '2' > '1').
        #   4) -our_number : كسر تعادل ثابت.
        return (
            queryset.filter(q)
            .annotate(
                _exact=Case(
                    When(our_number=search_text, then=Value(0)),
                    default=Value(1), output_field=IntegerField(),
                ),
                _num_pri=Case(
                    When(Q(our_number__icontains=search_text) | Q(series_no=ival),
                         then=Value(0)),
                    When(Q(sender_number__icontains=search_text)
                         | Q(legacy_number__icontains=search_text), then=Value(1)),
                    default=Value(2),
                    output_field=IntegerField(),
                ),
            )
            .distinct()
            .order_by('_exact', '_num_pri', '-date', '-our_number')
        )

    from django.db import connection
    if connection.vendor == 'postgresql':
        return _pg_search(queryset, search_text)
    return _simple_search(queryset, search_text)


def _legacy_flexible_q(search_text):
    """
    يبني Q-filter يطابق legacy_number بمرونة (يتجاهل المسافات/الشرطات بين الكلمات).
    مثال: 'قديم 544' و 'قديم-544' و 'قديم544' كلها تطابق legacy='قديم-544' أو 'قديم-544-2'.
    """
    tokens = [t for t in re.split(r'[\s\-_/،,]+', search_text or '') if t]
    if len(tokens) <= 1:
        return Q(legacy_number__icontains=search_text) if search_text else Q()
    pattern = r'[-\s_/،,]*'.join(re.escape(t) for t in tokens)
    return Q(legacy_number__iregex=pattern)


def _simple_search(queryset, search_text):
    """بحث icontains بسيط — يُستخدم في بيئة SQLite (الاختبارات)."""
    return queryset.filter(
        Q(our_number__icontains=search_text)
        | Q(sender_number__icontains=search_text)
        | Q(legacy_number__icontains=search_text)
        | _legacy_flexible_q(search_text)
        | Q(title__icontains=search_text)
        | Q(margin__icontains=search_text)
        | Q(issuing_entities__name__icontains=search_text)
        | Q(receiving_entities__name__icontains=search_text)
    ).distinct()


def _pg_search(queryset, search_text):
    """PostgreSQL Full-Text Search + Trigram Similarity."""
    from django.contrib.postgres.search import (
        SearchQuery, SearchRank, SearchVector, TrigramSimilarity,
    )

    vector = (
        SearchVector('our_number', weight='A', config='simple')
        + SearchVector('sender_number', weight='A', config='simple')
        + SearchVector('legacy_number', weight='A', config='simple')
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
            | Q(title__icontains=search_text)
            | Q(margin__icontains=search_text)
            | Q(our_number__icontains=search_text)
            | Q(sender_number__icontains=search_text)
            | Q(legacy_number__icontains=search_text)
            | _legacy_flexible_q(search_text)
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
        'kind': 'kind'
    }

    if sort_by not in valid_sorts:
        sort_by = 'date'
    if sort_dir not in ('asc', 'desc'):
        sort_dir = 'desc'

    return valid_sorts[sort_by], sort_dir


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
