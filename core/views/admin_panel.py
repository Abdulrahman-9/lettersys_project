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

from core.admin_service import (assign_user, create_department, delete_group,
                                save_group,
                                update_department)
from core.models import Department, Entity, EntityGroup
from core.roles import CONTROLLER_GROUP_NAME
from core.scoping import is_privileged

TABS = ('departments', 'users', 'groups')


@login_required
def admin_panel(request):
    """التبويبات الثلاثة — قراءةً وكتابة."""
    if not is_privileged(request.user):
        raise PermissionDenied('لوحةُ الإدارة لمدير النظام.')

    tab = request.GET.get('tab')
    tab = tab if tab in TABS else 'departments'

    if request.method == 'POST':
        return _handle(request)

    return render(request, 'core/admin_panel.html', {
        'tab': tab,
        'departments': _department_rows(),
        'all_departments': Department.objects.order_by('code'),
        'people': _user_rows(),
        'groups': EntityGroup.objects.prefetch_related('members').order_by('name'),
        'entities': Entity.objects.filter(is_active=True).order_by('name'),
        'auto_rules': EntityGroup.AUTO_RULE_CHOICES,
        # `?edit=<id>` يملأ النموذجَ بعنقودٍ قائم — تعديلٌ بصفر JS، ورابطٌ
        # يُنسخ ويُشارَك. وسقفُ الـ500 على الجهات أُسقط: عنقودٌ لا يجد عضوَه
        # في القائمة عيبٌ صامت (674 جهةً في القاعدة).
        'editing': _editing_group(request),
        'member_ids': _editing_member_ids(request),
    })


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
    return '/books/admin/?tab=%s' % (tab if tab in TABS else 'departments')


def _create_department(request):
    department = create_department(
        name=request.POST.get('name', ''),
        code=request.POST.get('code', ''),
        parent=_department(request.POST.get('parent')),
        entity=_entity(request.POST.get('entity')),
        by=request.user,
    )
    return 'أُنشئ القسم «%s» ومعه جهتُه في الدليل.' % department.name


def _update_department(request):
    department = _department(request.POST.get('id'))
    if department is None:
        raise ValidationError('القسمُ غير موجود.')

    # «بلا أب» اختيارٌ صريحٌ يفترق عن «لم أغيّر الأب»
    parent_raw = request.POST.get('parent')
    from core.admin_service import UNSET
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

    assign_user(
        user, by=request.user,
        department=_department(request.POST.get('department')),
        is_department_head=_flag(request.POST.get('is_department_head')) or False,
        is_controller=_flag(request.POST.get('is_controller')) or False,
    )
    return 'حُدِّث حساب «%s».' % user.get_username()


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

def _department_rows():
    """الأقسامُ مرتَّبةً **شجريّاً** — القائمةُ المسطّحة تُخفي البنية التي بُنيت لأجلها."""
    from django.db.models import Count

    nodes = list(Department.objects
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


def _user_rows():
    people = (User.objects.filter(is_active=True)
              .select_related('profile', 'profile__department')
              .prefetch_related('groups')
              .order_by('username'))
    return [{
        'user': u,
        'department': getattr(getattr(u, 'profile', None), 'department', None),
        'is_head': bool(getattr(getattr(u, 'profile', None), 'is_department_head', False)),
        'is_controller': any(g.name == CONTROLLER_GROUP_NAME for g in u.groups.all()),
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
