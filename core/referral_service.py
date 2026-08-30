# -*- coding: utf-8 -*-
"""
عمودُ التسيير — **مسارُ الكتابة الوحيد** إلى ``BookReferral``.

شهادةُ موظّف البريد: «نمسك الكتاب نذهب به للمدير ويكتب إمّا هامشَ الاطّلاع
والحفظ أو إجابةً مباشرةً بالهامش أو **التوجيهَ للوحدات بأوامر مداولة أو إعدادِ
مذكّراتٍ حسب اختصاص كلّ وحدة**». فالتفريقُ فعلٌ يوميٌّ لا استثناء، وكلُّ قفزةٍ
فيه لها توجيهُها ومدّتُها ومَن يتابعها.

**ما يكتبه ``distribute`` في نَفَسٍ واحد:** صفوفَ الإحالة · إسقاطَ M2M للوارد
(كي لا يعمى دفترُ «إلى مَن وُزِّع» القائم) · حدثاً واحداً في تاريخ الكتاب ·
وإشعاراً لكلّ موظّفٍ في الوحدة المستقبِلة — «حساب الوحدة يجمع التنبيهات لكلّ
موظّفيه بشفافيّة» بأمر المالك.

**ممنوعٌ منعاً باتّاً خارج هذه الدوالّ:** كتابةُ ``status`` أو ``closed_by_link``
أو M2M التفريق. صفٌّ يُكتب على جنبٍ يُخلّف التزاماً لا يطارده أحد — وهو تماماً
ما نبني هذا العمود لمنعه.
"""

import logging

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

logger = logging.getLogger(__name__)


def distribute(book, targets, *, purpose=None, margin='', margin_crop=None,
               due_date=None, assignee=None, by, allow_repeat=False):
    """يُفرّق كتاباً على وحداتٍ/أقسامٍ أو جهاتٍ خارجيّة، ويُنشئ التزاماً لكلٍّ منها.

    ``targets`` عناصرُها إمّا كائنُ ``Department``/``Entity``، وإمّا قاموسٌ
    ``{'target': obj, ...}`` يحمل ما يخصّ هذا الهدف وحده — لأنّ التوجيهَ يختلف
    باختلاف اختصاص الوحدة، وتوحيدُه قسراً يُفقد الهامشَ معناه.

    يرفع ``PermissionDenied`` إن لم يملك ``by`` محتوى الكتاب، و``ValidationError``
    على هدفٍ مجهولِ النوع أو تفريقٍ مكرَّرٍ فوق التزامٍ ما زال مفتوحاً.
    """
    from core.models import BookReferral, Department, Entity
    from core.scoping import can_open_content

    if not can_open_content(book, by):
        raise PermissionDenied('لا تملك صلاحيةَ تفريق هذا الكتاب.')

    items = [_normalise(t) for t in targets]
    if not items:
        raise ValidationError('لا هدفَ للتفريق.')

    from_department = _origin_department(book, by)
    default_purpose = purpose or BookReferral.ACTION

    # التحقّق كلُّه **قبل** أيّ كتابة: تفريقٌ نصفُه ناجحٌ أسوأُ من تفريقٍ مرفوض.
    prepared = []
    for item in items:
        target = item['target']
        if isinstance(target, Department):
            keys = {'to_department': target}
        elif isinstance(target, Entity):
            keys = {'to_entity': target}
        else:
            raise ValidationError('هدفُ تفريقٍ غيرُ معروف: %r' % (target,))

        if not allow_repeat and _has_open_referral(book, keys):
            raise ValidationError(
                'الكتابُ مُفرَّقٌ إلى «%s» والتزامُه ما زال مفتوحاً.' % (target,)
            )
        prepared.append((keys, item))

    created = []
    with transaction.atomic():
        for keys, item in prepared:
            created.append(BookReferral.objects.create(
                book=book, from_department=from_department,
                purpose=item.get('purpose', default_purpose),
                margin=item.get('margin', margin),
                margin_crop=item.get('margin_crop', margin_crop),
                due_date=item.get('due_date', due_date),
                assignee=item.get('assignee', assignee),
                created_by=by,
                **keys
            ))

        _project_onto_m2m(book, created)
        _record(book, 'referral', by,
                'فُرِّق إلى: ' + ' · '.join(r.target_name for r in created))
        _notify(created, book, by)

    return created


