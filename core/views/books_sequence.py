# -*- coding: utf-8 -*-
"""
Book sequence/settings views extracted from books.py.
"""

import logging
import os
import re

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render

from ..extraction.kinds import BOOK_KIND_CHOICES, normalize_book_kind
from ..models import BookSequence
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

    from django.conf import settings as dj_settings
    current_expire = getattr(dj_settings, 'RESERVATION_EXPIRE_MINUTES', 45)
    reservation_settings = {
        'expire_minutes': current_expire,
        'is_custom': hasattr(dj_settings, 'RESERVATION_EXPIRE_MINUTES'),
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

        new_expire = request.POST.get('reservation_expire_minutes', '').strip()
        if new_expire.isdigit() and 5 <= int(new_expire) <= 480:
            _write_reservation_expire_setting(int(new_expire))
            reservation_settings['expire_minutes'] = int(new_expire)
            reservation_settings['is_custom'] = True

        messages.success(request, 'تم حفظ إعدادات العدّادات والحجز بنجاح.')
        return redirect('sequence_settings')

    return render(request, 'core/sequence_settings.html', {
        'sequences': sequences,
        'reservation_settings': reservation_settings,
    })


def _write_reservation_expire_setting(minutes: int):
    """Write RESERVATION_EXPIRE_MINUTES value to the project's .env."""
    env_path = os.path.join(settings.BASE_DIR, '.env')
    key = 'RESERVATION_EXPIRE_MINUTES'
    new_line = f'{key}={minutes}\n'
    try:
        if os.path.exists(env_path):
            with open(env_path, 'r', encoding='utf-8') as f:
                content = f.read()
            if re.search(rf'^{key}=.*', content, re.MULTILINE):
                content = re.sub(rf'^{key}=.*', new_line.strip(), content, flags=re.MULTILINE)
            else:
                content += ('\n' if not content.endswith('\n') else '') + new_line
            with open(env_path, 'w', encoding='utf-8') as f:
                f.write(content)
        else:
            with open(env_path, 'w', encoding='utf-8') as f:
                f.write(new_line)

        from django.conf import settings as dj_settings
        dj_settings.RESERVATION_EXPIRE_MINUTES = minutes

        import core.reservation_api as _rapi
        _rapi.EXPIRE_MINUTES = minutes
        logger.info(f'[SequenceSettings] RESERVATION_EXPIRE_MINUTES updated to {minutes}')
    except Exception as exc:
        logger.warning(f'[SequenceSettings] Could not write .env: {exc}')
