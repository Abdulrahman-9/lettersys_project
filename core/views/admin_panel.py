# -*- coding: utf-8 -*-
"""
لوحةُ الإدارة — الأقسامُ والمستخدمون والعناقيد.

شاشةٌ واحدةٌ بثلاثة تبويبات بدل ثلاث شاشات: الثلاثةُ يُضبطون معاً في جلسةِ
تهيئةٍ واحدة (أنشئ القسم ⟵ أسنِد إليه موظّفاً ⟵ ضعه في عنقود)، وتفريقُهم على
صفحاتٍ يجعل التهيئةَ رحلةً بين ثلاثِ روابط.

**العرضُ لا يحمل قاعدةً:** كلُّ كتابةٍ تمرّ من ``core/admin_service.py`` —
هناك تعيش التوأمةُ التلقائيّة وحارسُ حلقات الشجرة وأثرُ تغيير الأدوار.
"""


from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, Q
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache

from core.admin_service import UNSET, create_department, delete_group, save_group, update_department
from core.logging_models import UserActivityLog
from core.models import Department, Entity, EntityGroup
from core.scoping import (ROLE_GRANT_KEYS, ROLE_LABELS, can_add_units, can_manage_accounts, can_manage_departments,
                          grantable_roles, managed_department_ids, user_department_id)

TABS = ('overview', 'departments', 'groups', 'reservations', 'audit', 'settings')
#: الدفعة 1: تبويباتٌ صار لها صفحاتُها في البرنامج (ورشةُ العناقيد · الحجوزات · سجلُّ الحركات · مركزُ الإعدادات)
MOVED_TABS = ('groups', 'reservations', 'audit', 'settings')


def _moved_tab_url(request, tab):
    """وجهةُ التبويب المنقول — من قائمةٍ ثابتة، ومعاملاتُه الرقميّة وحدها تُحمل."""
    from urllib.parse import urlencode

    if tab == 'groups':
        edit = request.GET.get('edit', '')
        return reverse('entity_list') + '?view=groups' + (f'&edit={edit}' if edit.isdecimal() else '')
    if tab == 'reservations':
        query = {key: request.GET[key] for key in ('days', 'page') if request.GET.get(key, '').isdecimal()}
        return reverse('system_reservations') + ('?' + urlencode(query) if query else '')
    return reverse('audit_log' if tab == 'audit' else 'settings_hub')


#: حالاتُ قائمة الحسابات التي تحملها روابطُ اللوحة القديمة (بطاقاتُ الأعداد)
_ACCOUNT_LINK_STATUSES = ('active', 'inactive', 'password', 'sensitive')


def _accounts_url(request):
    """``?tab=users`` القديم ⟵ قائمةُ الحسابات بتصفيته: الحالةُ من قائمةٍ ثابتة، والقسمُ رقمٌ أو لا شيء."""
    from urllib.parse import urlencode

    query = {}
    if request.GET.get('status', '') in _ACCOUNT_LINK_STATUSES:
        query['status'] = request.GET['status']
    department = request.GET.get('dept', '') or request.GET.get('department', '')
    if department.isdecimal():
        query['department'] = department
    return reverse('system_accounts') + ('?' + urlencode(query) if query else '')


ADMIN_ACTIONS = ('CREATE_DEPARTMENT', 'EDIT_DEPARTMENT', 'ASSIGN_USER',
                 'CREATE_USER', 'DELETE_USER', 'CREATE_GROUP', 'EDIT_GROUP', 'DELETE_GROUP',
                 'PASSWORD_RESET', 'EDIT_SETTINGS', 'EDIT_PERMISSIONS')

@login_required
@never_cache
def admin_panel(request):
    """إدارةٌ عالمية للسوبر أدمن وإدارةٌ شجرية لرئيس القسم."""
    if not can_manage_departments(request.user):
        raise PermissionDenied('إدارة الأقسام لمدير النظام ورئيس القسم.')

    tab = request.GET.get('tab')
    # الدفعة 2: الحساباتُ صفحةٌ في البرنامج يفتحها كلُّ مَن يفتح اللوحة (والرئيسُ بنطاقه) — والكتابةُ في المحرّر
    if request.method == 'GET' and tab == 'users':
        return redirect(_accounts_url(request))
    # الدفعة 1: تبويباتٌ مكرّرة صارت صفحاتٍ في البرنامج — الرابطُ القديم يُحوَّل إليها لمن يملكها،
    # ورئيسُ القسم (لا يملكها) يبقى على «نظرة عامة» كما كان.
    if request.method == 'GET' and tab in MOVED_TABS and can_manage_accounts(request.user):
        return redirect(_moved_tab_url(request, tab))
    tab = (tab if tab in TABS and tab not in MOVED_TABS else 'overview')

    if request.method == 'POST':
        return _handle(request)

    return _render_panel(request, tab)


