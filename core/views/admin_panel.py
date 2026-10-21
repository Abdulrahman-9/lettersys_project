# -*- coding: utf-8 -*-
"""
لوحةُ الإدارة — الأقسامُ والمستخدمون والعناقيد.

شاشةٌ واحدةٌ بثلاثة تبويبات بدل ثلاث شاشات: الثلاثةُ يُضبطون معاً في جلسةِ
تهيئةٍ واحدة (أنشئ القسم ⟵ أسنِد إليه موظّفاً ⟵ ضعه في عنقود)، وتفريقُهم على
صفحاتٍ يجعل التهيئةَ رحلةً بين ثلاثِ روابط.

**العرضُ لا يحمل قاعدةً:** كلُّ كتابةٍ تمرّ من ``core/admin_service.py`` —
هناك تعيش التوأمةُ التلقائيّة وحارسُ حلقات الشجرة وأثرُ تغيير الأدوار.
"""

from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache

from core.admin_service import (UNSET, assign_user, create_department,
                                create_department_user, delete_group, save_group,
                                update_department)
from core.models import BookNumberReservation, Department, Entity, EntityGroup
from core.roles import (ARCHIVE_ALL_GROUP_NAME, ARCHIVIST_GROUP_NAME,
                        CONTROLLER_GROUP_NAME, ENTRY_GROUP_NAME)
from core.scoping import (can_manage_accounts, can_manage_departments,
                          managed_department_ids, user_department_id)

TABS = ('overview', 'departments', 'users', 'groups', 'reservations')
ADMIN_ACTIONS = ('CREATE_DEPARTMENT', 'EDIT_DEPARTMENT', 'ASSIGN_USER',
                 'CREATE_USER', 'CREATE_GROUP', 'EDIT_GROUP')
RESERVATION_REPORT_DAYS = (7, 30, 90)
RESERVATION_REPORT_PAGE_SIZE = 50


@login_required
@never_cache
def admin_panel(request):
    """إدارةٌ عالمية للسوبر أدمن وإدارةٌ شجرية لرئيس القسم."""
    if not can_manage_departments(request.user):
        raise PermissionDenied('إدارة الأقسام لمدير النظام ورئيس القسم.')

    tab = request.GET.get('tab')
    superadmin_only = ('groups', 'reservations')
    tab = (tab if tab in TABS and (tab not in superadmin_only or can_manage_accounts(request.user))
           else 'overview')

    if request.method == 'POST':
        return _handle(request)

    return _render_panel(request, tab)


def _render_panel(request, tab, created_credentials=None, create_form_values=None):
    is_superadmin = can_manage_accounts(request.user)
    department_ids = managed_department_ids(request.user)
    departments = Department.objects.filter(pk__in=department_ids).order_by('code')
    people = _user_rows(None if is_superadmin else set(department_ids),
                        actor_id=request.user.pk)
    root_department = (Department.objects.filter(
        pk=user_department_id(request.user)).first() if not is_superadmin else None)
    department_rows = _department_rows(None if is_superadmin else set(department_ids))
    context = {
        'tab': tab,
        'is_superadmin': is_superadmin,
        'manager_root_id': user_department_id(request.user),
        'scope_label': 'جميع أقسام المؤسسة' if is_superadmin else str(root_department or 'قسم غير محدد'),
        'departments': department_rows,
        'all_departments': departments,
        'active_departments': departments.filter(is_active=True),
        'people': people,
        'department_count': len(department_rows),
        'active_department_count': sum(
            row['department'].is_active for row in department_rows),
        'staff_count': len(people),
        'inactive_user_count': sum(not row['is_active'] for row in people),
        'password_pending_count': sum(row['must_change_password'] for row in people),
        'sensitive_role_count': sum(row['is_sensitive'] for row in people),
        'groups': (EntityGroup.objects.prefetch_related('members').order_by('name')
                   if is_superadmin else EntityGroup.objects.none()),
        'entities': (Entity.objects.filter(is_active=True).order_by('name')
                    if is_superadmin else Entity.objects.none()),
        'auto_rules': EntityGroup.AUTO_RULE_CHOICES,
        # `?edit=<id>` يملأ النموذجَ بعنقودٍ قائم — تعديلٌ بصفر JS، ورابطٌ
        # يُنسخ ويُشارَك. وسقفُ الـ500 على الجهات أُسقط: عنقودٌ لا يجد عضوَه
        # في القائمة عيبٌ صامت (674 جهةً في القاعدة).
        'editing': _editing_group(request) if is_superadmin else None,
        'member_ids': _editing_member_ids(request) if is_superadmin else set(),
        'created_credentials': created_credentials,
        'create_form_values': create_form_values or {},
    }
    if tab == 'reservations':
        context.update(_reservation_report(request))
    if tab == 'overview':
        context.update(_overview(request.user, department_rows, people,
                                 None if is_superadmin else set(department_ids)))
    return render(request, 'core/admin_panel.html', context)


