# -*- coding: utf-8 -*-
"""
Book sequence/settings views extracted from books.py.
"""

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import redirect, render

from ..extraction.kinds import BOOK_KIND_CHOICES, normalize_book_kind
from ..models import Book, BookSequence, SystemSettings
from ..numbering import MANUAL_KINDS, max_series_seq
from .helpers import staff_required

logger = logging.getLogger(__name__)


def _parse_int(raw):
    """عددٌ صحيحٌ غيرُ سالب، أو ``None``. **لا ``isdigit()``.**

    ``'²'.isdigit()`` صحيحٌ و``int('²')`` يرفع ``ValueError``: كان نمطُ
    ``if raw.isdigit(): int(raw)`` يعطي 500 بعد أن حُفظت العدّاداتُ فعلاً
    (والطلبُ غيرُ ذرّيّ — لا ``ATOMIC_REQUESTS``). و``isdecimal()`` لا يكفي
    بديلاً: الأرقامَ العربيّةَ الهنديّة ('٤٥') ``isdecimal`` صحيحٌ لها
    و``int`` يقبلها — فالحكمُ الصادقُ الوحيد هو ``int()`` نفسُه داخل حارس.
    """
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def _last_issued(kind):
    """آخرُ تسلسلٍ صدر في السلسلة الجارية لنوعٍ (والمحذوفُ ناعماً صدر أيضاً)؛ 0 للصادر الخارجيّ."""
    if kind in MANUAL_KINDS:
        return 0
    return max_series_seq(
        Book.all_objects.filter(kind=kind).values_list('our_number', flat=True).iterator())


@login_required
def next_number_api(request):
    """API to return the next sequence number for a book kind."""
    kind = request.GET.get('kind', 'incoming_internal')
    kind = normalize_book_kind(kind, 'incoming_internal')
    if kind not in BookSequence.SERIES_KINDS:
        return JsonResponse({
            'kind': kind, 'number': None, 'year': None,
            'formatted': '', 'manual_number': True,
        })
    profile = getattr(request.user, 'profile', None)
    department = getattr(profile, 'department', None)
    data = BookSequence.get_next(kind, department=department)
    return JsonResponse(data)


