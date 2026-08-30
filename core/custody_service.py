# -*- coding: utf-8 -*-
"""
العهدة — **مسارُ الكتابة الوحيد** إلى ``CustodyEvent`` و``Book.current_custody``.

«إذا كانت المهامُّ والمسؤوليّاتُ واضحةً وظاهرةً لي **كلُّ تفاصيل الاستلام
وبعهدة مَن**: مَن استلم، ومَن أكّد، ومَن أعدّ… لاستغنينا عن الدفتر. **المهمّ
الشفافيّة: لا يضيع مستندٌ أبداً ولا تفاصيله.**» — وهذا الملفُّ هو ذلك الشرط.

``record_custody`` تكتب في نَفَسٍ واحد: **الحدثَ** + **حالةَ الإحالة** إن كان
الاستلامُ استلامَ وحدةٍ + **مؤشّرَ «بعهدة مَن»** + **الأثرَ في تاريخ الكتاب**.
كتابةُ أيٍّ من الأربعة على حدة تُخلّف سلسلةً مكسورة — والسلسلةُ المكسورة هي
المستندُ الضائع.
"""

import logging

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


def record_custody(book, event, *, referral=None, to_department=None, to_user=None,
                   to_name='', signed_at=None, mode=None, note='', by):
    """يسجّل انتقالَ عهدةٍ ويُحدّث «بعهدة مَن» — وما يتبعهما.

    ``to_name`` نصٌّ حرٌّ لمتعهّد البريد ومَن ليس مستخدماً عندنا: سلسلةُ العهدة
    لا يصحّ أن تنقطع عند أوّل حاملٍ من خارج الحسابات.

    يرفع ``ValidationError`` على حدثٍ مجهول أو صفٍّ بلا حامل أو إحالةٍ لكتابٍ
    آخر، و``PermissionDenied`` إن لم يملك ``by`` محتوى الكتاب.
    """
    from core.models import CustodyEvent
    from core.scoping import can_open_content

    if event not in dict(CustodyEvent.EVENT_CHOICES):
        raise ValidationError('حدثُ عهدةٍ غيرُ معروف.')
    if not (to_department or to_user or (to_name or '').strip()):
        raise ValidationError('لا حاملَ لهذه العهدة — ولا تُسجَّل عهدةٌ إلى لا أحد.')
    if referral is not None and referral.book_id != book.pk:
        raise ValidationError('الإحالةُ ليست لهذا الكتاب.')
    if not can_open_content(book, by):
        raise PermissionDenied('لا تملك صلاحيةَ تسجيل عهدةٍ على هذا الكتاب.')

    with transaction.atomic():
        moment = CustodyEvent.objects.create(
            book=book, referral=referral, event=event,
            to_holder_department=to_department, to_holder_user=to_user,
            to_holder_name=(to_name or '').strip()[:120],
            signed_at=signed_at or timezone.now(),
            recorded_by=by, note=(note or '').strip()[:255],
            **_mode(mode)
        )

        # استلامُ الوحدة **هو** إقرارُ الإحالة: حدثان في الواقع فعلٌ واحد،
        # وفصلُهما يُنتج وحدةً «استلمت» ولم «تستلم».
        if referral is not None and event == CustodyEvent.UNIT_RECEIPT:
            from core.referral_service import mark_received
            mark_received(referral, by=by)

        _point_at(book, moment)
        _record(book, 'custody', by, '%s ⟵ %s%s' % (
            moment.get_event_display(), moment.holder_name,
            ' — ' + moment.note if moment.note else ''))

    return moment


def custody_chain(book):
    """سلسلةُ العهدة كاملةً — الأحدثُ أوّلاً، وهي ما يُعرض في صفحة الكتاب."""
    return book.custody_events.select_related(
        'to_holder_department', 'to_holder_user', 'recorded_by', 'referral'
    ).all()


def held_by(department, qs=None):
    """كلُّ ما هو **بعهدة** قسمٍ الآن — عمودُ كشف التسليم وطاولة الوارد."""
    from core.models import Book

    qs = Book.objects.filter(is_deleted=False) if qs is None else qs
    return qs.filter(current_custody__to_holder_department=department)


def undelivered(department, qs=None):
    """ما فُرِّق إلى قسمٍ ولم تُسجَّل له عهدةٌ عنده — **طابورُ «لم يُستلم»**.

    وهو أخطرُ عمودٍ في الطاولة: الكتابُ الذي خرج من يدٍ ولم يدخل يداً هو
    المستندُ الذي يضيع.
    """
    from core.models import BookReferral, CustodyEvent

    referred = BookReferral.objects.filter(
        to_department=department, status__in=BookReferral.OPEN_STATUSES,
    )
    if qs is not None:
        referred = referred.filter(book__in=qs)
    signed = CustodyEvent.objects.filter(
        to_holder_department=department, event=CustodyEvent.UNIT_RECEIPT,
    ).values('book_id')
    return referred.exclude(book_id__in=signed)


# ───────────────────────────── الداخليّات ─────────────────────────────

def _mode(mode):
    """الافتراضُ **ورقيّ**: هذا ما يجري اليوم فعلاً، وادّعاءُ التوقيع الرقميّ
    حيث لا يوجد يُفسد الحجّة التي بُني الجدولُ لأجلها."""
    from core.models import CustodyEvent

    if mode is None:
        return {'signature_mode': CustodyEvent.PAPER}
    if mode not in dict(CustodyEvent.SIGNATURE_MODES):
        raise ValidationError('نوعُ توقيعٍ غيرُ معروف.')
    return {'signature_mode': mode}


def _point_at(book, moment):
    """يُحرّك المؤشّر **فقط إن كان هذا الحدثُ هو الأحدث**.

    تسجيلٌ بأثرٍ رجعيّ (كشفُ تسليمٍ يعود بتاريخ أمس) لا يصحّ أن يقلب «بعهدة
    مَن» إلى الوراء — والصفوفُ كلُّها محفوظةٌ في السلسلة على أيّ حال.
    """
    current = book.current_custody
    if current is not None and current.signed_at > moment.signed_at:
        return
    book.current_custody = moment
    book.save(update_fields=['current_custody'])


def _record(book, action, by, notes):
    from core.models import BookHistory

    BookHistory.objects.create(
        book=book, action=action, by=by,
        by_snapshot=(by.get_full_name() or by.get_username()) if by else '',
        notes=notes,
    )
