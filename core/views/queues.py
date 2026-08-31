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
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone

from core.models import Book, BookReferral
from core.scoping import (ACCESS_STUB, STUB_TITLE, can_use_desk, scope_books_for,
                          scope_referrals_for, secret_access, subtree_ids,
                          user_department_id)

#: أقصى ما يُعرض في الطابور الواحد — الطابورُ لمحةٌ لا جدول.
ROW_LIMIT = 12


def _row(referral, user):
    """صفُّ طابورٍ — الموضوعُ محجوبٌ إن كان الكتابُ سرّيّاً على القارئ.

    الحجبُ هنا لا في القالب: الطابورُ يُصيَّر في صفحةٍ ويُصدَّر في أخرى،
    وقاعدةٌ في القالب تُنسى عند أوّل مستهلكٍ ثانٍ.
    """
    book = referral.book
    restricted = secret_access(user, book) == ACCESS_STUB
    return {
        'referral': referral,
        'book': book,
        'title': STUB_TITLE if restricted else (book.title or '—'),
        'restricted': restricted,
        'overdue': bool(referral.due_date and referral.due_date < timezone.localdate()),
    }


def _queue(qs, user, limit=ROW_LIMIT):
    """طابورٌ جاهزٌ للعرض: عددُه الكاملُ وصفوفُه المقطوعة.

    العدُّ **قبل** القطع — عدّادٌ يقول 12 بينما الطابورُ 80 كذبٌ مريح.
    """
    total = qs.count()
    rows = [_row(r, user) for r in qs.select_related(
        'book', 'to_department', 'from_department', 'assignee')[:limit]]
    return {'total': total, 'rows': rows, 'more': max(0, total - len(rows))}


@login_required
def desk_board(request):
    """طاولةُ الوارد — خمسةُ طوابيرَ تصف عملَ القسم اليوم."""
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
    overdue = open_here.filter(due_date__lt=today)
    due_today = open_here.filter(due_date=today)
    # «بلا ردّ» = غرضُه التنفيذ ولم يُقفَل بجوابٍ ولا موعدَ له يُطارَد به.
    no_reply = open_here.filter(purpose=BookReferral.ACTION,
                                closed_by_link__isnull=True, due_date__isnull=True)

    visible_books = scope_books_for(request.user, Book.objects.filter(is_deleted=False))
    secret_open = open_here.filter(book__in=visible_books.exclude(secret_level='normal'))

    queues = [
        {'key': 'overdue', 'label': 'متأخّر', 'tone': 'danger',
         'hint': 'مرّ موعدُه ولم يُنجَز', **_queue(overdue, request.user)},
        {'key': 'unreceived', 'label': 'غير مُستلَم', 'tone': 'warn',
         'hint': 'أُرسل ولم تُؤشَّر عهدتُه', **_queue(unreceived, request.user)},
        {'key': 'today', 'label': 'يستحقّ اليوم', 'tone': 'accent',
         'hint': 'موعدُه اليوم', **_queue(due_today, request.user)},
        {'key': 'no_reply', 'label': 'بلا ردّ', 'tone': 'muted',
         'hint': 'للتنفيذ وبلا جوابٍ ولا موعد', **_queue(no_reply, request.user)},
        {'key': 'secret', 'label': 'سرّي مفتوح', 'tone': 'secret',
         'hint': 'التزامٌ قائمٌ على كتابٍ مقيَّد', **_queue(secret_open, request.user)},
    ]

    return render(request, 'core/desk_board.html', {
        'queues': queues,
        'today': today,
        'department_id': dept_id,
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
         'hint': 'مرّ موعدُه', **_queue(assigned.filter(due_date__lt=today), user)},
        {'key': 'today', 'label': 'يستحقّ اليوم', 'tone': 'accent',
         'hint': 'موعدُه اليوم', **_queue(assigned.filter(due_date=today), user)},
        {'key': 'new', 'label': 'محالٌ إليّ ولم أستلمه', 'tone': 'warn',
         'hint': 'لم أؤشّر استلامَه بعد',
         **_queue(assigned.filter(status=BookReferral.SENT), user)},
        {'key': 'action', 'label': 'مطلوبٌ ردّي', 'tone': 'muted',
         'hint': 'للتنفيذ لا للعلم',
         **_queue(assigned.filter(purpose=BookReferral.ACTION), user)},
    ]

    return render(request, 'core/my_today.html', {
        'queues': queues,
        'today': today,
        'assigned_total': assigned.count(),
    })
