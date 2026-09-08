# -*- coding: utf-8 -*-
"""تمامُ الأرشفة — **مسارُ الكتابة الوحيد** لخاتمة دورة الكتاب.

شهادةُ موظّف البريد تذكر ثلاثةَ توقيعاتٍ حقيقيّةً على الورقة الواحدة: استلامُ
الوحدة · **تمامُ الأرشفة والحفظ** · تسليمُ المتعهّد. وهذا الملفُّ صاحبُ الثاني.

**الأرشفةُ حدثٌ لا علَم — والقرارُ مبنيٌّ على قياسٍ لا ذوق.** الحقلُ
``Book.is_archived`` يبدو الموضعَ الطبيعيَّ حتى تُقاس القاعدة: **13,188 من
13,194** كتاباً عليه أصلاً، منها 13,174 لمجرّد غياب ``due_date`` — لأنّ
``Book.save()`` فيه قاعدةٌ ذهبيّةٌ قائمة (``if not self.due_date:
self.is_archived = True``). فمعناه «انتهت المتابعة» لا «حُفظت الورقة»،
وإعادةُ استعماله كانت ستُنتج ثلاثةَ أعطاب:

1. طابورُ «منجَزٌ ولم يُؤرشَف» يولد كاذباً (كلُّ القاعدة «مؤرشَفة»).
2. إعادةُ الفتح مستحيلةٌ لـ13,174 كتاباً — أوّلُ ``save()`` يقلب العلَمَ ثانيةً.
3. لا زمنَ ولا فاعلَ ولا موضعَ حفظ: علَمٌ بلا شهادة.

فالعلامةُ هنا ``CustodyEvent(ARCHIVE_DONE)`` نفسُه: حدثٌ له وقتٌ وفاعلٌ وحاملٌ
وموضعُ حفظ، وسلسلةُ العهدة تحفظه كما تحفظ أخواته. و``is_archived`` **لا
تُلمَس** — لها معناها ومستهلكوها (تبويبُ «archived» و``followup_state``).

**والحاملُ قسمُ الكتاب لا الأرشيفيّ**: الورقةُ تُحفظ في أرشيف القسم، ولو
جُعلت بعهدة الشخص لبدا أنّها تخرج معه حين ينتقل — وهو عكسُ ما تعنيه الأرشفة.
"""

import logging

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

logger = logging.getLogger(__name__)

#: سعةُ ``CustodyEvent.note`` — وتحمل موضعَ الحفظ والملاحظةَ معاً.
NOTE_MAX = 255


def archive_book(book, *, by, place='', note=''):
    """يقيّد «تمامَ الأرشفة» على كتاب — ويُعيد ``CustodyEvent``.

    ``place`` موضعُ الحفظ (الرفّ/الصندوق/المجلّد) — وهو ما يسأل عنه الكاتبُ
    بعد سنة، فيُخزَّن في صدر ملاحظة الحدث لا يضيع في نصٍّ حرّ.

    يرفع ``PermissionDenied`` لمن ليس أرشيفيّاً، و``ValidationError`` على
    كتابٍ عليه التزامٌ مفتوح أو مؤرشَفٍ سلفاً.
    """
    from core.custody_service import record_archive_event
    from core.models import BookReferral, CustodyEvent

    department = _gate(book, by, 'تمامُ الأرشفة لمسؤول الأرشفة ومدير النظام.')
    summary = _compose(place, note)

    # **الأرشفةُ خاتمةٌ لا إخفاء**: التزامٌ مفتوحٌ يعني أنّ الورقةَ ما زالت
    # عند وحدةٍ تعمل عليها، وإغلاقُ الملفّ عليها يجعل الطابورَ يكذب ويُسقط
    # الكتابَ من عين مَن يطارده.
    pending = list(BookReferral.objects
                   .filter(book=book, status__in=BookReferral.OPEN_STATUSES)
                   .select_related('to_department', 'to_entity')[:5])
    if pending:
        raise ValidationError('الكتابُ مُفرَّقٌ والتزامُه ما زال مفتوحاً عند: %s '
                              '— يُؤرشَف بعد الإنجاز.' % ' · '.join(_target(r)
                                                                    for r in pending))
    # **الحفظُ يستلزم انتهاءَ المتابعة** (قرارُ المالك 2026-09-06): ورقةٌ لها
    # موعدُ استحقاقٍ قائمٌ ما زالت في طابور المتابعة، وحفظُها على الرفّ يُخرجها
    # من عين مَن يطاردها. والمفهومان يبقيان منفصلين في التخزين — هذا شرطُ
    # ترتيبٍ بينهما لا دمجٌ لهما.
    if book.followup_state != 'archived':
        raise ValidationError(
            'المتابعةُ ما زالت قائمة (يستحقّ %s) — تُغلق أوّلاً ثمّ يُحفظ الورق.'
            % book.due_date)
    if is_archived(book):
        raise ValidationError('هذا الكتابُ مؤرشَفٌ سلفاً — يُفتح بسببٍ قبل أن يُؤرشَف ثانيةً.')

    with transaction.atomic():
        moment = record_archive_event(
            book, CustodyEvent.ARCHIVE_DONE,
            to_department=department, by=by, note=summary)
        _record(book, 'archived', by, summary or 'بلا موضعِ حفظ')

    logger.info('archive: book=%s by=%s place=%r', book.pk, by.pk, place)
    return moment


