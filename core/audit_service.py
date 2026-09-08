# -*- coding: utf-8 -*-
"""
سجلُّ الحركات — **مسارُ الكتابة الوحيد** إلى ``UserActivityLog``.

طلبُ المالك: «مَن رأى، مَن شاهد، مَن استلم، مَن فرّق، مَن عدّل، مَن حذف — كلُّ
الحركات تُحفظ في سجلّ الحركات للأدمن الرئيسيّ لكلّ قسم فضلاً عن السوبر أدمن».

**قاعدةٌ لا تُخرق:** فشلُ التسجيل **لا يُفشل الصفحة أبداً**. سجلُّ تدقيقٍ يُسقط
صفحةً هو عطلٌ يوميّ، وعطلٌ يوميّ يُطفئه أحدُهم فيصير صفرَ تدقيق.

**وما يُطوى وما لا يُطوى:** الفتحُ المتعمَّد يُطوى في صفٍّ لكلّ يوم بعدّاد —
وإلّا صارت القراءةُ ربعَ مليون صفٍّ سنويّاً بلا جوابٍ أفضل. وما **يُخرج
بياناتٍ من الجهاز** (تحميلٌ وتصديرٌ وطباعةٌ ورابطٌ موقَّع وسرّيّ) يبقى صفّاً
لكلّ واقعة: طيُّ «حمّله خمس مرّات» في صفٍّ واحد **إتلافُ دليل**.
"""

import logging

from django.db import IntegrityError, transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


def record_view(request, book, action=None):
    """يسجّل **فتحاً متعمَّداً** لكتاب — مطويّاً في صفٍّ واحدٍ لليوم.

    لا يُسجَّل الظهورُ في قائمة: قائمةٌ تعرض خمسين صفّاً لا تعني أنّ صاحبها
    «رأى» خمسين كتاباً، وتسجيلُها يضخّم السجلَّ عشرين ضعفاً بلا معنى.
    """
    from core.logging_models import UserActivityLog

    return _fold(request, book, action or UserActivityLog.VIEW_BOOK)


def record_event(request, action, *, book=None, metadata=None):
    """يسجّل واقعةً **لا تُطوى** — كلُّ مرّةٍ صفّ.

    للتحميل والتصدير والطباعة والرابط الموقَّع والاطّلاع على سرّيّ: هذه أحداثُ
    إخراجِ بياناتٍ من الجهاز، وعددُ مرّاتها ومواقيتُها **هي الدليل**.
    """
    from core.logging_models import UserActivityLog

    user = _actor(request)
    try:
        return UserActivityLog.objects.create(
            user=user, action=action, book=book,
            department=_department_of(user),
            ip_address=client_ip(request),
            user_agent=(request.META.get('HTTP_USER_AGENT') or '')[:1000],
            path=(request.path or '')[:500],
            method=(request.method or '')[:10],
            metadata=metadata or {},
        )
    except Exception:                                # noqa: BLE001
        logger.warning('تعذّر تسجيل الحركة %s', action, exc_info=True)
        return None


def record_login(user, request, *, action='LOGIN', username=''):
    """دخولٌ وخروجٌ وفشلُ دخول — والفاشلُ يحمل الاسمَ المُحاوَل لا كلمةَ السرّ.

    **ولا يُسجَّل شيءٌ من حقل كلمة المرور إطلاقاً** — ولا حتّى طولُه.
    """
    from core.logging_models import UserActivityLog

    try:
        return UserActivityLog.objects.create(
            user=user if (user and user.is_authenticated) else None,
            username_snapshot=(username or (user.get_username() if user else ''))[:150],
            action=action,
            department=_department_of(user),
            ip_address=client_ip(request),
            user_agent=(request.META.get('HTTP_USER_AGENT') or '')[:1000] if request else '',
            path=(request.path or '')[:500] if request else '',
        )
    except Exception:                                # noqa: BLE001
        logger.warning('تعذّر تسجيل %s', action, exc_info=True)
        return None


