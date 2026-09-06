from django.contrib.auth.models import Group, Permission

ENTRY_GROUP_NAME = 'مدخل الكتب'
CONTROLLER_GROUP_NAME = 'مشرف المتابعة'
ARCHIVIST_GROUP_NAME = 'مسؤول الأرشفة'

ROLE_DEFINITIONS = {
    'entry': {
        'label': ENTRY_GROUP_NAME,
        'description': 'إدخال الكتب اليومية مع إمكانية إضافة الجهات المرتبطة.'
    },
    'controller': {
        'label': CONTROLLER_GROUP_NAME,
        'description': 'الوصول السريع للكتب وتحديث الحالات دون صلاحيات إدارية كاملة.'
    },
    'archivist': {
        'label': ARCHIVIST_GROUP_NAME,
        'description': 'إدخالُ الكتب وحفظُها: تمامُ الأرشفة والاستعلامُ وفتحُ الأضابير.'
    },
    'viewer': {
        'label': 'قارئ فقط',
        'description': 'عرض البيانات المتاحة دون أي إمكانية للتعديل.'
    },
    'dept_head': {
        'label': 'رئيس القسم',
        'description': 'صلاحيات إدارية داخل قسمه وحده — ومنها الاطّلاع على سرّيّات القسم.'
    },
    'admin': {
        'label': 'مدير النظام',
        'description': 'إدارة المستخدمين والإعدادات وجميع الصلاحيات المتقدمة.'
    },
}


def ensure_role_groups():
    entry_group, _ = Group.objects.get_or_create(name=ENTRY_GROUP_NAME)
    if entry_group.permissions.count() == 0:
        entry_perms = Permission.objects.filter(codename__in=[
            'view_book', 'add_book',
            'view_entity', 'add_entity',
        ])
        entry_group.permissions.add(*entry_perms)

    controller_group, _ = Group.objects.get_or_create(name=CONTROLLER_GROUP_NAME)
    if controller_group.permissions.count() == 0:
        controller_perms = Permission.objects.filter(codename__in=[
            'view_book', 'add_book', 'change_book',
            'view_entity',
        ])
        controller_group.permissions.add(*controller_perms)

    archivist_group, _ = Group.objects.get_or_create(name=ARCHIVIST_GROUP_NAME)
    if archivist_group.permissions.count() == 0:
        archivist_perms = Permission.objects.filter(codename__in=[
            'view_book', 'add_book', 'change_book',
            'view_entity', 'add_entity',
        ])
        archivist_group.permissions.add(*archivist_perms)
    return entry_group, controller_group, archivist_group


def get_user_role(user):
    if not getattr(user, 'is_authenticated', False):
        return 'anonymous'
    if user.is_superuser:
        return 'admin'
    # رئاسةُ القسم صفةٌ في ملفّ المستخدم لا مجموعةٌ في جانغو: هي علاقةٌ بقسمٍ
    # بعينه، والمجموعاتُ عالميّة لا تعرف الأقسام.
    profile = getattr(user, 'profile', None)
    if profile is not None and profile.is_department_head:
        return 'dept_head'
    if user.groups.filter(name=CONTROLLER_GROUP_NAME).exists():
        return 'controller'
    # **بعد** مختصّ البريد وقبل المُدخِل: الرجلُ قد يجمع البريدَ والأرشفة
    # (الشهادةُ الميدانيّة تقول «مسؤول إدارة البريد والأرشفة» بصيغةٍ واحدة)،
    # وهذه تسميةُ عرضٍ واحدة لا تحتمل الجمع. فبوّابةُ الأرشفة عضويّةُ مجموعةٍ
    # في `scoping.is_archivist` لا تسميةٌ هنا — وإلّا فقَد الجامعُ طاولةَ بريده.
    if user.groups.filter(name=ARCHIVIST_GROUP_NAME).exists():
        return 'archivist'
    if user.groups.filter(name=ENTRY_GROUP_NAME).exists():
        return 'entry'
    return 'viewer'


def user_has_role(user, roles):
    role = get_user_role(user)
    return role == 'admin' or role in roles


def role_capabilities(role):
    caps = {
        'can_manage_users': False,
        'can_view_reports': False,
        'can_manage_books': False,
        'can_manage_entities': False,
        'can_view_notifications': False,
    }
    if role == 'admin':
        for key in caps:
            caps[key] = True
    elif role == 'dept_head':
        caps.update({
            'can_manage_books': True,
            'can_manage_entities': True,
            'can_view_notifications': True,
            'can_view_reports': True,
        })
    elif role == 'controller':
        caps.update({
            'can_manage_books': True,
            'can_manage_entities': True,
            'can_view_notifications': True,
        })
    elif role == 'archivist':
        caps.update({
            'can_manage_books': True,
            'can_manage_entities': True,
        })
    elif role == 'entry':
        caps.update({
            'can_manage_books': True,
            'can_manage_entities': True,
        })
    return caps