def _overview(user, department_rows, people, department_ids):
    """صورةٌ واحدةٌ للنطاق: شجرةٌ بصريّة وصحّةُ الأقسام وآخرُ الحركات الإداريّة."""
    from core.logging_models import UserActivityLog
    from core.scoping import books_in_scope, scope_activity_for
    from core.views.filter_helpers import followup_q

    today = timezone.localdate()
    books = books_in_scope(user)
    if department_ids is not None:
        books = books.filter(department_id__in=department_ids)
    overdue = dict(
        books.filter(followup_q('overdue', today))
        .order_by().values('department_id')
        .annotate(total=Count('pk')).values_list('department_id', 'total')
    )
    active_members = {}
    for row in people:
        if row['department'] is not None and row['is_active']:
            active_members[row['department'].pk] = active_members.get(row['department'].pk, 0) + 1

    nodes = {}
    for row in department_rows:
        department = row['department']
        nodes[department.pk] = {
            'department': department,
            'depth': row['depth'],
            'overdue': overdue.get(department.pk, 0),
            'active_members': active_members.get(department.pk, 0),
            'children': [],
        }
    roots = []
    for node in nodes.values():
        parent = nodes.get(node['department'].parent_id)
        (parent['children'] if parent else roots).append(node)

    def descendants(node):
        return sum(1 + descendants(child) for child in node['children'])

    for node in roots:
        node['descendant_count'] = descendants(node)
    roots.sort(key=lambda n: (-n['descendant_count'], -n['overdue'], n['department'].code))

    health = sorted(
        nodes.values(),
        key=lambda n: (-n['overdue'], -n['department'].book_count, n['department'].code),
    )[:6]
    peak = max((n['department'].book_count for n in health), default=0)
    for node in health:
        node['load_percent'] = round(node['department'].book_count * 100 / peak) if peak else 0
        members = node['department'].member_count
        node['active_percent'] = round(node['active_members'] * 100 / members) if members else 0

    activity = (
        scope_activity_for(user, UserActivityLog.objects.filter(action__in=ADMIN_ACTIONS))
        .select_related('user', 'department')
        .order_by('-timestamp')[:8]
    )
    return {
        'org_roots': roots,
        'org_overdue_total': sum(overdue.get(pk, 0) for pk in nodes),
        'health_rows': health,
        'admin_activity': activity,
    }


