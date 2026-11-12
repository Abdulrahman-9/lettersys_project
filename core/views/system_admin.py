# -*- coding: utf-8 -*-
"""صفحاتُ إدارة النظام: مركزُ الأقسام وصفحةُ القسم وتشغيلُ النظام — لمدير النظام وحده."""
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
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
from core.scoping import (CAPABILITIES, WIRED_CAPABILITIES, can_enter_for, can_use_system_admin, secret_openers,
                          subtree_ids)
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
        # «إدخال في دفتره» لمن يقبله الخادم (``can_enter_for``) — الحفظُ يسأل تأكيداً يسمّي القسمَ والرقم
        'can_enter_here': can_enter_for(request.user, unit),
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
            'wired_text': ' و'.join(f'«{CAPABILITIES[k].label}»' for k in CAPABILITIES if k in WIRED_CAPABILITIES),
        })

    changes, reset = request.POST.getlist('change'), request.POST.get('reset', '')
    if bool(changes) == bool(reset) or (reset and reset != 'all' and reset not in CAPABILITIES):
        return HttpResponseBadRequest('طلبٌ غير مفهوم.')
    parsed = _parse_changes(changes)
    if changes and parsed is None:
        return HttpResponseBadRequest('خليّةٌ غير مفهومة.')
    # صلاحيّةٌ لم يُربط حارسُها لا تُعدَّل: تعديلُها لا يغيّر شيئاً، والصفحةُ تقول «يسري الآن».
    if parsed and any(key not in WIRED_CAPABILITIES for _role, key in parsed):
        raise PermissionDenied('هذه الصلاحيّة لم يُربط حارسُها بعد، فتعديلُها لا يسري.')
    # المعاملةُ الواحدة: خليّةٌ مقفلةٌ في الطلب تُسقطه كلَّه بـ403 فلا يُحفظ نصفُه.
    with transaction.atomic():
        if reset:
            done = permission_service.reset_role_overrides(request, None if reset == 'all' else reset)
        else:
            done = [cell for cell, allowed in parsed.items()
                    if permission_service.set_role_override(request, cell[0], cell[1], allowed)]
    # العودةُ إلى الصفّ الذي عُمل فيه لا إلى رأس الصفحة.
    if reset == 'all':
        back = reverse('system_roles')
    else:
        touched = {reset} if reset else {key for _role, key in parsed}
        back = f"{reverse('system_roles')}#cap-{next(k for k in CAPABILITIES if k in touched)}"
    if not done:
        messages.info(request, 'لم يتغيّر شيء: الخلايا على ما كانت عليه.')
        return redirect(back)
    _admins, holders = permission_service.role_holders()
    roles = {role for role, _key in done}
    people = sum(holders[role] for role in roles)
    cells = count_ar(len(done), 'خليّة واحدة', 'خليّتان', 'خلايا', 'خليّة')
    nobody = {1: 'الدورَ', 2: 'هذين الدورين'}.get(len(roles), 'هذه الأدوارَ')
    reach = f'ويسري الآن على {_people_ar(people)}' if people else f'ولا يحمل {nobody} أحدٌ الآن'
    messages.success(request, f"{'عادت إلى المعتمد' if reset else 'حُفظت'} {cells}، {reach}.")
    return redirect(back)


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


# ───────────────────────── محرّرُ الحساب (ج، الشريحة 2) ─────────────────────────
# التصميمُ المعتمد: shots_v2/v2_account.png و v2_account_change.png. الدورُ الواحدُ يملأ الصلاحيّات،
# والاستثناءُ يضيف أو يحجب لشخصٍ بعينه (الموصولُ وحده)، وتغييرُ الدور أو القسم يُلغي الاستثناءات بتأكيد.

_SUMMARY_SKIP = ('book.read', 'book.comment')


def _join_ar(items):
    items = list(items)
    if len(items) < 2:
        return ''.join(items)
    return '، '.join(items[:-1]) + '، و' + items[-1]