@login_required
@staff_required
def sequence_settings(request):
    """Sequence settings page for all book kinds."""
    sequences = []
    # عدّادُ القسم الذي يُصدر منه الترقيمُ فعلاً (``consume_next`` بلا قسم ⟵ ``resolve_department``).
    # كان البحثُ بالنوع وحدَه، و«قيِّده عندنا» تُنشئ لكلّ قسمٍ صفّاً من النوع نفسِه — فأوّلُ
    # قيدٍ في قسمٍ ثانٍ يجعل الصفحةَ MultipleObjectsReturned (500).
    department = BookSequence.resolve_department()
    for kind_value, kind_label in BOOK_KIND_CHOICES:
        obj, _ = BookSequence.objects.get_or_create(kind=kind_value, department=department,
                                                    defaults={'next_number': 1})
        sequences.append({'obj': obj, 'label': kind_label, 'kind': kind_value})

    # مدّةُ الحجز بيانٌ في القاعدة لا سطرٌ في ``.env``. الشارةُ «مخصَّص» تُقاس
    # بالمقارنة مع الافتراض، لا بـ``hasattr`` على كائن الإعدادات (كان يكذب:
    # يعود «افتراضي» بعد كلّ إقلاع مهما ضُبط).
    cfg = SystemSettings.get()
    reservation_settings = {
        'expire_minutes': cfg.reservation_expire_minutes,
        'is_custom': (
            cfg.reservation_expire_minutes != SystemSettings.RESERVATION_TTL_DEFAULT
        ),
        'ttl_min': SystemSettings.RESERVATION_TTL_MIN,
        'ttl_max': SystemSettings.RESERVATION_TTL_MAX,
        'ttl_default': SystemSettings.RESERVATION_TTL_DEFAULT,
    }

    if request.method == 'POST':
        ttl_error = None
        # «الرقمُ التالي» تحت آخر رقمٍ صدر يعيد إصدارَ أرقامٍ مستعملة — كان يُحفظ
        # كما كُتب بلا كلمة (تدقيقُ نيلسن E#4). الصادرُ الخارجيّ يدويٌّ لا عدّادَ له.
        sequence_errors = []
        saved = False   # «حُفظ» يُقال حين حُفظ شيءٌ فعلاً (تدقيقُ نيلسن F#9)
        # ذرّيّةٌ صريحة: لا ``ATOMIC_REQUESTS`` في هذا المشروع، وكان خطأُ تحليلٍ
        # في حقل المدّة يترك العدّاداتَ محفوظةً والصفحةَ على 500.
        with transaction.atomic():
            for seq in sequences:
                prefix_key = f"prefix_{seq['kind']}"
                number_key = f"next_number_{seq['kind']}"
                # البادئةُ مهملةٌ ولا حقلَ لها في الصفحة: غيابُ المفتاح لا يمسح المخزَّن
                new_prefix = request.POST.get(prefix_key, seq['obj'].prefix).strip()
                new_number = _parse_int(request.POST.get(number_key, '').strip())
                update_fields = []
                if new_prefix != seq['obj'].prefix:
                    seq['obj'].prefix = new_prefix
                    update_fields.append('prefix')
                if new_number is not None and new_number != seq['obj'].next_number:
                    issued = _last_issued(seq['kind'])
                    if new_number <= issued:
                        sequence_errors.append(
                            f"«{seq['label']}»: الرقمُ التالي {new_number} لا يأتي بعد آخر رقمٍ "
                            f"صدر ({issued}) فكان سيكرّر أرقاماً — بقي {seq['obj'].next_number}.")
                    else:
                        seq['obj'].next_number = new_number
                        update_fields.append('next_number')
                if update_fields:
                    seq['obj'].save(update_fields=update_fields + ['updated_at'])
                    saved = True

            # المدى من ثوابت النموذج — لا رقمَ مكتوباً بيدٍ هنا ولا في القالب.
            raw_expire = request.POST.get('reservation_expire_minutes', '').strip()
            minutes = _parse_int(raw_expire) if raw_expire else None
            if raw_expire and (
                minutes is None
                or not (SystemSettings.RESERVATION_TTL_MIN
                        <= minutes
                        <= SystemSettings.RESERVATION_TTL_MAX)
            ):
                # **الرفضُ يُقال**: كانت رسالةُ النجاح تُطلَق على كلّ طلبٍ، فقيمةٌ
                # مرفوضةٌ تُسقَط بصمتٍ والصفحةُ تقول «حُفظ». حارسا ``min/max`` في
                # القالب يمنعان متصفّحاً عاديّاً، لا طلباً مصنوعاً.
                ttl_error = (
                    'مدّةُ حجز الرقم مرفوضة: يجب أن تكون عدداً صحيحاً بين '
                    f'{SystemSettings.RESERVATION_TTL_MIN} و'
                    f'{SystemSettings.RESERVATION_TTL_MAX} دقيقة. بقيت على '
                    f'{cfg.reservation_expire_minutes} دقيقة.'
                )
            elif minutes is not None:
                # بلا ``except`` واسع: إن فشل الحفظُ فليظهر. الرسالةُ كانت تُطلَق
                # دائماً حتّى حين تفشل الكتابةُ بصمت — «حُفظ» صار يعني حُفظ.
                cfg.reservation_expire_minutes = minutes
                cfg.save(update_fields=['reservation_expire_minutes', 'updated_at'])
                saved = True
                logger.info(
                    '[SequenceSettings] reservation_expire_minutes=%s by %s',
                    minutes, request.user.username,
                )

        for err in sequence_errors:
            messages.error(request, err)
        if ttl_error:
            messages.error(request, ttl_error)
        if ttl_error or sequence_errors:
            # الرفضُ يُقال وحدَه حين لم يُحفظ غيرُه — كانت «حُفظت» تُطلق معه دائماً
            if saved:
                messages.success(request, 'حُفظت بقيّةُ التغييرات.')
        else:
            messages.success(request, 'تم حفظ إعدادات العدّادات والحجز بنجاح.')
        return redirect('sequence_settings')

    return render(request, 'core/sequence_settings.html', {
        'sequences': sequences,
        'reservation_settings': reservation_settings,
    })
