# -*- coding: utf-8 -*-
"""مساعداتُ الاختبار المشتركة — لا اختباراتَ هنا."""


def as_writer(user):
    """يمنح مستخدمَ الاختبار دورَ «مدخل الكتب» ويُعيده.

    منذ 2026-11-01 مَن بلا مجموعةِ دورٍ «قارئ فقط» يقرأ ويعلّق ولا يكتب
    (``scoping.can_write``). والاختباراتُ التي كُتبت قبلها تُنشئ فاعليها بلا دور؛
    فالفاعلُ الذي يكتب — **ومعه الغريبُ الذي يُرفض** — يُمنح الدورَ صراحةً، وإلّا
    نجح اختبارُ «الوحدةُ المُحالُ إليها لا تعدّل» لأنّ الفاعلَ قارئٌ لا لأنّ النطاقَ يمنعه.
    """
    from django.contrib.auth.models import Group

    from core.roles import ENTRY_GROUP_NAME

    group, _ = Group.objects.get_or_create(name=ENTRY_GROUP_NAME)
    user.groups.add(group)
    return user