def _account_context(request, target):
    from core.models import UserCapabilityOverride
    from core.permission_service import role_change_preview
    from core.scoping import (CAPABILITIES, WIRED_CAPABILITIES, can_delete_account, has_capability,
                              role_of, roles_for_department)

    profile = getattr(target, 'profile', None)
    department = getattr(profile, 'department', None)
    role = None if target.is_superuser else role_of(target)
    overrides = {row.capability: row for row in
                 UserCapabilityOverride.objects.filter(user=target).select_related('changed_by')}
    groups, can, cannot = {}, [], []
    for key, capability in CAPABILITIES.items():
        allowed = has_capability(target, key)
        row = overrides.get(key)
        if capability.locked:
            state = 'locked'
        elif key not in WIRED_CAPABILITIES:
            state = 'unwired'
        elif row is not None:
            state = 'added' if row.allowed else 'blocked'
        else:
            state = 'role'
        group = groups.setdefault(capability.group, {'name': capability.group, 'rows': [], 'can': 0})
        group['rows'].append({'key': key, 'label': capability.label, 'allowed': allowed, 'state': state,
                              'editable': state in ('role', 'added', 'blocked') and role is not None})
        group['can'] += int(allowed)
        if key in _SUMMARY_SKIP:
            continue
        note = {'added': ' (استثناء)', 'blocked': ' (محجوب عنه)'}.get(state, '')
        (can if allowed else cannot).append(capability.label + note)
    for group in groups.values():
        group['total'] = len(group['rows'])
    exceptions = [{'key': key, 'label': CAPABILITIES[key].label if key in CAPABILITIES else key,
                   'allowed': row.allowed, 'by': row.changed_by.get_username() if row.changed_by else '',
                   'at': row.changed_at}
                  for key, row in overrides.items()]
    options = [] if role is None else [(r, MATRIX_ROLES[r]) for r in roles_for_department(department)]
    scope = 'نطاقه'
    if department is not None:
        scope = 'قسم «%s»%s' % (department.name, ' وما يتبعه' if department.children.exists() else '')
    return {
        'target': target, 'profile': profile, 'department': department,
        'role': role, 'role_label': MATRIX_ROLES.get(role, 'مدير النظام'), 'role_options': options,
        'previews': {r: {**role_change_preview(target, r), 'label': label} for r, label in options if r != role},
        'summary_can': _join_ar(can), 'summary_cannot': _join_ar(cannot), 'scope_text': scope,
        'exceptions': exceptions, 'groups': list(groups.values()),
        'departments': Department.objects.filter(is_active=True).order_by('code'),
        'can_delete': can_delete_account(request.user, target),
        'is_self': target.pk == request.user.pk,
        'audit_url': f"{reverse('audit_log')}?actor={target.get_username()}",
    }


def _account_post(request, target):
    """فعلٌ واحدٌ لكلّ طلب؛ يعيد (رسالة، كلمة مرورٍ مؤقّتة أو None، وجهة أو None)."""
    from core.admin_service import UNSET, assign_user, delete_user, reset_department_user_password
    from core.permission_service import set_user_override, set_user_role
    from core.scoping import CAPABILITIES, WIRED_CAPABILITIES

    action = request.POST.get('action', '')
    if action == 'role':
        if request.POST.get('confirm') != '1':
            raise ValidationError('أكّد تغيير الدور.')
        set_user_role(request, target, request.POST.get('role', ''))
        return 'غُيّر دورُ «%s».' % target.get_username(), None, None
    if action == 'override':
        key = request.POST.get('key', '')
        value = {'allow': True, 'deny': False, 'reset': None}.get(request.POST.get('value'), 'bad')
        if key not in CAPABILITIES or key not in WIRED_CAPABILITIES or value == 'bad':
            raise ValidationError('صلاحيّةٌ لا تُعدَّل من هنا.')
        set_user_override(request, target, key, value)
        return 'حُدِّثت صلاحيّة «%s».' % CAPABILITIES[key].label, None, None
    if action == 'password':
        return 'أُعيد تعيين كلمة المرور، وتظهر الكلمة المؤقّتة مرّةً واحدة.', \
            reset_department_user_password(by=request.user, user=target), None
    if action == 'delete':
        username = target.get_username()
        delete_user(by=request.user, user=target)
        return 'حُذف حساب «%s».' % username, None, f"{reverse('admin_panel')}?tab=users"
    if action == 'save':
        raw = (request.POST.get('department') or '').strip()
        department = Department.objects.filter(pk=raw).first() if raw.isdigit() else None
        current = getattr(getattr(target, 'profile', None), 'department', None)
        if department != current and request.POST.get('confirm_department') != '1':
            raise ValidationError('أكّد تغيير القسم — يُلغي استثناءاتِ الحساب.')
        first, _, last = (request.POST.get('name') or '').strip().partition(' ')
        assign_user(target, by=request.user, department=department if department != current else UNSET,
                    first_name=first, last_name=last.strip(), job_title=request.POST.get('job_title', ''),
                    is_active=bool(request.POST.get('is_active')))
        return 'حُفظ حساب «%s».' % target.get_username(), None, None
    raise ValidationError('إجراءٌ غير معروف.')


@require_http_methods(['GET', 'POST'])
@system_admin_required
def system_account_view(request, pk):
    """محرّرُ الحساب — الدورُ والاستثناءاتُ والحسابُ والدخولُ في صفحةٍ واحدة لمدير النظام."""
    from django.contrib.auth.models import User
    from django.core.exceptions import ValidationError as _VE

    target = get_object_or_404(User.objects.select_related('profile__department'), pk=pk)
    password = None
    if request.method == 'POST':
        try:
            with transaction.atomic():
                message, password, back = _account_post(request, target)
        except (_VE, PermissionDenied) as exc:
            messages.error(request, exc.messages[0] if isinstance(exc, _VE) else str(exc))
            return redirect('system_account', pk=pk)
        messages.success(request, message)
        if back:
            return redirect(back)
        if password is None:
            return redirect('system_account', pk=pk)
        target = User.objects.select_related('profile__department').get(pk=pk)
    response = render(request, 'core/system_admin/account.html',
                      {**_account_context(request, target), 'temp_password': password})
    if password:
        response['Cache-Control'] = 'no-store, private'
        response['Referrer-Policy'] = 'no-referrer'
    return response


