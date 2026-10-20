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
from django.db.models import Q
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from core.branding import org_name
from core import numbering
from core.custody_service import undelivered
from core.forms import DeskFilterForm
from core.models import Book, BookReferral, CustodyEvent, Department, Entity
from core.scoping import (ACCESS_STUB, STUB_TITLE, can_use_desk, content_authorized_books,
                          is_privileged,
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
        scope_books_for(request.user, Book.objects.all()), filters, department, request.user,
    )

    targets = _units_with_pending(department, visible)
    courier_books = _courier_pending(department, visible)
    courier_count = courier_books.count()
    is_courier = (request.GET.get('to') or '').strip() == COURIER.pk and courier_count > 0
    chosen = COURIER if is_courier else _chosen_unit(request, targets)

    rows = []
    if is_courier:
        rows = [_courier_row(b, request.user, department)
                for b in courier_books.prefetch_related(
                    'registrations', 'receiving_entities').order_by('date', 'id')]
    elif chosen is not None:
        pending = undelivered(chosen, qs=visible).select_related(
            'book', 'to_department', 'assignee'
        ).prefetch_related('book__registrations').order_by('created_at')
        rows = [_handover_row(r, request.user, department) for r in pending]
        rows = _grouped_by_kind(rows, filters)

    context = _filter_context(request, filters)
    if chosen is not None:
        context['desk_back_url'] = '?' + context['target_query']
        context['desk_back_label'] = 'الرجوع لاختيار الجهة المستلِمة'

    return render(request, 'core/desk_handover.html', {
        'org_name': org_name(),
        'department': department,
        'department_choices': _department_choices(request),
        'targets': targets,
        'courier': COURIER,
        'courier_count': courier_count,
        'is_courier': is_courier,
        'chosen': chosen,
        'rows': rows,
        'any_restricted': any(row['restricted'] for row in rows),
        **context,
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
    register = scope_books_for(request.user, Book.objects.live()).filter(
        _in_our_register(department))
    filters = DeskFilterForm(request.GET, party_choices=_party_choices(
        department, content_authorized_books(register, request.user)))

    # §7.2 صراحةً: الحرزُ الذي كان يُبعد المنقولَ من الورق عن الدفتر **عرَضيّ**
    # (``legacy_restore`` لا يكتب ``department`` فيسقط بـ``_in_our_register``)؛
    # أوّلُ سكربتٍ يملأ ``department`` بأثرٍ رجعيّ كان سيطبع 13 ألفَ سطر.
    books = _filtered_books(register, filters, department, request.user).select_related(
        'department', 'current_custody',
    ).prefetch_related(
        'registrations__department', 'referrals__to_department', 'referrals__to_entity',
        'receiving_entities',
        'custody_events__to_holder_department', 'custody_events__to_holder_user',
    )
    rows = [_ledger_row(b, department, request.user) for b in books.order_by('date', 'id')]
    rows = _grouped_by_kind(rows, filters)

    return render(request, 'core/desk_ledger.html', {
        'org_name': org_name(),
        'department': department,
        'department_choices': _department_choices(request),
        'rows': rows,
        **_filter_context(request, filters),
    })


# ───────────────────────────── الداخليّات ─────────────────────────────

class _CourierTarget:
    """مستلِمُ الصادر الخارجيّ: متعهّدُ البريد — ليس وحدةً في الهيكل."""
    pk = 'courier'

    def __str__(self):
        return 'متعهّد البريد'


COURIER = _CourierTarget()

# اسمُ البريد في العناوين يتبع اختيارَ «نوع البريد»: الكلُّ بريد، والفرعُ باسمه.
MAIL_NOUNS = {
    '': 'البريد',
    'incoming': 'الوارد',
    'outgoing': 'الصادر',
    'incoming_internal': 'الوارد الداخلي',
    'incoming_external': 'الوارد الخارجي',
    'outgoing_internal': 'الصادر الداخلي',
    'outgoing_external': 'الصادر الخارجي',
}


def _selected_kind(filters):
    return (filters.cleaned_data.get('kind') or '') if filters.is_valid() else ''


KIND_ORDER = ('incoming_external', 'incoming_internal', 'outgoing_external', 'outgoing_internal')


def _grouped_by_kind(rows, filters):
    """البريدُ المختلط يُجمع بنوعه — صفُّ عنوانٍ لكل نوعٍ بدل وسمٍ يضاعف ارتفاعَ كلِّ سطر.

    الترتيبُ داخل النوع يبقى ترتيبَ الاستعلام (مستقرّ)، فلا تختلط سلسلتا ترقيم.
    """
    if _selected_kind(filters) in dict(Book.KIND_CHOICES):
        return rows
    return sorted(rows, key=lambda row: KIND_ORDER.index(row['kind'])
                  if row['kind'] in KIND_ORDER else len(KIND_ORDER))


def _mail_noun(filters):
    return MAIL_NOUNS.get(_selected_kind(filters), 'البريد')


def _courier_pending(department, visible):
    """صادرٌ خارجيٌّ أصدره القسمُ نفسُه ولم يُسلَّم بعدُ لمتعهّد البريد."""
    if department is None:
        return visible.none()
    delivered = CustodyEvent.objects.filter(
        event=CustodyEvent.COURIER_PICKUP).values('book_id')
    # المُصدِرُ وحدَه يُرسل: صادرُ غيرنا المقيَّدُ عندنا واردٌ في دفترنا لا التزامُ إرسال.
    return visible.filter(department_id=department.pk, kind='outgoing_external',
                          pk__in=Book.objects.live().values('pk')).exclude(pk__in=delivered)


def _courier_row(book, user, department):
    restricted = secret_access(user, book) == ACCESS_STUB
    number = _register_number(book, department)
    entities = [str(e) for e in book.receiving_entities.all()]
    return {
        'number': numbering.display(number) or '—',
        'number_year': numbering.year_tag(number),
        'kind': book.kind,
        'kind_label': book.get_kind_display(),
        'date': book.date,
        'title': STUB_TITLE if restricted else (book.title or '—'),
        'restricted': restricted,
        'purpose': '—' if restricted else (' · '.join(entities) or '—'),
        'margin': '',
        'due_date': None,
        'assignee': None,
    }


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
        'kind': book.kind,
        'kind_label': book.get_kind_display(),
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
    if not distributed and book.kind == 'outgoing_external':
        distributed = [str(e) for e in book.receiving_entities.all()]
    received = [
        '%s (%s)' % (e.holder_name, timezone.localtime(e.signed_at).strftime('%d/%m/%Y'))
        for e in book.custody_events.all()
        if e.event in (CustodyEvent.UNIT_RECEIPT, CustodyEvent.COURIER_PICKUP)
    ]

    return {
        'number': numbering.display(number) or '—',
        'number_year': numbering.year_tag(number),
        'kind': book.kind,
        'kind_label': book.get_kind_display(),
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


def _party_choices(department, register):
    """جهاتُ الدفتر للتصفية — ما ورد في دفترنا فعلاً لا الدليلُ كلُّه.

    الوحداتُ: وحداتُ القسم وكلُّ قسمٍ وُزِّع إليه كتابٌ من دفترنا. والجهاتُ: كلُّ
    جهةٍ ورد منها كتابٌ أو أُرسل إليها أو أُحيل. الجهةُ التوأمُ لوحدةٍ معروضة
    (``Department.entity``) لا تتكرّر — مطابقتُها تجري عبر الوحدة.
    """
    if department is None:
        return []
    book_ids = register.values('pk')
    unit_ids = set(BookReferral.objects.filter(
        book__in=book_ids, to_department__isnull=False).values_list('to_department_id', flat=True))
    unit_ids |= set(subtree_ids(department.pk))
    unit_ids.discard(department.pk)
    units = list(Department.objects.filter(pk__in=unit_ids).order_by('code'))

    entity_ids = set(Entity.objects.filter(issued_books__in=book_ids).values_list('pk', flat=True))
    entity_ids |= set(Entity.objects.filter(received_books__in=book_ids).values_list('pk', flat=True))
    entity_ids |= set(BookReferral.objects.filter(
        book__in=book_ids, to_entity__isnull=False).values_list('to_entity_id', flat=True))
    entity_ids -= {unit.entity_id for unit in units if unit.entity_id}
    entities = Entity.objects.filter(pk__in=entity_ids).order_by('name')

    groups = []
    if units:
        groups.append(('وحدات وأقسام داخلية', [('u:%d' % u.pk, str(u)) for u in units]))
    entity_options = [('e:%d' % e.pk, str(e)) for e in entities]
    if entity_options:
        groups.append(('جهات المراسلة', entity_options))
    return groups


def _party_q(value):
    """كتبٌ وُزِّعت إلى الجهة أو أُرسلت إليها أو وردت منها."""
    kind, _, raw = value.partition(':')
    pk = int(raw)
    if kind == 'u':
        twin = Department.objects.filter(pk=pk).values_list('entity_id', flat=True).first()
        entity_ids = [twin] if twin else []
        query = Q(pk__in=BookReferral.objects.filter(to_department_id=pk).values('book_id'))
    else:
        entity_ids = [pk]
        query = Q(pk__in=BookReferral.objects.filter(to_department__entity_id=pk).values('book_id'))
    if entity_ids:
        query |= Q(pk__in=BookReferral.objects.filter(to_entity_id__in=entity_ids).values('book_id'))
        query |= Q(pk__in=Book.objects.filter(issuing_entities__in=entity_ids).values('pk'))
        query |= Q(pk__in=Book.objects.filter(receiving_entities__in=entity_ids).values('pk'))
    return query


def _filtered_books(books, filters, department, user):
    if not filters.is_valid():
        return books.none()
    data = filters.cleaned_data
    if data.get('party'):
        # علاقاتُ السرّيّ محتوىً: تصفيتُه بجهةٍ تؤكّد مراسلاتِه لمن حُجب عنه موضوعُه.
        books = content_authorized_books(books, user).filter(_party_q(data['party']))
    if data['kind'] in ('incoming', 'outgoing'):
        books = books.filter(kind__startswith=data['kind'] + '_')
    elif data['kind']:
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
                if name == 'kind':
                    label = dict(field.choices).get(value)
                elif name == 'party':
                    label = filters.party_label(value)
                else:
                    label = filters[name].value()
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
        'mail_noun': _mail_noun(filters),
        'show_kind': _selected_kind(filters) not in dict(Book.KIND_CHOICES),
        'desk_filters': filters,
        'active_filter_labels': active,
        'target_query': target_query,
        'desk_ledger_url': reverse('desk_ledger') + ('?' + target_query if target_query else ''),
        'desk_handover_url': reverse('desk_handover') + ('?' + target_query if target_query else ''),
        'reset_filter_url': '?' + urlencode(reset),
        'date_from': request.GET.get('date_from', ''),
        'date_to': request.GET.get('date_to', ''),
    }
