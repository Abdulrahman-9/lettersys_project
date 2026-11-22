# -*- coding: utf-8 -*-
"""صفحاتُ إدارة النظام: مركزُ الأقسام وصفحةُ القسم وتشغيلُ النظام — لمدير النظام وحده."""
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from datetime import timedelta

from django.core.paginator import Paginator
from django.db.models import Count, Max, Q
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods

from core import permission_service, system_centre, system_ops
from core.field_errors import FIELD_CODE, error_for
from core.logging_models import UserActivityLog
from core.models import Book, BookNumberReservation, BookReferral, BookSequence, Department, UserProfile
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
    if go.isdecimal() and Department.objects.filter(pk=go).exists():
        return redirect('system_department', pk=int(go))

    now = timezone.localtime()
    rows, orphan = system_centre.centre_rows(now)
    query = (request.GET.get('q') or '').strip()
    expanded = request.GET.get('more') == '1'
    picked = system_centre.filter_rows(rows, show=request.GET.get('show', ''), query=query, expanded=expanded)
    jobs = system_ops.job_statuses(now)
    backup = jobs[0]
    # «حالة الخادم» أوّلُ ما يراه المدير العامّ: هذه صفحتُه بعد الدخول (مقيسٌ 11-19)، لا اللوحة
    from core.scoping import can_view_server_status
    from core.server_status.checks import strip_summary
    return render(request, 'core/system_admin/centre.html', {
        'rows': picked['rows'], 'matched': picked['matched'], 'show': picked['show'],
        'filters': picked['filters'], 'query': query, 'expanded': expanded, 'orphan': orphan,
        'backup': backup, 'backup_hour': _backup_hour(), 'failing': sum(1 for j in jobs if j['state'] == system_ops.STALE),
        'disk': system_ops.disk_percent(),
        'server_strip': strip_summary() if can_view_server_status(request.user) else None,
    })


@require_GET
@system_admin_required
def system_ui_kit_view(request):
    """لوحةُ المكوّنات — كلُّ توستٍ وحوارٍ وزرٍّ في حالاته وفي الوضعين، مرجعُ الصفحات القادمة (11-15)."""
    return render(request, 'core/system_admin/ui_kit.html')


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


#: تقريرُ الحجوزات (الدفعة 1: كان تبويباً في لوحة الإدارة المستقلّة)
RESERVATION_REPORT_DAYS = (7, 30, 90)
RESERVATION_REPORT_PAGE_SIZE = 50


def _reservation_report(request):
    """ملخّصٌ للقراءة فقط: كلّ الحجوزات القائمة وسجلّات الفترة المختارة."""
    now = timezone.now()
    raw_days = request.GET.get('days', '')
    # isdecimal لا isdigit: «²» رقمٌ عند isdigit ويُسقط int() بخطأ 500
    days = int(raw_days) if raw_days.isdecimal() and int(raw_days) in RESERVATION_REPORT_DAYS else 7
    cutoff = now - timedelta(days=days)
    live_statuses = (
        BookNumberReservation.STATUS_ACTIVE,
        BookNumberReservation.STATUS_REACTIVATED,
    )
    rows = (
        BookNumberReservation.objects.filter(
            Q(status__in=live_statuses)
            | Q(status=BookNumberReservation.STATUS_COOLDOWN,
                cooldown_until__gt=now)
            | Q(assigned_at__gte=cutoff)
            | Q(assigned_at__isnull=True, reserved_at__gte=cutoff)
        )
        .select_related('user', 'department')
        .order_by('-assigned_at', '-reserved_at', '-pk')
    )
    status_counts = {
        row['status']: row['total']
        for row in rows.order_by().values('status').annotate(total=Count('pk'))
    }
    summary = {
        'total': rows.count(),
        'active': rows.filter(status__in=live_statuses, expires_at__gt=now).count(),
        'overdue_active': rows.filter(status__in=live_statuses, expires_at__lte=now).count(),
        'cooldown': rows.filter(status=BookNumberReservation.STATUS_COOLDOWN,
                                cooldown_until__gt=now).count(),
        'elapsed_cooldown': rows.filter(status=BookNumberReservation.STATUS_COOLDOWN).filter(
            Q(cooldown_until__isnull=True) | Q(cooldown_until__lte=now)).count(),
        'used': status_counts.get(BookNumberReservation.STATUS_USED, 0),
        'expired': status_counts.get(BookNumberReservation.STATUS_EXPIRED, 0),
        'voided': status_counts.get(BookNumberReservation.STATUS_VOIDED, 0),
        'recycled': rows.filter(is_recycled=True).count(),
    }

    page_obj = Paginator(rows, RESERVATION_REPORT_PAGE_SIZE).get_page(request.GET.get('page'))
    report_rows = []
    for reservation in page_obj.object_list:
        # «فائت» = حجزٌ تجاوز موعدَه ولم يُنظَّف بعد — نبرتُه تُقرَّر هنا لا من نصّ التسمية
        stale = False
        if reservation.status in live_statuses and reservation.expires_at <= now:
            status_label, stale = 'انتهت المهلة — بانتظار التنظيف', True
        elif reservation.status == BookNumberReservation.STATUS_COOLDOWN:
            if reservation.cooldown_until and reservation.cooldown_until > now:
                status_label = 'فترة السماح'
            else:
                status_label, stale = 'انتهت فترة السماح — بانتظار التدوير', True
        else:
            status_label = reservation.get_status_display()

        assigned_at = reservation.assigned_at
        age_seconds = (max(0, int((now - assigned_at).total_seconds()))
                       if assigned_at else None)
        if age_seconds is None:
            age_label = 'غير متاح'   # يُشرح مرّةً تحت الجدول (has_legacy) لا في كلّ صفّ
        elif age_seconds < 60:
            age_label = 'أقل من دقيقة'
        elif age_seconds < 3600:
            age_label = f'{age_seconds // 60} دقيقة'
        elif age_seconds < 86400:
            age_label = f'{age_seconds // 3600} ساعة'
        else:
            age_label = f'{age_seconds // 86400} يوم'
        deadline = (reservation.cooldown_until
                    if reservation.status == BookNumberReservation.STATUS_COOLDOWN
                    else reservation.expires_at)
        report_rows.append({
            'reservation': reservation,
            'legacy': age_seconds is None,
            'status_label': status_label,
            'stale': stale,
            'age_label': age_label,
            'assigned_at': timezone.localtime(assigned_at) if assigned_at else None,
            'deadline': timezone.localtime(deadline) if deadline else None,
        })

    return {
        'reservation_summary': summary,
        'reservation_rows': report_rows,
        'reservation_has_legacy': any(row['legacy'] for row in report_rows),
        'reservation_page': page_obj,
        'reservation_days': days,
        'reservation_day_options': RESERVATION_REPORT_DAYS,
        'reservation_cutoff': timezone.localtime(cutoff),
    }


