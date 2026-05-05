# -*- coding: utf-8 -*-
"""
Book create/form views.
"""

import logging

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.urls import reverse

logger = logging.getLogger(__name__)


@login_required
def book_create_incoming(request):
    """إدخال كتاب وارد جديد - إعادة توجيه للواجهة الذكية الجديدة."""
    target = f"{reverse('extraction-smart-desktop')}?kind=incoming_internal"
    return redirect(target)


@login_required
def book_create_outgoing(request):
    """إدخال كتاب صادر جديد - إعادة توجيه للواجهة الذكية الجديدة."""
    target = f"{reverse('extraction-smart-desktop')}?kind=outgoing_internal"
    return redirect(target)


__all__ = ['book_create_incoming', 'book_create_outgoing']