def _reservation_report(request):
    """ملخّصٌ للقراءة فقط: كلّ الحجوزات القائمة وسجلّات الفترة المختارة."""
    now = timezone.now()
    raw_days = request.GET.get('days', '')
    days = int(raw_days) if raw_days.isdigit() and int(raw_days) in RESERVATION_REPORT_DAYS else 7
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
    current_active = rows.filter(
        status__in=live_statuses, expires_at__gt=now,
    ).count()
    overdue_active = rows.filter(
        status__in=live_statuses, expires_at__lte=now,
    ).count()
    current_cooldown = rows.filter(
        status=BookNumberReservation.STATUS_COOLDOWN, cooldown_until__gt=now,
    ).count()
    elapsed_cooldown = rows.filter(
        status=BookNumberReservation.STATUS_COOLDOWN,
    ).filter(Q(cooldown_until__isnull=True) | Q(cooldown_until__lte=now)).count()
    summary = {
        'total': rows.count(),
        'active': current_active,
        'overdue_active': overdue_active,
        'cooldown': current_cooldown,
        'elapsed_cooldown': elapsed_cooldown,
        'used': status_counts.get(BookNumberReservation.STATUS_USED, 0),
        'expired': status_counts.get(BookNumberReservation.STATUS_EXPIRED, 0),
        'voided': status_counts.get(BookNumberReservation.STATUS_VOIDED, 0),
        'recycled': rows.filter(is_recycled=True).count(),
    }

    page_obj = Paginator(rows, RESERVATION_REPORT_PAGE_SIZE).get_page(
        request.GET.get('page'))
    report_rows = []
    for reservation in page_obj.object_list:
        if reservation.status in live_statuses and reservation.expires_at <= now:
            status_label = 'انتهت المهلة — بانتظار التنظيف'
        elif reservation.status == BookNumberReservation.STATUS_COOLDOWN:
            if reservation.cooldown_until and reservation.cooldown_until > now:
                status_label = 'فترة السماح'
            else:
                status_label = 'انتهت فترة السماح — بانتظار التدوير'
        else:
            status_label = reservation.get_status_display()

        assigned_at = reservation.assigned_at
        age_seconds = (
            max(0, int((now - assigned_at).total_seconds()))
            if assigned_at else None
        )
        if age_seconds is None:
            age_label = 'غير متاح — حجز سابق لإضافة تتبّع الإسناد'
        elif age_seconds < 60:
            age_label = 'أقل من دقيقة'
        elif age_seconds < 3600:
            age_label = f'{age_seconds // 60} دقيقة'
        elif age_seconds < 86400:
            age_label = f'{age_seconds // 3600} ساعة'
        else:
            age_label = f'{age_seconds // 86400} يوم'
        deadline = (
            reservation.cooldown_until
            if reservation.status == BookNumberReservation.STATUS_COOLDOWN
            else reservation.expires_at
        )
        report_rows.append({
            'reservation': reservation,
            'status_label': status_label,
            'age_label': age_label,
            'assigned_at': timezone.localtime(assigned_at) if assigned_at else None,
            'deadline': timezone.localtime(deadline) if deadline else None,
        })

    return {
        'reservation_summary': summary,
        'reservation_rows': report_rows,
        'reservation_page': page_obj,
        'reservation_days': days,
        'reservation_day_options': RESERVATION_REPORT_DAYS,
        'reservation_cutoff': timezone.localtime(cutoff),
    }


# ───────────────────────────── الكتابة ─────────────────────────────

def _handle(request):
    action = request.POST.get('action', '')
    tab = request.POST.get('tab', 'departments')
    if action == 'create_department_user':
        try:
            user, password = _create_department_user(request)
        except ValidationError as exc:
            messages.error(request, exc.messages[0])
            response = _render_panel(request, 'users', create_form_values={
                key: request.POST.get(key, '') for key in (
                    'department', 'username', 'first_name', 'last_name',
                    'email', 'job_title', 'role',
                )
            })
            response['Cache-Control'] = 'no-store, private'
            return response
        except PermissionDenied as exc:
            messages.error(request, str(exc))
            return redirect(_back_to(request, 'users'))
        else:
            messages.success(request, 'أُنشئ الحساب، وستظهر كلمة المرور المؤقتة مرة واحدة.')
            response = _render_panel(request, 'users', {
                'username': user.get_username(),
                'password': password,
            })
            response['Cache-Control'] = 'no-store, private'
            response['Pragma'] = 'no-cache'
            response['Referrer-Policy'] = 'no-referrer'
            return response
        return redirect(_back_to(request, 'users'))

    try:
        handler = _HANDLERS.get(action)
        if handler is None:
            raise ValidationError('إجراءٌ غير معروف.')
        messages.success(request, handler(request))
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
    except PermissionDenied as exc:
        messages.error(request, str(exc))
    return redirect(_back_to(request, tab))


#: الوجهاتُ المسموحة بعد الكتابة — قائمةٌ بيضاء لا عنوانٌ حرّ.
_RETURN_TO = {
    'groups_workshop': '/books/entities/?view=groups',
}


