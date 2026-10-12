# -*- coding: utf-8 -*-
"""طابورا العمل — طاولةُ الوارد و«ما يخصّني اليوم».

**شاشتان لجمهورين لا واحدة لجمهورٍ عامّ:**

- ``desk_board`` (``/desk/``) — طاولةُ الوارد لمختصّ البريد ورئيس القسم:
  خريطةُ عملِ القسم كلِّه في خمسة طوابير. جمهورُها هو جمهورُ الورقتين
  المطبوعتين نفسُه (``can_use_desk``).
- ``my_today`` (``/my/today/``) — الطابورُ الشخصيّ **لكلّ الأدوار**: ما
  يخصُّني أنا. وهو ما يجعل الموظّفَ يسكن النظامَ بدل أن يزوره؛ الخطّةُ بنت
  طاولةً لموظّف البريد وحده، وهذه الشاشةُ حصّةُ البقيّة.

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

from core.models import Attachment, Book, BookHistory, BookReferral, CustodyEvent
from core.scoping import (ACCESS_STUB, STUB_TITLE, can_archive, can_use_desk,
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
    privileged = is_privileged(user)
    for referral in referral_rows:
        target_side = (
            privileged
            or referral.to_department_id in department_scope
            or referral.book.department_id == department_id
        )
        source_side = (
            privileged
            or referral.from_department_id in department_scope
            or referral.book.department_id == department_id
        )
        referral.desk_can_receive = (
            referral.status == BookReferral.SENT and target_side
        )
        referral.desk_can_finish = (
            referral.status == BookReferral.RECEIVED
            and referral.purpose == BookReferral.ACTION
            and target_side
        )
        referral.desk_can_cancel = (
            referral.status == BookReferral.SENT and source_side
        )
        referral.desk_can_update_followup = (
            referral.status in BookReferral.OPEN_STATUSES
            and referral.purpose == BookReferral.ACTION
            and (privileged or referral.book.department_id == department_id)
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


def _book_row(book, user):
    """صفُّ كتابٍ — لا إحالةَ خلفه، فلا هدفَ ولا موعد."""
    return _shape(book, user)


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
    """طاولةُ الوارد — طوابيرُ التسليم والاستلام والإنجاز المفتوحة."""
    if not can_use_desk(request.user):
        raise PermissionDenied('طاولةُ الوارد لمختصّ البريد ورئيس القسم.')

    today = timezone.localdate()
    dept_id = user_department_id(request.user)
    mine = subtree_ids(dept_id) if dept_id else []

    open_here = scope_referrals_for(request.user, BookReferral.objects.filter(
        status__in=BookReferral.OPEN_STATUSES,
    ))
    if mine:
        open_here = open_here.filter(
            Q(to_department_id__in=mine) | Q(from_department_id__in=mine))

    # «غيرُ مستلَم» حالةٌ لا حساب: الصفُّ أُرسل ولم يُؤشَّر استلامُه بعد.
    unreceived = open_here.filter(status=BookReferral.SENT)
    overdue = open_here.filter(purpose=BookReferral.ACTION, due_date__lt=today)
    due_today = open_here.filter(purpose=BookReferral.ACTION, due_date=today)
    # «بلا ردّ» = غرضُه التنفيذ ولم يُقفَل بجوابٍ ولا موعدَ له يُطارَد به.
    no_reply = open_here.filter(purpose=BookReferral.ACTION,
                                closed_by_link__isnull=True, due_date__isnull=True)
    received_action = open_here.filter(
        status=BookReferral.RECEIVED, purpose=BookReferral.ACTION,
    )

    visible_books = scope_books_for(request.user, Book.objects.all())
    secret_open = open_here.filter(book__in=visible_books.exclude(secret_level='normal'))
    recent_books = _recent_desk_books(request.user, dept_id, mine)

    queues = [
        {'key': 'overdue', 'label': 'متأخّر', 'tone': 'danger',
         'hint': 'مرّ موعدُه ولم يُنجَز', **_queue(overdue, request.user, limit=_limit_for(request, 'overdue'))},
        {'key': 'unreceived', 'label': 'غير مُستلَم', 'tone': 'warn',
         'hint': 'أُرسل ولم تُؤشَّر عهدتُه', **_queue(unreceived, request.user, limit=_limit_for(request, 'unreceived'))},
        {'key': 'received_action', 'label': 'مستلَم وقيد الإنجاز', 'tone': 'accent',
         'hint': 'الوصول مؤشّر؛ توجيه التنفيذ ما زال مفتوحاً',
         **_queue(received_action, request.user, limit=_limit_for(request, 'received_action'))},
        {'key': 'today', 'label': 'يستحقّ اليوم', 'tone': 'accent',
         'hint': 'موعدُه اليوم', **_queue(due_today, request.user, limit=_limit_for(request, 'today'))},
        {'key': 'no_reply', 'label': 'بلا ردّ', 'tone': 'muted',
         'hint': 'للتنفيذ وبلا جوابٍ ولا موعد', **_queue(no_reply, request.user, limit=_limit_for(request, 'no_reply'))},
        {'key': 'secret', 'label': 'سرّي مفتوح', 'tone': 'secret',
         'hint': 'التزامٌ قائمٌ على كتابٍ مقيَّد', **_queue(secret_open, request.user, limit=_limit_for(request, 'secret'))},
    ]

    return render(request, 'core/desk_board.html', {
        'queues': queues,
        # فراغٌ واحدٌ بمخرج بدل خمس بطاقاتٍ تقول «لا شيء هنا» — كـ«ما يخصّني» (تدقيقُ نيلسن D#24)
        'queues_empty': not any(q.get('total') for q in queues),
        'today': today,
        'department_id': dept_id,
        'recent_books': recent_books,
        'recent_book_limit': RECENT_BOOK_LIMIT,
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


@login_required
def archive_desk(request):
    """طاولةُ الأرشفة — أسئلةُ الأرشيفيّ اليوميّة، **مبنيّةً على المقيس**.

    الخطّةُ اقترحت خمسةَ طوابير، وقياسُ القاعدة الحيّة أسقط ثلاثةً منها:

    - «مرفقٌ بلا نصّ» = 13,148 صفّاً — **تقريرُ إرثٍ لا طابورُ عمل**: 13,037
      منها مرفقاتُ استيرادٍ جُمليّ، وتغطيةُ المسار الحيّ 19/19 = 100%.
    - «مسحٌ حديثٌ بلا نصّ» = 2,060 — كاذب: ``uploaded_at`` على صفوف الإرث هو
      **وقتُ تشغيل سكربت الاستيراد** لا وقتُ المسح (قمّتا مايو 11,007 وآب 2,060).
    - «عهدةٌ خارجة» طابورُ مختصّ البريد بأسماءٍ أخرى (``undelivered``)، وطابورُ
      الأرشيفيّ الحقيقيُّ يحتاج حدثَ خروجٍ لم يكن معرَّفاً حين كُتبت الخطّة.

    فكلُّ استعلامٍ هنا يحمل ``source_ref=''`` و``is_training=False``: بدونهما
    يولد الطابورُ بـ13 ألف صفٍّ لا يُغلقها عملُ إنسان — وطابورٌ لا يُفرَغ يُهجَر
    في أسبوع، فيصير الدورُ بلا أداة.
    """
    if not can_archive(request.user):
        raise PermissionDenied('طاولةُ الأرشفة لمسؤول الأرشفة ومدير النظام.')

    user = request.user
    mine = scope_books_for(user, Book.objects.all())
    #: الحيُّ وحدَه: المنقولُ من الورق دخل بالجملة ولم يمرّ بيدِ أرشيفيّ.
    live = mine.filter(source_ref='', is_training=False)
    #: قُيِّد ولم يُوجَّه — لا صفَّ إحالةٍ له: نُسيت الجهاتُ المستلِمة أو لم يُهمَّش بعد.
    never_moved = live.filter(referrals__isnull=True)
    #: قيدٌ بلا مسح: لا مرفقَ يُحفظ. (لا ``attachments__isnull`` — الضمُّ لا يمرّ
    #: بمدير، فكتابٌ مرفقُه الوحيدُ محذوفٌ ناعماً كان يختفي من الطابور بدل أن يظهر.)
    no_file = live.exclude(pk__in=Attachment.objects.values('book_id'))
    completed_followups = live.filter(
        due_date__isnull=False, is_archived=True,
    ).order_by('-updated_at', '-pk')
    completed_referrals = BookReferral.objects.filter(
        book__in=live, status=BookReferral.DONE,
    ).order_by('-created_at', '-pk')
    # (قراراتُ الدورة §6) الإنجازُ هنا حالةُ متابعة/إحالة لا علامةُ رفّ؛
    # الأرشفةُ في الأضابير تلقائيّة ولا يُطلب تأكيدٌ ورقيّ.
    queues = [
        {'key': 'idle', 'label': 'قُيِّد ولم يُوجَّه', 'tone': 'warn',
         'hint': 'دخل الدفترَ بلا جهةٍ مستلِمة — لم يذهب إلى أضبارة أحد',
         **_queue(never_moved, user, limit=_limit_for(request, 'idle'), row=_book_row, select=())},
        {'key': 'nofile', 'label': 'بلا مرفق', 'tone': 'accent',
         'hint': 'قيدٌ بلا مسح — لا ورقةَ في الأضبارة',
         **_queue(no_file, user, limit=_limit_for(request, 'nofile'), row=_book_row, select=())},
        {'key': 'completed_followups', 'label': 'متابعات أُنجزت', 'tone': 'done',
         'hint': 'متابعات أُغلقت فعلياً — لا تعني موضع حفظ ورقيّاً',
         **_queue(completed_followups, user,
                  limit=_limit_for(request, 'completed_followups'),
                  row=_book_row, select=())},
        {'key': 'completed_referrals', 'label': 'إحالات أُنجزت', 'tone': 'done',
         'hint': 'مهام الوحدات التي أُشير إلى إنجازها',
         **_queue(completed_referrals, user,
                  limit=_limit_for(request, 'completed_referrals'))},
    ]
    return render(request, 'core/archive_desk.html', {
        'queues': queues,
        'today': timezone.localdate(),
        'legacy_total': mine.exclude(source_ref='').count(),
    })


@login_required
def my_today(request):
    """ما يخصّني اليوم — الطابورُ الشخصيّ لكلّ الأدوار."""
    today = timezone.localdate()
    user = request.user

    assigned = scope_referrals_for(user, BookReferral.objects.filter(
        assignee=user, status__in=BookReferral.OPEN_STATUSES,
    ))

    queues = [
        {'key': 'overdue', 'label': 'متأخّر عليّ', 'tone': 'danger',
         'hint': 'مرّ موعدُه', **_queue(assigned.filter(
             purpose=BookReferral.ACTION, due_date__lt=today,
         ), user, limit=_limit_for(request, 'overdue'))},
        {'key': 'today', 'label': 'يستحقّ اليوم', 'tone': 'accent',
         'hint': 'موعدُه اليوم', **_queue(assigned.filter(
             purpose=BookReferral.ACTION, due_date=today,
         ), user, limit=_limit_for(request, 'today'))},
        {'key': 'new', 'label': 'محالٌ إليّ ولم أستلمه', 'tone': 'warn',
         'hint': 'لم أؤشّر استلامَه بعد',
         **_queue(assigned.filter(status=BookReferral.SENT), user, limit=_limit_for(request, 'new'))},
        {'key': 'action', 'label': 'مطلوبٌ ردّي', 'tone': 'muted',
         'hint': 'للتنفيذ لا للعلم',
         **_queue(assigned.filter(purpose=BookReferral.ACTION), user, limit=_limit_for(request, 'action'))},
    ]

    return render(request, 'core/my_today.html', {
        'queues': queues,
        'today': today,
        'assigned_total': assigned.count(),
        # مشتقٌّ من الطوابير نفسِها لا من عدٍّ مستقلّ: فلا يمكن أن يُخفي صفّاً
        # موجوداً (ي-4). `assigned_total` وحدَه لا يكفي حَكَماً لأنّ الطوابيرَ
        # مرشّحاتٌ متقاطعة، فقد يختلف عن مجموعها (ي-6).
        'queues_empty': not any(q.get('total') for q in queues),
    })
