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

import secrets
from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.utils import timezone

#: حارسُ «لم يُمرَّر» — يفترق عن ``None`` التي تعني هنا «اجعله بلا أب/بلا قسم».
UNSET = object()


def create_department(*, name, code, parent=None, by, entity=None):
    """يُنشئ قسماً **ومعه توأمُه في الدليل** في نَفَسٍ واحد.

    ``entity`` يُمرَّر إن كانت الجهةُ قائمةً سلفاً (الحالةُ الغالبة في شركةٍ
    دليلُها يحمل الوحدات منذ سنوات)؛ وإلّا تُنشأ باسم القسم.
    """
    from core.models import Department, Entity

    _guard_department_parent(by, parent)
    if not _is_superuser(by) and entity is not None:
        raise PermissionDenied('رئيسُ القسم لا يربط جهاتٍ عامةً بأقسامه.')
    name = (name or '').strip()
    code = (code or '').strip()
    if not name or not code:
        raise ValidationError('الاسم والرمز مطلوبان.')
    if parent is not None and not parent.is_active:
        raise ValidationError('لا يُتبع قسمٌ لقسمٍ معطَّل.')

    with transaction.atomic():
        if entity is None:
            entity, _ = Entity.objects.get_or_create(
                name=name,
                defaults={'kind': Entity.KIND_UNIT if parent else Entity.KIND_INTERNAL},
            )
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

    _guard_department(by, department)
    changes = {}

    if name is not None and name.strip() and name.strip() != department.name:
        changes['name'] = department.name = name.strip()
    if code is not None and code.strip() and code.strip() != department.code:
        changes['code'] = department.code = code.strip()
    if parent is not UNSET:
        _guard_department_parent(by, parent)
        _guard_no_cycle(department, parent)
        if parent is not None and not parent.is_active:
            raise ValidationError('لا يُتبع قسمٌ لقسمٍ معطَّل.')
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
            if 'name' in changes and department.entity_id:
                department.entity.name = department.name
                department.entity.save(update_fields=['name'])
        except IntegrityError as exc:
            raise ValidationError('الاسمُ أو الرمزُ مستعملٌ سلفاً.') from exc
        _log(by, 'EDIT_DEPARTMENT', {'department': department.code, **changes})
    return department


def assign_user(user, *, by, department=UNSET, is_department_head=None,
                is_controller=None, is_archivist=None, is_company_archivist=None,
                job_title=None, is_entry=None, is_active=None, first_name=None,
                last_name=None, email=None):
    """يُسند موظّفاً إلى قسمٍ ويمنحه أدوارَه — **وكلُّ منحٍ واقعةٌ مسجَّلة**.

    الدورُ يفتح سجلَّ القراءة والكتبَ السرّيّة، فمنحُه بلا أثرٍ يُبطل السجلّ.
    """
    from django.contrib.auth.models import Group

    from core.roles import (ARCHIVE_ALL_GROUP_NAME, ARCHIVIST_GROUP_NAME,
                            CONTROLLER_GROUP_NAME, ENTRY_GROUP_NAME)
    from core.scoping import ensure_profile

    _guard_user_target(by, user)
    profile = ensure_profile(user)
    changes = {}

    with transaction.atomic():
        if department is not UNSET and department != profile.department:
            if department is not None and not department.is_active:
                raise ValidationError('لا يُسند موظّفٌ إلى قسمٍ معطَّل.')
            if department is None:
                if not _is_superuser(by):
                    raise PermissionDenied('لا يمكن لرئيس القسم إزالة موظّفٍ من نطاقه.')
            else:
                _guard_department(by, department)
            changes['department'] = department.code if department else None
            profile.department = department
        if job_title is not None:
            job_title = job_title.strip()
            if len(job_title) > 120:
                raise ValidationError('المسمّى الوظيفي يتجاوز 120 حرفاً.')
            if job_title != profile.job_title:
                changes['job_title'] = job_title
                profile.job_title = job_title
        user_fields = []
        for field, value in (('first_name', first_name), ('last_name', last_name)):
            if value is None:
                continue
            value = value.strip()
            if len(value) > 150:
                raise ValidationError('الاسم يتجاوز 150 حرفاً.')
            if getattr(user, field) != value:
                setattr(user, field, value)
                changes[field + '_updated'] = True
                user_fields.append(field)
        if email is not None:
            email = email.strip()
            if email:
                try:
                    validate_email(email)
                except ValidationError as exc:
                    raise ValidationError('صيغة البريد الإلكتروني غير صحيحة.') from exc
            if len(email) > 254:
                raise ValidationError('البريد الإلكتروني يتجاوز 254 حرفاً.')
            if user.email != email:
                user.email = email
                changes['email_updated'] = True
                user_fields.append('email')
        if user_fields:
            user.save(update_fields=user_fields)
        if is_department_head is not None and is_department_head != profile.is_department_head:
            _guard_admin(by)
            changes['is_department_head'] = profile.is_department_head = is_department_head
        if changes:
            profile.save()

        # الدوران مستقلّان ويُجمعان في شخصٍ واحد: كتلتان لا سلسلةٌ واحدة.
        for flag, name, key in (
                (is_controller, CONTROLLER_GROUP_NAME, 'is_controller'),
                (is_archivist, ARCHIVIST_GROUP_NAME, 'is_archivist'),
                (is_company_archivist, ARCHIVE_ALL_GROUP_NAME, 'is_company_archivist')):
            if flag is None:
                continue
            _guard_admin(by)
            group, _ = Group.objects.get_or_create(name=name)
            had = user.groups.filter(pk=group.pk).exists()
            if flag != had:
                (user.groups.add if flag else user.groups.remove)(group)
                changes[key] = flag

        if is_entry is not None:
            group, _ = Group.objects.get_or_create(name=ENTRY_GROUP_NAME)
            had = user.groups.filter(pk=group.pk).exists()
            if is_entry != had:
                (user.groups.add if is_entry else user.groups.remove)(group)
                changes['is_entry'] = is_entry

        if is_active is not None and is_active != user.is_active:
            if user.pk == getattr(by, 'pk', None) and not is_active:
                raise ValidationError('لا يمكن تعطيل الحساب الذي تستخدمه الآن.')
            user.is_active = is_active
            user.save(update_fields=['is_active'])
            changes['is_active'] = is_active

        if changes:
            _log(by, 'ASSIGN_USER', {'user': user.get_username(), **changes})
    return profile


