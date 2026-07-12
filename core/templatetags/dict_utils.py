# -*- coding: utf-8 -*-
"""مرشِّحات قواميس للقوالب — Django لا يدعم فهرسة القاموس بمتغير أصلاً."""
from django import template

register = template.Library()


@register.filter
def get_item(mapping, key):
    """`{{ counts|get_item:t.table }}` — قيمة المفتاح أو None (يتكامل مع default)."""
    if hasattr(mapping, 'get'):
        return mapping.get(key)
    return None