def mark_received(referral, *, by):
    """«استلمتُه» — الوحدةُ تُقرّ بوصول الكتاب إليها."""
    from core.models import BookReferral

    return _advance(referral, BookReferral.RECEIVED, 'referral-received', by,
                    'استلمت «%s» الكتاب' % referral.target_name)


def mark_done(referral, *, by, note=''):
    """«أُنجز» — الالتزامُ أُغلق: صار الصفُّ تاريخاً لا طابوراً."""
    from core.models import BookReferral

    detail = 'أنجزت «%s» ما وُجّه إليها' % referral.target_name
    return _advance(referral, BookReferral.DONE, 'referral-done', by,
                    detail + (' — ' + note if note else ''))


def mark_returned(referral, *, by, note=''):
    """«أُعيد» — رجع الكتابُ بلا إنجاز (خطأُ توجيهٍ أو انتفاءُ اختصاص)."""
    from core.models import BookReferral

    detail = 'أعادت «%s» الكتاب' % referral.target_name
    return _advance(referral, BookReferral.RETURNED, 'referral-returned', by,
                    detail + (' — ' + note if note else ''))


def send_reminder(referral, *, by):
    """تنبيهٌ على وحدةٍ تأخّرت — «موظّفُ البريد يستطيع التنبيه على الوحدة».

    يختم ``last_reminder_at`` كي لا يتحوّل التنبيهُ إلى مضايقةٍ يوميّة، ويصل
    **كلَّ موظّفي الوحدة** لا المكلَّفَ وحده: الشفافيّةُ هي الغرض.
    """
    from django.utils import timezone

    if not referral.is_open:
        raise ValidationError('الالتزامُ مُغلقٌ — لا تنبيهَ عليه.')
    _guard(referral, by)

    with transaction.atomic():
        referral.last_reminder_at = timezone.now()
        referral.save(update_fields=['last_reminder_at'])
        _record(referral.book, 'reminder', by,
                'تنبيهٌ على «%s»' % referral.target_name)
        _notify([referral], referral.book, by, urgent=True,
                lead='تنبيه: كتابٌ بانتظار إنجازكم')
    return referral


def send_circular(book, group, *, by, purpose=None, margin='', due_date=None,
                  member_overrides=None):
    """يُعمّم كتاباً على عنقودٍ كاملٍ بضغطةٍ واحدة — «حفظ وإرسال».

    **رقمُ صادرٍ واحدٌ للكتاب كلّه** — هذا هو الورقُ نفسه: التعميمُ يحمل رقماً
    واحداً، ورقمٌ لكلّ عضوٍ يفجّر الدفتر ويناقض الممارسة. وواقعةُ المخاطبة
    تُسجَّل في ``Book.sent_to_group`` بدل رشّ اثنين وأربعين صفَّ M2M.

    **والجسرُ بين الطبقتين هنا:** عضوُ العنقود جهةٌ في الدليل، فإن كانت لها
    **عقدةُ قسمٍ توأم** صار الهدفُ القسمَ (فتعمل طاولةُ وارده وعدّاداته)،
    وإلّا بقي جهةً خارجيّة. فالوحدةُ كلا الأمرين بإسقاطيها.

    ``member_overrides`` قاموسٌ ``{entity_id: {...}}`` لما يخصّ عضواً بعينه —
    «أحياناً إلى قسمين أو ثلاثة» بتوجيهاتٍ مختلفة.
    """
    from core.models import Book

    members = list(group.resolved_members())
    if not members:
        raise ValidationError('العنقودُ «%s» بلا أعضاء.' % group)

    overrides = member_overrides or {}
    targets = []
    for entity in members:
        item = dict(overrides.get(entity.pk, {}))
        item['target'] = _bridge(entity)
        targets.append(item)

    created = distribute(book, targets, by=by, purpose=purpose, margin=margin,
                         due_date=due_date, allow_repeat=True)

    with transaction.atomic():
        # كتابةٌ ضيّقةٌ لا `save()`: التعميمُ لا يمسّ بقيّةَ حقول الكتاب
        Book.objects.filter(pk=book.pk).update(sent_to_group=group)
        book.sent_to_group = group      # والكائنُ في يد المستدعي يوافق القاعدة
        _record(book, 'circular', by,
                'عُمِّم على «%s» — %d جهة' % (group, len(created)))
    return created


