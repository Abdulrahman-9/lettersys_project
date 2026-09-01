# -*- coding: utf-8 -*-
"""توقيعُ المصادقة — **مسارُ الكتابة الوحيد**.

المرحلة هـ / الطور الأوّل. الغرضُ العمليّ: **مَن صادق على ماذا ومتى، وإثباتُ
أنّ ما وُقّع عليه لم يتغيّر**. لا ادّعاءَ بتوقيعٍ رقميٍّ معياريّ (PAdES/X.509)
— ذاك الطورُ الثاني، وهو قرارُ شركةٍ يتوقّف على مرجع شهاداتٍ وعتادٍ واعترافٍ
قانونيّ. والخلطُ بينهما يُنتج ثقةً كاذبة، فيُقال هنا صراحةً ما هذا وما ليس هو.

**ثلاثةُ التزامات:**

1. **البصمةُ هي الحجّة** — SHA-256 لبايتات الملفّ لحظةَ التوقيع. لا تُخزَّن
   نسخةٌ ثانيةٌ من الملفّ: البصمةُ تكفي للإثبات والملفُّ قد يُنقل.
2. **الختمُ نسخةٌ جديدة لا كتابةٌ فوق الأصل** — `AttachmentVersion` بسلسلتها،
   فالأصلُ باقٍ والموقَّعُ مميَّز.
3. **لا يُحذف توقيع** — الإبطالُ صفٌّ يُوسَم لا صفٌّ يُمحى.
"""

import hashlib
import io
import logging
import secrets

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

#: ارتفاعُ شريط الختم على أسفل الصفحة (بالنقاط، 72 نقطة = بوصة).
STAMP_HEIGHT = 46


def digest_of(data):
    """بصمةُ بايتات — SHA-256 بصيغةٍ ستّ عشريّة."""
    return hashlib.sha256(data).hexdigest()


def can_sign(user, book):
    """أيحقّ له التوقيع على هذا الكتاب؟

    **دورٌ وقسمٌ معاً**: رئيسُ القسم أو مديرُ النظام، وعلى كتابٍ يفتح محتواه.
    ومختصُّ البريد **ليس منهم**: هو يُسلّم ويستلم ولا يُصادق — والخلطُ بين
    مَن يمسك الورقةَ ومَن يُقرّ مضمونَها هو ما تُوجد التواقيعُ لمنعه.
    """
    from core.scoping import (can_open_content, is_department_head,
                              is_privileged, user_department_id)

    if not can_open_content(book, user):
        return False
    if is_privileged(user):
        return True
    return (is_department_head(user)
            and user_department_id(user) == book.department_id)


def capacity_of(user, book):
    """صفةُ الموقِّع — تُشتقّ من دوره لا يختارها بنفسه."""
    from core.models import BookSignature
    from core.scoping import is_department_head, is_privileged

    if is_department_head(user):
        return BookSignature.CAPACITY_HEAD
    if is_privileged(user):
        return BookSignature.CAPACITY_MANAGER
    return BookSignature.CAPACITY_DELEGATE


def sign_attachment(attachment, *, by, note=''):
    """يوقّع أحدثَ نسخةٍ من مرفق: ختمٌ بصريّ + بصمةٌ + قيدٌ في السجلّ.

    يُعيد ``BookSignature``. ويرفع ``PermissionDenied`` لمن لا يملك الصفة،
    و``ValidationError`` إن لم يكن الملفُّ مستنداً يُختم.
    """
    from core.models import AttachmentVersion, BookSignature

    book = attachment.book
    if not can_sign(by, book):
        raise PermissionDenied('التوقيعُ لرئيس القسم ومدير النظام.')

    try:
        source = attachment.file.read()
    except (ValueError, OSError) as exc:
        raise ValidationError('تعذّر قراءةُ المرفق.') from exc
    finally:
        try:
            attachment.file.close()
        except Exception:                                   # noqa: BLE001
            pass

    if not source:
        raise ValidationError('المرفقُ فارغ.')

    token = secrets.token_urlsafe(16)[:32]
    signer_name = (by.get_full_name() or by.username).strip()
    stamped = _stamp(source, signer_name, token)
    if stamped is None:
        raise ValidationError('الختمُ يعمل على مستندات PDF فقط.')

    with transaction.atomic():
        version = _new_version(attachment, stamped, by, signer_name)
        signature = BookSignature.objects.create(
            book=book, version=version, signer=by,
            capacity=capacity_of(by, book),
            digest=digest_of(stamped), verify_token=token, note=note,
        )
        _record(book, 'sign', by, 'الصفة: %s' % signature.get_capacity_display())

    logger.info('signature: book=%s by=%s token=%s', book.pk, by.pk, token)
    return signature


def revoke(signature, *, by, reason=''):
    """يُبطل توقيعاً — **ولا يحذفه**: التوقيعُ واقعةٌ حدثت.

    والختمُ البصريُّ على النسخة القديمة يبقى، فصفحةُ التحقّق هي التي تقول
    «أُبطل» — ولذلك وُجد رمزُ التحقّق على الختم أصلاً.
    """
    from core.scoping import is_privileged

    if not (is_privileged(by) or signature.signer_id == by.id):
        raise PermissionDenied('الإبطالُ للموقِّع نفسِه أو لمدير النظام.')
    if signature.revoked_at is not None:
        return signature

    signature.revoked_at = timezone.now()
    signature.revoked_by = by
    signature.revoke_reason = (reason or '').strip()[:255]
    signature.save(update_fields=['revoked_at', 'revoked_by', 'revoke_reason'])
    _record(signature.book, 'sign-revoked', by, signature.revoke_reason)
    return signature


