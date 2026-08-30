# -*- coding: utf-8 -*-
"""
سجلُّ الحركات — «مَن رأى، مَن شاهد، مَن استلم، مَن فرّق، مَن عدّل، مَن حذف».

**تبويبان لا خطٌّ زمنيٌّ مدموج:** «حركات الكتب» من ``BookHistory`` (سجلُّ
الأعمال، مكتوبٌ منذ سنواتٍ وأضفنا إليه أفعالَ التسيير) و«نشاط المستخدمين» من
``UserActivityLog`` (القراءةُ والإخراج). دمجُ ترقيمِ الصفحات عبر جدولين تعقيدٌ
بلا قيمة، والسؤالان مختلفان أصلاً.

**والسجلُّ نفسُه سطحُ محتوى** — درسُ تصدير CSV حرفيّاً: صفٌّ يشير إلى كتابٍ
سرّيٍّ لا يملك القارئُ محتواه يجب أن يظهر بعنوانٍ محجوب، وإلّا صار سجلُّ
التدقيق بابَ تسريبٍ خلفيّاً للعناوين.
"""

from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.shortcuts import render

from core.logging_models import UserActivityLog
from core.models import BookHistory, Department
from core.scoping import (ACCESS_STUB, STUB_TITLE, can_view_audit, is_privileged,
                          scope_activity_for, secret_access, subtree_ids,
                          user_department_id)

PER_PAGE = 40

#: التبويبان — ولكلٍّ مصدرُه وأعمدتُه.
TAB_BOOKS = 'books'
TAB_USERS = 'users'


@login_required
def audit_log(request):
    """شاشةُ السجلّ — رئيسُ القسم يرى شجرتَه، والسوبر أدمن يرى الكلّ."""
    if not can_view_audit(request.user):
        raise PermissionDenied('سجلُّ الحركات لرئيس القسم ومدير النظام.')

    # مَن يراقب المراقبين: فتحُ السجلّ نفسُه واقعةٌ مسجَّلة
    from core.audit_service import record_event
    record_event(request, 'VIEW_AUDIT_LOG')

    tab = TAB_USERS if request.GET.get('tab') == TAB_USERS else TAB_BOOKS
    date_from, date_to = _date_range(request)
    actor = (request.GET.get('actor') or '').strip()
    action = (request.GET.get('action') or '').strip()

    if tab == TAB_USERS:
        rows, actions = _user_activity(request, date_from, date_to, actor, action)
    else:
        rows, actions = _book_history(request, date_from, date_to, actor, action)

    page = _paginate(rows, request.GET.get('page'))

    return render(request, 'core/audit_log.html', {
        'tab': tab,
        'page_obj': page,
        'rows': [_present(row, request.user, tab) for row in page.object_list],
        'actions': actions,
        'departments': _visible_departments(request.user),
        'filters': {
            'actor': actor, 'action': action,
            'date_from': request.GET.get('date_from', ''),
            'date_to': request.GET.get('date_to', ''),
        },
        # صدقُ الواجهة: لا سجلَّ لما قبل التفعيل — ولا يُختلق واحد.
        'first_record': _first_record(tab),
    })


# ───────────────────────────── المصدران ─────────────────────────────

def _book_history(request, date_from, date_to, actor, action):
    """أفعالُ العمل: إنشاءٌ وتعديلٌ وحذفٌ وتفريقٌ وعهدةٌ وقيدٌ وربط."""
    from core.scoping import scope_books_for
    from core.models import Book

    books = scope_books_for(request.user, Book.all_objects.all())
    rows = (BookHistory.objects
            .filter(book__in=books)
            .select_related('by', 'book', 'book__department'))

    if actor:
        rows = rows.filter(by__username__icontains=actor)
    if action:
        rows = rows.filter(action=action)
    if date_from:
        rows = rows.filter(created_at__date__gte=date_from)
    if date_to:
        rows = rows.filter(created_at__date__lte=date_to)

    return rows.order_by('-created_at'), BookHistory.ACTION_CHOICES


def _user_activity(request, date_from, date_to, actor, action):
    """القراءةُ والإخراج — أداةُ المساءلة، وبوّابتُها أضيق."""
    rows = scope_activity_for(request.user).select_related(
        'user', 'book', 'book__department', 'department')

    if actor:
        rows = rows.filter(username_snapshot__icontains=actor)
    if action:
        rows = rows.filter(action=action)
    if date_from:
        rows = rows.filter(timestamp__date__gte=date_from)
    if date_to:
        rows = rows.filter(timestamp__date__lte=date_to)

    return rows.order_by('-timestamp'), UserActivityLog.ACTION_CHOICES


# ───────────────────────────── العرض ─────────────────────────────

def _present(row, user, tab):
    """صفٌّ معروضٌ — **وعنوانُ الكتاب السرّيّ يُحجب هنا كما يُحجب في القائمة**."""
    book = row.book
    restricted = bool(book) and secret_access(user, book) == ACCESS_STUB

    if tab == TAB_USERS:
        who = row.user.get_full_name() if row.user_id else ''
        return {
            'when': row.timestamp,
            'who': who or row.username_snapshot or '—',
            'department': row.department.name if row.department_id else '',
            'action': row.get_action_display(),
            'book_id': None if restricted else (book.pk if book else None),
            'book_number': book.our_number_display if book else '',
            'book_title': (STUB_TITLE if restricted else book.title) if book else '',
            'count': row.count,
            'ip': row.ip_address or '',
            'note': '',
        }

    who = (row.by.get_full_name() if row.by_id else '') or row.by_snapshot
    return {
        'when': row.created_at,
        'who': who or '—',
        'department': book.department.name if book and book.department_id else '',
        'action': row.get_action_display(),
        'book_id': None if restricted else book.pk,
        'book_number': book.our_number_display,
        'book_title': STUB_TITLE if restricted else book.title,
        'count': 1,
        'ip': '',
        'note': '' if restricted else (row.notes or ''),
    }


def _visible_departments(user):
    if is_privileged(user):
        return Department.objects.filter(is_active=True).order_by('code')
    return Department.objects.filter(pk__in=subtree_ids(user_department_id(user)))


def _first_record(tab):
    """أوّلُ صفٍّ في السجلّ — تعلنه الواجهةُ صراحةً.

    13,193 كتاباً سبقت التفعيل، ولوحةُ «مَن رأى» ستقول «لا أحد» عنها. قولُ ذلك
    صراحةً صدق؛ والسكوتُ عنه يجعل الواجهةَ تكذب كما كذب ``created_at`` المستورد.
    """
    model = UserActivityLog if tab == TAB_USERS else BookHistory
    field = 'timestamp' if tab == TAB_USERS else 'created_at'
    row = model.objects.order_by(field).values_list(field, flat=True).first()
    return row


def _paginate(rows, page_number):
    paginator = Paginator(rows, PER_PAGE)
    try:
        return paginator.page(page_number or 1)
    except (PageNotAnInteger, EmptyPage):
        return paginator.page(1)


def _date_range(request):
    def parse(key):
        raw = (request.GET.get(key) or '').strip()
        try:
            return datetime.strptime(raw, '%Y-%m-%d').date() if raw else None
        except (ValueError, TypeError):
            return None

    return parse('date_from'), parse('date_to')