def reopen_archive(book, *, by, reason):
    """يُخرج كتاباً من الأرشيف **بسببٍ مسجَّل** — ولا يمحو أثرَ حفظه.

    الأحداثُ لا تُحذف: حدثُ ``ARCHIVE_DONE`` يبقى، ويُكتب فوقه ``ARCHIVE_REOPEN``
    يقول «خرجت الورقةُ من الأرشيف إلى يد فلان» — فالسلسلةُ تُقرأ كما جرت.
    وحدثٌ **مخصَّصٌ** لا ``RETURN`` المشترك: لو أُخذت الإعادةُ العامّة علامةَ
    خروجٍ لألغى رجوعُ متعهّدِ بريدٍ حفظَ الورقة بلا أن يقصد أحدٌ ذلك.
    والسببُ **إلزاميّ**: فتحُ ملفٍّ مقفولٍ بلا سببٍ هو ما يجعل الأرشيفَ بلا معنى.
    """
    from core.custody_service import record_archive_event
    from core.models import CustodyEvent

    _gate(book, by, 'فتحُ المؤرشَف لمسؤول الأرشفة ومدير النظام.')
    reason = (reason or '').strip()
    if not reason:
        raise ValidationError('لا يُفتح مؤرشَفٌ بلا سببٍ مسجَّل.')
    if len(reason) > NOTE_MAX:
        raise ValidationError('السببُ يتجاوز %d حرفاً.' % NOTE_MAX)
    if not is_archived(book):
        raise ValidationError('هذا الكتابُ ليس مؤرشَفاً.')

    with transaction.atomic():
        moment = record_archive_event(
            book, CustodyEvent.ARCHIVE_REOPEN, to_user=by, by=by, note=reason)
        _record(book, 'archive-reopened', by, reason[:255])

    logger.info('archive-reopen: book=%s by=%s', book.pk, by.pk)
    return moment


# ───────────────────────────── البوّابة ─────────────────────────────

def _gate(book, by, denial):
    """يتحقّق من الحقّ **قبل** أيّ كشفٍ عن حال الكتاب — ويُعيد قسمَ الحفظ.

    الترتيبُ مقصود: لو سبق فحصُ «أعليه التزامٌ مفتوح؟» فحصَ الحقّ، لتعلّم
    الغريبُ من رسالة الرفض أنّ الكتابَ مُفرَّقٌ وإلى أين — وهو تسريبٌ برسالة.

    **وثلاثةُ شروطٍ لا شرطان**: يفتح المحتوى · أرشيفيٌّ · و**الكتابُ من أرشيف
    شجرته**. الثالثُ هو الذي كان ناقصاً: الكتابُ المُفرَّق إلى وحدةٍ مرئيٌّ
    لأرشيفيّها، وليس له أن يُغلق ملفَّ القسم المالك. والشجرةُ لا المساواة —
    أرشيفُ الشعبة تحت أرشيفيّ قسمها كما يسيل النطاق.
    """
    from core.models import Department
    from core.scoping import (can_archive, can_open_content,
                              is_company_archivist, is_privileged,
                              subtree_ids, user_department_id)

    if not can_open_content(book, by):
        raise PermissionDenied('لا تملك صلاحيةَ أرشفة هذا الكتاب.')
    if not can_archive(by):
        raise PermissionDenied(denial)

    department = book.department
    if department is None:
        # كتابٌ بلا قسم: المخطّطُ يسمح والواقعُ فيه صفوف. يُحفظ في أرشيف
        # مَن يحفظه — وهو أصدقُ من رفضٍ يترك الورقةَ بلا رفّ.
        mine = user_department_id(by)
        if mine is None:
            raise ValidationError(
                'لا قسمَ للكتاب ولا للأرشيفيّ — لا يُعرف أيُّ أرشيفٍ يحفظه.')
        department = Department.objects.get(pk=mine)

    if not (is_privileged(by) or is_company_archivist(by)
            or department.pk in subtree_ids(user_department_id(by))):
        raise PermissionDenied('هذا الكتابُ من أرشيف قسمٍ آخر — يُؤرشفه أرشيفيُّه.')
    return department