# ───────────────────────── إنشاءُ حساب (ج، الشريحة 3) ─────────────────────────
# التصميمُ المعتمد shots_v2/v2_account_new.png: الأدوارُ بحسب القسم المختار (``roles_for_department``)
# وملخّصُ ما سيستطيعه، ثمّ يُفتح محرّرُ الحساب الجديد بكلمته المؤقّتة مرّةً واحدة.

#: مفتاحُ الدور في المصفوفة ⟵ مفتاحُه في ``create_department_user`` (لوحةُ الإدارة القديمة).
_PANEL_ROLE = {'head': 'department_head', 'unit': 'department_head', 'mail': 'controller',
               'archivist': 'archivist', 'entry': 'entry', 'executor': 'executor', 'reader': 'viewer'}
_ROLE_HINTS = {
    'head': 'يدير قسمه وما يتبعه، ويُحيل ويوقّع ويرى التقارير.',
    'mail': 'يمسك ديوان القسم: البريد والطاولة والدفتر والإحالة.',
    'archivist': 'يحفظ ورق القسم ويفتح سرّيّه، ويسترجع من السلّة.',
    'entry': 'يُدخل الكتب ويعدّلها ويحجز أرقامها.',
    'unit': 'يدير موظّفي وحدته، ويُحيل ويتابع تقاريرها.',
    'executor': 'يستلم المُحال إلى وحدته وينجزه، بلا إدخال.',
    'reader': 'يقرأ كتب نطاقه ويعلّق عليها فقط.',
}
_NOTABLE = ('book.enter', 'book.edit', 'book.trash', 'secret.own', 'referral.send', 'mail.operate', 'report.view')


def _new_account_roles():
    """ما يستطيعه كلُّ دورٍ كما المصفوفةُ الآن — الموصولُ وحده كمعاينة تغيير الدور، والقراءةُ للجميع بالنطاق."""
    from core.models import RoleCapabilityOverride
    from core.scoping import role_capability

    overrides = {(r, k): allowed for r, k, allowed in
                 RoleCapabilityOverride.objects.values_list('role', 'capability', 'allowed')}
    meta = {}
    for role, label in MATRIX_ROLES.items():
        can = [c.label for k, c in CAPABILITIES.items()
               if (k == 'book.read' or k in WIRED_CAPABILITIES) and role_capability(role, k, overrides)]
        cannot = [CAPABILITIES[k].label for k in _NOTABLE if not role_capability(role, k, overrides)]
        meta[role] = {'label': label, 'hint': _ROLE_HINTS.get(role, ''), 'can': can, 'cannot': cannot}
    return meta


@require_http_methods(['GET', 'POST'])
@system_admin_required
def system_account_new_view(request):
    """إنشاءُ حسابٍ بدورٍ يناسب قسمه — لمدير النظام؛ والقاعدةُ نفسُها في ``create_department_user``."""
    from django.core.exceptions import ValidationError as _VE

    from core.admin_service import create_department_user
    from core.scoping import roles_for_department

    departments = list(Department.objects.filter(is_active=True).order_by('code'))
    values = {}
    if request.method == 'POST':
        values = {key: (request.POST.get(key) or '').strip()
                  for key in ('name', 'username', 'department', 'job_title', 'role')}
        raw = values['department']
        department = next((d for d in departments if raw.isdigit() and d.pk == int(raw)), None)
        try:
            if department is None:
                raise _VE('اختر قسمَ الحساب.')
            if values['role'] not in roles_for_department(department):
                raise _VE('اختر دوراً يُسند في هذا القسم.')
            first, _, last = values['name'].partition(' ')
            user, password = create_department_user(   # ذرّيّةٌ في داخلها
                by=request.user, department=department, username=values['username'],
                first_name=first, last_name=last.strip(), job_title=values['job_title'],
                role=_PANEL_ROLE[values['role']])
        except (_VE, PermissionDenied) as exc:
            messages.error(request, exc.messages[0] if isinstance(exc, _VE) else str(exc))
        else:
            messages.success(request, 'أُنشئ حساب «%s».' % user.get_username())
            response = render(request, 'core/system_admin/account.html',
                              {**_account_context(request, user), 'temp_password': password})
            response['Cache-Control'] = 'no-store, private'
            response['Referrer-Policy'] = 'no-referrer'
            return response
    return render(request, 'core/system_admin/account_new.html', {
        'departments': departments, 'values': values,
        'roles_meta': _new_account_roles(),
        'department_roles': {str(d.pk): {'roles': list(roles_for_department(d)), 'register': d.holds_register}
                             for d in departments},
        'role_order': list(MATRIX_ROLES),
    })
