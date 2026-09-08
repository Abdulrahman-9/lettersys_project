# -*- coding: utf-8 -*-
"""نقاطُ التواقيع — أغلفةٌ رقيقةٌ فوق `core/signature_service.py`.

صفرُ قاعدةِ عملٍ هنا: مَن يوقّع، وماذا يُختم، ومتى يُبطَل — كلُّها في الخدمة.
هذه تُترجم HTTP إلى استدعاءٍ والاستثناءَ إلى رسالةٍ عربيّة.

**وصفحةُ التحقّق عامّةٌ بلا تسجيل دخول** — وهذا مقصود: الورقةُ تخرج من الشركة
ويقرأ ختمَها مَن ليس مستخدماً. ولذلك **لا تعرض مضمونَ الكتاب**: اسمُ الموقِّع
وصفتُه ووقتُه وحكمُ البصمة فقط. مَن يريد المضمونَ يدخل النظام.
"""

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.models import Attachment, BookSignature
from core.signature_service import revoke, sign_attachment, verify

logger = logging.getLogger(__name__)


@login_required
@require_POST
def sign_attachment_view(request, pk):
    """يوقّع مرفقاً — والعودةُ إلى صفحة الكتاب بأثرٍ مرئيّ."""
    attachment = get_object_or_404(Attachment, pk=pk, is_deleted=False)
    book = attachment.book

    try:
        signature = sign_attachment(attachment, by=request.user,
                                    note=request.POST.get('note', ''))
    except PermissionDenied as exc:
        messages.error(request, str(exc))
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
    else:
        messages.success(
            request,
            'وُقّع المستند — رمزُ التحقّق %s. والأصلُ باقٍ نسخةً سابقة.'
            % signature.verify_token)

    return redirect('book_detail', book.pk)


@login_required
@require_POST
def revoke_signature_view(request, pk):
    """يُبطل توقيعاً — ولا يحذفه."""
    signature = get_object_or_404(BookSignature, pk=pk)

    try:
        revoke(signature, by=request.user, reason=request.POST.get('reason', ''))
    except PermissionDenied as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, 'أُبطل التوقيع — وبقي أثرُه في السجلّ.')

    return redirect('book_detail', signature.book_id)


def verify_signature_view(request, token):
    """صفحةُ التحقّق العامّة — **بلا تسجيل دخول وبلا مضمون**.

    ورمزٌ مجهولٌ يُعرض بالصفحة نفسِها لا بـ404: مَن يقرأ ختماً على ورقة يحتاج
    جواباً مفهوماً («هذا الرمزُ لا يقابل توقيعاً») لا شاشةَ خطأ.
    """
    signature = BookSignature.objects.filter(verify_token=token).select_related(
        'signer', 'book', 'version').first()

    state = verify(signature) if signature else None
    return render(request, 'core/signature_verify.html', {
        'token': token,
        'state': state,
        'signature': signature,
    })
