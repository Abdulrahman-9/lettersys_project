# -*- coding: utf-8 -*-
"""أقسامُ لوحة التحكّم — **لكلّ دورٍ لوحتُه، ومصدرُ القسمة واحد**.

لوحةٌ واحدةٌ للجميع تعني أنّ موظّفَ الوحدة يرى عدّاداتِ قسمٍ لا يملكه، وأنّ
مختصَّ البريد يبحث عن طابوره بين إحصاءاتٍ لا تخصّه. فالقسمةُ هنا:

- **مسجّلٌ واحدٌ للأقسام** (`SECTIONS`): لكلّ قسمٍ مفتاحٌ وعنوانٌ وبوّابةٌ
  وبانٍ. إضافةُ قسمٍ جديد سطرٌ واحدٌ في مكانٍ واحد.
- **البوّابةُ دالّةٌ لا قائمةُ أدوار**: «مَن يفتح طاولةَ الوارد» سؤالٌ أُجيب
  عنه مرّةً في `core/scoping.py` (`can_use_desk`)، ولا يُعاد هنا بصياغةٍ
  ثانيةٍ تنحرف عنه. وهذا هو الدرسُ الذي كلّف هذه الدفعةَ ثلاثَ مرّات.
- **البانِي كسولٌ**: لا يُستدعى إلّا لمن يملك القسمَ — فلوحةُ الموظّف العاديّ
  لا تدفع ثمنَ استعلاماتِ لوحة المدير.

**والأدوارُ الثلاثةُ التي سمّاها المالك** تنعكس هنا كتركيباتٍ من الأقسام:
موظّفُ الشعبة/الوحدة · مسؤولُ البريد والأرشفة · رئيسُ القسم. ولا دورَ رابعاً
مخفيّاً: ما يراه كلٌّ منهم هو حاصلُ بوّاباتِه لا قائمةً مكتوبةً بيدٍ ثالثة.
"""

from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone


# ═══════════════════════════ البنائيّات ═══════════════════════════

def _my_queue(user):
    """ما يخصّني أنا — الالتزاماتُ المفتوحةُ باسمي."""
    from core.models import BookReferral
    from core.scoping import scope_referrals_for

    today = timezone.localdate()
    mine = scope_referrals_for(user, BookReferral.objects.filter(
        assignee=user, status__in=BookReferral.OPEN_STATUSES))

    counts = mine.aggregate(
        total=Count('id'),
        overdue=Count('id', filter=Q(due_date__lt=today)),
        today=Count('id', filter=Q(due_date=today)),
        unreceived=Count('id', filter=Q(status=BookReferral.SENT)),
    )
    return {
        'counters': [
            {'label': 'متأخّر عليّ', 'value': counts['overdue'], 'tone': 'danger',
             'href': '/books/my/today/'},
            {'label': 'يستحقّ اليوم', 'value': counts['today'], 'tone': 'accent',
             'href': '/books/my/today/'},
            {'label': 'لم أستلمه', 'value': counts['unreceived'], 'tone': 'warn',
             'href': '/books/my/today/'},
            {'label': 'كلُّ التزاماتي', 'value': counts['total'], 'tone': 'calm',
             'href': '/books/my/today/'},
        ],
        'empty': not counts['total'],
    }


