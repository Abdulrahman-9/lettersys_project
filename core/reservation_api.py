"""
APIs نظام حجز أرقام القيود
- reserve  : حجز ذري لرقم جديد
- void     : إلغاء الحجز يدوياً
- reactivate: إعادة تفعيل حجز منتهي الصلاحية
- status   : فحص حالة الحجز الحالي للمستخدم
"""
import json
import logging

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from django.conf import settings

from .models import BookNumberReservation, BookSequence
from .decorators import rate_limit

logger = logging.getLogger('lettersys')

# مدة صلاحية الحجز بالدقائق — قابلة للتخصيص عبر settings.py
EXPIRE_MINUTES = getattr(settings, 'RESERVATION_EXPIRE_MINUTES', 45)


def _reservation_dict(r):
    """تحويل سجل الحجز إلى dict للـ JSON."""
    return {
        'id':               r.pk,
        'number':           r.number,
        'prefix':           r.prefix,
        'formatted':        r.formatted,
        'year':             r.year,
        'kind':             r.kind,
        'status':           r.status,
        'status_label':     r.get_status_display(),
        'remaining_seconds': r.remaining_seconds,
        'expires_at':       r.expires_at.isoformat(),
        'reserved_at':      r.reserved_at.isoformat(),
        'is_recycled':      r.is_recycled,
        'cooldown_until':   r.cooldown_until.isoformat() if r.cooldown_until else None,
    }


@login_required
@require_http_methods(['POST'])
@rate_limit('reserve_number', max_attempts=30, window_seconds=60, by='user')
def reserve_number(request):
    """
    POST /books/api/reservation/reserve/
    body JSON: { "kind": "incoming_internal" }

    - إذا كان للمستخدم حجز نشط بنفس النوع → يُرجعه بدون إنشاء جديد
    - وإلا → يحجز رقماً جديداً بشكل ذري
    """
    try:
        body = json.loads(request.body or '{}')
        kind = (body.get('kind') or 'incoming_internal').strip()
    except (ValueError, TypeError):
        return JsonResponse({'success': False, 'message': 'بيانات غير صالحة'}, status=400)

    # الخدمة الموحّدة تتكفّل بكل الحالات: قائم / استرجاع cooldown / إعادة تدوير / جديد
    try:
        from .reservation_service import reserve_number as _svc_reserve
        reservation, outcome = _svc_reserve(request.user, kind, EXPIRE_MINUTES)
    except Exception as e:
        logger.error(f'[Reservation] Error: {e}', exc_info=True)
        return JsonResponse({'success': False, 'message': 'خطأ في الحجز'}, status=500)

    messages = {
        'existing': f'لديك قيد محجوز بالفعل: {reservation.formatted}',
        'resumed':  f'تم استرجاع قيدك بعد انقطاع سابق: {reservation.formatted}',
        'recycled': f'رقم مُدوّر: {reservation.formatted} — تأكّد أن ورقتك لا تحمل رقماً متضارباً.',
        'new':      f'تم حجز القيد {reservation.formatted} لك',
    }
    logger.info('[Reservation] %s %s for user=%s kind=%s',
                outcome, reservation.formatted, request.user.username, kind)
    return JsonResponse({
        'success': True,
        'already_reserved': outcome == 'existing',
        'outcome': outcome,
        'reservation': _reservation_dict(reservation),
        'message': messages.get(outcome, messages['new']),
    })


@login_required
@require_http_methods(['POST'])
def reservation_heartbeat(request):
    """
    POST /books/api/reservation/heartbeat/
    body JSON: { "reservation_id": 42 }

    نبضة حضور: تُحدّث last_heartbeat فيبقى الحجز حيّاً. تُرجع alive=False إن لم يعد
    الحجز نشطاً (سُحب/دُوّر/انتهى) — فتُنبّه الواجهة لطلب رقم جديد.
    """
    try:
        body = json.loads(request.body or '{}')
        res_id = body.get('reservation_id')
    except (ValueError, TypeError):
        return JsonResponse({'success': False, 'message': 'بيانات غير صالحة'}, status=400)

    try:
        r = BookNumberReservation.objects.get(pk=res_id, user=request.user)
    except BookNumberReservation.DoesNotExist:
        return JsonResponse({'success': False, 'alive': False, 'message': 'الحجز غير موجود'}, status=404)

    if not r.is_live_status:
        return JsonResponse({
            'success': True, 'alive': False,
            'status': r.status, 'status_label': r.get_status_display(),
            'message': 'انتهت صلاحية حجزك أو أُعيد تدويره — اطلب رقماً جديداً.',
        })

    r.touch_heartbeat()
    return JsonResponse({'success': True, 'alive': True, 'remaining_seconds': r.remaining_seconds})


