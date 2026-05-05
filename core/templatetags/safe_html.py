"""
core.templatetags.safe_html
============================
فلاتر قوالب لتعقيم HTML الخارجي وحماية من XSS.

الاستخدام في القوالب:
    {% load safe_html %}
    {{ email.body_html|sanitize_email_html }}
"""

import logging

from django import template
from django.utils.safestring import mark_safe

logger = logging.getLogger('lettersys')

register = template.Library()

# العلامات والخصائص المسموح بها في محتوى البريد الإلكتروني
_ALLOWED_TAGS = [
    'p', 'br', 'strong', 'b', 'em', 'i', 'u', 's',
    'a', 'blockquote', 'pre', 'code',
    'ul', 'ol', 'li',
    'table', 'thead', 'tbody', 'tr', 'th', 'td',
    'img', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'div', 'span',
]

_ALLOWED_ATTRIBUTES = {
    'a':   ['href', 'title', 'rel'],
    'img': ['src', 'alt', 'width', 'height', 'style'],
    'td':  ['colspan', 'rowspan', 'align', 'valign'],
    'th':  ['colspan', 'rowspan', 'align', 'valign'],
    'div': ['style', 'dir'],
    'p':   ['style', 'dir'],
    'span': ['style', 'dir'],
    'blockquote': ['style'],
    'table': ['border', 'cellpadding', 'cellspacing', 'style'],
}


@register.filter(is_safe=True)
def sanitize_email_html(value):
    """
    تعقيم HTML الوارد من مصادر خارجية (إيميلات) باستخدام bleach.
    يزيل السكربتات وعناصر الإيكزيكيوشن مع الإبقاء على التنسيق الآمن.
    """
    if not value:
        return ''
    try:
        import bleach
        clean = bleach.clean(
            str(value),
            tags=_ALLOWED_TAGS,
            attributes=_ALLOWED_ATTRIBUTES,
            strip=True,
            strip_comments=True,
        )
        return mark_safe(clean)
    except ImportError:
        logger.warning('[safe_html] bleach غير مثبت — سيتم تعطيل عرض HTML من الإيميلات')
        from django.utils.html import escape
        return escape(str(value))
    except Exception as exc:
        logger.error('[safe_html] فشل تعقيم HTML: %s', exc)
        from django.utils.html import escape
        return escape(str(value))