def readers_of(book):
    """مَن فتح هذا الكتاب — تجميعٌ فوق الصفوف المطويّة.

    هذا ما يُغني عن جدولِ «إيصالات قراءةٍ» منفصل: الصفوفُ نفسُها تُجيب «مَن
    رأى» و«متى أوّلَ مرّة وآخرَ مرّة وكم مرّة» بمصدرِ حقيقةٍ واحد.
    """
    from django.db.models import Max, Min, Sum

    from core.logging_models import UserActivityLog

    return (UserActivityLog.objects
            .filter(book=book, action__in=UserActivityLog.FOLDED_ACTIONS)
            .values('user_id', 'username_snapshot')
            .annotate(first_day=Min('day'), last_seen=Max('last_seen_at'),
                      times=Sum('count'))
            .order_by('-last_seen'))


def client_ip(request):
    """``REMOTE_ADDR`` حصراً ما لم يكن الخادمُ خلف بروكسي مضبوط.

    الترويسةُ ``X-Forwarded-For`` **يرسلها العميل**، والثقةُ بها في سجلٍّ غرضُه
    المساءلة تعني أنّ أيَّ موظّفٍ على الشبكة يلبس عنوانَ غيره ويُزوّر الدليل.
    فلا تُقرأ إلّا إذا أعلن النشرُ صراحةً أنّه خلف بروكسي
    (``TRUST_X_FORWARDED_FOR = True``).
    """
    if request is None:
        return None

    from django.conf import settings

    if getattr(settings, 'TRUST_X_FORWARDED_FOR', False):
        forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
        if forwarded:
            return forwarded.split(',')[0].strip()[:45]
    return request.META.get('REMOTE_ADDR')


# ───────────────────────────── الداخليّات ─────────────────────────────

def _actor(request):
    user = getattr(request, 'user', None)
    return user if (user is not None and user.is_authenticated) else None


def _department_of(user):
    """لقطةُ القسم وقتَ الحدث — تُقرأ مرّةً وتُخزَّن، ولا تُشتقّ لاحقاً."""
    if user is None or not getattr(user, 'is_authenticated', False):
        return None
    profile = getattr(user, 'profile', None)
    return profile.department if profile else None


def _fold(request, book, action):
    """صفٌّ واحدٌ لكلّ (مستخدم، كتاب، فعل، يوم) — بعدّادٍ وآخرِ وقت."""
    from core.logging_models import UserActivityLog

    user = _actor(request)
    if user is None:
        return None

    now = timezone.now()
    today = timezone.localdate()
    keys = dict(user=user, book=book, action=action, day=today)

    try:
        with transaction.atomic():
            row, created = UserActivityLog.objects.get_or_create(
                defaults=dict(
                    department=_department_of(user),
                    ip_address=client_ip(request),
                    user_agent=(request.META.get('HTTP_USER_AGENT') or '')[:1000],
                    path=(request.path or '')[:500],
                    method=(request.method or '')[:10],
                    last_seen_at=now,
                ),
                **keys
            )
    except IntegrityError:
        # سباقٌ على الصفّ نفسه: الفائزُ أنشأه، ونحن نزيد عدّادَه.
        row, created = UserActivityLog.objects.filter(**keys).first(), False
        if row is None:
            logger.warning('تعذّر طيُّ حركة القراءة', exc_info=True)
            return None
    except Exception:                                # noqa: BLE001
        logger.warning('تعذّر تسجيل قراءة الكتاب %s', getattr(book, 'pk', None),
                       exc_info=True)
        return None

    if not created:
        try:
            from django.db.models import F

            UserActivityLog.objects.filter(pk=row.pk).update(
                count=F('count') + 1, last_seen_at=now)
        except Exception:                            # noqa: BLE001
            logger.warning('تعذّر تحديث عدّاد القراءة', exc_info=True)
    return row
