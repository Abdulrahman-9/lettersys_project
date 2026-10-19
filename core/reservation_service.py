# -*- coding: utf-8 -*-
"""
خدمة حجز أرقام القيود — منطق موحّد (DRY) تستدعيه الـAPIs والـWebSocket والمهمة الدورية.

الضمانات:
  • **لا فجوات**: الأرقام المتروكة (ملغاة/منتهية/انتهت فترة سماحها) تُعاد تدويرها لأصغرها
    أولاً قبل استهلاك رقم جديد من العدّاد.
  • **لا تضارب**: كل شيء داخل transaction.atomic + select_for_update (ذرّي).
  • **تعدّد الأجهزة**: الحجز الفعّال مفصول ببصمة جلسة المتصفح؛ الحساب المشترك لا
    يجعل جهازاً يستعيد حجز جهاز آخر، واستهلاك الحجز عند الحفظ يُعاد التحقق منه بقفل صفّه.
  • **أولوية العودة**: بعد انقطاع قسريّ يبقى الرقم محجوزاً لصاحبه (cooldown 15د)؛ إن عاد
    خلالها استرجعه (غالباً كتبه ورقياً)، وإلّا دُوّر لغيره بعلَم is_recycled + تحذير.
"""
from datetime import timedelta
import hashlib

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

COOLDOWN_MINUTES = 15          # فترة سماح عودة نفس المستخدم بعد انقطاع قسريّ
HEARTBEAT_DEAD_SECONDS = 120   # نبضة أقدم من هذا = انقطاع قسريّ (شبكة أمان للـWS)


def reservation_client_key(session_key):
    """Return a non-reversible browser-session identifier for reservation ownership."""
    if not session_key:
        return ''
    return hashlib.sha256(session_key.encode('utf-8')).hexdigest()


def claim_reservation_for_client(reservation_id, user, client_key, department=None):
    """Load a reservation for this browser, claiming a legacy unscoped hold once."""
    from django.db import IntegrityError
    from .models import BookNumberReservation as R

    filters = {'pk': reservation_id, 'user': user}
    if department is not None:
        filters['department'] = department
    try:
        return R.objects.get(**filters, client_key=client_key)
    except R.DoesNotExist:
        if not client_key:
            raise

    try:
        with transaction.atomic():
            claimed = R.objects.filter(**filters, client_key='').update(
                client_key=client_key)
    except IntegrityError as exc:
        raise R.DoesNotExist from exc
    if not claimed:
        raise R.DoesNotExist
    return R.objects.get(**filters, client_key=client_key)


def _recyclable_qs(kind, now, department):
    """حجوزات أرقامها متاحة لإعادة التدوير: ملغاة/منتهية، أو cooldown انقضى — وغير مرتبطة بكتاب."""
    from .models import BookNumberReservation as R
    return (
        R.objects.filter(kind=kind, department=department, book__isnull=True)
        .filter(
            Q(status__in=[R.STATUS_VOIDED, R.STATUS_EXPIRED])
            | Q(status=R.STATUS_COOLDOWN, cooldown_until__lte=now)
        )
        .order_by('number')
    )