@never_cache   # أسماءُ المستخدمين وأعمارُ حجوزاتهم — لا تبقى في ذاكرة المتصفّح (كانت اللوحةُ كذلك)
@system_admin_required
@require_GET
def system_reservations_view(request):
    """حجوزاتُ الأرقام — صفحةٌ في إطار البرنامج للقراءة فقط (الدفعة 1)."""
    return render(request, 'core/system_admin/reservations.html', _reservation_report(request))


@require_http_methods(['GET', 'POST'])
@system_admin_required
def system_roles_view(request):
    if request.method == 'GET':
        from urllib.parse import urlencode

        from core.models import UserCapabilityOverride

        matrix = permission_service.role_matrix()
        now = timezone.localtime()
        accounts = reverse('system_accounts')
        # الاستثناءاتُ الشخصيّة على كلّ صلاحيّة باستعلامٍ واحد — العددُ رابطٌ إلى أصحابها في قائمة الحسابات
        exceptions = dict(UserCapabilityOverride.objects.order_by().values('capability')
                          .annotate(n=Count('pk')).values_list('capability', 'n'))
        # الدفعة 3أ: ما لم يُربط حارسُه ولم يُقفل يُجمع في «قادمة» آخرَ الصفحة — يُعرض ولا يُعدَّل
        groups, later = [], []
        for group in matrix['groups']:
            live = []
            for row in group['rows']:
                if row['last']:
                    by = row['last'].changed_by
                    row['last_text'] = f"عدّلها {by.get_full_name() or by.username if by else 'حساب محذوف'} {system_centre.human_when(row['last'].changed_at, now)}"
                row['exceptions'] = exceptions.get(row['key'], 0)
                row['exceptions_url'] = f"{accounts}?{urlencode({'exception': row['key']})}"
                (live if row['wired'] or row['locked'] else later).append(row)
            if live:
                groups.append({'name': group['name'], 'rows': live})
        for role in matrix['roles']:
            role['holders_text'] = _people_ar(role['holders']) if role['holders'] else 'لا أحد'
            # العددُ عددُ النشطين (``role_holders``)، فالقائمةُ تُفتح على النشطين ليطابقها
            role['url'] = f"{accounts}?{urlencode({'role': role['key'], 'status': 'active'})}"
        return render(request, 'core/system_admin/roles.html', {
            'matrix': matrix, 'groups': groups, 'later': later,
            'admins_text': count_ar(matrix['admins'], 'حساب واحد', 'حسابان', 'حسابات', 'حساباً'),
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
    """ما يعرضه المحرّر — **بحسب الناظر** (الدفعة 2): مديرُ النظام كلَّه، ورئيسُ القسم ما يملكه في شجرته.

    القالبُ لا يقرّر: كلُّ «يملك/لا يملك» هنا من المصدر الواحد في ``core/scoping.py``.
    """
    from core.models import UserCapabilityOverride
    from core.permission_service import role_change_preview
    from core.scoping import (CAPABILITIES, WIRED_CAPABILITIES, assignable_roles, can_delete_account,
                              can_edit_exception, can_manage_accounts, can_view_audit, foreign_exceptions,
                              has_capability, is_sensitive_account, managed_department_ids, role_change_block,
                              role_of)

    from core.scoping import can_manage_user

    viewer = request.user
    is_admin = can_manage_accounts(viewer)
    # ما لا يتعلّق بالمفتاح يُحسب مرّةً لا لكلّ صلاحيّة (فيبل 11-16: ~30 سؤالاً للصفحة)
    asked = {'by_role': role_of(viewer), 'manages': can_manage_user(viewer, target)}
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
            # استثناءٌ خامد (أمرُ التحويل، الدفعة 0): مكتوبٌ ولا حارسَ يقرؤه — لا يُعدّ «يستطيع»، ويُحذف من هنا
            state = 'dormant' if row is not None else 'unwired'
        elif row is not None:
            state = 'added' if row.allowed else 'blocked'
        else:
            state = 'role'
        group = groups.setdefault(capability.group, {'name': capability.group, 'rows': [], 'can': 0})
        if state == 'dormant':
            allowed = False
        group['rows'].append({'key': key, 'label': capability.label, 'allowed': allowed, 'state': state,
                              'editable': (state in ('role', 'added', 'blocked', 'dormant') and role is not None
                                           and can_edit_exception(viewer, target, key, **asked))})
        group['can'] += int(allowed)
        if key in _SUMMARY_SKIP or state == 'dormant':
            continue
        note = {'added': ' (استثناء)', 'blocked': ' (محجوب عنه)'}.get(state, '')
        (can if allowed else cannot).append(capability.label + note)
    for group in groups.values():
        group['total'] = len(group['rows'])
    # عضويّةُ دورٍ لا يعرضها الدورُ الواحد — «سلطةٌ خفيّة»؛ من المصدر الواحد (``extra_role_memberships``).
    from core.scoping import extra_role_memberships
    extra_memberships = [] if role is None else extra_role_memberships(target)
    def granter(row):
        # اسمُ دخول مدير النظام لا يُعرض لغيره — يكفي رئيسَ القسم أن يعرف أنّه من المدير (فيبل 11-16)
        if row.changed_by is None:
            return ''
        if row.changed_by.is_superuser and not is_admin:
            return 'مدير النظام'
        return row.changed_by.get_username()
    exceptions = [{'key': key, 'label': CAPABILITIES[key].label if key in CAPABILITIES else key,
                   'allowed': row.allowed, 'by': granter(row), 'at': row.changed_at,
                   'editable': key in CAPABILITIES and can_edit_exception(viewer, target, key, **asked)}
                  for key, row in overrides.items()]
    role_block = '' if role is None else role_change_block(viewer, target)
    options = [] if role is None or role_block else [(r, MATRIX_ROLES[r]) for r in assignable_roles(viewer, target)]
    if options and role not in dict(options):   # حالٌ لا يناسب قسمَه: يظهر كما هو لا خياراً أوّلَ مختاراً زوراً
        options.insert(0, (role, MATRIX_ROLES[role]))
    # النقلُ: لا يُلغي ما لا يملكه الناقل، ونقلُ رئيسٍ أو مسؤولٍ عند المدير (``assign_user``)
    foreign = foreign_exceptions(viewer, target)
    move_block = ''
    if not is_admin and getattr(profile, 'is_department_head', False):
        move_block = 'نقلُ الرئيس أو المسؤول عند مدير النظام.'
    elif foreign:
        move_block = 'له استثناءاتٌ لا تملك تعديلها (%s)، والنقلُ يُلغيها — فنقلُه عند مدير النظام.' % '، '.join(foreign)
    # والقسمُ الحاليّ خيارٌ دائماً ولو عُطِّل: غيابُه يجعل المتصفّحَ يختار الأوّل، فيصير كلُّ حفظٍ «نقلاً»
    # يُلغي الاستثناءات (فيبل 11-16)
    departments = (Department.objects.filter(Q(is_active=True) | Q(pk=getattr(department, 'pk', None)))
                   .order_by('code'))
    if not is_admin:
        departments = departments.filter(pk__in=managed_department_ids(viewer))
    scope = 'نطاقه'
    if department is not None:
        scope = 'قسم «%s»%s' % (department.name, ' وما يتبعه' if department.children.exists() else '')
    is_self = target.pk == viewer.pk
    return {
        'extra_memberships': extra_memberships, 'is_admin': is_admin,
        'target': target, 'profile': profile, 'department': department,
        'role': role, 'role_label': MATRIX_ROLES.get(role, 'مدير النظام'), 'role_options': options,
        'role_block': role_block, 'move_block': move_block,
        'previews': {r: {**role_change_preview(target, r), 'label': label} for r, label in options if r != role},
        'summary_can': _join_ar(can), 'summary_cannot': _join_ar(cannot), 'scope_text': scope,
        'exceptions': exceptions, 'groups': list(groups.values()),
        'departments': departments,
        'can_delete': can_delete_account(viewer, target),
        # حارسُ ``reset_department_user_password`` نفسُه: لا حسابَك ولا معطَّلاً ولا حسّاساً لغير المدير
        'can_reset': not is_self and target.is_active and (is_admin or not is_sensitive_account(target)),
        'is_self': is_self,
        # كلمةٌ أُبطلت أو لم تُصدر بعد (قرارُ المالك 11-18) — تُقال، ومديرُ النظام يصدرها
        'no_password': not target.has_usable_password(),
        'audit_url': (f"{reverse('audit_log')}?actor={target.get_username()}" if can_view_audit(viewer) else ''),
    }


def _account_post(request, target):
    """فعلٌ واحدٌ لكلّ طلب؛ يعيد (رسالة، كلمة مرورٍ مؤقّتة أو None، وجهة أو None)."""
    from core.admin_service import UNSET, assign_user, delete_user, reset_department_user_password
    from core.models import UserCapabilityOverride
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
        # غيرُ الموصول لا يُعدَّل — إلّا حذفُ استثناءٍ خامدٍ قائم (أمرُ التحويل، فيبل 11-16)
        dormant_reset = (value is None and key in CAPABILITIES
                         and UserCapabilityOverride.objects.filter(user=target, capability=key).exists())
        if key not in CAPABILITIES or value == 'bad' or (key not in WIRED_CAPABILITIES and not dormant_reset):
            raise ValidationError('صلاحيّةٌ لا تُعدَّل من هنا.')
        set_user_override(request, target, key, value)
        return 'حُدِّثت صلاحيّة «%s».' % CAPABILITIES[key].label, None, None
    if action == 'password':
        return 'أُعيد تعيين كلمة المرور، وتظهر الكلمة المؤقّتة مرّةً واحدة.', \
            reset_department_user_password(by=request.user, user=target), None
    if action == 'delete':
        username = target.get_username()
        delete_user(by=request.user, user=target)
        return 'حُذف حساب «%s».' % username, None, reverse('system_accounts')
    if action == 'save':
        raw = (request.POST.get('department') or '').strip()
        department = Department.objects.filter(pk=raw).first() if raw.isdecimal() else None
        current = getattr(getattr(target, 'profile', None), 'department', None)
        if department != current and request.POST.get('confirm_department') != '1':
            raise ValidationError('أكّد تغيير القسم — يُلغي استثناءاتِ الحساب.')
        first, _, last = (request.POST.get('name') or '').strip().partition(' ')
        before = UserCapabilityOverride.objects.filter(user=target).count()
        assign_user(target, by=request.user, department=department if department != current else UNSET,
                    first_name=first, last_name=last.strip(), job_title=request.POST.get('job_title', ''),
                    is_active=bool(request.POST.get('is_active')))
        # نقلُ القسم يُلغي الاستثناءات (``assign_user``) — يُقال بعد الحفظ كما سُئل قبله
        cancelled = before - UserCapabilityOverride.objects.filter(user=target).count()
        if cancelled > 0:
            return ('حُفظ حساب «%s»، وأُلغيت استثناءاتُه (%d) لأنّه نُقل إلى قسمٍ آخر.'
                    % (target.get_username(), cancelled)), None, None
        return 'حُفظ حساب «%s».' % target.get_username(), None, None
    raise ValidationError('إجراءٌ غير معروف.')


def _secret_page(response):
    """صفحةٌ تعرض كلمةَ مرورٍ مؤقّتة: لا تُخبَّأ، ولا يغادر عنوانُها الموقع.

    ``same-origin`` لا ``no-referrer``: مع ``no-referrer`` يرسل المتصفّحُ أصلَ كلّ نموذجٍ في الصفحة «null»
    (مواصفةُ Fetch لطلبات POST)، فيرفض حارسُ CSRF في Django كلَّ حفظٍ بعد الإنشاء بـ403 — وقع للمالك في
    الإنتاج 11-16: أُنشئ الحساب ثمّ رُفضت ثلاثُ محاولاتِ حفظٍ عليه. والكلمةُ في المتن لا في العنوان، فلا
    يحتاج إخفاؤها أكثرَ من ألّا يصل العنوانُ موقعاً آخر.
    """
    response['Cache-Control'] = 'no-store, private'
    response['Referrer-Policy'] = 'same-origin'
    return response


def _editor_target(viewer, pk):
    """الحسابُ الذي يفتحه المحرّر: مديرُ النظام أيَّ حساب، ورئيسُ القسم ما يديره (``can_manage_user``).

    غيرُ المُدار يُعامَل كغير الموجود (404): رفضٌ مختلف يكشف أيّ المعرّفات قائمة (فيبل 11-16).
    """
    from django.contrib.auth.models import User
    from django.http import Http404

    from core.scoping import can_manage_departments, can_manage_user

    if not can_manage_departments(viewer):
        raise PermissionDenied('محرّرُ الحساب لمدير النظام، ولرئيس القسم في شجرته.')
    target = User.objects.select_related('profile__department').filter(pk=pk).first()
    if target is None or not can_manage_user(viewer, target):
        raise Http404
    return target


@never_cache
@login_required
@require_http_methods(['GET', 'POST'])
def system_account_view(request, pk):
    """محرّرُ الحساب — الدورُ والاستثناءاتُ والحسابُ والدخولُ في صفحةٍ واحدة؛ لمدير النظام ولرئيس القسم بنطاقه."""
    from django.contrib.auth.models import User
    from django.core.exceptions import ValidationError as _VE

    target = _editor_target(request.user, pk)
    password = None
    if request.method == 'POST':
        try:
            with transaction.atomic():
                message, password, back = _account_post(request, target)
        except (_VE, PermissionDenied) as exc:
            if isinstance(exc, _VE):
                error_for(request, exc)           # تحت حقله إن سمّاه رمزُه، وإلّا توست
            else:
                messages.error(request, str(exc))
            return redirect('system_account', pk=pk)
        messages.success(request, message)
        if back:
            return redirect(back)
        if password is None:
            return redirect('system_account', pk=pk)
        target = User.objects.select_related('profile__department').get(pk=pk)
    response = render(request, 'core/system_admin/account.html',
                      {**_account_context(request, target), 'temp_password': password})
    return _secret_page(response) if password else response


# ───────────────────────── إنشاءُ حساب (ج، الشريحة 3) ─────────────────────────
# التصميمُ المعتمد shots_v2/v2_account_new.png: الأدوارُ بحسب القسم المختار (``roles_for_department``)
# وملخّصُ ما سيستطيعه، ثمّ يُفتح محرّرُ الحساب الجديد بكلمته المؤقّتة مرّةً واحدة.

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


@never_cache
@login_required
@require_http_methods(['GET', 'POST'])
def system_account_new_view(request):
    """إنشاءُ حسابٍ بدورٍ يناسب قسمه — لمدير النظام، ولرئيس القسم في شجرته بما يمنحه (الدفعة 2)؛
    والقاعدةُ نفسُها في ``create_department_user`` (``_guard_department`` و``_guard_grant``)."""
    from django.core.exceptions import ValidationError as _VE

    from core.admin_service import create_department_user
    from core.scoping import (ROLE_GRANT_KEYS, can_manage_accounts, can_manage_departments, grantable_roles,
                              managed_department_ids, roles_for_department)

    viewer = request.user
    allowed = grantable_roles(viewer)
    if not (can_manage_departments(viewer) and allowed):
        raise PermissionDenied('إنشاءُ الحسابات لمدير النظام، ولرئيس القسم في شجرته.')
    departments = Department.objects.filter(is_active=True).order_by('code')
    if not can_manage_accounts(viewer):
        departments = departments.filter(pk__in=managed_department_ids(viewer))
    departments = list(departments)

    def roles_here(department):
        return [role for role in roles_for_department(department) if ROLE_GRANT_KEYS[role] in allowed]
    values = {}
    if request.method == 'POST':
        values = {key: (request.POST.get(key) or '').strip()
                  for key in ('name', 'username', 'department', 'job_title', 'role')}
        raw = values['department']
        department = next((d for d in departments if raw.isdecimal() and d.pk == int(raw)), None)
        try:
            if department is None:
                raise _VE('اختر قسمَ الحساب.', code=FIELD_CODE + 'department')
            if values['role'] not in roles_here(department):
                raise _VE('اختر دوراً يُسند في هذا القسم.', code=FIELD_CODE + 'role')
            first, _, last = values['name'].partition(' ')
            user, password = create_department_user(   # ذرّيّةٌ في داخلها
                by=request.user, department=department, username=values['username'],
                first_name=first, last_name=last.strip(), job_title=values['job_title'],
                role=ROLE_GRANT_KEYS[values['role']])
        except (_VE, PermissionDenied) as exc:
            if isinstance(exc, _VE):
                error_for(request, exc)           # تحت حقله إن سمّاه رمزُه، وإلّا توست
            else:
                messages.error(request, str(exc))
        else:
            if password is None:   # حسّاسٌ أنشأه غيرُ المدير — كلمتُه الأولى من المدير (قرارُ المالك 11-18)
                messages.success(request, 'أُنشئ حساب «%s». دورُه يفتح السرّيّ، فكلمتُه الأولى يصدرها مدير النظام.'
                                 % user.get_username())
                return render(request, 'core/system_admin/account.html',
                              {**_account_context(request, user), 'temp_password': None})
            messages.success(request, 'أُنشئ حساب «%s».' % user.get_username())
            return _secret_page(render(request, 'core/system_admin/account.html',
                                       {**_account_context(request, user), 'temp_password': password}))
    return render(request, 'core/system_admin/account_new.html', {
        'departments': departments, 'values': values,
        'roles_meta': _new_account_roles(),
        'department_roles': {str(d.pk): {'roles': roles_here(d), 'register': d.holds_register}
                             for d in departments},
        'role_order': list(MATRIX_ROLES),
    })


# ───────────────────────── قائمةُ الحسابات (الدفعة 2) ─────────────────────────
# تحلّ محلّ تبويب «الحسابات والأدوار» في اللوحة المستقلّة: **قائمةٌ تُقرأ والمحرّرُ يكتب** (القاعدةُ 1 في
# مراجعة التصميم) — لا حقلَ في الجدول، فلا تعديلَ يضيع ولا سلطةَ خفيّةً تُكتب من خانة. النطاقُ قاعدةُ
# اللوحة نفسُها (``managed_department_ids``)، والرابطُ إلى المحرّر بحارسه نفسِه (``can_manage_user``).

ACCOUNTS_PAGE_SIZE = 50
_ACCOUNT_STATUSES = (('all', 'الكلّ'), ('active', 'نشط'), ('inactive', 'موقوف'), ('password', 'كلمة مؤقّتة'),
                     ('sensitive', 'حسّاس'))
_ACCOUNT_COLUMNS = (('name', 'الموظّف'), ('role', 'الدور'), ('department', 'القسم'),
                    ('status', 'الحالة'), ('login', 'آخر دخول'))
_ADMIN_ROLE = 'admin'


def account_rows(viewer):
    """صفوفُ الحسابات في نطاق الناظر: مديرُ النظام كلُّها، ورئيسُ القسم شجرتُه بلا الحسابات الإداريّة.

    مصدرٌ واحدٌ للقائمة ولبطاقات الأعداد في لوحة الإدارة — البطاقةُ رابطٌ إلى تصفيتها، فعددُها عددُ ما تُظهره.
    """
    from django.contrib.auth.models import User

    from core.models import UserCapabilityOverride
    from core.scoping import (can_manage_accounts, can_manage_user, is_sensitive_account, managed_department_ids,
                              role_of)

    people = User.objects.select_related('profile__department').prefetch_related('groups')
    managed = None
    if not can_manage_accounts(viewer):
        managed = set(managed_department_ids(viewer))
        # ولا مديرَ نظامٍ بلا علَم الموظّف الإداريّ (فيبل 11-16: ``_user_rows`` كان يُسقط is_staff وحده)
        people = (people.filter(profile__department_id__in=managed)
                  .exclude(is_staff=True).exclude(is_superuser=True))
    # حاملو الاستثناءات الموجبة مرّةً واحدة لا استعلاماً لكلّ صفّ (``is_sensitive_account``)
    holders = set(UserCapabilityOverride.objects.filter(allowed=True).values_list('user_id', flat=True))
    rows = []
    for user in people:
        profile = getattr(user, 'profile', None)
        names = {group.name for group in user.groups.all()}
        role = _ADMIN_ROLE if user.is_superuser else role_of(user)
        can_edit = can_manage_user(viewer, user, group_names=names, managed_ids=managed)
        rows.append({
            'user': user, 'name': user.get_full_name().strip(), 'username': user.get_username(),
            'job_title': (getattr(profile, 'job_title', '') or '').strip(),
            'role': role, 'role_label': 'مدير النظام' if role == _ADMIN_ROLE else MATRIX_ROLES.get(role, role),
            'department': getattr(profile, 'department', None),
            'is_active': user.is_active,
            'temp_password': bool(getattr(profile, 'must_change_password', False)),
            'is_sensitive': is_sensitive_account(user, names, holders),
            'last_login': user.last_login,
            'can_edit': can_edit,
            # صفٌّ لا يُدار يُقال لماذا، لا رابطٌ يُرفض عند فتحه
            'note': '' if can_edit else ('حسابك' if user.pk == viewer.pk else 'يديره مدير النظام'),
        })
    return rows


def _account_sort_key(sort):
    order = {key: index for index, key in enumerate((_ADMIN_ROLE, *MATRIX_ROLES))}

    def name(row):
        return (row['name'] or row['username']).casefold()
    return {
        'name': name,
        'role': lambda row: (order.get(row['role'], len(order)), name(row)),
        'department': lambda row: (row['department'] is None, getattr(row['department'], 'code', '') or '', name(row)),
        'status': lambda row: (not row['is_active'], not row['temp_password'], name(row)),
        'login': lambda row: row['last_login'],   # مَن لم يدخل قطّ يُفصل قبل الفرز ويبقى آخراً
    }[sort]


@never_cache
@login_required
@require_GET
def system_accounts_view(request):
    """الحساباتُ للقراءة: بحثٌ ورقائقُ حالةٍ بأعدادها وفرزٌ معلَن وصفحاتٌ من 50 — والصفُّ رابطٌ إلى المحرّر."""
    from urllib.parse import urlencode

    from core.scoping import (can_manage_accounts, can_manage_departments, grantable_roles,
                              managed_department_ids, user_department_id)

    viewer = request.user
    if not can_manage_departments(viewer):
        raise PermissionDenied('الحساباتُ لمدير النظام، ولرئيس القسم بنطاق شجرته.')
    is_admin = can_manage_accounts(viewer)
    rows = account_rows(viewer)

    departments = list(Department.objects.filter(pk__in=managed_department_ids(viewer)).order_by('code'))
    present_roles = {row['role'] for row in rows}
    known_roles = dict(((_ADMIN_ROLE, 'مدير النظام'), *MATRIX_ROLES.items()))

    query = (request.GET.get('q') or '').strip()[:100]
    role = request.GET.get('role', '')
    # دورٌ لا يحمله أحدٌ يبقى تصفيةً تقول «لا حساب» — رابطُ المصفوفة لا يصير «كلّ الحسابات» (فيبل 11-18)
    role = role if role in known_roles else ''
    role_options = [(key, label) for key, label in known_roles.items() if key in present_roles or key == role]
    # أصحابُ استثناءٍ على صلاحيّة — لمدير النظام وحده: لرئيس القسم صفوفٌ لا يفتحها (حسابُه، ونظيرُه)،
    # والتصفيةُ بمفتاحٍ بعد مفتاح كانت ستكشف استثناءاتِها ومنها حجبُ المدير (فيبل 11-18)
    exception = request.GET.get('exception', '') if is_admin else ''
    exception = exception if exception in CAPABILITIES else ''
    raw_department = request.GET.get('department', '')
    department = next((d for d in departments if raw_department.isdecimal() and d.pk == int(raw_department)), None)
    # «بلا قسم» لمدير النظام وحده — نطاقُ الرئيس شجرتُه، فلا حسابَ بلا قسمٍ فيه
    no_department = is_admin and raw_department == 'none'
    status = request.GET.get('status', 'all')
    status = status if status in dict(_ACCOUNT_STATUSES) else 'all'
    sort = request.GET.get('sort', 'name')
    sort = sort if sort in dict(_ACCOUNT_COLUMNS) else 'name'
    direction = 'desc' if request.GET.get('dir') == 'desc' else 'asc'

    base = rows
    if query:
        needle = query.casefold()
        # ما تعرضه القائمة وحده: الاسم واسمُ الدخول والمسمّى — بريدٌ لا يُرى لا يُطابَق (فيبل 11-16)
        base = [row for row in base if any(needle in (value or '').casefold() for value in (
            row['username'], row['name'], row['job_title']))]
    if role:
        base = [row for row in base if row['role'] == role]
    if department is not None:
        tree = set(subtree_ids(department.pk))   # القسمُ وما يتبعه
        base = [row for row in base if row['department'] is not None and row['department'].pk in tree]
    elif no_department:
        base = [row for row in base if row['department'] is None]
    exception_note = ''
    if exception:
        from core.models import UserCapabilityOverride

        holding = dict(UserCapabilityOverride.objects.filter(capability=exception).values_list('user_id', 'allowed'))
        # يسري الاستثناءُ على صلاحيّةٍ مربوطةٍ غير مقفلةٍ لغير مدير النظام (``has_capability``) — وإلّا فهو «خامد»:
        # مكتوبٌ لا يغيّر شيئاً، كما يقوله المحرّر. لا «مضاف» أخضرَ لقدرةٍ لا يملكها أحد (فيبل 11-18)
        if CAPABILITIES[exception].locked:
            exception_note = 'الصلاحيّة مقفلة، فلا يسري عليها استثناء.'
        elif exception not in WIRED_CAPABILITIES:
            exception_note = 'لم يُربط حارسها بعد، فالاستثناءات عليها خامدة لا تسري.'

        def effect(row):
            if exception_note or row['role'] == _ADMIN_ROLE:
                return 'dormant'
            return 'added' if holding[row['user'].pk] else 'blocked'
        base = [{**row, 'exception': effect(row)} for row in base if row['user'].pk in holding]
    tests = {'all': lambda row: True, 'active': lambda row: row['is_active'],
             'inactive': lambda row: not row['is_active'], 'password': lambda row: row['temp_password'],
             # يفتح السرّيّ أو يدير غيرَه (``is_sensitive_account``) — بطاقةُ «أدوار حسّاسة» في اللوحة
             'sensitive': lambda row: row['is_sensitive']}
    counts = {key: sum(1 for row in base if tests[key](row)) for key, _ in _ACCOUNT_STATUSES}
    shown = [row for row in base if tests[status](row)]
    never = [row for row in shown if sort == 'login' and row['last_login'] is None]
    shown = sorted((row for row in shown if row not in never), key=_account_sort_key(sort),
                   reverse=direction == 'desc') + never   # مَن لم يدخل قطّ آخرَ القائمة في الاتّجاهين
    page = Paginator(shown, ACCOUNTS_PAGE_SIZE).get_page(request.GET.get('page'))

    state = {'q': query, 'role': role, 'department': department.pk if department else ('none' if no_department else ''),
             'exception': exception,
             'status': '' if status == 'all' else status, 'sort': '' if sort == 'name' else sort,
             'dir': '' if direction == 'asc' else direction}

    def url(**changes):
        params = {key: value for key, value in {**state, **changes}.items() if value not in ('', None)}
        return reverse('system_accounts') + ('?' + urlencode(params) if params else '')

    columns = []
    for key, label in _ACCOUNT_COLUMNS:
        current = key == sort
        columns.append({'key': key, 'label': label,
                        'aria': ('ascending' if direction == 'asc' else 'descending') if current else '',
                        'url': url(sort='' if key == 'name' else key,
                                   dir='desc' if current and direction == 'asc' else '', page='')})
    exception_label = CAPABILITIES[exception].label if exception else ''
    applied = [label for label, on in (
        (f'البحث «{query}»', query), (f'الدور «{known_roles.get(role, "")}»', role),
        (f'القسم «{department.name if department else ""}»', department), ('«بلا قسم»', no_department),
        (f'الاستثناء على «{exception_label}»', exception),
        (f'الحالة «{dict(_ACCOUNT_STATUSES)[status]}»', status != 'all')) if on]

    scope_text = ''
    if not is_admin:
        root = next((d for d in departments if d.pk == user_department_id(viewer)), None)
        if root is not None:
            scope_text = f'{root.name}{" وما يتبعه" if len(departments) > 1 else ""}'
    return render(request, 'core/system_admin/accounts.html', {
        'page_obj': page, 'rows': page.object_list, 'total': len(rows), 'is_admin': is_admin,
        'shown_text': count_ar(len(shown), 'حسابٌ واحد', 'حسابان', 'حسابات', 'حساباً'),
        'scope_text': scope_text, 'can_create': bool(grantable_roles(viewer)),
        'query': query, 'role': role, 'role_options': role_options,
        'department': department, 'departments': departments, 'no_department': no_department,
        'statuses': [{'key': key, 'label': label, 'count': counts[key], 'on': key == status,
                      'url': url(status='' if key == 'all' else key, page='')} for key, label in _ACCOUNT_STATUSES],
        # الطريقُ إلى المصفوفة وبالعكس (الدفعة 3أ) — المصفوفةُ لمدير النظام وحده
        'role_matrix_url': (f"{reverse('system_roles')}#role-{role}" if is_admin and role in MATRIX_ROLES else ''),
        'role_label': known_roles.get(role, ''),
        'exception': exception, 'exception_label': exception_label, 'exception_note': exception_note,
        'exception_matrix_url': f"{reverse('system_roles')}#cap-{exception}" if exception else '',
        'exception_clear_url': url(exception='', page='') if exception else '',
        'status': status, 'sort': sort, 'dir': direction, 'columns': columns,
        'applied': _join_ar(applied), 'clear_url': reverse('system_accounts'),
        'prev_url': url(page=page.previous_page_number()) if page.has_previous() else '',
        'next_url': url(page=page.next_page_number()) if page.has_next() else '',
    })
