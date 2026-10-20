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

from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from core.branding import org_name
from core import numbering
from core.custody_service import undelivered
from core.forms import DeskFilterForm
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
    filters = DeskFilterForm(request.GET)
    visible = _filtered_books(
        scope_books_for(request.user, Book.objects.all()), filters, department,
    )

    targets = _units_with_pending(department, visible)
    chosen = _chosen_unit(request, targets)

    rows = []
    if chosen is not None:
        pending = undelivered(chosen, qs=visible).select_related(
            'book', 'to_department', 'assignee'
        ).prefetch_related('book__registrations').order_by('created_at')
        rows = [_handover_row(r, request.user, department) for r in pending]

    return render(request, 'core/desk_handover.html', {
        'org_name': org_name(),
        'department': department,
        'department_choices': _department_choices(request),
        'targets': targets,
        'chosen': chosen,
        'rows': rows,
        'any_restricted': any(row['restricted'] for row in rows),
        **_filter_context(request, filters),
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
    filters = DeskFilterForm(request.GET)

    # §7.2 صراحةً: الحرزُ الذي كان يُبعد المنقولَ من الورق عن الدفتر **عرَضيّ**
    # (``legacy_restore`` لا يكتب ``department`` فيسقط بـ``_in_our_register``)؛
    # أوّلُ سكربتٍ يملأ ``department`` بأثرٍ رجعيّ كان سيطبع 13 ألفَ سطر.
    visible = _filtered_books(
        scope_books_for(request.user, Book.objects.live()), filters, department,
    )
    books = visible.filter(
        _in_our_register(department)
    ).select_related('department', 'current_custody').prefetch_related(
        'registrations__department', 'referrals__to_department', 'referrals__to_entity',
        'custody_events__to_holder_department', 'custody_events__to_holder_user',
    )
    rows = [_ledger_row(b, department, request.user) for b in books.order_by('date', 'id')]

    return render(request, 'core/desk_ledger.html', {
        'org_name': org_name(),
        'department': department,
        'department_choices': _department_choices(request),
        'rows': rows,
        **_filter_context(request, filters),
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


def _department_choices(request):
    """منتقي القسم لمدير النظام وحدَه — كان ``?department=`` مقروءاً بلا حقلٍ يضبطه، فيرى
    المديرُ بلا قسمٍ ورقةً فارغةً تلوم «المدّة» (تدقيقُ نيلسن D#11). ``None`` لغيره."""
    if not is_privileged(request.user):
        return None
    return list(Department.objects.filter(is_active=True).order_by('name'))


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


def _handover_row(referral, user, department):
    """صفٌّ في الكشف — والموضوعُ محجوبٌ إن كان الكتابُ سرّيّاً على القارئ."""
    book = referral.book
    restricted = secret_access(user, book) == ACCESS_STUB
    number = _register_number(book, department)
    return {
        'number': numbering.display(number) or '—',
        'number_year': numbering.year_tag(number),
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

    number = _register_number(book, department)

    distributed = [r.target_name for r in book.referrals.all()]
    received = [
        '%s (%s)' % (e.holder_name, timezone.localtime(e.signed_at).strftime('%d/%m/%Y'))
        for e in book.custody_events.all() if e.event == CustodyEvent.UNIT_RECEIPT
    ]

    return {
        'number': numbering.display(number) or '—',
        'number_year': numbering.year_tag(number),
        'date': book.date,
        'title': STUB_TITLE if restricted else (book.title or '—'),
        'restricted': restricted,
        'distributed': '—' if restricted else (' · '.join(distributed) or '—'),
        'received': '—' if restricted else (' · '.join(received) or '—'),
        'book_id': book.pk,
    }


def _register_number(book, department):
    if department is None:
        return ''
    ours = next((r for r in book.registrations.all()
                 if r.department_id == department.pk), None)
    if ours:
        return ours.number
    return book.our_number if book.department_id == department.pk else ''


def _filtered_books(books, filters, department):
    if not filters.is_valid():
        return books.none()
    data = filters.cleaned_data
    if data['kind']:
        books = books.filter(kind=data['kind'])
    if data['date_from']:
        books = books.filter(date__gte=data['date_from'])
    if data['date_to']:
        books = books.filter(date__lte=data['date_to'])
    lower, upper = data['number_from'], data['number_to']
    if lower or upper:
        bound = lower or upper
        matches = []
        candidates = books.only('pk', 'department_id', 'our_number').prefetch_related(
            'registrations',
        )
        for book in candidates.iterator(chunk_size=256):
            parsed = numbering.parse(_register_number(book, department))
            if (parsed.is_official and parsed.year == bound.year
                    and (lower is None or parsed.seq >= lower.seq)
                    and (upper is None or parsed.seq <= upper.seq)):
                matches.append(book.pk)
        books = books.filter(pk__in=matches)
    return books


def _filter_context(request, filters):
    active = []
    if filters.is_valid():
        for name, field in filters.fields.items():
            value = filters.cleaned_data.get(name)
            if value:
                label = dict(field.choices).get(value) if name == 'kind' else filters[name].value()
                active.append('%s: %s' % (field.label, label))
    first_error = True
    for name in filters.errors:
        if name in filters.fields:
            attrs = filters.fields[name].widget.attrs
            attrs['aria-invalid'] = 'true'
            attrs['aria-describedby'] = filters[name].auto_id + '-errors'
            if first_error:
                attrs['autofocus'] = True
                first_error = False
    query = request.GET.copy()
    query.pop('to', None)
    target_query = query.urlencode()
    reset = {}
    for key in ('department', 'to'):
        if request.GET.get(key):
            reset[key] = request.GET[key]
    return {
        'desk_filters': filters,
        'active_filter_labels': active,
        'target_query': target_query,
        'desk_ledger_url': reverse('desk_ledger') + ('?' + target_query if target_query else ''),
        'desk_handover_url': reverse('desk_handover') + ('?' + target_query if target_query else ''),
        'reset_filter_url': '?' + urlencode(reset),
        'date_from': request.GET.get('date_from', ''),
        'date_to': request.GET.get('date_to', ''),
    }
