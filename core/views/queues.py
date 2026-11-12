# -*- coding: utf-8 -*-
"""طاولتا العمل — طاولةُ البريد و«طاولتي».

- ``desk_board`` (``/desk/``) — طاولةُ البريد لرئيس القسم ومختصّ البريد والمنفِّذ (``can_use_desk``):
  خريطةُ عملِ القسم في ستّة طوابير و«آخر القيود»، والمنفِّذ مقصورٌ على وحدته.
- ``my_desk`` (``/desk/mine/``) — «طاولتي» لمسؤول الشعبة أو الوحدة (``can_use_my_desk``): طوابيرُ
  العمل الأربعة على ما أُحيل إلى شجرته، بلا رقابة ولا دفتر.

و«ما يخصّني اليوم» (``my_today``) حُذفت بقرار المالك (11‑04): كانت تكرّر الطاولة.

**والطابورُ ينقر إلى القائمة الموحّدة بفلاتر — لا جدولَ كتبٍ ثانٍ في النظام.**
عدّادٌ هنا وصفوفٌ هناك؛ ونسخُ جدول الكتب ثالثةً كان سيُنشئ مصدرَ حقيقةٍ ثالثاً
للفرز والترقيم والصلاحيّة.

النطاقُ في الاستعلام: كلُّ طابورٍ يُبنى فوق ``scope_books_for`` /
``scope_referrals_for``، والسرّيُّ يظهر رقماً ويُحجب موضوعُه — الطابورُ يعرض
عناوينَ كتبٍ لم يفتحها صاحبُ الشاشة بعد.
"""

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import OuterRef, Q, Subquery
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.models import Book, BookHistory, BookReferral, CustodyEvent, Department
from core.scoping import (ACCESS_STUB, STUB_TITLE, can_send_referral, can_use_desk, can_use_my_desk, has_capability,
                          is_privileged, scope_books_for, scope_referrals_for,
                          secret_access, subtree_ids, user_department_id)

#: أقصى ما يُعرض في الطابور الواحد — الطابورُ لمحةٌ لا جدول.
ROW_LIMIT = 12
RECENT_BOOK_LIMIT = 20
RECENT_REFERRAL_LIMIT = 5


def _recent_desk_books(user, department_id, department_scope):
    """آخرُ قيود القسم مع إحالاتها الظاهرة وآخر حدثٍ تدقيقيّ لكلّ كتاب."""
    if not department_scope and not is_privileged(user):
        return []

    history = BookHistory.objects.filter(book_id=OuterRef('pk')).order_by('-created_at', '-pk')
    book_filters = {
        'source_ref': '',
        'is_training': False,
        'is_deleted': False,
    }
    if not is_privileged(user):
        book_filters['department_id__in'] = department_scope

    books = list(
        scope_books_for(user, Book.objects.filter(**book_filters))
        .annotate(
            desk_activity_at=Subquery(history.values('created_at')[:1]),
            desk_activity_action=Subquery(history.values('action')[:1]),
            desk_activity_notes=Subquery(history.values('notes')[:1]),
        )
        .select_related('department')
        .order_by('-created_at', '-pk')[:RECENT_BOOK_LIMIT]
    )
    if not books:
        return books

    book_ids = [book.pk for book in books]
    referral_rows = scope_referrals_for(
        user,
        BookReferral.objects.filter(book_id__in=book_ids),
    ).select_related(
        'book', 'from_department', 'to_department', 'to_entity', 'assignee', 'created_by',
    ).order_by('-created_at', '-pk')
    referrals_by_book = {}
    # (ب)6: الأعلامُ من حرّاس الخدمة نفسِها لا من «كتابُ قسمي» — كان الشرطُ يفترض رئيساً أو مختصَّ بريد
    # فيُظهر للمنفِّذ «إلغاء» و«متابعة» و«استلام» ثمّ يرفضها الخادم (مراجعةُ فيبل). الاستلامُ والإنجاز
    # ``_guard_target``، والإلغاءُ ``_guard_chaser``، وتفعيلُ المتابعة ``can_send_referral``.
    from core.referral_service import _chaser_side, _target_side

    may_receive = has_capability(user, 'referral.receive')
    for referral in referral_rows:
        may_send = can_send_referral(referral.book, user)
        target_side = may_receive and _target_side(referral, user)
        referral.desk_can_receive = (
            referral.status == BookReferral.SENT and target_side
        )
        referral.desk_can_finish = (
            referral.status == BookReferral.RECEIVED
            and referral.purpose == BookReferral.ACTION
            and target_side
        )
        referral.desk_can_cancel = (
            referral.status == BookReferral.SENT and may_send and _chaser_side(referral, user)
        )
        referral.desk_can_update_followup = (
            referral.status in BookReferral.OPEN_STATUSES
            and referral.purpose == BookReferral.ACTION
            and may_send
        )
        referrals_by_book.setdefault(referral.book_id, []).append(referral)

    action_labels = dict(BookHistory.ACTION_CHOICES)
    for book in books:
        shape = _shape(book, user)
        book.desk_title = shape['title']
        book.desk_activity_label = action_labels.get(
            book.desk_activity_action, 'حركة على الكتاب',
        )
        book.desk_activity_notes = (
            '' if shape['restricted'] else book.desk_activity_notes
        )
        book_refs = referrals_by_book.get(book.pk, [])
        book.desk_referrals = book_refs[:RECENT_REFERRAL_LIMIT]
        book.desk_referrals_more = max(0, len(book_refs) - RECENT_REFERRAL_LIMIT)
    return books


