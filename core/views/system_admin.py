# -*- coding: utf-8 -*-
"""صفحاتُ إدارة النظام: مركزُ الأقسام وصفحةُ القسم وتشغيلُ النظام — لمدير النظام وحده."""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Max
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET

from core import system_centre, system_ops
from core.logging_models import UserActivityLog
from core.models import Book, BookReferral, BookSequence, Department, UserProfile
from core.roles import get_user_role
from core.scoping import can_use_system_admin, secret_openers, subtree_ids
from core.views.filter_helpers import followup_q

ROLE_LABELS = {
    'dept_head': 'رئيس قسم', 'department_head': 'رئيس قسم', 'controller': 'مختصّ البريد',
    'archivist': 'مسؤول أرشفة', 'entry': 'مدخل', 'executor': 'موظّف تنفيذ', 'viewer': 'قارئ',
    'superuser': 'مدير النظام', 'admin': 'مدير النظام',
}


def system_admin_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not can_use_system_admin(request.user):
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return login_required(wrapped)


@require_GET
@system_admin_required
def system_centre_view(request):
    go = (request.GET.get('go') or '').strip()
    if go.isdigit() and Department.objects.filter(pk=go).exists():
        return redirect('system_department', pk=int(go))

    now = timezone.localtime()
    rows, orphan = system_centre.centre_rows(now)
    query = (request.GET.get('q') or '').strip()
    expanded = request.GET.get('more') == '1'
    picked = system_centre.filter_rows(rows, show=request.GET.get('show', ''), query=query, expanded=expanded)
    jobs = system_ops.job_statuses(now)
    backup = jobs[0]
    return render(request, 'core/system_admin/centre.html', {
        'rows': picked['rows'], 'matched': picked['matched'], 'show': picked['show'],
        'filters': picked['filters'], 'query': query, 'expanded': expanded, 'orphan': orphan,
        'backup': backup, 'backup_hour': _backup_hour(), 'failing': sum(1 for j in jobs if j['state'] == system_ops.STALE),
        'disk': system_ops.disk_percent(),
    })


def _backup_hour():
    from core.models import BackupSettings
    return BackupSettings.get().hour


@require_GET
@system_admin_required
def system_department_view(request, pk):
    unit = get_object_or_404(Department.objects.select_related('parent'), pk=pk)
    now = timezone.localtime()
    today = now.date()
    tree = list(subtree_ids(unit.id))
    books = Book.objects.filter(is_training=False, department_id__in=tree)
    rows, _orphan = system_centre.centre_rows(now)
    by_id = {row['unit'].id: row for row in rows}
    row = by_id[unit.id]

    late_qs = books.filter(followup_q('overdue', today))
    oldest = late_qs.order_by('due_date').values_list('due_date', flat=True).first()
    secret_qs = books.exclude(secret_level__in=['', 'normal'])
    sample_secret = secret_qs.first()
    openers = len(secret_openers(sample_secret)) if sample_secret else 0

    recent = list(books.select_related('department').order_by('-date', '-id')[:5])
    for book in recent:
        book.is_late = bool(book.due_date and book.due_date < today and not book.is_archived)
    feed = (UserActivityLog.objects.filter(department_id__in=tree)
            .select_related('user', 'book').order_by('-timestamp')[:6])
    profiles = list(UserProfile.objects.filter(department=unit).select_related('user')
                    .order_by('-user__is_active', 'user__username'))
    last_seen = dict(UserActivityLog.objects.filter(user__in=[p.user_id for p in profiles])
                     .values('user_id').annotate(at=Max('timestamp')).order_by().values_list('user_id', 'at'))
    staff = [{'name': p.user.get_full_name() or p.user.username, 'active': p.user.is_active,
              'role': ROLE_LABELS.get(get_user_role(p.user), 'قارئ'),
              'last': system_centre.human_when(last_seen.get(p.user_id), now)} for p in profiles]
    return render(request, 'core/system_admin/department.html', {
        'unit': unit, 'row': row, 'tree_size': len(tree) - 1,
        'late_count': late_qs.count(), 'late_days': (today - oldest).days if oldest else 0,
        'open_referrals': BookReferral.objects.filter(book__in=books, status__in=BookReferral.OPEN_STATUSES).count(),
        'secret_count': secret_qs.count(), 'openers': openers,
        'recent': recent, 'feed': [{'row': e, 'when': system_centre.human_when(e.timestamp, now)} for e in feed],
        'children': [by_id[c.id] for c in unit.children.order_by('code') if c.id in by_id],
        'staff': staff, 'sequences': BookSequence.objects.filter(department=unit).order_by('kind'),
        'all_units': [(r['unit'].id, r['unit'].name) for r in rows],
        'lens_url': f"{reverse('book_unified')}?tab=all&dept={unit.id}",
    })


@require_GET
@system_admin_required
def system_ops_view(request):
    now = timezone.localtime()
    source = request.GET.get('log', '')
    source = source if source in system_ops.LOG_SOURCES else 'system'
    errors_only = request.GET.get('all') != '1'
    query = (request.GET.get('q') or '').strip()[:100]
    lines, log_error = system_ops.read_log(source, errors_only=errors_only, query=query)
    return render(request, 'core/system_admin/ops.html', {
        'jobs': system_ops.job_statuses(now), 'services': system_ops.service_errors(now),
        'lines': lines, 'log_error': log_error, 'source': source, 'errors_only': errors_only, 'query': query,
        'sources': [{'key': k, 'label': v[0], 'on': k == source} for k, v in system_ops.LOG_SOURCES.items()],
        'tail_kb': system_ops.LOG_TAIL_BYTES // 1024,
    })