def _back_to(request, tab):
    """أين يعود المستخدمُ بعد الحفظ.

    ورشةُ العناقيد تعيش في صفحة الجهات وتُرسل إلى هنا، فإعادتُها إلى اللوحة
    تقذف المستخدمَ خارج عمله. و**الوجهةُ من قائمةٍ بيضاء لا من الطلب**: عنوانٌ
    حرٌّ في `next` يفتح تحويلاً مفتوحاً.
    """
    wanted = (request.POST.get('return_to') or '').strip()
    if wanted in _RETURN_TO:
        return _RETURN_TO[wanted]
    return '/books/admin/?tab=%s' % (tab if tab in TABS else 'departments')


def _create_department(request):
    department = create_department(
        name=request.POST.get('name', ''),
        code=request.POST.get('code', ''),
        parent=_department(request.POST.get('parent')),
        entity=_entity(request.POST.get('entity')) if can_manage_accounts(request.user) else None,
        by=request.user,
    )
    return 'أُنشئ القسم «%s» ومعه جهتُه في الدليل.' % department.name


def _update_department(request):
    department = _department(request.POST.get('id'))
    if department is None:
        raise ValidationError('القسمُ غير موجود.')

    # «بلا أب» اختيارٌ صريحٌ يفترق عن «لم أغيّر الأب»
    parent_raw = request.POST.get('parent')
    parent = UNSET if parent_raw is None else _department(parent_raw)

    update_department(
        department, by=request.user,
        name=request.POST.get('name'),
        code=request.POST.get('code'),
        parent=parent,
        is_active=_flag(request.POST.get('is_active')),
    )
    return 'حُدِّث القسم «%s».' % department.name


def _assign_user(request):
    user = User.objects.filter(pk=request.POST.get('user_id')).first()
    if user is None:
        raise ValidationError('المستخدمُ غير موجود.')

    if can_manage_accounts(request.user):
        roles = {
            'is_department_head': _flag(request.POST.get('is_department_head')) or False,
            'is_controller': _flag(request.POST.get('is_controller')) or False,
            'is_archivist': _flag(request.POST.get('is_archivist')) or False,
            'is_company_archivist': _flag(request.POST.get('is_company_archivist')) or False,
            'is_entry': _flag(request.POST.get('is_entry')) or False,
        }
    else:
        roles = {'is_entry': _flag(request.POST.get('is_entry'))}

    assign_user(
        user, by=request.user,
        department=_department(request.POST.get('department')),
        job_title=request.POST.get('job_title'),
        first_name=request.POST.get('first_name'),
        last_name=request.POST.get('last_name'),
        email=request.POST.get('email'),
        **roles,
    )
    return 'حُدِّث حساب «%s».' % user.get_username()


def _toggle_user_active(request):
    user = User.objects.filter(pk=request.POST.get('user_id')).first()
    if user is None:
        raise ValidationError('المستخدمُ غير موجود.')
    active = _flag(request.POST.get('is_active'))
    if active is None:
        raise ValidationError('حالة الحساب مطلوبة.')
    assign_user(user, by=request.user, is_active=active)
    return 'حُدِّثت حالة حساب «%s».' % user.get_username()


def _create_department_user(request):
    return create_department_user(
        by=request.user,
        department=_department(request.POST.get('department')),
        username=request.POST.get('username', ''),
        first_name=request.POST.get('first_name', ''),
        last_name=request.POST.get('last_name', ''),
        email=request.POST.get('email', ''),
        job_title=request.POST.get('job_title', ''),
        role=request.POST.get('role', 'viewer'),
    )


def _save_group(request):
    group = EntityGroup.objects.filter(pk=request.POST.get('id')).first()

    # **الفرقُ بين «لم أرسل الأعضاء» و«أرسلتُهم فارغين»**: القائمةُ المتعدّدة في
    # HTML لا ترسل شيئاً حين لا يُحدَّد أحد، فزرُّ التعطيل — ولا حقلَ أعضاءَ فيه
    # — كان يُمرّر `[]` فتمسح `members.set([])` عضويّةَ العنقود **صامتاً**.
    # العلامةُ الصريحة تفصل الحالتين.
    members = ([int(v) for v in request.POST.getlist('members') if v.isdigit()]
               if request.POST.get('members_submitted') else None)

    saved = save_group(
        by=request.user, group=group,
        name=request.POST.get('name', ''),
        auto_rule=request.POST.get('auto_rule', ''),
        member_ids=members,
        is_active=_flag(request.POST.get('is_active')),
    )
    return 'حُفظ العنقود «%s» — %d جهة.' % (saved.name, saved.resolved_members().count())