def reserve_number(user, kind, expire_minutes=None, department=None, client_key=''):
    """يُعيد (reservation, outcome) حيث outcome ∈ {'existing','resumed','recycled','new'}.

    ``expire_minutes=None`` (الافتراض) ⟵ تُحَلُّ المدّةُ من
    ``SystemSettings.reservation_ttl()``: قراءةٌ عند الاستعمال لا ثابتٌ وقتَ
    الاستيراد، فيسري ضبطُ صفحة العدّادات على كلّ عمليّةٍ وخيطٍ بلا إعادةِ تشغيل.
    """
    from .models import BookNumberReservation as R, BookSequence, Book, SystemSettings
    if expire_minutes is None:
        expire_minutes = SystemSettings.reservation_ttl()
    if department is None:
        department = getattr(getattr(user, 'profile', None), 'department', None)
    department = BookSequence.resolve_department(department)
    now = timezone.now()
    with transaction.atomic():
        # Serialize reservations for one user. Without a stable row to lock,
        # two first-time requests can both observe no live reservation and
        # race to create one before the partial unique constraint is checked.
        from django.contrib.auth import get_user_model
        user = get_user_model().objects.select_for_update().get(pk=user.pk)
        # 0) حجز نشط قائم لنفس المستخدم/النوع → أعِده (لا نُنشئ جديداً)
        existing = (
            R.objects.select_for_update()
            .filter(user=user, kind=kind, department=department,
                    client_key=client_key,
                    status__in=[R.STATUS_ACTIVE, R.STATUS_REACTIVATED])
            .order_by('-reserved_at').first()
        )
        if existing:
            if timezone.now() <= existing.expires_at:
                return existing, 'existing'
            existing.mark_expired()   # منتهٍ فعلياً → يصبح متاحاً للتدوير أدناه

        # Claim a pre-session reservation once, for the first browser that resumes it.
        legacy = (
            R.objects.select_for_update()
            .filter(user=user, kind=kind, department=department, client_key='',
                    status__in=[R.STATUS_ACTIVE, R.STATUS_REACTIVATED])
            .order_by('-reserved_at').first()
        )
        if legacy:
            if timezone.now() <= legacy.expires_at:
                legacy.client_key = client_key
                legacy.save(update_fields=['client_key'])
                return legacy, 'existing'
            legacy.mark_expired()

        # 1) أولوية العودة: حجز cooldown لم ينتهِ لنفس المستخدم/النوع
        own_cd = (
            R.objects.select_for_update()
            .filter(user=user, kind=kind, department=department, status=R.STATUS_COOLDOWN,
                    client_key=client_key,
                    cooldown_until__gt=now, book__isnull=True)
            .order_by('number').first()
        )
        if own_cd:
            own_cd.assigned_at = now
            own_cd.status = R.STATUS_ACTIVE
            own_cd.expires_at = now + timedelta(minutes=expire_minutes)
            own_cd.last_heartbeat = now
            own_cd.cooldown_until = None
            own_cd.void_reason = ''
            own_cd.save(update_fields=['assigned_at', 'status', 'expires_at', 'last_heartbeat',
                                       'cooldown_until', 'void_reason'])
            return own_cd, 'resumed'

        # 2) إعادة تدوير أصغر رقم متروك (يحقّق «بلا فجوات»)
        for cand in _recyclable_qs(kind, now, department).select_for_update(skip_locked=True):
            # لا نُدوّر رقماً استُهلك فعلاً بكتاب (قد يُحفظ بلا حجز عبر auto_number)
            if Book.objects.filter(
                    Q(department=department) | Q(department__isnull=True),
                    kind=kind, our_number=cand.formatted).exists():
                continue
            cand.user = user
            cand.client_key = client_key
            cand.assigned_at = now
            cand.status = R.STATUS_ACTIVE
            cand.is_recycled = True
            cand.expires_at = now + timedelta(minutes=expire_minutes)
            cand.last_heartbeat = now
            cand.cooldown_until = None
            cand.void_reason = ''
            cand.note = ''
            cand.save(update_fields=['user', 'client_key', 'assigned_at', 'status',
                                     'is_recycled', 'expires_at',
                                     'last_heartbeat', 'cooldown_until', 'void_reason', 'note'])
            return cand, 'recycled'

        # 3) رقم جديد من العدّاد
        consumed = BookSequence.consume_next(kind, department=department)
        res = R.objects.create(
            user=user, department=department, kind=kind,
            client_key=client_key,
            number=consumed['number'], prefix='',
            year=consumed['year'], formatted=consumed['formatted'],
            status=R.STATUS_ACTIVE, expires_at=now + timedelta(minutes=expire_minutes),
            assigned_at=now, last_heartbeat=now, is_recycled=False,
        )
        return res, 'new'


def force_cooldown_for_user(user, kind=None, minutes=COOLDOWN_MINUTES,
                            client_key=None):
    """انقطاع قسريّ (WS disconnect): تحويل حجوزات المستخدم النشطة إلى cooldown.
    يُعيد عدد الحجوزات المُحوّلة."""
    from .models import BookNumberReservation as R
    qs = R.objects.filter(user=user, status__in=[R.STATUS_ACTIVE, R.STATUS_REACTIVATED],
                          book__isnull=True)
    if kind:
        qs = qs.filter(kind=kind)
    if client_key is not None:
        qs = qs.filter(client_key=client_key)
    count = 0
    for r in qs:
        r.enter_cooldown(minutes)
        count += 1
    return count


def heartbeat_reservation(reservation, user, client_key):
    """Resume only an owned hold still inside its exclusive return window."""
    from django.contrib.auth import get_user_model
    from .models import BookNumberReservation as R, SystemSettings

    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=user.pk)
        r = R.objects.select_for_update().get(
            pk=reservation.pk, user=user, client_key=client_key)
        now = timezone.now()
        if r.is_live_status and r.is_expired:
            r.mark_expired()
        if (r.status == R.STATUS_COOLDOWN and r.book_id is None
                and r.cooldown_until and r.cooldown_until > now):
            other_active = R.objects.filter(
                user=user, kind=r.kind, department_id=r.department_id,
                client_key=client_key,
                status__in=[R.STATUS_ACTIVE, R.STATUS_REACTIVATED],
            ).exclude(pk=r.pk).exists()
            if not other_active:
                r.assigned_at = now
                r.status = R.STATUS_ACTIVE
                r.expires_at = now + timedelta(minutes=SystemSettings.reservation_ttl())
                r.cooldown_until = None
                r.void_reason = ''
                r.save(update_fields=[
                    'assigned_at', 'status', 'expires_at', 'cooldown_until', 'void_reason'])
        if r.is_live_status:
            r.touch_heartbeat()
        return r


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
