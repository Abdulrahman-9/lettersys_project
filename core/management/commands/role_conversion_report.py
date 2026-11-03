# -*- coding: utf-8 -*-
"""تقريرُ تحويل الحسابات إلى دورٍ واحد: للقراءة فقط، ويُعرض قبل وصل أوّل حارس."""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from core.models import UserProfile
from core.roles import (ARCHIVE_ALL_GROUP_NAME, ARCHIVIST_GROUP_NAME, CONTROLLER_GROUP_NAME,
                        ENTRY_GROUP_NAME, EXECUTOR_GROUP_NAME)
from core.scoping import ROLE_LABELS, role_of

ROLE_GROUPS = {CONTROLLER_GROUP_NAME, ARCHIVIST_GROUP_NAME, ARCHIVE_ALL_GROUP_NAME, ENTRY_GROUP_NAME, EXECUTOR_GROUP_NAME}


def losses(user):
    """ما يخسره هذا الحساب حين يصير له دورٌ واحد."""
    out = []
    groups = set(user.groups.values_list('name', flat=True)) & ROLE_GROUPS
    profile = UserProfile.objects.filter(user=user).select_related('department').first()
    is_head = bool(profile and profile.is_department_head)
    if len(groups) + int(is_head) > 1:
        out.append('يجمع أدواراً: ' + '، '.join(sorted(groups) + (['رئيس'] if is_head else [])))
    if user.is_staff and not user.is_superuser:
        out.append('is_staff بلا سوبر')
    department = profile.department if profile else None
    if ENTRY_GROUP_NAME in groups and department is not None and not department.holds_register:
        out.append('مدخل في وحدة لا تمسك سجلّاً')
    return out


class Command(BaseCommand):
    help = 'يعرض دور كلّ حساب وما يخسره عند التحويل إلى دور واحد. لا يكتب شيئاً.'

    def handle(self, *args, **options):
        for user in User.objects.select_related('profile').order_by('-is_active', 'username'):
            role = 'مدير النظام' if user.is_superuser else ROLE_LABELS[role_of(user)]
            state = 'نشط' if user.is_active else 'معطَّل'
            notes = ' | '.join(losses(user)) or '-'
            self.stdout.write(f'{user.username}\t{state}\t{role}\t{notes}')