def _render_panel(request, tab):
    from core.views.system_admin import account_rows

    is_superadmin = can_manage_accounts(request.user)
    department_ids = managed_department_ids(request.user)
    departments = Department.objects.filter(pk__in=department_ids).order_by('code')
    # بطاقاتُ الأعداد روابطُ إلى قائمة الحسابات بتصفيتها — فتُعدّ من صفوفها هي (الدفعة 2)
    people = account_rows(request.user)
    root_department = (Department.objects.filter(
        pk=user_department_id(request.user)).first() if not is_superadmin else None)
    department_rows = _department_rows(None if is_superadmin else set(department_ids))
    overview = _overview(request.user, department_rows, None if is_superadmin else set(department_ids))
    grantable = grantable_roles(request.user)

    # شجرةُ الأقسام لـJS — قائمةٌ لا نصّ: ``json_script`` يرمّزها مرّةً واحدة، وكان
    # ``json.dumps`` قبله يرمّزها مرّتين فيصل نصٌّ لا مصفوفة (deps.filter ليست دالّة).
    # الأبُ بمعرِّفه لا برمزه: الرمزُ عربيٌّ يُكتب باليد، ومعرّفُ DOM منه كان يتصادم.
    # والمستوى من الاسم (``Department.level``) — العمقُ سمّى «قسم المتابعة» شعبة.
    departments_data = [
        {
            'id': row['department'].pk,
            'c': row['department'].code,
            'n': row['department'].name,
            'pid': row['department'].parent_id,
            'lv': row['department'].level(row['depth'])[0],
            'u': row['department'].member_count,
            'a': row['department'].active_member_count,
            'b': row['department'].book_count,
            'o': overview['overdue'].get(row['department'].pk, 0),
            'e': bool(row['department'].entity_id),
            'active': row['department'].is_active,
        }
        for row in department_rows
    ]


    unit_ids = Department.unit_level_ids()
    context = {
        'tab': tab,
        'is_superadmin': is_superadmin,
        'manager_root_id': user_department_id(request.user),
        'scope_label': 'جميع أقسام المؤسسة' if is_superadmin else str(root_department or 'قسم غير محدد'),
        'departments': department_rows,
        'all_departments': departments,
        'active_departments': departments.filter(is_active=True),
        # الأبُ لا يكون وحدة: الشجرةُ تقف عندها (قرارُ المالك 11‑02)
        'parent_departments': [d for d in departments if d.is_active and d.pk not in unit_ids],
        'unit_ids': unit_ids,
        'can_shape_tree': can_add_units(request.user),
        'department_count': len(department_rows),
        'active_department_count': sum(
            row['department'].is_active for row in department_rows),
        'staff_count': len(people),
        'inactive_user_count': sum(not row['is_active'] for row in people),
        # كلُّ عدّادٍ = عددُ ما تُظهره تصفيتُه (data-status): المعطَّلُ معدودٌ في الاثنين
        'password_pending_count': sum(row['temp_password'] for row in people),
        'sensitive_role_count': sum(row['is_sensitive'] for row in people),
        # «إسناد دور» في الإجراءات السريعة: ما يمنحه الناظر بأسماء الأدوار الواحدة
        'grantable_labels': [label for role, label in ROLE_LABELS.items() if ROLE_GRANT_KEYS[role] in grantable],
        # الجهةُ المقابلة في نافذة «وحدة جديدة» (العناقيدُ صارت في ورشتها — الدفعة 1)
        'entities': (Entity.objects.filter(is_active=True).order_by('name')
                    if is_superadmin else Entity.objects.none()),
        'departments_data': departments_data,
        'health_rows': overview['health_rows'],
        'org_overdue_total': overview['overdue_total'],
        'admin_activity': overview['admin_activity'],
    }
    return render(request, 'core/admin_panel.html', context)