def _desk(user):
    """طاولةُ الوارد — عملُ القسم اليوم، لمن يمسك بريدَه."""
    from core.models import Book, BookReferral
    from core.scoping import (scope_books_for, scope_referrals_for,
                              subtree_ids, user_department_id)

    today = timezone.localdate()
    dept_id = user_department_id(user)
    mine = subtree_ids(dept_id) if dept_id else []

    rows = scope_referrals_for(user, BookReferral.objects.filter(
        status__in=BookReferral.OPEN_STATUSES))
    if mine:
        rows = rows.filter(Q(to_department_id__in=mine) | Q(from_department_id__in=mine))

    counts = rows.aggregate(
        overdue=Count('id', filter=Q(due_date__lt=today)),
        today=Count('id', filter=Q(due_date=today)),
        unreceived=Count('id', filter=Q(status=BookReferral.SENT)),
    )
    secret_open = rows.filter(book__in=scope_books_for(
        user, Book.objects.filter(is_deleted=False)).exclude(secret_level='normal')).count()

    return {
        'counters': [
            {'label': 'متأخّر', 'value': counts['overdue'], 'tone': 'danger',
             'href': '/books/desk/'},
            {'label': 'غير مُستلَم', 'value': counts['unreceived'], 'tone': 'warn',
             'href': '/books/desk/'},
            {'label': 'يستحقّ اليوم', 'value': counts['today'], 'tone': 'accent',
             'href': '/books/desk/'},
            {'label': 'سرّي مفتوح', 'value': secret_open, 'tone': 'secret',
             'href': '/books/desk/'},
        ],
        'links': [
            {'label': 'طاولة الوارد', 'href': '/books/desk/', 'icon': 'bi-inboxes'},
            {'label': 'دفتر الوارد', 'href': '/books/desk/ledger/', 'icon': 'bi-journal-text'},
            {'label': 'كشف التسليم', 'href': '/books/desk/handover/', 'icon': 'bi-pen'},
        ],
    }


def _register(user):
    """دفترُ القسم — حجمُ العمل ومساره، لمن يملك دفتراً."""
    from core.models import Book
    from core.scoping import scope_books_for

    today = timezone.localdate()
    books = scope_books_for(user, Book.objects.filter(is_deleted=False))
    active = Q(is_archived=False, due_date__isnull=False)

    counts = books.aggregate(
        total=Count('id'),
        today=Count('id', filter=Q(date=today)),
        week=Count('id', filter=Q(date__gte=today - timedelta(days=7))),
        overdue=Count('id', filter=active & Q(due_date__lt=today)),
    )
    return {
        'counters': [
            {'label': 'كتبُ اليوم', 'value': counts['today'], 'tone': 'accent',
             'href': '/books/?tab=today'},
            {'label': 'هذا الأسبوع', 'value': counts['week'], 'tone': 'calm',
             'href': '/books/'},
            {'label': 'متأخّر', 'value': counts['overdue'], 'tone': 'danger',
             'href': '/books/?tab=overdue'},
            {'label': 'كلُّ الدفتر', 'value': counts['total'], 'tone': 'calm',
             'href': '/books/'},
        ],
    }


def _dossier(user):
    """أضبارتي — ما ذُكر فيه اسمُ وحدتي صادراً أو وارداً."""
    from core.models import Department, Entity
    from core.scoping import user_department_id

    dept_id = user_department_id(user)
    department = Department.objects.filter(pk=dept_id).select_related('entity').first()
    if department is None or department.entity_id is None:
        # وحدةٌ بلا توأمِ جهةٍ لا اسمَ لها يُذكَر — فلا أضبارة. صحيحٌ لا نقص.
        return None

    entity = department.entity
    from core.models import Book
    issued = Book.objects.filter(is_deleted=False, issuing_entities=entity).count()
    received = Book.objects.filter(is_deleted=False, receiving_entities=entity).count()

    return {
        'counters': [
            {'label': 'وارد إلينا', 'value': received, 'tone': 'accent',
             'href': '/books/dossiers/%d/' % entity.pk},
            {'label': 'صادر منّا', 'value': issued, 'tone': 'calm',
             'href': '/books/dossiers/%d/' % entity.pk},
        ],
        'note': 'أضبارةُ «%s» — يتدفّق إليها الكتابُ من ذكر اسمها في الصادر والوارد.'
                % department.name,
    }


