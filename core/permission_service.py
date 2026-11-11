# -*- coding: utf-8 -*-
"""الطريقُ الوحيد للكتابة في جدولَي الصلاحيّات، وكلُّ تغييرٍ له صفٌّ في سجلّ الحركات.

الأثرُ في المعاملة نفسها: تغييرٌ بلا أثرٍ لا يقع. والصفُّ الذي يساوي الافتراضَ يُحذف
ولا يُحفظ، وإلّا ثبّت الخليّةَ حين يتغيّر الافتراضُ لاحقاً.
"""
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
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
