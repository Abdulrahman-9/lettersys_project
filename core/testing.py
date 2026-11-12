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


def as_referrer(user):
    """كاتبٌ يُحيل ويستلم باستثناءٍ شخصيّ — لاختبارات آليّة الإحالة.

    منذ شريحة الإحالات (2026‑11‑04) لا يُحيل المدخلُ ولا يستلم. وهذه الاختباراتُ تحرس
    الآليّةَ لا الدور، والدورُ محروسٌ في ``tests_referral_gates`` و``tests_capabilities``.
    """
    from core.models import UserCapabilityOverride

    as_writer(user)
    for key in ('referral.send', 'referral.receive'):
        UserCapabilityOverride.objects.update_or_create(user=user, capability=key, defaults={'allowed': True})
    return user


def as_custodian(user):
    """كاتبٌ يحذف إلى السلّة ويسترجع منها باستثناءٍ شخصيّ — لاختبارات آليّة السلّة.

    منذ (ب)4 (2026‑11‑11) الحذفُ لرئيس القسم ومختصّ البريد، والاسترجاعُ لهما ولمسؤول الأرشفة.
    وهذه الاختباراتُ تحرس الآليّةَ لا الدور، والدورُ محروسٌ في ``tests_b4_trash``.
    """
    from core.models import UserCapabilityOverride

    as_writer(user)
    for key in ('book.trash', 'book.restore'):
        UserCapabilityOverride.objects.update_or_create(user=user, capability=key, defaults={'allowed': True})
    return user


def as_mail_operator(user):
    """كاتبٌ يشغّل البريد ويرسل الكتابَ باستثناءٍ شخصيّ — لاختبارات آليّة البريد ونطاقه.

    منذ (ب)5 (2026‑11‑12) الإنشاءُ والإرسالُ لمختصّ البريد. ونطاقُ قراءة البريد عضويّةٌ لا مفتاح،
    فالاستثناءُ يفتح الأفعالَ ولا يغيّر ما يُرى. والدورُ محروسٌ في ``tests_b5_mail``.
    """
    from core.models import UserCapabilityOverride

    as_writer(user)
    for key in ('mail.operate', 'mail.send_book'):
        UserCapabilityOverride.objects.update_or_create(user=user, capability=key, defaults={'allowed': True})
    return user