def _mail(user):
    """البريدُ الإلكترونيّ — لمن يُرسله ويتابعه."""
    # التوقيعُ `(qs, user)` لا العكس — ونطاقُ البريد مصدرُه `messaging.scoping`
    # وحده، فلا تُعاد كتابةُ قاعدةِ «مَن يرى أيَّ بريد» هنا.
    from core.messaging.scoping import scope_incoming, scope_sent_logs
    from core.models import BookEmailLog, IncomingEmail

    unread = scope_incoming(IncomingEmail.objects.filter(is_read=False), user).count()
    failed = scope_sent_logs(BookEmailLog.objects.filter(status='failed'), user).count()

    return {
        'counters': [
            {'label': 'غير مقروء', 'value': unread, 'tone': 'accent', 'href': '/books/mail/inbox/'},
            {'label': 'إرسالٌ أخفق', 'value': failed, 'tone': 'danger', 'href': '/books/mail/'},
        ],
        'links': [{'label': 'مركز البريد', 'href': '/books/mail/', 'icon': 'bi-envelope'}],
    }


def _administration(user):
    """الإدارة — الشجرةُ والناسُ والعناقيد."""
    from core.models import Department, Entity, EntityGroup
    from django.contrib.auth.models import User

    return {
        'counters': [
            {'label': 'أقسام', 'value': Department.objects.filter(is_active=True).count(),
             'tone': 'calm', 'href': '/books/admin/?tab=departments'},
            {'label': 'مستخدمون', 'value': User.objects.filter(is_active=True).count(),
             'tone': 'calm', 'href': '/books/admin/?tab=users'},
            {'label': 'جهات', 'value': Entity.objects.filter(is_active=True).count(),
             'tone': 'calm', 'href': '/books/entities/'},
            {'label': 'عناقيد', 'value': EntityGroup.objects.filter(is_active=True).count(),
             'tone': 'accent', 'href': '/books/entities/?view=groups'},
        ],
        'links': [
            {'label': 'لوحة الإدارة', 'href': '/books/admin/', 'icon': 'bi-sliders'},
            {'label': 'سجلّ الحركات', 'href': '/books/audit/', 'icon': 'bi-clock-history'},
        ],
    }


# ═══════════════════════════ المسجّل ═══════════════════════════

def _always(user):
    return True


def _can_desk(user):
    from core.scoping import can_use_desk
    return can_use_desk(user)


def _has_register(user):
    """يملك دفتراً: مَن له قسمٌ — أو مديرُ النظام الذي يرى الكلّ."""
    from core.scoping import is_privileged, user_department_id
    return is_privileged(user) or user_department_id(user) is not None


def _can_mail(user):
    from core.scoping import is_mail_officer, is_privileged
    return is_privileged(user) or is_mail_officer(user)


def _can_admin(user):
    from core.scoping import is_privileged
    return is_privileged(user)


#: (المفتاح · العنوان · الشرح · البوّابة · البانِي) — والترتيبُ ترتيبُ العرض:
#: **ما يخصّني أوّلاً** لأنّه ما يفتحه الموظّفُ صباحاً، ثمّ ما يتّسع دائرةً.
SECTIONS = (
    ('mine', 'ما يخصّني اليوم', 'التزاماتي المفتوحة باسمي', _always, _my_queue),
    ('desk', 'طاولة الوارد', 'عملُ القسم اليوم', _can_desk, _desk),
    ('dossier', 'أضبارة وحدتي', 'ما ذُكر فيه اسمُنا', _always, _dossier),
    ('register', 'دفتر القسم', 'حجمُ العمل ومساره', _has_register, _register),
    ('mail', 'البريد الإلكتروني', 'ما وصل وما أخفق', _can_mail, _mail),
    ('admin', 'الإدارة', 'الشجرةُ والناسُ والعناقيد', _can_admin, _administration),
)


def sections_for(user):
    """أقسامُ لوحة هذا المستخدم — مبنيّةً وجاهزةً للعرض.

    القسمُ الذي يُعيد بانيه ``None`` **يُسقَط**: «لا أضبارةَ لوحدةٍ بلا توأم»
    حالةٌ صحيحةٌ لا خطأ، وعرضُ صندوقٍ فارغٍ عليها ضجيجٌ يُعلّم المستخدمَ أن
    يتجاهل اللوحة.
    """
    built = []
    for key, title, hint, gate, builder in SECTIONS:
        if not gate(user):
            continue
        data = builder(user)
        if data is None:
            continue
        built.append({'key': key, 'title': title, 'hint': hint, **data})
    return built
