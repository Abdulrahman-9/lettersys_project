# -*- coding: utf-8 -*-
"""
نسيجُ الوثائق — **مسارُ الكتابة الوحيد** إلى ``BookLink``.

يُمنع إنشاءُ ضلعٍ أو حذفُه خارج هذه الدالّتين: الضلعُ وحدَه نصفُ الحقيقة،
ونصفُها الآخر أثرُه في دورة حياة **الكتابين معاً**. وكتابةٌ متفرّقةٌ تُخلّف
أضلاعاً بلا أثرٍ في التاريخ — فيقرأ الكاتبُ خطّاً زمنيّاً ينقصه ما جرى.

(نمطُ ``core/attachment_service.py`` و``reservation_service.py`` نفسُه: خدمةٌ
تكتب كلَّ ما يلزم في نَفَسٍ واحد داخل معاملة.)
"""

import logging

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction

logger = logging.getLogger(__name__)


def add_link(from_book, to_book, relation, *, by, note=''):
    """يربط كتاباً بكتاب، ويكتب الأثر في تاريخ الطرفين.

    يرفع ``ValidationError`` على الربط الذاتيّ أو العلاقة المجهولة أو التكرار،
    و``PermissionDenied`` إن لم يكن الرابطُ يملك **محتوى** الطرفين: ربطُ كتابٍ
    لا تراه يكشف وجودَه ورقمَه لصاحب الطرف الآخر.
    """
    from core.models import BookHistory, BookLink
    from core.scoping import can_open_content

    if from_book.pk == to_book.pk:
        raise ValidationError('لا يُربط الكتاب بنفسه.')
    if relation not in dict(BookLink.RELATION_CHOICES):
        raise ValidationError('نوعُ علاقةٍ غير معروف.')
    for book in (from_book, to_book):
        if not can_open_content(book, by):
            raise PermissionDenied('لا تملك صلاحيةَ الربط بهذا الكتاب.')

    label = dict(BookLink.RELATION_CHOICES)[relation]
    try:
        with transaction.atomic():
            link = BookLink.objects.create(
                from_book=from_book, to_book=to_book,
                relation=relation, note=note.strip()[:255], created_by=by,
            )
            # حدثٌ في تاريخ الطرفين: صاحبُ الأصل يحتاج أن يعرف أنّ كتاباً أشار
            # إليه بقدر ما يحتاج المُشيرُ أن يعرف بمن ارتبط.
            _record(from_book, 'link-added', by,
                    f'{label} الكتاب {_ref(to_book)}')
            _record(to_book, 'link-added', by,
                    f'الكتاب {_ref(from_book)} — {label} هذا الكتاب')
    except IntegrityError as exc:
        raise ValidationError('هذا الربط موجودٌ سلفاً.') from exc

    return link


def remove_link(link, *, by):
    """يفكّ ربطاً ويكتب الأثر في تاريخ الطرفين."""
    from core.models import BookLink
    from core.scoping import can_open_content

    from_book, to_book = link.from_book, link.to_book
    if not can_open_content(from_book, by):
        raise PermissionDenied('لا تملك صلاحيةَ فكّ هذا الربط.')

    label = dict(BookLink.RELATION_CHOICES)[link.relation]
    with transaction.atomic():
        link.delete()
        _record(from_book, 'link-removed', by, f'فُكّ «{label} {_ref(to_book)}»')
        _record(to_book, 'link-removed', by, f'فُكّ ربطُ الكتاب {_ref(from_book)}')


def links_of(book, user):
    """أضلاعُ الكتاب في الاتّجاهين، مع بيان الطرف الآخر — أو تقييدِه.

    الضلعُ نحو كتابٍ لا يملك المستخدمُ محتواه يُصيَّر **«كتاب مقيَّد»**: رقمُه
    ظاهرٌ (وهو في الدفتر أصلاً) ولا عنوانَ ولا معاينة. فالنسيجُ لا يصير ثغرةً
    جانبيّةً تكشف ما حجبته الطبقةُ في وجهها.
    """
    from core.scoping import STUB_TITLE, can_open_content, can_view_book

    rows = []
    for link in book.links_out.select_related('to_book').all():
        rows.append(_present(link, link.to_book, 'out', user, can_view_book, can_open_content, STUB_TITLE))
    for link in book.links_in.select_related('from_book').all():
        rows.append(_present(link, link.from_book, 'in', user, can_view_book, can_open_content, STUB_TITLE))
    return [row for row in rows if row is not None]


def _present(link, other, direction, user, can_view, can_open, stub_title):
    if not can_view(other, user):
        return None            # كتابُ قسمٍ آخر: لا يُلمَّح إلى وجوده أصلاً
    openable = can_open(other, user)
    return {
        'id': link.id,
        'relation': link.relation,
        'relation_label': link.label_for(direction),
        'direction': direction,
        'note': link.note,
        'book_id': other.id if openable else None,
        'number': other.our_number_display,
        'date': other.date,
        'title': other.title if openable else stub_title,
        'restricted': not openable,
    }


def _record(book, action, by, notes):
    from core.models import BookHistory

    BookHistory.objects.create(
        book=book, action=action, by=by,
        by_snapshot=(by.get_full_name() or by.get_username()) if by else '',
        notes=notes,
    )


def _ref(book):
    """إشارةٌ قصيرةٌ للكتاب في نصّ الحدث — رقمُه بعرض ``numbering`` وتاريخُه."""
    number = book.our_number_display or '(بلا رقم)'
    return f'{number}' + (f' في {book.date:%Y/%m/%d}' if book.date else '')
