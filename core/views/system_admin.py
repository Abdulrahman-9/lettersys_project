# -*- coding: utf-8 -*-
"""صفحاتُ إدارة النظام: مركزُ الأقسام وصفحةُ القسم وتشغيلُ النظام — لمدير النظام وحده."""
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Max
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from core import permission_service, system_centre, system_ops
from core.logging_models import UserActivityLog
from core.models import Book, BookReferral, BookSequence, Department, UserProfile
from core.roles import get_user_role
from core.scoping import CAPABILITIES, can_use_system_admin, secret_openers, subtree_ids
from core.scoping import ROLE_LABELS as MATRIX_ROLES
from core.views.filter_helpers import days_ar, followup_q

ROLE_LABELS = {
    'dept_head': 'رئيس قسم', 'department_head': 'رئيس قسم', 'controller': 'مختصّ البريد',
    'archivist': 'مسؤول أرشفة', 'entry': 'مدخل', 'executor': 'موظّف تنفيذ', 'viewer': 'قارئ',
    'superuser': 'مدير النظام', 'admin': 'مدير النظام',
}


def count_ar(n, one, two, few, many):
    """العددُ والمعدودُ بقاعدة العربيّة: موظّفٌ واحد، موظّفان، 3 موظّفين، 11 موظّفاً."""
    if n == 1:
        return one
    if n == 2:
        return two
    return f'{n} {few}' if 3 <= n <= 10 else f'{n} {many}'


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
        'tree_text': count_ar(len(tree) - 1, 'وحدة تابعة', 'وحدتان تابعتان', 'وحدات تابعة', 'وحدة تابعة'),
        'late_count': late_qs.count(), 'late_age': days_ar((today - oldest).days, after_preposition=True) if oldest else '',
        'open_referrals': BookReferral.objects.filter(book__in=books, status__in=BookReferral.OPEN_STATUSES).count(),
        'secret_count': secret_qs.count(),
        'openers_text': (f"يفتحها {count_ar(openers, 'موظّف واحد', 'موظّفان', 'موظّفين', 'موظّفاً')}" if openers else 'لا يفتحها موظّف نشط الآن'),
        'recent': recent, 'feed': [{'row': e, 'when': system_centre.human_when(e.timestamp, now)} for e in feed],
        'children': [by_id[c.id] for c in unit.children.order_by('code') if c.id in by_id],
        'staff': staff, 'sequences': BookSequence.objects.filter(department=unit).order_by('kind'),
        'all_units': [(r['unit'].id, r['unit'].name) for r in rows],
        'lens_url': f"{reverse('book_unified')}?tab=all&dept={unit.id}",
    })


def _people_ar(n):
    return count_ar(n, 'موظّف واحد', 'موظّفَين', 'موظّفين', 'موظّفاً')


def _parse_changes(values):
    """``role:key:0|1`` لكلّ خليّة ⟵ {(role, key): allowed}، و``None`` لأيّ شيءٍ غير مفهوم أو مكرَّر."""
    changes = {}
    for value in values:
        parts = value.split(':')
        if len(parts) != 3 or parts[0] not in MATRIX_ROLES or parts[1] not in CAPABILITIES or parts[2] not in ('0', '1'):
            return None
        cell = (parts[0], parts[1])
        if cell in changes:
            return None
        changes[cell] = parts[2] == '1'
    return changes


@require_http_methods(['GET', 'POST'])
@system_admin_required
def system_roles_view(request):
    if request.method == 'GET':
        matrix = permission_service.role_matrix()
        now = timezone.localtime()
        for group in matrix['groups']:
            for row in group['rows']:
                if row['last']:
                    by = row['last'].changed_by
                    row['last_text'] = f"عدّلها {by.get_full_name() or by.username if by else 'حساب محذوف'} {system_centre.human_when(row['last'].changed_at, now)}"
        for role in matrix['roles']:
            role['holders_text'] = _people_ar(role['holders']) if role['holders'] else 'لا أحد'
        return render(request, 'core/system_admin/roles.html', {
            'matrix': matrix, 'admins_text': count_ar(matrix['admins'], 'حساب واحد', 'حسابان', 'حسابات', 'حساباً'),
            'columns': len(matrix['roles']) + 2,
        })

    changes, reset = request.POST.getlist('change'), request.POST.get('reset', '')
    if bool(changes) == bool(reset) or (reset and reset != 'all' and reset not in CAPABILITIES):
        return HttpResponseBadRequest('طلبٌ غير مفهوم.')
    parsed = _parse_changes(changes)
    if changes and parsed is None:
        return HttpResponseBadRequest('خليّةٌ غير مفهومة.')
    # المعاملةُ الواحدة: خليّةٌ مقفلةٌ في الطلب تُسقطه كلَّه بـ403 فلا يُحفظ نصفُه.
    with transaction.atomic():
        if reset:
            done = permission_service.reset_role_overrides(request, None if reset == 'all' else reset)
        else:
            done = [cell for cell, allowed in parsed.items()
                    if permission_service.set_role_override(request, cell[0], cell[1], allowed)]
    if not done:
        messages.info(request, 'لم يتغيّر شيء: الخلايا على ما كانت عليه.')
        return redirect('system_roles')
    _admins, holders = permission_service.role_holders()
    roles = {role for role, _key in done}
    people = sum(holders[role] for role in roles)
    cells = count_ar(len(done), 'خليّة واحدة', 'خليّتان', 'خلايا', 'خليّة')
    nobody = {1: 'الدورَ', 2: 'هذين الدورين'}.get(len(roles), 'هذه الأدوارَ')
    reach = f'ويسري الآن على {_people_ar(people)}' if people else f'ولا يحمل {nobody} أحدٌ الآن'
    messages.success(request, f"{'عادت إلى المعتمد' if reset else 'حُفظت'} {cells}، {reach}.")
    return redirect('system_roles')


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
