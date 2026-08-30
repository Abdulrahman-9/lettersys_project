# -*- coding: utf-8 -*-
"""
طاولةُ البريد — الورقتان اللتان يطلبهما الكاتبُ ليترك دفترَه.

**كشفُ التسليم** ورقةُ توقيعٍ تُطبع وتُرتجع موقَّعة: ما فُرِّق إلى وحدةٍ ولم
تُسجَّل له عهدةٌ عندها. و**دفترُ الوارد المطبوع** بأعمدة الكاتب الخمسة حرفيّاً
(الرقم · التاريخ · الموضوع · إلى مَن وُزِّع · مَن استلم) — وهو **جسرُ الثقة**:
ورقةٌ يقارنها بدفتره فيرى أنّ النظام يقول ما يقوله دفترُه ثمّ يتركه.

النطاقُ في الاستعلام كالعادة: كلُّ ما تعرضه هاتان الصفحتان يمرّ من
``scope_books_for``، والسرّيُّ يظهر برقمه وتاريخه ويُحجب موضوعُه — **الكشفُ
المطبوع يخرج من الجهاز، فهو أخطرُ من الشاشة لا أقلّ**.
"""

from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render

from core.custody_service import undelivered
from core.models import Book, BookReferral, CustodyEvent, Department
from core.scoping import (ACCESS_STUB, STUB_TITLE, can_use_desk, is_privileged,
                          scope_books_for, secret_access, subtree_ids,
                          user_department_id)


@login_required
def desk_handover(request):
    """كشفُ التسليم — ورقةُ توقيعٍ لوحدةٍ بعينها.

    ``?to=<department_id>`` يختار الوحدة؛ وبلا اختيارٍ تُعرض قائمةُ الوحدات
    التي عليها التزاماتٌ غيرُ موقَّعة كي لا يبدأ الكاتبُ من فراغ.
    """
    department = _acting_department(request)
    visible = scope_books_for(request.user, Book.objects.filter(is_deleted=False))

    targets = _units_with_pending(department, visible)
    chosen = _chosen_unit(request, targets)

    rows = []
    if chosen is not None:
        pending = undelivered(chosen, qs=visible).select_related(
            'book', 'to_department', 'assignee'
        ).order_by('created_at')
        rows = [_handover_row(r, request.user) for r in pending]

    return render(request, 'core/desk_handover.html', {
        'department': department,
        'targets': targets,
        'chosen': chosen,
        'rows': rows,
    })


@login_required
def desk_ledger(request):
    """دفترُ الوارد المطبوع — أعمدةُ الكاتب الخمسة.

    يجمع مصدرَي الرقم في دفترٍ واحد: كتبٌ يملكها القسمُ (رقمُها ``our_number``)
    وكتبٌ يملكها غيرُه وقُيّدت عندنا (رقمُها في ``BookRegistration``). كلاهما
    **قيدٌ في دفترنا** — وفصلُهما في ورقتين يُنتج دفترين لا يطابقان الواحدَ
    الذي على الطاولة.
    """
    department = _acting_department(request)
    date_from, date_to = _date_range(request)

    visible = scope_books_for(request.user, Book.objects.filter(is_deleted=False))
    books = visible.filter(
        _in_our_register(department)
    ).select_related('department', 'current_custody').prefetch_related(
        'registrations__department', 'referrals__to_department', 'referrals__to_entity',
        'custody_events__to_holder_department', 'custody_events__to_holder_user',
    )
    if date_from:
        books = books.filter(date__gte=date_from)
    if date_to:
        books = books.filter(date__lte=date_to)

    rows = [_ledger_row(b, department, request.user) for b in books.order_by('date', 'id')]

    return render(request, 'core/desk_ledger.html', {
        'department': department,
        'rows': rows,
        'date_from': request.GET.get('date_from', ''),
        'date_to': request.GET.get('date_to', ''),
    })


# ───────────────────────────── الداخليّات ─────────────────────────────