def _row(referral, user):
    """صفُّ طابورٍ — الموضوعُ محجوبٌ إن كان الكتابُ سرّيّاً على القارئ.

    الحجبُ هنا لا في القالب: الطابورُ يُصيَّر في صفحةٍ ويُصدَّر في أخرى،
    وقاعدةٌ في القالب تُنسى عند أوّل مستهلكٍ ثانٍ.
    """
    return _shape(referral.book, user,
                  referral=referral,
                  meta_label=(referral.to_department.name
                              if referral.to_department_id else ''),
                  meta_date=referral.due_date,
                  status_label=referral.get_status_display(),
                  purpose_label=referral.get_purpose_display(),
                  overdue=bool(referral.due_date
                               and referral.due_date < timezone.localdate()))


def _custody_row(moment, user):
    """صفُّ حدثِ عهدة — الحاملُ في موضع الهدف، ووقتُ التوقيع في موضع الموعد."""
    return _shape(moment.book, user,
                  meta_label=moment.holder_name,
                  meta_date=moment.signed_at.date())


def _shape(book, user, *, referral=None, meta_label='', meta_date=None,
           status_label='', purpose_label='', overdue=False):
    """الشكلُ الواحد الذي يقرأه القالب — **والحجبُ هنا لا هناك**.

    ثلاثةُ أنواعِ صفوفٍ (إحالةٌ · كتابٌ · حدثُ عهدة) تُصيَّر في القالب نفسِه،
    فالمفتاحان `meta_label`/`meta_date` محايدان عمداً: لو تنكّر الكتابُ في زيّ
    إحالةٍ ليُرضي القالبَ لصارت الكذبةُ معماريّةً عند النوع الرابع.
    """
    restricted = secret_access(user, book) == ACCESS_STUB
    return {
        'referral': referral,
        'book': book,
        'title': STUB_TITLE if restricted else (book.title or '—'),
        'restricted': restricted,
        'overdue': overdue,
        'meta_label': meta_label,
        'meta_date': meta_date,
        'status_label': status_label,
        'purpose_label': purpose_label,
    }


