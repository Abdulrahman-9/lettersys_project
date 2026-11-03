# -*- coding: utf-8 -*-
"""أرقامُ مركز الأقسام وصفحة القسم — لمدير النظام وحده.

استعلاماتٌ مجمَّعة منفصلة بلا ضربٍ بين الجداول، وعمودُ الأضبارة بالشجرة كما تفتحه
``dossier_entity_ids``: استعلامان على جدولَي الوصل وتجميعٌ بمجموعات، لأنّ جمعَ الأبناء
بالعدّ يكرّر الكتاب المذكور في وحدتين (مقيس على الإنتاج: 26 ملّي ثانية لـ15,703 كتاباً).
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.db.models import Count, Max, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from core.logging_models import UserActivityLog
from core.models import Book, Department, UserProfile
from core.views.filter_helpers import followup_q

DEFAULT_ROWS = 12
SHOW_NAMED, SHOW_ACTIVE, SHOW_LATE, SHOW_ALL = 'named', 'active', 'late', 'all'
SHOW_CHOICES = ((SHOW_ACTIVE, 'فيها نشاط'), (SHOW_LATE, 'فيها متأخّرات'),
                (SHOW_NAMED, 'مذكورة في الكتب'), (SHOW_ALL, 'الكلّ'))


def human_when(moment, now=None) -> str:
    """«اليوم 09:12» · «أمس 09:29» · «قبل يومين 08:47» · «قبل 5 أيام»."""
    if not moment:
        return ''
    now = now or timezone.localtime()
    local = timezone.localtime(moment)
    gap = (now.date() - local.date()).days
    clock = local.strftime('%H:%M')
    if gap <= 0:
        return f'اليوم {clock}'
    if gap == 1:
        return f'أمس {clock}'
    if gap == 2:
        return f'قبل يومين {clock}'
    return f'قبل {gap} أيام' if gap <= 10 else f'قبل {gap} يوماً'


def spark_bars(values):
    """ارتفاعاتُ أعمدة نشاط الأيّام السبعة، بالبكسل على مقياسٍ واحد."""
    top = max(values) or 1
    return [max(2, round(v * 26 / top)) for v in values]


def _book_mentions(live_ids):
    """لكلّ جهةٍ: مجموعةُ الكتب التي تذكرها، صادراً أو وارداً."""
    mentions = {}
    for through in (Book.issuing_entities.through, Book.receiving_entities.through):
        for book_id, entity_id in through.objects.values_list('book_id', 'entity_id'):
            if book_id in live_ids:
                mentions.setdefault(entity_id, set()).add(book_id)
    return mentions


def _activity(now):
    """نشاطُ سبعة أيّام منسوبٌ إلى قسم الفاعل، وآخرُ حركةٍ في تسعين يوماً."""
    since = now - timedelta(days=7)
    axis = [(now.date() - timedelta(days=i)) for i in range(6, -1, -1)]
    days = {}
    rows = (UserActivityLog.objects.filter(timestamp__gte=since)
            .annotate(on=TruncDate('timestamp')).values('department_id', 'on')
            .annotate(n=Sum('count')).order_by())
    for row in rows:
        days.setdefault(row['department_id'], {})[row['on']] = row['n'] or 0
    last = dict(UserActivityLog.objects.filter(timestamp__gte=now - timedelta(days=90))
                .values('department_id').annotate(at=Max('timestamp')).order_by()
                .values_list('department_id', 'at'))
    return axis, days, last


def centre_rows(now=None):
    """صفُّ كلّ وحدة بأرقام شجرتها، مرتّبةً شجريّاً. ويعيد صفَّ «بلا قسم» معها."""
    now = now or timezone.localtime()
    today = now.date()
    books = Book.objects.filter(is_training=False)
    owned = {r['department_id']: r for r in books.values('department_id').annotate(
        n=Count('id'), paper=Count('id', filter=~Q(source_ref='')),
        late=Count('id', filter=followup_q('overdue', today))).order_by()}
    mentions = _book_mentions(set(books.values_list('pk', flat=True)))
    axis, days, last = _activity(now)
    staff = {r['department_id']: r for r in UserProfile.objects.values('department_id').annotate(
        total=Count('id'), active=Count('id', filter=Q(user__is_active=True))).order_by()}
    heads = {}
    for profile in (UserProfile.objects.filter(is_department_head=True, user__is_active=True)
                    .select_related('user').order_by('id')):
        heads.setdefault(profile.department_id, profile.user.get_full_name() or profile.user.username)

    units = list(Department.objects.order_by('code'))
    by_id = {u.id: u for u in units}
    kids = {}
    for unit in units:
        kids.setdefault(unit.parent_id, []).append(unit.id)

    rows = {}

    def fill(unit_id):
        unit = by_id[unit_id]
        own = owned.get(unit_id, {})
        week = [days.get(unit_id, {}).get(day, 0) for day in axis]
        row = {
            'unit': unit, 'parent_name': by_id[unit.parent_id].name if unit.parent_id else '',
            'books': own.get('n', 0), 'paper': own.get('paper', 0), 'late': own.get('late', 0),
            'act7': sum(week), 'bars': spark_bars(week), 'last': human_when(last.get(unit_id), now),
            'staff_total': staff.get(unit_id, {}).get('total', 0),
            'staff_active': staff.get(unit_id, {}).get('active', 0),
            'head': heads.get(unit_id, ''), 'dossier_id': unit.entity_id,
        }
        seen = set(mentions.get(unit.entity_id, ())) if unit.entity_id else set()
        activity = row['act7']
        for child in kids.get(unit_id, []):
            sub, sub_seen, sub_activity = fill(child)
            row['books'] += sub['books']
            row['paper'] += sub['paper']
            row['late'] += sub['late']
            seen |= sub_seen
            activity += sub_activity
        row['dossier'] = len(seen)
        row['tree_activity'] = activity
        row['live'] = row['books'] - row['paper']
        rows[unit_id] = row
        return row, seen, activity

    for root in kids.get(None, []):
        fill(root)

    ordered = []

    def walk(unit_id, depth):
        rows[unit_id]['depth'] = depth
        ordered.append(rows[unit_id])
        for child in sorted(kids.get(unit_id, []), key=_rank(rows)):
            walk(child, depth + 1)

    for root in sorted(kids.get(None, []), key=_rank(rows)):
        walk(root, 0)

    orphan_week = [days.get(None, {}).get(day, 0) for day in axis]
    orphan = {
        'books': owned.get(None, {}).get('n', 0), 'bars': spark_bars(orphan_week),
        'act7': sum(orphan_week), 'last': human_when(last.get(None), now),
        'staff_active': User.objects.filter(is_active=True).filter(
            Q(profile__isnull=True) | Q(profile__department__isnull=True)).count(),
    }
    return ordered, orphan


def _rank(rows):
    def key(unit_id):
        row = rows[unit_id]
        return (-row['late'], -row['tree_activity'], -row['dossier'], row['unit'].name)
    return key


def _matches(row, show):
    if show == SHOW_ACTIVE:
        return row['tree_activity'] > 0
    if show == SHOW_LATE:
        return row['late'] > 0
    if show == SHOW_NAMED:
        return row['dossier'] > 0 or row['books'] > 0
    return True


def filter_rows(rows, *, show=SHOW_NAMED, query='', expanded=False):
    """الصفوفُ المعروضة وعدّادُ كلّ مرشِّح. المرشِّحُ المجهول يعود إلى الافتراض."""
    show = show if show in dict(SHOW_CHOICES) else SHOW_NAMED
    counts = {key: sum(1 for r in rows if _matches(r, key)) for key, _ in SHOW_CHOICES}
    matched = [r for r in rows if _matches(r, show)]
    query = query.strip()
    if query:
        matched = [r for r in matched if query in r['unit'].name or query in r['unit'].code]
    shown = matched if expanded or query else matched[:DEFAULT_ROWS]
    return {'rows': shown, 'matched': len(matched), 'show': show,
            'filters': [{'key': key, 'label': label, 'count': counts[key], 'on': key == show}
                        for key, label in SHOW_CHOICES]}
