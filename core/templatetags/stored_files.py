# -*- coding: utf-8 -*-
"""ملفّاتٌ مخزَّنة في القوالب بلا سقوط الصفحة — واجهةٌ رفيعة فوق ``core.file_presence``."""
from django import template

from core.file_presence import stored_size as _stored_size

register = template.Library()


@register.filter
def stored_size(field):
    """``{{ att.file|stored_size }}`` ⟵ الحجمُ بالبايت، أو ``None`` إن غاب الملفّ عن التخزين."""
    return _stored_size(field)
