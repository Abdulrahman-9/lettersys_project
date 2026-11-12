# -*- coding: utf-8 -*-
"""الطريقُ الوحيد للكتابة في جدولَي الصلاحيّات، وكلُّ تغييرٍ له صفٌّ في سجلّ الحركات.

الأثرُ في المعاملة نفسها: تغييرٌ بلا أثرٍ لا يقع. والصفُّ الذي يساوي الافتراضَ يُحذف
ولا يُحفظ، وإلّا ثبّت الخليّةَ حين يتغيّر الافتراضُ لاحقاً.
"""
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from core.audit_service import _department_of, client_ip
from core.logging_models import UserActivityLog
from core.models import RoleCapabilityOverride, UserCapabilityOverride
from core.scoping import (CAPABILITIES, ROLE_LABELS, WIRED_CAPABILITIES, can_edit_exception,
                          can_edit_role_matrix, clear_capability_cache, is_privileged, role_capability,
                          role_cell_frozen, role_of)

EDIT_PERMISSIONS = 'EDIT_PERMISSIONS'


def _word(value):
    return {True: 'يستطيع', False: 'لا يستطيع', None: 'حسب الدور'}[value]


def _audit(request, *, scope, subject, key, before, after, extra=None):
    """صفُّ الأثر، مباشرةً لا عبر ``record_event`` الذي يبتلع الخطأ: فشلُه يُلغي التغيير."""
    by = request.user
    label = CAPABILITIES[key].label
    UserActivityLog.objects.create(
        user=by, action=EDIT_PERMISSIONS, department=_department_of(by),
        ip_address=client_ip(request), user_agent=(request.META.get('HTTP_USER_AGENT') or '')[:1000],
        path=(request.path or '')[:500], method=(request.method or '')[:10],
        metadata={'scope': scope, 'capability': key, 'from': before, 'to': after, **(extra or {}),
                  'summary': f'صلاحيّة «{label}» لـ{subject}: {_word(before)} ⟵ {_word(after)}'[:500]},
    )


@transaction.atomic
def set_role_override(request, role, key, allowed):
    """يعدّل خليّةً في مصفوفة الأدوار. يعيد True إن تغيّر شيء."""
    if not can_edit_role_matrix(request.user):
        raise PermissionDenied('مصفوفة الأدوار يعدّلها مدير النظام وحده.')
    capability = CAPABILITIES[key]
    if role not in ROLE_LABELS:
        raise ValueError(f'دور غير معروف: {role}')
    if capability.locked or role_cell_frozen(key, role):
        raise PermissionDenied('هذه الخليّة مقفلة.')
    allowed = bool(allowed)
    before = role_capability(role, key)
    if before == allowed:
        return False
    if allowed == (role in capability.holders):
        RoleCapabilityOverride.objects.filter(role=role, capability=key).delete()
    else:
        RoleCapabilityOverride.objects.update_or_create(
            role=role, capability=key, defaults={'allowed': allowed, 'changed_by': request.user})
    _audit(request, scope='role', subject=ROLE_LABELS[role], key=key, before=before, after=allowed,
           extra={'role': role})
    return True


@transaction.atomic
def reset_role_overrides(request, key=None):
    """يعيد صفّاً، أو المصفوفةَ كلّها، إلى المعتمد خليّةً خليّة عبر ``set_role_override``
    فلكلّ خليّةٍ أثرُها. يعيد الخلايا التي عادت ``[(role, key)]``."""
    if not can_edit_role_matrix(request.user):
        raise PermissionDenied('مصفوفة الأدوار يعدّلها مدير النظام وحده.')
    rows = RoleCapabilityOverride.objects.filter(role__in=list(ROLE_LABELS), capability__in=[key] if key else list(CAPABILITIES))
    changed = []
    for row in rows.order_by('capability', 'role'):
        capability = CAPABILITIES[row.capability]
        # صفٌّ مزروعٌ على خليّةٍ مقفلة مُهمَلٌ في القرار، فلا شيء يعود.
        if capability.locked or role_cell_frozen(row.capability, row.role):
            continue
        if set_role_override(request, row.role, row.capability, row.role in capability.holders):
            changed.append((row.role, row.capability))
    return changed


def role_holders():
    """الحساباتُ النشطة لكلّ دور بـ``role_of``، ومديرُ النظام عمودٌ وحده: (admins, {role: n})."""
    counts = dict.fromkeys(ROLE_LABELS, 0)
    admins = 0
    for user in User.objects.filter(is_active=True).select_related('profile__department').prefetch_related('groups'):
        if is_privileged(user):
            admins += 1
        else:
            counts[role_of(user)] += 1
    return admins, counts


