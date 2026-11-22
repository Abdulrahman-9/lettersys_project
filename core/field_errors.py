# -*- coding: utf-8 -*-
"""خطأُ الحقل بجوار حقله (11-22) — المصدرُ الواحد.

كانت صفحاتُ الإعدادات والنسخ والحساب تقول خطأَ الحقل توستاً في الزاوية بعد التحويل، فيبحث
المستخدمُ عن الحقل المقصود. الآن: الرسالةُ موسومةٌ باسم حقلها (``FIELD_TAG`` + الاسم)، ووسمُ
القالب ``{% field_error %}`` يرسمها تحت الحقل، وحلقةُ التوست العامّة في base.html تتخطّاها.

لا تَسِم حقلاً لا يرسمه قالبُ الصفحة التي يعود إليها الطلب — تختفي الرسالة. حرّاسُ
``core.tests_field_errors`` يطابقون كلَّ وسمٍ بموضعه.
"""
from django.contrib import messages

FIELD_TAG = 'lx-field-'
#: رمزُ ValidationError الذي يسمّي حقله: ``ValidationError('…', code=FIELD_CODE + 'username')``
FIELD_CODE = 'field:'


def field_error(request, field, text):
    """خطأٌ يُرسم تحت الحقل ``field`` في الصفحة التالية لا توستاً."""
    messages.error(request, text, extra_tags=FIELD_TAG + field)


def error_for(request, exc):
    """ValidationError من الخدمة: تحت حقله إن سمّى رمزُه حقلاً، وإلّا توستٌ كما كان."""
    text = exc.messages[0]
    code = getattr(exc, 'code', None) or ''
    if code.startswith(FIELD_CODE):
        field_error(request, code[len(FIELD_CODE):], text)
    else:
        messages.error(request, text)


def field_of(message):
    """اسمُ الحقل الذي وُسمت به الرسالة، أو ``None`` لرسالةٍ عامّة."""
    for tag in (message.extra_tags or '').split():
        if tag.startswith(FIELD_TAG):
            return tag[len(FIELD_TAG):]
    return None