def _queue(qs, user, limit=ROW_LIMIT, row=_row,
           select=('book', 'to_department', 'from_department', 'assignee')):
    """طابورٌ جاهزٌ للعرض: عددُه الكاملُ وصفوفُه المقطوعة.

    العدُّ **قبل** القطع — عدّادٌ يقول 12 بينما الطابورُ 80 كذبٌ مريح.

    و``row``/``select`` افتراضُهما سلوكُ الإحالة، فطوابيرُ الكتب وأحداثِ العهدة
    تمرّ من هنا بلا نسخِ الآلة ولا نسخِ القالب.
    """
    total = qs.count()
    sliced = qs.select_related(*select)
    rows = [row(r, user) for r in (sliced if limit is None else sliced[:limit])]
    return {'total': total, 'rows': rows, 'more': max(0, total - len(rows)),
            'expanded': limit is None}


def _limit_for(request, key):
    """«و{n} غيرها» يجب أن يُوصل: ``?expand=<key>`` يرفع القطعَ عن طابورٍ واحد
    (لا عن الصفحة كلِّها) — الطريقُ المسدودُ صار باباً (مواصفةُ الواجهات، الدفعة 2)."""
    return None if request.GET.get('expand') == key else ROW_LIMIT


@login_required
def desk_board(request):
    """طاولةُ البريد — طوابيرُ التسليم والاستلام والإنجاز المفتوحة."""
    if not can_use_desk(request.user):
        raise PermissionDenied('طاولةُ البريد لمختصّ البريد ورئيس القسم وموظّف التنفيذ.')

    today = timezone.localdate()
    dept_id = user_department_id(request.user)
    mine = subtree_ids(dept_id) if dept_id else []

    open_here = scope_referrals_for(request.user, BookReferral.objects.filter(
        status__in=BookReferral.OPEN_STATUSES,
    ))
    if mine:
        open_here = open_here.filter(
            Q(to_department_id__in=mine) | Q(from_department_id__in=mine))

    # «بلا ردّ» = غرضُه التنفيذ ولم يُقفَل بجوابٍ ولا موعدَ له يُطارَد به.
    no_reply = open_here.filter(purpose=BookReferral.ACTION,
                                closed_by_link__isnull=True, due_date__isnull=True)

    visible_books = scope_books_for(request.user, Book.objects.all())
    secret_open = open_here.filter(book__in=visible_books.exclude(secret_level='normal'))
    recent_books = _recent_desk_books(request.user, dept_id, mine)

    queues = _work_queues(request, open_here, today) + [
        {'key': 'no_reply', 'label': 'بلا ردّ', 'tone': 'muted',
         'hint': 'للتنفيذ وبلا جوابٍ ولا موعد', **_queue(no_reply, request.user, limit=_limit_for(request, 'no_reply'))},
        {'key': 'secret', 'label': 'سرّي مفتوح', 'tone': 'secret',
         'hint': 'التزامٌ قائمٌ على كتابٍ مقيَّد', **_queue(secret_open, request.user, limit=_limit_for(request, 'secret'))},
    ]
    active_queue = request.GET.get('queue') or request.GET.get('expand') or 'recent'
    selected_queue = next((q for q in queues if q['key'] == active_queue), None)
    if active_queue != 'recent' and selected_queue is None:
        raise Http404('تصنيف المتابعة غير موجود.')

    queues_empty = not any(q.get('total') for q in queues)
    return render(request, 'core/desk_board.html', {
        'queues': queues,
        'active_queue': active_queue,
        'selected_queue': selected_queue,
        # فراغٌ واحدٌ بمخرج بدل خمس بطاقاتٍ تقول «لا شيء هنا» — كـ«ما يخصّني» (تدقيقُ نيلسن D#24)
        'queues_empty': queues_empty,
        'show_blank': queues_empty and active_queue == 'recent',
        'show_recent': True,
        'today': today,
        'department_id': dept_id,
        'recent_books': recent_books,
        'recent_book_limit': RECENT_BOOK_LIMIT,
    })