def role_matrix():
    """المصفوفةُ كما تُعرض: أعمدةُ الأدوار بعدد حامليها، وصفوفٌ بمجموعاتها، ولكلّ خليّةٍ
    قيمتُها وافتراضُها وقفلُها، وللمعدَّلة صفُّها (من عدّلها ومتى)."""
    admins, holders = role_holders()
    rows = {(r.role, r.capability): r for r in RoleCapabilityOverride.objects.select_related('changed_by')}
    overrides = {cell: row.allowed for cell, row in rows.items()}
    groups = {}
    for key, capability in CAPABILITIES.items():
        cells = []
        for role in ROLE_LABELS:
            default = role in capability.holders
            locked = capability.locked or role_cell_frozen(key, role)
            allowed = role_capability(role, key, overrides)
            cells.append({'role': role, 'label': ROLE_LABELS[role], 'allowed': allowed, 'default': default, 'locked': locked,
                          'row': rows[(role, key)] if allowed != default else None})
        changed = [c['row'] for c in cells if c['row']]
        groups.setdefault(capability.group, []).append({
            'key': key, 'label': capability.label, 'locked': capability.locked, 'cells': cells,
            'wired': key in WIRED_CAPABILITIES,
            'changed': len(changed), 'last': max(changed, key=lambda r: r.changed_at) if changed else None})
    return {
        'admins': admins,
        'roles': [{'key': role, 'label': label, 'holders': holders[role]} for role, label in ROLE_LABELS.items()],
        'groups': [{'name': name, 'rows': caps} for name, caps in groups.items()],
        'changed': sum(row['changed'] for caps in groups.values() for row in caps),
    }


@transaction.atomic
def set_user_override(request, target, key, allowed):
    """يضع استثناءً لشخص، و``allowed=None`` رجوعٌ إلى الدور. يعيد True إن تغيّر شيء."""
    if not can_edit_exception(request.user, target, key):
        raise PermissionDenied('لا تملك تعديل هذه الصلاحيّة لهذا الموظّف.')
    row = UserCapabilityOverride.objects.filter(user=target, capability=key).first()
    before = row.allowed if row else None
    base = role_capability(role_of(target), key)
    after = None if allowed is None or bool(allowed) == base else bool(allowed)
    if before == after:
        return False
    if after is None:
        row.delete()
    else:
        UserCapabilityOverride.objects.update_or_create(
            user=target, capability=key, defaults={'allowed': after, 'changed_by': request.user})
    _audit(request, scope='user', subject=target.get_username(), key=key, before=before, after=after,
           extra={'target_id': target.pk, 'target': target.get_username()})
    clear_capability_cache(target)
    return True


def orphan_rows():
    """صفوفٌ بمفتاحٍ لم يعد مسجَّلاً: تُتجاهل في القرار، وهذا يكشفها حتّى لا تبقى صامتة."""
    known = set(CAPABILITIES)
    return (list(RoleCapabilityOverride.objects.exclude(capability__in=known))
            + list(UserCapabilityOverride.objects.exclude(capability__in=known)))


#: الأعلامُ الستّة التي يُشتقّ منها الدورُ الواحد (``role_of``) — تُضبط كلُّها صراحةً عند كلّ تغيير:
#: علمٌ باقٍ من دورٍ سابق سلطةٌ خفيّة (حرّاسُ السرّيّ و``is_sensitive_account`` يقرؤون المجموعات).
ROLE_FLAG_NAMES = ('is_department_head', 'is_controller', 'is_archivist', 'is_company_archivist',
                   'is_entry', 'is_executor')
ROLE_FLAGS = {
    'head': {'is_department_head': True}, 'unit': {'is_department_head': True},
    'mail': {'is_controller': True}, 'archivist': {'is_archivist': True},
    'entry': {'is_entry': True}, 'executor': {'is_executor': True}, 'reader': {},
}


def _capability_label(key):
    return CAPABILITIES[key].label if key in CAPABILITIES else key