def _compose(place, note):
    """موضعُ الحفظ ثمّ الملاحظة — **ويُرفض الطويلُ ولا يُبتَر**.

    البترُ الصامت يأكل آخرَ ما كُتب، وموضعُ الرفّ هو الشيءُ الوحيد الذي يُسأل
    عنه بعد سنة. فأن يُقال «طويل» خيرٌ من أن يُحفظ نصفُ عنوانِ الرفّ.
    """
    text = ' — '.join(part for part in ((place or '').strip(), (note or '').strip())
                      if part)
    if len(text) > NOTE_MAX:
        raise ValidationError(
            'موضعُ الحفظ والملاحظةُ معاً يتجاوزان %d حرفاً.' % NOTE_MAX)
    return text


def _target(referral):
    """اسمُ مَن عنده الالتزامُ المفتوح — ليقول الرفضُ **أين** الورقة."""
    if referral.to_department_id:
        return referral.to_department.name
    if referral.to_entity_id:
        return referral.to_entity.name
    return 'جهةٍ غير مسمّاة'


# ───────────────────────── الاشتقاقُ من الحدث ─────────────────────────
#
# مصدرٌ واحدٌ لسؤال «أمؤرشَفٌ هو؟» بصيغتيه: للصفّ الواحد وللاستعلام. ولو
# كُتب الشرطُ في كلّ مستهلكٍ على حدة لانفرجت النسخُ عند أوّل تغيير — وهو
# الجذرُ الذي كلّف هذه الدفعةَ ثماني مرّات.

def is_archived(book):
    """أقُيِّد على هذا الكتاب «تمامُ أرشفة» لم يُفتح بعده؟"""
    from core.models import CustodyEvent

    last = (CustodyEvent.objects
            .filter(book=book, event__in=(CustodyEvent.ARCHIVE_DONE,
                                          CustodyEvent.ARCHIVE_REOPEN))
            .order_by('-signed_at', '-id').first())
    return last is not None and last.event == CustodyEvent.ARCHIVE_DONE


def archived_books(qs=None):
    """الكتبُ المحفوظة — استعلامٌ لا حلقةُ بايثون."""
    return _by_archive(qs, archived=True)


def unarchived_books(qs=None):
    """الكتبُ التي لم تُحفظ بعد."""
    return _by_archive(qs, archived=False)


def _by_archive(qs, *, archived):
    """التوأمُ الاستعلاميُّ لـ``is_archived`` — والفرزُ نفسُه.

    آخرُ حدثٍ أرشيفيٍّ على الكتاب هو الحاكم: ``ARCHIVE_DONE`` محفوظ،
    و``ARCHIVE_REOPEN`` بعده مفتوح. ويُقارَن بـ``Subquery`` لا بـ``Exists`` وحده،
    وإلّا عُدّ المفتوحُ محفوظاً لأنّ حدثَ حفظه القديم ما زال قائماً.
    """
    from django.db.models import OuterRef, Q, Subquery

    from core.models import Book, CustodyEvent

    qs = Book.objects.filter(is_deleted=False) if qs is None else qs
    latest = (CustodyEvent.objects
              .filter(book=OuterRef('pk'),
                      event__in=(CustodyEvent.ARCHIVE_DONE,
                                 CustodyEvent.ARCHIVE_REOPEN))
              .order_by('-signed_at', '-id')
              .values('event')[:1])
    marked = qs.annotate(_last_archive_event=Subquery(latest))
    if archived:
        return marked.filter(_last_archive_event=CustodyEvent.ARCHIVE_DONE)
    # **الفراغُ ليس نفياً في SQL**: `exclude(x=v)` يترجَم `NOT (x = v)` وهو
    # `NULL` للكتاب الذي لا حدثَ أرشيفيّاً له أصلاً — فيسقط من الطابور صامتاً.
    # وهو أخطرُ ما يمكن أن يحدث هنا: الطابورُ الذي يعيش عليه الدورُ يُخفي
    # الكتبَ التي لم تُحفظ قطّ، ويبدو نظيفاً وهو أعمى. (اصطاده حارسُ الثلاثة.)
    return marked.filter(Q(_last_archive_event__isnull=True)
                         | ~Q(_last_archive_event=CustodyEvent.ARCHIVE_DONE))


def _record(book, action, by, notes=''):
    """قيدٌ في سجلّ الكتاب بمفتاحٍ من ``ACTION_CHOICES`` لا بنصٍّ حرّ.

    **ولا ``except`` واسعٌ هنا**: القيدُ جزءٌ من الأثر، وسقوطُه يجب أن يُسقط
    المعاملةَ لا أن يُخفي نفسَه — وهو درسٌ كلّف هذه الدفعةَ قيداً ضائعاً.
    """
    from core.models import BookHistory

    BookHistory.objects.create(
        book=book, action=action, by=by,
        by_snapshot=(by.get_full_name() or by.username) if by else '',
        notes=notes or '',
    )
