# -*- coding: utf-8 -*-
"""
Book sequence/settings views extracted from books.py.
"""

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render

from ..extraction.kinds import BOOK_KIND_CHOICES, normalize_book_kind
from ..models import BookSequence, SystemSettings
from .helpers import staff_required

logger = logging.getLogger(__name__)


@login_required
def next_number_api(request):
    """API to return the next sequence number for a book kind."""
    kind = request.GET.get('kind', 'incoming_internal')
    kind = normalize_book_kind(kind, 'incoming_internal')
    data = BookSequence.get_next(kind)
    return JsonResponse(data)


@login_required
@staff_required
def sequence_settings(request):
    """Sequence settings page for all book kinds."""
    sequences = []
    for kind_value, kind_label in BOOK_KIND_CHOICES:
        obj, _ = BookSequence.objects.get_or_create(kind=kind_value, defaults={'next_number': 1})
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
        for seq in sequences:
            prefix_key = f"prefix_{seq['kind']}"
            number_key = f"next_number_{seq['kind']}"
            new_prefix = request.POST.get(prefix_key, '').strip()
            new_number = request.POST.get(number_key, '').strip()
            update_fields = []
            if new_prefix != seq['obj'].prefix:
                seq['obj'].prefix = new_prefix
                update_fields.append('prefix')
            if new_number.isdigit() and int(new_number) != seq['obj'].next_number:
                seq['obj'].next_number = int(new_number)
                update_fields.append('next_number')
            if update_fields:
                seq['obj'].save(update_fields=update_fields + ['updated_at'])

        # المدى من ثوابت النموذج — لا رقمَ مكتوباً بيدٍ هنا ولا في القالب.
        new_expire = request.POST.get('reservation_expire_minutes', '').strip()
        if new_expire.isdigit() and (
            SystemSettings.RESERVATION_TTL_MIN
            <= int(new_expire)
            <= SystemSettings.RESERVATION_TTL_MAX
        ):
            # بلا ``except`` واسع: إن فشل الحفظُ فليظهر. الرسالةُ كانت تُطلَق
            # دائماً حتّى حين تفشل الكتابةُ بصمت — «حُفظ» صار يعني حُفظ.
            cfg.reservation_expire_minutes = int(new_expire)
            cfg.save(update_fields=['reservation_expire_minutes', 'updated_at'])
            logger.info(
                '[SequenceSettings] reservation_expire_minutes=%s by %s',
                new_expire, request.user.username,
            )

        messages.success(request, 'تم حفظ إعدادات العدّادات والحجز بنجاح.')
        return redirect('sequence_settings')

    return render(request, 'core/sequence_settings.html', {
        'sequences': sequences,
        'reservation_settings': reservation_settings,
    })