def cancel_exceptions(request, target):
    """يُلغي استثناءاتِ الشخص كلَّها بأثرٍ لكلٍّ منها، ويعيد أسماءها.

    الموصولُ غيرُ المقفل يمرّ بـ``set_user_override`` (أثرُه المعتاد)؛ والمقفلُ واليتيمُ (مفتاحٌ أُزيل من
    السجلّ) يُحذفان مباشرةً بأثرٍ يسمّيهما — كانا يرفعان ``PermissionDenied``/``KeyError`` فيُفشلان التغييرَ كلَّه.
    """
    names = []
    for row in list(UserCapabilityOverride.objects.filter(user=target)):
        key = row.capability
        names.append(_capability_label(key))
        capability = CAPABILITIES.get(key)
        if capability is not None and not capability.locked:
            set_user_override(request, target, key, None)
            continue
        row.delete()
        UserActivityLog.objects.create(
            user=request.user, action=EDIT_PERMISSIONS, department=_department_of(request.user),
            ip_address=client_ip(request), path=(request.path or '')[:500], method=(request.method or '')[:10],
            metadata={'scope': 'user', 'capability': key, 'from': row.allowed, 'to': None,
                      'target_id': target.pk, 'target': target.get_username(),
                      'summary': f'أُلغي استثناءُ «{_capability_label(key)}» لـ{target.get_username()} (مقفلٌ أو يتيم)'[:500]},
        )
    clear_capability_cache(target)
    return names


def role_change_preview(target, role):
    """ما يُفقد وما يبقى وما يُلغى إن صار دورُ الشخص ``role`` — يُحسب على الخادم، والموصولُ وحده."""
    from core.scoping import has_capability, role_capability

    lose, keep = [], []
    for key in CAPABILITIES:
        if key not in WIRED_CAPABILITIES or key in ('book.read', 'book.comment'):
            continue
        before = has_capability(target, key)
        after = role_capability(role, key)
        if before and not after:
            lose.append(CAPABILITIES[key].label)
        elif before and after:
            keep.append(CAPABILITIES[key].label)
    cancel = [_capability_label(key) for key in
              UserCapabilityOverride.objects.filter(user=target).values_list('capability', flat=True)]
    return {'lose': lose, 'keep': keep, 'cancel': cancel}


@transaction.atomic
def set_user_role(request, target, role):
    """يجعل للشخص دوراً واحداً: يُلغي استثناءاتِه، ويضبط الأعلامَ الستّة كلَّها، ويكتب الأثر.

    لمدير النظام وحده، ولا على نفسه ولا على مدير نظامٍ آخر (``assign_user`` لا يحرسهما للسوبر).
    والدورُ مقيَّدٌ بقسم الشخص (``roles_for_department``). يعيد True إن تغيّر شيء.
    """
    from core.admin_service import assign_user
    from core.roles import ARCHIVE_ALL_GROUP_NAME
    from core.scoping import can_manage_accounts, roles_for_department

    by = request.user
    if not can_manage_accounts(by):
        raise PermissionDenied('أدوارُ الحسابات يغيّرها مدير النظام وحده.')
    # ومَن يملك هذا مديرُ نظام، فحسابُه هو يقع هنا أيضاً — لا يغيّر أحدٌ دورَه بنفسه.
    if target.is_superuser:
        raise PermissionDenied('دورُ مدير النظام لا يُعدَّل من هنا.')
    department = getattr(getattr(target, 'profile', None), 'department', None)
    if role not in roles_for_department(department):
        raise ValidationError('هذا الدورُ لا يُسند في هذا القسم.')
    before = role_of(target)
    if before == role:
        return False

    cancelled = cancel_exceptions(request, target)
    flags = dict.fromkeys(ROLE_FLAG_NAMES, False)
    flags.update(ROLE_FLAGS[role])
    if role == 'archivist':   # أرشيفُ الشركة صفةٌ للأرشيفيّ تبقى معه ولا تبقى بعده
        flags['is_company_archivist'] = target.groups.filter(name=ARCHIVE_ALL_GROUP_NAME).exists()
    assign_user(target, by=by, **flags)
    clear_capability_cache(target)
    UserActivityLog.objects.create(
        user=by, action=EDIT_PERMISSIONS, department=_department_of(by),
        ip_address=client_ip(request), path=(request.path or '')[:500], method=(request.method or '')[:10],
        metadata={'scope': 'role_change', 'from': before, 'to': role, 'target_id': target.pk,
                  'target': target.get_username(), 'cancelled': cancelled,
                  'summary': f'دورُ {target.get_username()}: «{ROLE_LABELS[before]}» ⟵ «{ROLE_LABELS[role]}»'[:500]},
    )
    return True

