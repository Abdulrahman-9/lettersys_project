# -*- coding: utf-8 -*-
"""
لوحةُ الإدارة — **مسارُ الكتابة الوحيد** إلى الأقسام والأدوار والعناقيد.

ثلاثةُ أشياءَ تجعل هذه الوحدةَ لازمةً بدل الكتابة المباشرة من العروض:

**١. قاعدةُ التوأمة التلقائيّة** (§12.2 من الخطّة): عقدةُ القسم في الشجرة
وجهتُه في الدليل **إسقاطان لشيءٍ واحد**، وإنشاءُ أحدهما بلا الآخر يُنتج قسماً
لا يُخاطَب أو جهةً بلا دفتر. فلا يُنشئ الكاتبُ توأماً يدويّاً أبداً.

**٢. تغييرُ الأدوار واقعةٌ تُسجَّل**: مَن منح رئاسةَ قسمٍ لمن، ومتى. الدورُ
يفتح سجلَّ القراءة والكتبَ السرّيّة — ومنحُه بلا أثرٍ يُبطل السجلَّ نفسَه.

**٣. الشجرةُ لا تُغلق على نفسها**: قسمٌ يصير أباً لجدّه يُنتج حلقةً تُعلّق
``subtree_ids`` إلى الأبد — والحارسُ هنا لا في الواجهة.
"""

import logging

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction

logger = logging.getLogger(__name__)

#: حارسُ «لم يُمرَّر» — يفترق عن ``None`` التي تعني هنا «اجعله بلا أب/بلا قسم».
UNSET = object()


def create_department(*, name, code, parent=None, by, entity=None):
    """يُنشئ قسماً **ومعه توأمُه في الدليل** في نَفَسٍ واحد.

    ``entity`` يُمرَّر إن كانت الجهةُ قائمةً سلفاً (الحالةُ الغالبة في شركةٍ
    دليلُها يحمل الوحدات منذ سنوات)؛ وإلّا تُنشأ باسم القسم.
    """
    from core.models import Department, Entity

    _guard_admin(by)
    name = (name or '').strip()
    code = (code or '').strip()
    if not name or not code:
        raise ValidationError('الاسم والرمز مطلوبان.')
    if parent is not None and not parent.is_active:
        raise ValidationError('لا يُتبع قسمٌ لقسمٍ معطَّل.')

    with transaction.atomic():
        if entity is None:
            entity, _ = Entity.objects.get_or_create(name=name)
        elif Department.objects.filter(entity=entity).exists():
            raise ValidationError('هذه الجهةُ مرتبطةٌ بقسمٍ آخر.')

        try:
            department = Department.objects.create(
                name=name, code=code, parent=parent, entity=entity)
        except IntegrityError as exc:
            raise ValidationError('الاسمُ أو الرمزُ مستعملٌ سلفاً.') from exc

        _log(by, 'CREATE_DEPARTMENT', {'code': code, 'name': name,
                                       'parent': parent.code if parent else None})
    return department


def update_department(department, *, by, name=None, code=None, parent=UNSET,
                      is_active=None):
    """يعدّل قسماً — **والشجرةُ محروسةٌ من الحلقات هنا لا في الواجهة**."""
    from core.models import Department

    _guard_admin(by)
    changes = {}

    if name is not None and name.strip() and name.strip() != department.name:
        changes['name'] = department.name = name.strip()
    if code is not None and code.strip() and code.strip() != department.code:
        changes['code'] = department.code = code.strip()
    if parent is not UNSET:
        _guard_no_cycle(department, parent)
        changes['parent'] = parent.code if parent else None
        department.parent = parent
    if is_active is not None and is_active != department.is_active:
        if not is_active and department.children.filter(is_active=True).exists():
            raise ValidationError('لا يُعطَّل قسمٌ له شُعبٌ نشطة.')
        changes['is_active'] = department.is_active = is_active

    if not changes:
        return department

    with transaction.atomic():
        try:
            department.save()
        except IntegrityError as exc:
            raise ValidationError('الاسمُ أو الرمزُ مستعملٌ سلفاً.') from exc
        _log(by, 'EDIT_DEPARTMENT', {'department': department.code, **changes})
    return department