def verify(signature):
    """يتحقّق أنّ الملفَّ الموقَّع لم يتغيّر — ويُعيد قاموسَ حالة.

    ``matches`` هو الحكم: بصمةُ الملفّ الآن مقابل البصمة المحفوظة. وغيابُ
    النسخة ليس فشلاً في التحقّق بل **غيابُ ما يُتحقَّق منه**، فيُقال هكذا.
    """
    state = {
        'signature': signature,
        'valid': signature.is_valid,
        'matches': None,
        'reason': '',
    }
    if signature.version is None:
        state['reason'] = 'النسخةُ الموقَّعة لم تعد موجودة — والبصمةُ محفوظة.'
        return state

    try:
        with signature.version.file.open('rb') as handle:
            current = digest_of(handle.read())
    except (ValueError, OSError):
        state['reason'] = 'تعذّر قراءةُ النسخة الموقَّعة.'
        return state

    state['matches'] = (current == signature.digest)
    if not state['matches']:
        state['reason'] = 'الملفُّ تغيّر بعد التوقيع — هذا ليس ما وُقّع عليه.'
    return state


# ───────────────────────────── الداخليّات ─────────────────────────────

def _stamp(pdf_bytes, signer_name, token):
    """يرسم شريطَ الختم أسفلَ كلّ صفحة — أو ``None`` إن لم يكن PDF.

    على **كلّ** صفحة لا الأولى وحدها: صفحةٌ تُقتطع من مستندٍ موقَّعٍ يجب أن
    تحمل ختمَها معها، وإلّا صار الختمُ إثباتاً للغلاف لا للمضمون.
    """
    try:
        import fitz  # PyMuPDF

        stamped_at = timezone.localtime().strftime('%Y/%m/%d %H:%M')
        line = 'وُقّع إلكترونيّاً: %s — %s' % (signer_name, stamped_at)

        with fitz.open(stream=pdf_bytes, filetype='pdf') as doc:
            for page in doc:
                rect = page.rect
                band = fitz.Rect(rect.x0, rect.y1 - STAMP_HEIGHT, rect.x1, rect.y1)
                page.draw_rect(band, color=(0.71, 0.33, 0.04),
                               fill=(0.99, 0.96, 0.92), width=0.8)
                # الخطُّ المدمج لا يرسم العربيّة متّصلة؛ فيُكتب الرمزُ لاتينيّاً
                # ويُترك الاسمُ للنصّ الحرّ الذي تقرؤه صفحةُ التحقّق. الحجّةُ
                # هي البصمةُ والرمز، لا شكلُ الحروف على الورق.
                page.insert_textbox(
                    fitz.Rect(band.x0 + 8, band.y0 + 6, band.x1 - 8, band.y1 - 6),
                    'LetterSys verify: %s\n%s' % (token, line),
                    fontsize=7.5, color=(0.21, 0.13, 0.08), align=0)
            return doc.tobytes()
    except Exception as exc:                                # noqa: BLE001
        logger.warning('تعذّر ختمُ المستند: %s', exc)
        return None


def _new_version(attachment, data, by, signer_name):
    """نسخةٌ جديدةٌ في السلسلة — الأصلُ باقٍ والموقَّعُ مميَّز."""
    from django.core.files.base import ContentFile

    from core.models import AttachmentVersion

    last = attachment.versions.order_by('-version_number').first()
    number = (last.version_number + 1) if last else 1

    version = AttachmentVersion(
        attachment=attachment, version_number=number, created_by=by,
        note='توقيع: %s' % signer_name,
    )
    version.file.save('signed_v%d.pdf' % number, ContentFile(data), save=False)
    version.save()
    return version


def _record(book, action, by, notes=''):
    """قيدٌ في سجلّ الكتاب — التوقيعُ حدثٌ يُطارَد كغيره.

    و``action`` **مفتاحٌ من `ACTION_CHOICES`** لا نصٌّ حرّ: النصُّ الحرُّ يمرّ
    ويُخزَّن ثمّ لا يُصفّى عليه أحدٌ في التدقيق.

    **ولا `except` واسعٌ هنا**: أوّلُ صياغةٍ ابتلعت خطأً في اسم حقلٍ
    (`user` بدل `by`) فضاع القيدُ صامتاً واجتازت الخدمةُ كلَّ شيءٍ إلّا
    الاختبارَ الذي سأل عن السجلّ. القيدُ جزءٌ من الأثر، وسقوطُه يجب أن
    يُسقط المعاملةَ لا أن يُخفي نفسَه.
    """
    from core.models import BookHistory

    BookHistory.objects.create(
        book=book, action=action, by=by,
        by_snapshot=(by.get_full_name() or by.username) if by else '',
        notes=notes or '',
    )
