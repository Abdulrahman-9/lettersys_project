# -*- coding: utf-8 -*-
"""``{% qs key=value %}`` — رابطُ الصفحة نفسِها بمرشّحاتها كلّها مع تغييرٍ واحد.

نمطُ ``{% querystring %}`` في Django 5.1 (والمشروعُ على 4.2). كانت روابطُ قائمة الجهات
تبني سلاسلَها يدويّاً فيُسقط كلٌّ منها مفتاحاً غيرَ الذي يُسقطه جارُه: الترقيمُ يُسقط
الترتيب (فالصفحةُ الثانية من «الأكثر كتباً» أبجديّة)، والتبويبُ يُسقط الترتيب،
و«مسح» البحث يُسقط التبويبَ واللغة (تدقيقُ نيلسن 2026‑10‑08، H3).
"""
from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def qs(context, **changes):
    """القيمةُ الفارغة تحذف مفتاحها؛ وأيُّ تغييرٍ يُعيد إلى الصفحة الأولى ما لم يُمرَّر ``page``."""
    params = context['request'].GET.copy()
    if 'page' not in changes:
        params.pop('page', None)
    for key, value in changes.items():
        if value in (None, ''):
            params.pop(key, None)
        else:
            params[key] = str(value)
    encoded = params.urlencode()
    return '?' + encoded if encoded else '?'