def _delete_group(request):
    group = EntityGroup.objects.filter(pk=request.POST.get('id')).first()
    if group is None:
        raise ValidationError('العنقودُ غير موجود.')
    return 'حُذف العنقود «%s».' % delete_group(by=request.user, group=group)


_HANDLERS = {
    'create_department': _create_department,
    'update_department': _update_department,
    'assign_user': _assign_user,
    'toggle_user_active': _toggle_user_active,
    'save_group': _save_group,
    'delete_group': _delete_group,
}


def _editing_group(request):
    """العنقودُ المطلوب تعديلُه عبر `?edit=<id>` — أو لا شيء."""
    raw = (request.GET.get('edit') or '').strip()
    if not raw.isdigit():
        return None
    return EntityGroup.objects.filter(pk=int(raw)).first()


def _editing_member_ids(request):
    """معرِّفاتُ أعضائه — لتأشير `selected` في القائمة المتعدّدة."""
    group = _editing_group(request)
    return set(group.members.values_list('pk', flat=True)) if group else set()


# ───────────────────────────── القراءة ─────────────────────────────

def _department_rows(department_ids=None):
    """الأقسامُ مرتَّبةً **شجريّاً** — القائمةُ المسطّحة تُخفي البنية التي بُنيت لأجلها."""
    from django.db.models import Count

    queryset = Department.objects
    if department_ids is not None:
        queryset = queryset.filter(pk__in=department_ids)
    nodes = list(queryset
                 .select_related('parent', 'entity')
                 .annotate(book_count=Count('books', distinct=True),
                           member_count=Count('members', distinct=True))
                 .order_by('code'))
    by_parent = {}
    for node in nodes:
        by_parent.setdefault(node.parent_id, []).append(node)

    rows, stack = [], [(node, 0) for node in reversed(by_parent.get(None, []))]
    while stack:
        node, depth = stack.pop()
        rows.append({'department': node, 'depth': depth})
        stack.extend((child, depth + 1) for child in reversed(by_parent.get(node.pk, [])))

    # أيتامٌ (أبٌ محذوفٌ أو حلقةٌ سبقت الحارس) لا يُسقَطون بصمت
    seen = {row['department'].pk for row in rows}
    rows.extend({'department': n, 'depth': 0} for n in nodes if n.pk not in seen)
    return rows


def _user_rows(department_ids=None, actor_id=None):
    people = User.objects.all()
    if department_ids is not None:
        people = (people.filter(profile__department_id__in=department_ids)
                  .exclude(is_staff=True))
    people = (people.select_related('profile', 'profile__department')
              .prefetch_related('groups')
              .order_by('username'))
    rows = [{
        'user': u,
        'department': getattr(getattr(u, 'profile', None), 'department', None),
        'is_head': bool(getattr(getattr(u, 'profile', None), 'is_department_head', False)),
        'is_controller': any(g.name == CONTROLLER_GROUP_NAME for g in u.groups.all()),
        'is_archivist': any(g.name == ARCHIVIST_GROUP_NAME for g in u.groups.all()),
        'is_company_archivist': any(g.name == ARCHIVE_ALL_GROUP_NAME
                                    for g in u.groups.all()),
        'is_entry': any(g.name == ENTRY_GROUP_NAME for g in u.groups.all()),
        'is_active': u.is_active,
        'must_change_password': bool(getattr(getattr(u, 'profile', None),
                                             'must_change_password', False)),
        'job_title': getattr(getattr(u, 'profile', None), 'job_title', ''),
        'is_self': u.pk == actor_id,
    } for u in people]
    for row in rows:
        row['is_sensitive'] = (row['user'].is_superuser or row['is_head']
                               or row['is_controller'] or row['is_company_archivist'])
    return rows


def _department(raw):
    return Department.objects.filter(pk=raw).first() if raw and str(raw).isdigit() else None


def _entity(raw):
    return Entity.objects.filter(pk=raw).first() if raw and str(raw).isdigit() else None


def _flag(raw):
    """``None`` تعني «لم يُرسَل الحقل» — وهي غيرُ «أُرسل فارغاً»."""
    if raw is None:
        return None
    return raw in ('1', 'on', 'true', 'True')