def assign_user(user, *, by, department=UNSET, is_department_head=None,
                is_controller=None):
    """يُسند موظّفاً إلى قسمٍ ويمنحه أدوارَه — **وكلُّ منحٍ واقعةٌ مسجَّلة**.

    الدورُ يفتح سجلَّ القراءة والكتبَ السرّيّة، فمنحُه بلا أثرٍ يُبطل السجلّ.
    """
    from django.contrib.auth.models import Group

    from core.roles import CONTROLLER_GROUP_NAME
    from core.scoping import ensure_profile

    _guard_admin(by)
    profile = ensure_profile(user)
    changes = {}

    with transaction.atomic():
        if department is not UNSET and department != profile.department:
            changes['department'] = department.code if department else None
            profile.department = department
        if is_department_head is not None and is_department_head != profile.is_department_head:
            changes['is_department_head'] = profile.is_department_head = is_department_head
        if changes:
            profile.save()

        if is_controller is not None:
            group, _ = Group.objects.get_or_create(name=CONTROLLER_GROUP_NAME)
            had = user.groups.filter(pk=group.pk).exists()
            if is_controller != had:
                (user.groups.add if is_controller else user.groups.remove)(group)
                changes['is_controller'] = is_controller

        if changes:
            _log(by, 'ASSIGN_USER', {'user': user.get_username(), **changes})
    return profile


def save_group(*, by, name, member_ids=None, auto_rule='', group=None, is_active=None):
    """يُنشئ عنقوداً أو يعدّله — والعضويّةُ **لقطتُها في صفوف الإحالة** لا هنا."""
    from core.models import Entity, EntityGroup

    _guard_admin(by)
    name = (name or '').strip()
    if not name:
        raise ValidationError('اسمُ العنقود مطلوب.')
    if auto_rule and auto_rule not in dict(EntityGroup.AUTO_RULE_CHOICES):
        raise ValidationError('قاعدةٌ ديناميكيّةٌ غيرُ معروفة.')

    with transaction.atomic():
        if group is None:
            try:
                group = EntityGroup.objects.create(name=name, auto_rule=auto_rule or '')
            except IntegrityError as exc:
                raise ValidationError('اسمُ العنقود مستعملٌ سلفاً.') from exc
            action = 'CREATE_GROUP'
        else:
            group.name = name
            group.auto_rule = auto_rule or ''
            if is_active is not None:
                group.is_active = is_active
            try:
                group.save()
            except IntegrityError as exc:
                raise ValidationError('اسمُ العنقود مستعملٌ سلفاً.') from exc
            action = 'EDIT_GROUP'

        # العضويّةُ اليدويّة لا معنى لها مع قاعدةٍ ديناميكيّة — والاحتفاظُ بها
        # يُوهم قارئَ الشاشة أنّ العنقود ثابتٌ وهو محسوب.
        if not group.auto_rule and member_ids is not None:
            group.members.set(Entity.objects.filter(pk__in=member_ids))

        _log(by, action, {'group': group.name, 'auto_rule': group.auto_rule,
                          'members': group.resolved_members().count()})
    return group


# ───────────────────────────── الداخليّات ─────────────────────────────

def _guard_admin(by):
    """الإدارةُ لمديري النظام — ورئيسُ القسم يُدير قسمَه من شاشةٍ أضيق لاحقاً."""
    from core.scoping import is_privileged

    if not is_privileged(by):
        raise PermissionDenied('لوحةُ الإدارة لمدير النظام.')


def _guard_no_cycle(department, parent):
    """قسمٌ يصير أباً لجدّه يُعلّق ``subtree_ids`` في حلقةٍ لا تنتهي."""
    if parent is None:
        return
    if parent.pk == department.pk:
        raise ValidationError('لا يتبع القسمُ نفسَه.')

    seen, node = {department.pk}, parent
    while node is not None:
        if node.pk in seen:
            raise ValidationError('هذا الإسنادُ يُنشئ حلقةً في الشجرة.')
        seen.add(node.pk)
        node = node.parent


def _log(by, action, metadata):
    """أثرٌ في سجلّ الحركات — لا في تاريخ كتابٍ (لا كتابَ هنا)."""
    from core.logging_models import UserActivityLog

    try:
        UserActivityLog.objects.create(
            user=by, action=action,
            username_snapshot=by.get_username()[:150] if by else '',
            department=getattr(getattr(by, 'profile', None), 'department', None),
            metadata=metadata,
        )
    except Exception:                                # noqa: BLE001
        logger.warning('تعذّر تسجيل %s', action, exc_info=True)