def _overview(user, department_rows, department_ids):
    """متأخّراتُ كلّ قسم (للشجرتين) وصحّةُ الأقسام وآخرُ الحركات الإداريّة في النطاق."""
    from core.scoping import listed_books, scope_activity_for
    from core.views.filter_helpers import followup_q

    books = listed_books(user)
    if department_ids is not None:
        books = books.filter(department_id__in=department_ids)
    overdue = dict(
        books.filter(followup_q('overdue', timezone.localdate()))
        .order_by().values('department_id')
        .annotate(total=Count('pk')).values_list('department_id', 'total')
    )

    health = sorted(
        (row['department'] for row in department_rows),
        key=lambda d: (-overdue.get(d.pk, 0), -d.book_count, d.code),
    )[:6]
    peak = max((d.book_count for d in health), default=0)
    health_rows = [{
        'department': d,
        'overdue': overdue.get(d.pk, 0),
        'load_percent': round(d.book_count * 100 / peak) if peak else 0,
    } for d in health]

    activity = (
        scope_activity_for(user, UserActivityLog.objects.filter(action__in=ADMIN_ACTIONS))
        .select_related('user', 'department')
        .order_by('-timestamp')[:8]
    )
    in_tree = {row['department'].pk for row in department_rows}
    return {
        'overdue': overdue,
        'overdue_total': sum(total for pk, total in overdue.items() if pk in in_tree),
        'health_rows': health_rows,
        'admin_activity': activity,
    }


# ───────────────────────────── الكتابة ─────────────────────────────

def _handle(request):
    action = request.POST.get('action', '')
    tab = request.POST.get('tab', 'departments')
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
    if tab == 'groups' and can_manage_accounts(request.user):   # الدفعة 1: ورشةُ العناقيد بيتُها
        return _RETURN_TO['groups_workshop']
    return '/books/admin/?tab=%s' % (tab if tab in TABS and tab not in MOVED_TABS else 'departments')


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


def _save_group(request):
    group = EntityGroup.objects.filter(pk=request.POST.get('id')).first()

    # **الفرقُ بين «لم أرسل الأعضاء» و«أرسلتُهم فارغين»**: القائمةُ المتعدّدة في
    # HTML لا ترسل شيئاً حين لا يُحدَّد أحد، فزرُّ التعطيل — ولا حقلَ أعضاءَ فيه
    # — كان يُمرّر `[]` فتمسح `members.set([])` عضويّةَ العنقود **صامتاً**.
    # العلامةُ الصريحة تفصل الحالتين.
    members = ([int(v) for v in request.POST.getlist('members') if v.isdecimal()]
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
    'save_group': _save_group,
    'delete_group': _delete_group,
}


# ───────────────────────────── القراءة ─────────────────────────────

def _department_rows(department_ids=None):
    """الأقسامُ مرتَّبةً **شجريّاً** — القائمةُ المسطّحة تُخفي البنية التي بُنيت لأجلها."""
    from django.db.models import Count, Q

    queryset = Department.objects
    if department_ids is not None:
        queryset = queryset.filter(pk__in=department_ids)
    nodes = list(queryset
                 .select_related('parent', 'entity')
                 .annotate(book_count=Count('books', distinct=True),
                           member_count=Count('members', distinct=True),
                           active_member_count=Count(
                               'members', filter=Q(members__user__is_active=True),
                               distinct=True))
                 .order_by('code'))
    # النطاقُ المقصوص (شجرةُ رئيس القسم): جذرُه أبوه خارج المجموعة، فيُعامَل جذراً
    # بعمقه **المطلق** — وإلّا سقط كلُّ شيءٍ في مسار الأيتام بعمق صفر.
    in_scope = {node.pk for node in nodes}
    parents = (dict(Department.objects.values_list('id', 'parent_id'))
               if department_ids is not None else {})

    def _absolute_depth(node):
        depth, pid, seen = 0, node.parent_id, {node.pk}
        while pid is not None and pid not in seen:
            seen.add(pid)
            depth += 1
            pid = parents.get(pid)
        return depth

    by_parent = {}
    for node in nodes:
        key = node.parent_id if node.parent_id in in_scope else None
        by_parent.setdefault(key, []).append(node)

    rows, stack = [], [(node, _absolute_depth(node) if department_ids is not None else 0)
                       for node in reversed(by_parent.get(None, []))]
    while stack:
        node, depth = stack.pop()
        rows.append({'department': node, 'depth': depth})
        stack.extend((child, depth + 1) for child in reversed(by_parent.get(node.pk, [])))

    # أيتامٌ (أبٌ محذوفٌ أو حلقةٌ سبقت الحارس) لا يُسقَطون بصمت
    seen = {row['department'].pk for row in rows}
    rows.extend({'department': n, 'depth': 0} for n in nodes if n.pk not in seen)
    return rows


def _department(raw):
    return Department.objects.filter(pk=raw).first() if raw and str(raw).isdecimal() else None


def _entity(raw):
    return Entity.objects.filter(pk=raw).first() if raw and str(raw).isdecimal() else None


def _flag(raw):
    """``None`` تعني «لم يُرسَل الحقل» — وهي غيرُ «أُرسل فارغاً»."""
    if raw is None:
        return None
    return raw in ('1', 'on', 'true', 'True')