def reply_matrix(book, user):
    """مَن ردّ ومَن تأخّر — مصفوفةُ التعميم.

    **«للعلم» لا يُعدّ متأخّراً أبداً**: المطاردةُ على «للتنفيذ» فقط، وإلّا
    امتلأ الطابورُ بما لا إجابةَ له فأهمله قارئُه.
    """
    from core.scoping import scope_referrals_for

    rows = scope_referrals_for(user, book.referrals.select_related(
        'to_department', 'to_entity', 'assignee', 'closed_by_link__from_book'
    )).order_by('created_at')

    matrix = []
    for row in rows:
        reply = row.closed_by_link.from_book if row.closed_by_link_id else None
        matrix.append({
            'referral': row,
            'target': row.target_name,
            'purpose': row.get_purpose_display(),
            'status': row.get_status_display(),
            'is_open': row.is_open,
            'is_overdue': row.is_overdue,
            'due_date': row.due_date,
            'reminded_at': row.last_reminder_at,
            'reply_id': reply.pk if reply else None,
            'reply_number': reply.our_number_display if reply else '',
        })
    return matrix


def _bridge(entity):
    """جسرُ الطبقتين: الجهةُ التي لها عقدةُ قسمٍ توأم **هدفُها القسم**.

    وهو ما يجعل التعميمَ يصل طاولةَ وارد الوحدة لا كتالوجَ الجهات وحده.
    """
    department = getattr(entity, 'department', None)
    return department if department is not None and department.is_active else entity


def close_by_reply(book, link, reply_book, *, by):
    """يُقفل الالتزامَ المفتوح الذي **أجابه** هذا الكتاب — إن وُجد.

    «المطابق» = التزامٌ مفتوحٌ على الأصل هدفُه القسمُ الذي صدر عنه الجواب.
    وإن لم يوجد فلا يُختلق إقفال: صفٌّ يُقفل بلا مطابقةٍ صحيحة يُخفي التزاماً
    قائماً — وإخفاءُ التزامٍ أسوأُ من تركه مفتوحاً.

    يعيش هنا لا في وحدة القيد لأنّ ``status`` **لا يُكتب إلّا في هذا الملفّ**.
    """
    from core.models import BookReferral

    answering = reply_book.department_id
    if not answering:
        return None
    row = BookReferral.objects.filter(
        book=book, to_department_id=answering,
        status__in=BookReferral.OPEN_STATUSES,
    ).order_by('created_at').first()
    if row is None:
        return None

    with transaction.atomic():
        row.status = BookReferral.DONE
        row.closed_by_link = link
        row.save(update_fields=['status', 'closed_by_link'])
        _record(book, 'referral-done', by,
                'أُقفل التزامُ «%s» بالجواب %s' % (row.target_name, _ref(reply_book)))
    return row


def _ref(book):
    """إشارةٌ قصيرةٌ للكتاب في نصّ الحدث."""
    number = book.our_number_display or '(بلا رقم)'
    return '%s%s' % (number, ' في %s' % book.date.strftime('%Y/%m/%d') if book.date else '')


def open_referrals_for(department, qs=None):
    """طابورُ وحدةٍ: التزاماتُها المفتوحة — الأسخنُ استعلاماً في الطاولة."""
    from core.models import BookReferral

    qs = BookReferral.objects.all() if qs is None else qs
    return qs.filter(to_department=department, status__in=BookReferral.OPEN_STATUSES)


# ───────────────────────────── الداخليّات ─────────────────────────────

