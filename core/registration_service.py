# -*- coding: utf-8 -*-
"""
القيدُ في دفترِ قسم، وتسجيلُ الردّ — **مسارا الكتابة الوحيدان**.

«ويدخل مرّةً بوارد مكتب المدير العامّ ثمّ مرّةً أخرى بوارد الأقسام المختصّة»،
و«ندخله برقم الكتاب الأصليّ… **ورقمِ واردٍ خاصٍّ بنا**» — تصحيحُ المالك. فالقيدُ
فعلٌ يتكرّر على الورقة الواحدة بعدد الدفاتر، وكلُّ رقمٍ منها من **عدّاد قسمه**.

و``register_reply`` هو ما يُغلق الدائرة: الجوابُ لا يُربط وحده — بل يُقفل معه
**الالتزامَ المفتوح المطابق**، وإلّا بقي الكتابُ في طابور المطاردة بعد أن أُجيب.
"""

import logging

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction

logger = logging.getLogger(__name__)


def register_book_here(book, department, *, by, direction=None, via_referral=None,
                       numberless=False):
    """«قيِّده عندنا» — يمنح الكتابَ رقمَ واردٍ من عدّاد هذا القسم.

    الرقمُ يأتي من ``BookSequence`` حصراً (``core/numbering.py`` هو المصدرُ
    الوحيد لكلّ قاعدةِ ترقيم) — ولا يُكتب رقمٌ بيدٍ هنا أبداً.

    ``numberless=True`` للاستثناء المدعوم: كتابٌ بلا رقمٍ رسميّ **لا يستهلك
    عدّاداً** ولا يفتح فجوةً في الدفتر.
    """
    from core.models import BookRegistration, BookSequence
    from core.scoping import can_open_content

    if not can_open_content(book, by):
        raise PermissionDenied('لا تملك صلاحيةَ قيدِ هذا الكتاب.')
    if department is None:
        raise ValidationError('لا قسمَ للقيد.')
    if via_referral is not None and via_referral.book_id != book.pk:
        raise ValidationError('الإحالةُ ليست لهذا الكتاب.')

    kind = direction or _direction_of(book)
    with transaction.atomic():
        issued = BookSequence.consume_next(kind, numberless=numberless,
                                           department=department)
        try:
            registration = BookRegistration.objects.create(
                book=book, department=department, direction=kind,
                number=issued['formatted'] or '', registered_by=by,
                via_referral=via_referral,
            )
        except IntegrityError as exc:
            raise ValidationError('الكتابُ مُقيَّدٌ في دفتر هذا القسم سلفاً.') from exc

        _record(book, 'registered', by,
                'قُيّد في دفتر «%s» بالرقم %s' % (department, registration.number or '(بلا رقم)'))

    return registration


GM_OFFICE_NAME = 'مكتب المدير العام'


def gm_office_department():
    """قسمُ «مكتب المدير العام» في الشجرة — يُنشأ إن غاب (قراراتُ الدورة §1 و§3)."""
    from core.models import Department
    dept = Department.objects.filter(name=GM_OFFICE_NAME).first()
    if dept is None:
        dept = Department.objects.create(name=GM_OFFICE_NAME, code='ر-م.ع')
    return dept


def record_gm_office_number(book, number, *, by):
    """**الاستثناءُ المعلَن** لقاعدة «لا رقمَ بيدٍ هنا»: الصادرُ الخارجيّ يحمل رقمَ
    مكتب المدير العام كما أتى مثبتاً على الورقة («ش13/…» أو بلا رمز) — قيدٌ في
    دفتر ذلك المكتب **بلا استهلاك أيّ سلسلة** (قراراتُ الدورة §3). فارغٌ ⟵ يُزال القيد.
    يُعيد القيدَ أو None."""
    from core.models import BookRegistration
    from core.scoping import can_open_content
    if not can_open_content(book, by):
        raise PermissionDenied('لا تملك صلاحيةَ قيدِ هذا الكتاب.')
    number = (number or '').strip()[:20]
    dept = gm_office_department()
    current = BookRegistration.objects.filter(book=book, department=dept).first()
    with transaction.atomic():
        if not number:
            if current is not None:
                current.delete()
                _record(book, 'registered', by, 'أُزيل رقمُ مكتب المدير العام')
            return None
        if current is None:
            current = BookRegistration.objects.create(
                book=book, department=dept, direction=_direction_of(book),
                number=number, registered_by=by)
            _record(book, 'registered', by, 'رقمُ مكتب المدير العام: %s' % number)
        elif current.number != number:
            current.number = number
            current.save(update_fields=['number'])
            _record(book, 'registered', by, 'صُحّح رقمُ مكتب المدير العام إلى %s' % number)
    return current


def register_reply(original, reply_book, *, by, note=''):
    """يربط جواباً بأصله **ويُقفل الالتزامَ المفتوح المطابق**.

    الربطُ وحده يترك الكتابَ في طابور المطاردة بعد أن أُجيب — وهو أسوأُ من عدم
    الربط: طابورٌ فيه ما أُنجز يفقد ثقةَ مَن يقرأه فيهمله.

    «المطابق» = التزامٌ مفتوحٌ على الأصل هدفُه القسمُ الذي صدر عنه الجواب.
    وإن لم يوجد فالربطُ يتمّ ولا يُقفل شيء — ولا يُختلق إقفال.
    """
    from core.linking_service import add_link
    from core.models import BookLink
    from core.referral_service import close_by_reply

    with transaction.atomic():
        link = add_link(reply_book, original, BookLink.REPLY, by=by, note=note)
        closed = close_by_reply(original, link, reply_book, by=by)

    return link, closed


def registrations_of(book, user):
    """قيودُ الكتاب في الدفاتر كلِّها — **وبوّابةُ الكتاب هي البوّابة**.

    قصرتُها أوّلاً على شجرة المستخدم ثمّ تراجعت: **التضييقُ حجب الميزةَ نفسَها**.
    غرضُ هذه القائمة أن تُظهر رحلةَ الورقة («يدخل مرّةً بوارد مكتب المدير العامّ
    ثمّ مرّةً أخرى بوارد الأقسام المختصّة») — ومَن يرى نصفَها لا يرى شيئاً.

    ولا تسريبَ فيها: مَن يفتح الكتابَ يرى صفوفَ تفريقه أصلاً، فمعرفةُ أنّ قسماً
    قيّده لا تضيف علماً جديداً — والرقمُ في دفترٍ ورقيٍّ مفتوحٍ على أيّ حال.
    """
    return list(book.registrations.select_related('department').all())


# ───────────────────────────── الداخليّات ─────────────────────────────

def _direction_of(book):
    """اتّجاهُ القيد من منظور **المقيِّد**: ما يَرِد إليه وارد، مهما كان عند غيره.

    كتابٌ صادرٌ من قسمٍ آخر هو **واردٌ داخليّ** في دفتري؛ والوارد الخارجيّ يبقى
    خارجيّاً لأنّ مصدره خارج الشركة.
    """
    return 'incoming_external' if book.kind == 'incoming_external' else 'incoming_internal'


def _record(book, action, by, notes):
    from core.models import BookHistory

    BookHistory.objects.create(
        book=book, action=action, by=by,
        by_snapshot=(by.get_full_name() or by.get_username()) if by else '',
        notes=notes,
    )