def _acting_department(request):
    """القسمُ الذي تُطبع طاولتُه — قسمُ المستخدم، ومديرُ النظام يختار.

    يرفع ``PermissionDenied`` لمن ليس مختصَّ بريدٍ ولا رئيسَ قسم: الكشفُ
    والدفترُ يُظهران خريطةَ عملِ القسم كاملةً في ورقةٍ تخرج من الجهاز.
    """
    if not can_use_desk(request.user):
        raise PermissionDenied('طاولةُ البريد لمختصّ البريد ورئيس القسم.')

    if is_privileged(request.user):
        wanted = (request.GET.get('department') or '').strip()
        if wanted.isdigit():
            return Department.objects.filter(pk=int(wanted)).first()

    dept_id = user_department_id(request.user)
    return Department.objects.filter(pk=dept_id).first() if dept_id else None


def _units_with_pending(department, visible):
    """الوحداتُ التي عليها التزاماتٌ غيرُ موقَّعة — نقطةُ بدءِ الكاتب."""
    if department is None:
        return []

    mine = subtree_ids(department.pk)
    signed = CustodyEvent.objects.filter(
        event=CustodyEvent.UNIT_RECEIPT
    ).values('book_id', 'to_holder_department_id')
    signed_pairs = {(row['book_id'], row['to_holder_department_id']) for row in signed}

    pending = BookReferral.objects.filter(
        from_department_id__in=mine, to_department__isnull=False,
        status__in=BookReferral.OPEN_STATUSES, book__in=visible,
    ).select_related('to_department')

    counts = {}
    for row in pending:
        if (row.book_id, row.to_department_id) in signed_pairs:
            continue
        entry = counts.setdefault(row.to_department, 0)
        counts[row.to_department] = entry + 1
    return sorted(counts.items(), key=lambda pair: str(pair[0]))


def _chosen_unit(request, targets):
    wanted = (request.GET.get('to') or '').strip()
    if not wanted.isdigit():
        return None
    return next((unit for unit, _ in targets if unit.pk == int(wanted)), None)


def _handover_row(referral, user):
    """صفٌّ في الكشف — والموضوعُ محجوبٌ إن كان الكتابُ سرّيّاً على القارئ."""
    book = referral.book
    restricted = secret_access(user, book) == ACCESS_STUB
    return {
        'number': book.our_number_display or '—',
        'date': book.date,
        'title': STUB_TITLE if restricted else (book.title or '—'),
        'restricted': restricted,
        'purpose': referral.get_purpose_display(),
        'margin': '' if restricted else referral.margin,
        'due_date': referral.due_date,
        'assignee': referral.assignee,
    }


def _in_our_register(department):
    """شرطُ «هذا الكتابُ في دفترنا»: نملكه أو قُيّد عندنا."""
    from django.db.models import Q

    from core.models import BookRegistration

    if department is None:
        return Q(pk__in=[])
    return (Q(department_id=department.pk)
            | Q(pk__in=BookRegistration.objects.filter(
                department=department).values('book_id')))


def _ledger_row(book, department, user):
    """أعمدةُ الكاتب الخمسة — والرقمُ رقمُ **دفترنا** لا رقمُ صاحبه."""
    restricted = secret_access(user, book) == ACCESS_STUB

    ours = next((r for r in book.registrations.all()
                 if r.department_id == department.pk), None)
    number = ours.number if ours else (book.our_number_display or '')

    distributed = [r.target_name for r in book.referrals.all()]
    received = [
        '%s (%s)' % (e.holder_name, e.signed_at.strftime('%Y/%m/%d'))
        for e in book.custody_events.all() if e.event == CustodyEvent.UNIT_RECEIPT
    ]

    return {
        'number': number or '—',
        'date': book.date,
        'title': STUB_TITLE if restricted else (book.title or '—'),
        'restricted': restricted,
        'distributed': '—' if restricted else (' · '.join(distributed) or '—'),
        'received': '—' if restricted else (' · '.join(received) or '—'),
        'book_id': book.pk,
    }


def _date_range(request):
    def parse(key):
        raw = (request.GET.get(key) or '').strip()
        try:
            return datetime.strptime(raw, '%Y-%m-%d').date() if raw else None
        except (ValueError, TypeError):
            return None

    return parse('date_from'), parse('date_to')
