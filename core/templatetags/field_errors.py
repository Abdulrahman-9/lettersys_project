# -*- coding: utf-8 -*-
"""``{% field_error 'app_name' 'gen_app_name' %}`` — خطأُ الحقل تحت حقله (المصدر: core.field_errors).

يُرسم ‎<p class="lx-field-error" id="<id>-error">‎، وapp.js يربطه بالحقل (aria-invalid + aria-describedby)
ويضع التركيزَ على أوّل حقلٍ خاطئ.
"""
from django import template
from django.utils.html import format_html

from core.field_errors import field_of

register = template.Library()


@register.simple_tag(takes_context=True)
def field_error(context, field, input_id):
    for message in context.get('messages') or ():
        if field_of(message) == field:
            return format_html(
                '<p class="lx-field-error" id="{0}-error" data-field-error-for="{0}">'
                '<i class="bi bi-exclamation-circle" aria-hidden="true"></i><span>{1}</span></p>',
                input_id, message.message)
    return ''