def _work_queues(request, open_here, today):
    """طوابيرُ العمل الأربعة — مصدرُها واحدٌ لطاولة البريد و«طاولتي»."""
    # «غيرُ مستلَم» حالةٌ لا حساب: الصفُّ أُرسل ولم يُؤشَّر استلامُه بعد.
    unreceived = open_here.filter(status=BookReferral.SENT)
    overdue = open_here.filter(purpose=BookReferral.ACTION, due_date__lt=today)
    due_today = open_here.filter(purpose=BookReferral.ACTION, due_date=today)
    received_action = open_here.filter(status=BookReferral.RECEIVED, purpose=BookReferral.ACTION)
    return [
        {'key': 'overdue', 'label': 'متأخّر', 'tone': 'danger',
         'hint': 'مرّ موعدُه ولم يُنجَز', **_queue(overdue, request.user, limit=_limit_for(request, 'overdue'))},
        {'key': 'unreceived', 'label': 'غير مُستلَم', 'tone': 'warn',
         'hint': 'أُرسل ولم تُؤشَّر عهدتُه', **_queue(unreceived, request.user, limit=_limit_for(request, 'unreceived'))},
        {'key': 'received_action', 'label': 'مستلَم وقيد الإنجاز', 'tone': 'accent',
         'hint': 'الوصول مؤشّر؛ توجيه التنفيذ ما زال مفتوحاً',
         **_queue(received_action, request.user, limit=_limit_for(request, 'received_action'))},
        {'key': 'today', 'label': 'يستحقّ اليوم', 'tone': 'accent',
         'hint': 'موعدُه اليوم', **_queue(due_today, request.user, limit=_limit_for(request, 'today'))},
    ]


@login_required
def my_desk(request):
    """«طاولتي» — مسؤولُ الشعبة أو الوحدة (قرارُ المالك 11‑02): ما أُحيل إلى شجرته فقط.

    طاولةُ عملٍ لا رقابة: طوابيرُ العمل الأربعة على ما وصل إلى وحدته وما يتبعها، بلا «آخر القيود»
    ولا «بلا ردّ» ولا «السرّيّ المفتوح»، وبلا الدفتر والكشف. والسرّيُّ يظهر رقماً بلا موضوع (``_shape``).
    """
    if not can_use_my_desk(request.user):
        raise PermissionDenied('«طاولتي» لمسؤول الشعبة أو الوحدة.')

    today = timezone.localdate()
    dept_id = user_department_id(request.user)
    open_here = scope_referrals_for(request.user, BookReferral.objects.filter(
        status__in=BookReferral.OPEN_STATUSES,
        to_department_id__in=subtree_ids(dept_id) if dept_id else [],
    ))
    queues = _work_queues(request, open_here, today)
    queues_empty = not any(q.get('total') for q in queues)
    asked = request.GET.get('queue') or request.GET.get('expand')
    selected_queue = next((q for q in queues if q['key'] == asked), None)
    if asked and selected_queue is None:
        raise Http404('تصنيف المتابعة غير موجود.')
    if selected_queue is None and not queues_empty:
        selected_queue = next(q for q in queues if q['total'])
    return render(request, 'core/desk_board.html', {
        'my_desk': True,
        'department': Department.objects.filter(pk=dept_id).first(),
        'queues': queues,
        'active_queue': selected_queue['key'] if selected_queue else None,
        'selected_queue': selected_queue,
        'queues_empty': queues_empty,
        'show_blank': queues_empty,
        'show_recent': False,
        'today': today,
    })


@login_required
@require_POST
def cancel_desk_referral(request, book_id, referral_id):
    """إلغاءُ إحالةٍ مرسلةٍ من الطاولة، مع إبقاء الإحالة وختمها في التاريخ."""
    from core.referral_service import cancel_referral

    referral = scope_referrals_for(request.user).filter(
        pk=referral_id, book_id=book_id,
    ).select_related('book', 'to_department', 'to_entity').first()
    if referral is None:
        raise Http404('الإحالة غير موجودة')

    try:
        cancel_referral(
            referral, by=request.user, note=(request.POST.get('note') or '').strip(),
        )
    except ValidationError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, 'أُلغي التفريق مع الاحتفاظ بسجله الزمني.')
    return redirect(reverse('desk_board') + '#recent-books')
