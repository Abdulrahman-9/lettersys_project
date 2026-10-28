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
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import redirect, render

from core.admin_service import (UNSET, assign_user, create_department,
                                create_department_user, delete_group, save_group,
                                update_department)
from core.logging_models import UserActivityLog
from core.models import Department, Entity, EntityGroup
from core.roles import (ARCHIVE_ALL_GROUP_NAME, ARCHIVIST_GROUP_NAME,
                        CONTROLLER_GROUP_NAME, ENTRY_GROUP_NAME)
from core.scoping import (can_manage_accounts, can_manage_departments,
                          managed_department_ids, user_department_id)

TABS = ('overview', 'departments', 'users', 'groups', 'audit', 'settings')


@login_required
def admin_panel(request):
    """إدارةٌ عالمية للسوبر أدمن وإدارةٌ شجرية لرئيس القسم."""
    if not can_manage_departments(request.user):
        raise PermissionDenied('إدارة الأقسام لمدير النظام ورئيس القسم.')

    is_superadmin = can_manage_accounts(request.user)
    tab = request.GET.get('tab', 'overview')
    if tab not in TABS:
        tab = 'overview'
    if tab in ('groups', 'audit') and not is_superadmin:
        tab = 'overview'

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

    # شجرةُ الأقسام لـJS — قائمةٌ لا نصّ: ``json_script`` يرمّزها مرّةً واحدة، وكان
    # ``json.dumps`` قبله يرمّزها مرّتين فيصل نصٌّ لا مصفوفة (deps.filter ليست دالّة)
    pk_to_code = {row['department'].pk: row['department'].code for row in department_rows}
    _LEVELS = ['قسم', 'شعبة', 'وحدة']
    departments_data = [
        {
            'id': row['department'].pk,
            'c': row['department'].code,
            'n': row['department'].name,
            'p': pk_to_code.get(row['department'].parent_id),
            'pid': row['department'].parent_id,
            'lv': _LEVELS[min(row['depth'], 2)],
            'u': row['department'].member_count,
            'a': row['department'].active_member_count,
            'b': row['department'].book_count,
            'active': row['department'].is_active,
        }
        for row in department_rows
    ]

    # حسابات بانتظار أول دخول (proxy لـ «تغيير كلمة المرور») — داخل النطاق وحدَه
    pending_pw_count = sum(
        1 for row in people if row['is_active'] and row['user'].last_login is None)

    # الأدوار الحسّاسة
    sensitive_count = sum(
        1 for row in people
        if (row['is_head'] or row['is_controller'] or
            row['is_archivist'] or row['is_company_archivist'] or
            row['user'].is_superuser)
    )

    # سجلّ الحركات (سوبر أدمن فقط، آخر 40 واقعة غير مطوية)
    audit_log = (
        list(UserActivityLog.objects
             .select_related('user', 'department')
             .exclude(action__in=UserActivityLog.FOLDED_ACTIONS)
             .order_by('-timestamp')[:40])
        if is_superadmin else []
    )

    return render(request, 'core/admin_panel.html', {
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
        'pending_pw_count': pending_pw_count,
        'sensitive_count': sensitive_count,
        'groups': (EntityGroup.objects.prefetch_related('members').order_by('name')
                   if is_superadmin else EntityGroup.objects.none()),
        'entities': (Entity.objects.filter(is_active=True).order_by('name')
                    if is_superadmin else Entity.objects.none()),
        'auto_rules': EntityGroup.AUTO_RULE_CHOICES,
        'editing': _editing_group(request) if is_superadmin else None,
        'member_ids': _editing_member_ids(request) if is_superadmin else set(),
        'created_credentials': created_credentials,
        'create_form_values': create_form_values or {},
        'departments_data': departments_data,
        'audit_log': audit_log,
    })


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
        # رئيسُ القسم يمنح: مدخل · أرشيفي · مشرف متابعة — لكن ليس رئيس قسم ولا أرشيف الشركة.
        roles = {
            'is_entry': _flag(request.POST.get('is_entry')),
            'is_archivist': _flag(request.POST.get('is_archivist')),
            'is_controller': _flag(request.POST.get('is_controller')),
        }

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


def _user_rows(department_ids=None, actor_id=None):
    people = User.objects.all()
    if department_ids is not None:
        people = (people.filter(profile__department_id__in=department_ids)
                  .exclude(is_staff=True))
    people = (people.select_related('profile', 'profile__department')
              .prefetch_related('groups')
              .order_by('username'))
    return [{
        'user': u,
        'department': getattr(getattr(u, 'profile', None), 'department', None),
        'is_head': bool(getattr(getattr(u, 'profile', None), 'is_department_head', False)),
        'is_controller': any(g.name == CONTROLLER_GROUP_NAME for g in u.groups.all()),
        'is_archivist': any(g.name == ARCHIVIST_GROUP_NAME for g in u.groups.all()),
        'is_company_archivist': any(g.name == ARCHIVE_ALL_GROUP_NAME
                                    for g in u.groups.all()),
        'is_entry': any(g.name == ENTRY_GROUP_NAME for g in u.groups.all()),
        'is_active': u.is_active,
        'job_title': getattr(getattr(u, 'profile', None), 'job_title', ''),
        'is_self': u.pk == actor_id,
    } for u in people]


def _department(raw):
    return Department.objects.filter(pk=raw).first() if raw and str(raw).isdigit() else None


def _entity(raw):
    return Entity.objects.filter(pk=raw).first() if raw and str(raw).isdigit() else None


def _flag(raw):
    """``None`` تعني «لم يُرسَل الحقل» — وهي غيرُ «أُرسل فارغاً»."""
    if raw is None:
        return None
    return raw in ('1', 'on', 'true', 'True')