def create_department_user(*, by, department, username, first_name='',
                           last_name='', email='', job_title='', role='viewer'):
    """ينشئ حساباً محلياً بكلمة مؤقتة عشوائية ويُعيدها لعرضٍ واحد."""
    from core.models import SecuritySettings, UserPassword, UserProfile
    from core.roles import ENTRY_GROUP_NAME, ensure_role_groups

    _guard_department(by, department)
    if not department.is_active:
        raise ValidationError('لا يمكن إنشاء حسابٍ في قسمٍ معطَّل.')
    if role not in ('viewer', 'entry'):
        raise PermissionDenied('هذا الدورُ لا يُمنح إلا من مدير النظام.')

    username = (username or '').strip()
    first_name = (first_name or '').strip()
    last_name = (last_name or '').strip()
    email = (email or '').strip()
    job_title = (job_title or '').strip()
    if not username:
        raise ValidationError('اسم المستخدم مطلوب.')
    if len(username) > 150:
        raise ValidationError('اسم المستخدم يتجاوز 150 حرفاً.')
    try:
        UnicodeUsernameValidator()(username)
        if email:
            validate_email(email)
    except ValidationError as exc:
        raise ValidationError('تحقّق من اسم المستخدم أو البريد الإلكتروني.') from exc
    if len(first_name) > 150 or len(last_name) > 150:
        raise ValidationError('الاسم يتجاوز 150 حرفاً.')
    if len(job_title) > 120:
        raise ValidationError('المسمّى الوظيفي يتجاوز 120 حرفاً.')
    if User.objects.filter(username__iexact=username).exists():
        raise ValidationError('اسم المستخدم مستعملٌ سلفاً.')

    password = secrets.token_urlsafe(max(24, SecuritySettings.get().password_min_length))
    with transaction.atomic():
        try:
            user = User.objects.create_user(
                username=username, email=email, first_name=first_name,
                last_name=last_name, password=password)
        except IntegrityError as exc:
            raise ValidationError('اسم المستخدم مستعملٌ سلفاً.') from exc
        UserProfile.objects.create(
            user=user, department=department, job_title=job_title,
            must_change_password=True)
        if role == 'entry':
            ensure_role_groups()
            user.groups.add(Group.objects.get(name=ENTRY_GROUP_NAME))
        temporary = UserPassword(
            user=user,
            expires_at=timezone.now() + timedelta(hours=24),
            is_viewed=True,
        )
        temporary.set_password(password)
        temporary.save()
        _log(by, 'CREATE_USER', {
            'user': user.get_username(), 'department': department.code,
            'job_title': job_title, 'role': role,
        })
    return user, password


