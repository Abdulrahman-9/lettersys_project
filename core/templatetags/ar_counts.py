# -*- coding: utf-8 -*-
"""عددُ الأيّام بقاعدة العربيّة في القوالب — واجهةٌ رفيعة فوق ``filter_helpers``.

القوالبُ كانت تكتب «{{ n }} يوم» فتخطئ في 2 و3–10؛ القاعدةُ في بايثون وحدها.
"""
from django import template

from core.views.filter_helpers import day_unit_ar as _day_unit_ar
from core.views.filter_helpers import days_ar as _days_ar

register = template.Library()


@register.filter
def day_unit_ar(n):
    """``{{ 9|day_unit_ar }}`` ⟵ «أيّام» (تمييزُ العدد وحده، والرقمُ يُكتب بجانبه)."""
    return _day_unit_ar(int(n))


@register.filter
def days_ar(n):
    """``{{ 2|days_ar }}`` ⟵ «يومان» · ``{{ 9|days_ar }}`` ⟵ «9 أيّام»."""
    return _days_ar(int(n))