def _normalise(target):
    """يقبل كائناً أو قاموساً — ويُرجع قاموساً دائماً."""
    if isinstance(target, dict):
        if 'target' not in target:
            raise ValidationError('عنصرُ تفريقٍ بلا مفتاح «target».')
        return dict(target)
    return {'target': target}


def _origin_department(book, by):
    """قسمُ المصدر: قسمُ الكتاب، وإلّا قسمُ الفاعل — ولا تفريقَ بلا أحدهما."""
    from core.models import Department
    from core.scoping import user_department_id

    if book.department_id:
        return book.department
    dept_id = user_department_id(by)
    if dept_id is None:
        raise ValidationError('لا قسمَ للكتاب ولا للمُفرِّق — لا مصدرَ للإحالة.')
    return Department.objects.get(pk=dept_id)


def _has_open_referral(book, keys):
    from core.models import BookReferral

    return BookReferral.objects.filter(
        book=book, status__in=BookReferral.OPEN_STATUSES, **keys
    ).exists()


def _project_onto_m2m(book, referrals):
    """إسقاطُ التفريق على ``receiving_entities`` — **للوارد فقط**.

    الدفترُ القائم (والبحثُ والتقارير) يقرأ «إلى مَن وُزِّع» من هذا الحقل منذ
    سنوات، وصفوفُ الإحالة وحدَها تتركه أعمى. أمّا **الصادر** فحقلُه مُخاطَبُه
    الحقيقيّ — والكتابةُ فيه تُفسد وجهةَ الكتاب، فلا تُمسّ.
    """
    if not book.kind.startswith('incoming'):
        return
    twins = [r.to_department.entity for r in referrals
             if r.to_department_id and r.to_department.entity_id]
    if twins:
        book.receiving_entities.add(*twins)


def _advance(referral, status, action, by, detail):
    """نقلةُ حالةٍ واحدة — وهي المكانُ الوحيد الذي يُكتب فيه ``status``."""
    _guard(referral, by)
    if referral.status == status:
        return referral

    with transaction.atomic():
        referral.status = status
        referral.save(update_fields=['status'])
        _record(referral.book, action, by, detail)
    return referral


def _guard(referral, by):
    """الصفُّ يرث بوّابتَي الكتاب — ويُضاف إليهما طرفا الإحالة نفسُها."""
    from core.scoping import can_open_content, user_department_id

    if can_open_content(referral.book, by):
        return
    dept_id = user_department_id(by)
    if dept_id and dept_id in (referral.to_department_id, referral.from_department_id):
        return
    raise PermissionDenied('لا تملك صلاحيةً على هذه الإحالة.')


def _notify(referrals, book, by, *, urgent=False, lead='كتابٌ فُرِّق إليكم'):
    """إشعارٌ لكلّ موظّفٍ في الوحدة المستقبِلة — لا للمكلَّف وحده.

    «يفضَّل حسابُ الوحدة يجمع البيانات والتنبيهات لكلّ موظّفيه **بشفافيّة**
    لمتابعة العمل» — أمرُ المالك حرفيّاً.
    """
    from django.contrib.auth.models import User

    from core.models import Notification

    dept_ids = {r.to_department_id for r in referrals if r.to_department_id}
    if not dept_ids:
        return                       # جهةٌ خارجيّة: لا مستخدمين لنا عندها

    recipients = User.objects.filter(
        is_active=True, profile__department_id__in=dept_ids
    ).exclude(pk=by.pk if by else None).values_list('pk', flat=True)

    number = book.our_number_display or '(بلا رقم)'
    Notification.objects.bulk_create([
        Notification(
            user_id=uid, category='book',
            priority=Notification.PRIORITY_URGENT if urgent else Notification.PRIORITY_INFO,
            title='%s: %s' % (lead, number),
            message=book.title or '',
            link_url='/books/%d/' % book.pk,
        )
        for uid in recipients
    ])


def _record(book, action, by, notes):
    from core.models import BookHistory

    BookHistory.objects.create(
        book=book, action=action, by=by,
        by_snapshot=(by.get_full_name() or by.get_username()) if by else '',
        notes=notes,
    )
