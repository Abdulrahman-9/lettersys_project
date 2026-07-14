# -*- coding: utf-8 -*-
"""
خدمة حجز أرقام القيود — منطق موحّد (DRY) تستدعيه الـAPIs والـWebSocket والمهمة الدورية.

الضمانات:
  • **لا فجوات**: الأرقام المتروكة (ملغاة/منتهية/انتهت فترة سماحها) تُعاد تدويرها لأصغرها
    أولاً قبل استهلاك رقم جديد من العدّاد.
  • **لا تضارب**: كل شيء داخل transaction.atomic + select_for_update (ذرّي).
  • **أولوية العودة**: بعد انقطاع قسريّ يبقى الرقم محجوزاً لصاحبه (cooldown 15د)؛ إن عاد
    خلالها استرجعه (غالباً كتبه ورقياً)، وإلّا دُوّر لغيره بعلَم is_recycled + تحذير.
"""
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

COOLDOWN_MINUTES = 15          # فترة سماح عودة نفس المستخدم بعد انقطاع قسريّ
HEARTBEAT_DEAD_SECONDS = 120   # نبضة أقدم من هذا = انقطاع قسريّ (شبكة أمان للـWS)


def _recyclable_qs(kind, now):
    """حجوزات أرقامها متاحة لإعادة التدوير: ملغاة/منتهية، أو cooldown انقضى — وغير مرتبطة بكتاب."""
    from .models import BookNumberReservation as R
    return (
        R.objects.filter(kind=kind, book__isnull=True)
        .filter(
            Q(status__in=[R.STATUS_VOIDED, R.STATUS_EXPIRED])
            | Q(status=R.STATUS_COOLDOWN, cooldown_until__lte=now)
        )
        .order_by('number')
    )


def reserve_number(user, kind, expire_minutes=45):
    """يُعيد (reservation, outcome) حيث outcome ∈ {'existing','resumed','recycled','new'}."""
    from .models import BookNumberReservation as R, BookSequence, Book
    now = timezone.now()
    with transaction.atomic():
        # 0) حجز نشط قائم لنفس المستخدم/النوع → أعِده (لا نُنشئ جديداً)
        existing = (
            R.objects.select_for_update()
            .filter(user=user, kind=kind, status__in=[R.STATUS_ACTIVE, R.STATUS_REACTIVATED])
            .order_by('-reserved_at').first()
        )
        if existing:
            if timezone.now() <= existing.expires_at:
                return existing, 'existing'
            existing.mark_expired()   # منتهٍ فعلياً → يصبح متاحاً للتدوير أدناه

        # 1) أولوية العودة: حجز cooldown لم ينتهِ لنفس المستخدم/النوع
        own_cd = (
            R.objects.select_for_update()
            .filter(user=user, kind=kind, status=R.STATUS_COOLDOWN,
                    cooldown_until__gt=now, book__isnull=True)
            .order_by('number').first()
        )
        if own_cd:
            own_cd.status = R.STATUS_ACTIVE
            own_cd.expires_at = now + timedelta(minutes=expire_minutes)
            own_cd.last_heartbeat = now
            own_cd.cooldown_until = None
            own_cd.void_reason = ''
            own_cd.save(update_fields=['status', 'expires_at', 'last_heartbeat',
                                       'cooldown_until', 'void_reason'])
            return own_cd, 'resumed'

        # 2) إعادة تدوير أصغر رقم متروك (يحقّق «بلا فجوات»)
        for cand in _recyclable_qs(kind, now).select_for_update(skip_locked=True):
            # لا نُدوّر رقماً استُهلك فعلاً بكتاب (قد يُحفظ بلا حجز عبر auto_number)
            if Book.objects.filter(kind=kind, our_number=cand.formatted).exists():
                continue
            cand.user = user
            cand.status = R.STATUS_ACTIVE
            cand.is_recycled = True
            cand.expires_at = now + timedelta(minutes=expire_minutes)
            cand.last_heartbeat = now
            cand.cooldown_until = None
            cand.void_reason = ''
            cand.note = ''
            cand.save(update_fields=['user', 'status', 'is_recycled', 'expires_at',
                                     'last_heartbeat', 'cooldown_until', 'void_reason', 'note'])
            return cand, 'recycled'

        # 3) رقم جديد من العدّاد
        consumed = BookSequence.consume_next(kind)
        res = R.objects.create(
            user=user, kind=kind, number=consumed['number'], prefix='',
            year=consumed['year'], formatted=consumed['formatted'],
            status=R.STATUS_ACTIVE, expires_at=now + timedelta(minutes=expire_minutes),
            last_heartbeat=now, is_recycled=False,
        )
        return res, 'new'


def force_cooldown_for_user(user, kind=None, minutes=COOLDOWN_MINUTES):
    """انقطاع قسريّ (WS disconnect): تحويل حجوزات المستخدم النشطة إلى cooldown.
    يُعيد عدد الحجوزات المُحوّلة."""
    from .models import BookNumberReservation as R
    qs = R.objects.filter(user=user, status__in=[R.STATUS_ACTIVE, R.STATUS_REACTIVATED],
                          book__isnull=True)
    if kind:
        qs = qs.filter(kind=kind)
    count = 0
    for r in qs:
        r.enter_cooldown(minutes)
        count += 1
    return count


def sweep_stale(now=None):
    """شبكة أمان دورية:
      • نبضة نشطة ميتة (> HEARTBEAT_DEAD_SECONDS) → cooldown (فوات حدث WS/انقطاع مفاجئ).
      • cooldown انقضى → لا شيء هنا (يُدوَّر تلقائياً عند طلب رقم عبر _recyclable_qs).
    يُعيد عدد الحجوزات المُحوّلة إلى cooldown."""
    from .models import BookNumberReservation as R
    now = now or timezone.now()
    dead_before = now - timedelta(seconds=HEARTBEAT_DEAD_SECONDS)
    stale = R.objects.filter(
        status__in=[R.STATUS_ACTIVE, R.STATUS_REACTIVATED],
        book__isnull=True,
        last_heartbeat__isnull=False,
        last_heartbeat__lt=dead_before,
    )
    count = 0
    for r in stale:
        r.enter_cooldown(COOLDOWN_MINUTES)
        count += 1
    return count