def reset_department_user_password(*, by, user):
    """كلمةُ مرورٍ مؤقّتةٌ جديدة لموظّفٍ في شجرة الرئيس — تُعرض مرّةً واحدة.

    الحرّاسُ حرّاسُ التعديل نفسُها (``_guard_user_target``: لا إداريَّ ولا رئيسَ
    آخر ولا أرشيفيّاً ولا خارجَ الشجرة)، وفوقها: لا حسابُك أنت (يُغيَّر بكلمتك
    الحاليّة) ولا حسابٌ معطَّل (يُفعَّل أوّلاً). والكلمةُ عشوائيّةٌ لا يكتبها الرئيس،
    و``must_change_password`` يُجبر صاحبَها على تغييرها في أوّل دخول — فلا تبقى
    للرئيس كلمةٌ يعرفها. و``set_password`` يُسقط جلساتِه المفتوحة.
    """
    from core.models import SecuritySettings, UserPassword, UserProfile

    if by is None or user.pk == by.pk:
        raise PermissionDenied('كلمةُ مرورك أنت تُغيَّر من صفحة «تغيير كلمة المرور».')
    _guard_user_target(by, user)
    if not user.is_active:
        raise ValidationError('الحسابُ معطَّل — فعِّله أوّلاً ثم أعِد تعيينَ كلمته.')

    password = secrets.token_urlsafe(max(24, SecuritySettings.get().password_min_length))
    with transaction.atomic():
        user.set_password(password)
        user.save(update_fields=['password'])
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.must_change_password = True
        profile.save(update_fields=['must_change_password'])
        UserPassword.objects.filter(user=user).delete()
        temporary = UserPassword(
            user=user,
            expires_at=timezone.now() + timedelta(hours=24),
            is_viewed=True,
        )
        temporary.set_password(password)
        temporary.save()
        _log(by, 'PASSWORD_RESET', {
            'user': user.get_username(),
            'department': profile.department.code if profile.department_id else '',
        })
    return password


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


def delete_group(*, by, group):
    """يحذف عنقوداً **لا كتابَ يشير إليه** — وإلّا يُعطَّل.

    `Book.sent_to_group` بـ``SET_NULL``: فحذفُ عنقودٍ عُمِّم به كتابٌ يمحو
    «عُمِّم على: 42 جهة» من سجلٍّ تاريخيٍّ صامتاً — حقيقةٌ حدثت ولا تُستعاد.
    والقاعدةُ نفسُها التي حكمت الجهاتِ الوهميّة: **لا حذفَ لما له تاريخ.**
    """
    from core.models import Book

    _guard_admin(by)
    used = Book.all_objects.filter(sent_to_group=group).count()
    if used:
        raise ValidationError(
            'لا يُحذف عنقودٌ عُمِّم به %d كتاباً — عطّله بدل حذفه ليبقى أثرُه '
            'في سجلّ تلك الكتب.' % used)

    name = group.name
    with transaction.atomic():
        group.delete()
        _log(by, 'DELETE_GROUP', {'group': name})
    return name


# ───────────────────────────── الداخليّات ─────────────────────────────

def _guard_admin(by):
    """إدارة الحسابات والأدوار الحسّاسة والعناقيد للسوبر أدمن فقط."""
    from core.scoping import can_manage_accounts

    if not can_manage_accounts(by):
        raise PermissionDenied('لوحةُ الإدارة لمدير النظام.')


def _is_superuser(user):
    return bool(getattr(user, 'is_superuser', False))


def _guard_department_parent(by, parent):
    from core.scoping import can_manage_accounts, can_manage_department

    if can_manage_accounts(by):
        return
    if parent is None or not can_manage_department(by, parent):
        raise PermissionDenied('يمكن لرئيس القسم إنشاء شُعبٍ داخل شجرته فقط.')


def _guard_department(by, department):
    from core.scoping import can_manage_department

    if department is None or not can_manage_department(by, department):
        raise PermissionDenied('لا يمكنك إدارة هذا القسم.')


def _guard_user_target(by, user):
    from core.scoping import can_manage_accounts, can_manage_department

    if can_manage_accounts(by):
        return
    profile = getattr(user, 'profile', None)
    from core.roles import (ARCHIVE_ALL_GROUP_NAME, ARCHIVIST_GROUP_NAME,
                            CONTROLLER_GROUP_NAME)

    sensitive_groups = (
        ARCHIVE_ALL_GROUP_NAME,
        ARCHIVIST_GROUP_NAME,
        CONTROLLER_GROUP_NAME,
    )
    if (user.is_superuser or user.is_staff or profile is None
            or profile.is_department_head
            or user.groups.filter(name__in=sensitive_groups).exists()
            or not can_manage_department(by, profile.department_id)):
        raise PermissionDenied('يمكن لرئيس القسم إدارة مستخدمي شجرته فقط، دون الحسابات الإدارية.')


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
    """أثرٌ إلزاميّ داخل معاملة التغيير؛ ففشل التسجيل يُفشل التغيير كلَّه."""
    from core.logging_models import UserActivityLog

    UserActivityLog.objects.create(
        user=by, action=action,
        username_snapshot=by.get_username()[:150] if by else '',
        department=getattr(getattr(by, 'profile', None), 'department', None),
        metadata=metadata,
    )