@login_required
@require_http_methods(['POST'])
def void_reservation(request):
    """
    POST /books/api/reservation/void/
    body JSON: { "reservation_id": 42, "note": "نص اختياري" }

    يُلغي الحجز النشط للمستخدم.
    """
    try:
        body = json.loads(request.body or '{}')
        res_id = body.get('reservation_id')
        note   = (body.get('note') or '').strip()[:200]
    except (ValueError, TypeError):
        return JsonResponse({'success': False, 'message': 'بيانات غير صالحة'}, status=400)

    try:
        r = BookNumberReservation.objects.get(pk=res_id, user=request.user)
    except BookNumberReservation.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'الحجز غير موجود'}, status=404)

    if r.status not in [BookNumberReservation.STATUS_ACTIVE, BookNumberReservation.STATUS_REACTIVATED]:
        return JsonResponse({
            'success': False,
            'message': f'لا يمكن إلغاء حجز بحالة: {r.get_status_display()}'
        }, status=400)

    r.mark_voided(reason=BookNumberReservation.VOID_REASON_CANCELLED, note=note)
    logger.info(f'[Reservation] Voided {r.formatted} by user={request.user.username}. Note: {note}')
    return JsonResponse({
        'success': True,
        'message': f'تم قفل القيد {r.formatted} وتسجيله كملغي',
        'reservation': _reservation_dict(r),
    })


@login_required
@require_http_methods(['POST'])
def reactivate_reservation(request):
    """
    POST /books/api/reservation/reactivate/
    body JSON: { "reservation_id": 42 }

    يُعيد تفعيل حجز منتهي الصلاحية (المستخدم كتبه على ورقة).
    """
    try:
        body = json.loads(request.body or '{}')
        res_id = body.get('reservation_id')
    except (ValueError, TypeError):
        return JsonResponse({'success': False, 'message': 'بيانات غير صالحة'}, status=400)

    try:
        r = BookNumberReservation.objects.get(pk=res_id, user=request.user)
    except BookNumberReservation.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'الحجز غير موجود'}, status=404)

    if r.status not in [BookNumberReservation.STATUS_EXPIRED]:
        return JsonResponse({
            'success': False,
            'message': f'لا يمكن إعادة تفعيل حجز بحالة: {r.get_status_display()}'
        }, status=400)

    # سقف إعادة التفعيل: مرة واحدة فقط لكل حجز
    if r.void_reason == BookNumberReservation.VOID_REASON_REACTIVATED or \
            BookNumberReservation.objects.filter(
                user=request.user, kind=r.kind,
                status=BookNumberReservation.STATUS_REACTIVATED,
                reserved_at__gte=r.reserved_at
            ).exists():
        return JsonResponse({
            'success': False,
            'message': 'تجاوزت الحد المسموح لإعادة التفعيل. اطلب رقماً جديداً.',
            'error_code': 'REACTIVATION_LIMIT',
        }, status=400)

    r.reactivate(extra_minutes=EXPIRE_MINUTES)
    logger.info(f'[Reservation] Reactivated {r.formatted} for user={request.user.username}')
    return JsonResponse({
        'success': True,
        'message': f'تم إعادة تفعيل القيد {r.formatted} لمدة {EXPIRE_MINUTES} دقيقة',
        'reservation': _reservation_dict(r),
    })


@login_required
@require_http_methods(['GET'])
def reservation_status(request):
    """
    GET /books/api/reservation/status/?kind=incoming_internal

    يُرجع الحجز النشط للمستخدم إن وجد، أو last_expired ليسأله.
    """
    kind = (request.GET.get('kind') or 'incoming_internal').strip()

    # فحص وتحديث الحجوزات المنتهية
    active = BookNumberReservation.objects.filter(
        user=request.user, kind=kind,
        status__in=[BookNumberReservation.STATUS_ACTIVE, BookNumberReservation.STATUS_REACTIVATED]
    ).order_by('-reserved_at').first()

    if active and active.is_expired:
        active.mark_expired()
        active = None

    if active:
        return JsonResponse({
            'has_reservation': True,
            'reservation': _reservation_dict(active),
        })

    # هل انتهت صلاحية حجز مؤخراً (آخر ساعة)؟
    recent_expired = BookNumberReservation.objects.filter(
        user=request.user, kind=kind,
        status=BookNumberReservation.STATUS_EXPIRED,
        voided_at__gte=timezone.now() - timezone.timedelta(hours=1)
    ).order_by('-voided_at').first()

    if recent_expired:
        return JsonResponse({
            'has_reservation': False,
            'expired_reservation': _reservation_dict(recent_expired),
            'message': f'انتهت صلاحية قيدك المحجوز {recent_expired.formatted} — هل كتبته على وثيقة؟'
        })

    # لا يوجد حجز
    seq_info = BookSequence.get_next(kind)
    return JsonResponse({
        'has_reservation': False,
        'expired_reservation': None,
        'preview_number': seq_info['formatted'],
    })
