# -*- coding: utf-8 -*-
"""
نقاطُ الكتابة لدورة حياة الكتاب — التفريقُ والعهدةُ والقيدُ والتنبيه.

بُنيت الجداولُ الخمسةُ وخدماتُها في البنود ②③④ **ولا شاشةَ تكتب فيها**: عمودُ
التسيير كلُّه كان بلا يدٍ تُحرّكه. هذه النقاطُ هي تلك اليد.

**وكلُّها أغلفةٌ رقيقة:** لا قاعدةَ عملٍ هنا — التحقّقُ والحراسةُ والأثرُ كلُّها
في الخدمات (`referral_service` · `custody_service` · `registration_service`)،
وهذه تُترجم HTTP إلى استدعاءٍ وتُترجم الاستثناءَ إلى رمزٍ عربيّ. أيُّ منطقٍ
يتسرّب إلى هنا يصير نسخةً ثانيةً للحقيقة.
"""

import json

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from core.decorators import rate_limit
from core.models import Book, BookReferral, CustodyEvent, Department, Entity
from core.scoping import scope_books_for, scope_referrals_for


@login_required
@require_http_methods(['POST'])
@rate_limit('book_distribute', max_attempts=60, window_seconds=300, by='user')
def api_distribute(request, pk):
    """«حفظ وإرسال» — يُفرّق الكتابَ على وحداتٍ أو عنقود."""
    from core.referral_service import distribute, send_circular

    book = _book(request, pk)
    if book is None:
        return _missing()

    data = _json(request)
    common = {
        'margin': (data.get('margin') or '').strip(),
        'due_date': _date(data.get('due_date')),
        'purpose': data.get('purpose') or BookReferral.ACTION,
        'assignee': _user_in_scope(request, data.get('assignee')),
    }

    try:
        group = _group(data.get('group'))
        if group is not None:
            rows = send_circular(book, group, by=request.user, **_without(common, 'assignee'))
        else:
            targets = _targets(data.get('targets') or [])
            if not targets:
                raise ValidationError('لم تختر جهةً واحدة.')
            rows = distribute(book, targets, by=request.user, **common)
    except ValidationError as exc:
        return _bad(exc)
    except PermissionDenied as exc:
        return _denied(exc)

    return JsonResponse({
        'success': True,
        'count': len(rows),
        'message': 'فُرِّق إلى %d جهة.' % len(rows),
    })


@login_required
@require_http_methods(['POST'])
def api_referral_action(request, pk, referral_id):
    """نقلةُ حالةٍ على صفّ إحالة، أو تنبيهٌ عليه."""
    from core.referral_service import (mark_done, mark_received, mark_returned,
                                       send_reminder)

    referral = scope_referrals_for(request.user).filter(
        pk=referral_id, book_id=pk).select_related('book').first()
    if referral is None:
        return _missing('الإحالة غير موجودة')

    data = _json(request)
    note = (data.get('note') or '').strip()
    handlers = {
        'received': lambda: mark_received(referral, by=request.user),
        'done': lambda: mark_done(referral, by=request.user, note=note),
        'returned': lambda: mark_returned(referral, by=request.user, note=note),
        'remind': lambda: send_reminder(referral, by=request.user),
    }
    handler = handlers.get(data.get('act'))
    if handler is None:
        return _bad(ValidationError('إجراءٌ غير معروف.'))

    try:
        handler()
    except ValidationError as exc:
        return _bad(exc)
    except PermissionDenied as exc:
        return _denied(exc)

    return JsonResponse({'success': True, 'status': referral.get_status_display()})


@login_required
@require_http_methods(['POST'])
def api_record_custody(request, pk):
    """تسجيلُ انتقال عهدة — «بعهدة مَن» بعد توقيع الكشف."""
    from core.custody_service import record_custody

    book = _book(request, pk)
    if book is None:
        return _missing()

    data = _json(request)
    referral = None
    if data.get('referral'):
        referral = scope_referrals_for(request.user).filter(
            pk=data['referral'], book=book).first()

    try:
        moment = record_custody(
            book, data.get('event') or CustodyEvent.UNIT_RECEIPT,
            referral=referral,
            to_department=_department(data.get('to_department')),
            to_user=_user_in_scope(request, data.get('to_user')),
            to_name=(data.get('to_name') or '').strip(),
            signed_at=_datetime(data.get('signed_at')),
            mode=data.get('mode'),
            note=(data.get('note') or '').strip(),
            by=request.user,
        )
    except ValidationError as exc:
        return _bad(exc)
    except PermissionDenied as exc:
        return _denied(exc)

    return JsonResponse({'success': True, 'holder': moment.holder_name,
                         'message': 'سُجّلت العهدة إلى «%s».' % moment.holder_name})


@login_required
@require_http_methods(['POST'])
def api_register_here(request, pk):
    """«قيِّده عندنا» — رقمُ واردٍ من عدّاد قسمي."""
    from core.registration_service import register_book_here
    from core.scoping import user_department_id

    book = _book(request, pk)
    if book is None:
        return _missing()

    data = _json(request)
    department = _department(data.get('department')) or _department(
        user_department_id(request.user))
    try:
        row = register_book_here(
            book, department, by=request.user,
            numberless=bool(data.get('numberless')))
    except ValidationError as exc:
        return _bad(exc)
    except PermissionDenied as exc:
        return _denied(exc)

    return JsonResponse({'success': True, 'number': row.number,
                         'message': 'قُيّد بالرقم %s.' % (row.number or '(بلا رقم)')})


@login_required
@require_http_methods(['GET'])
def api_targets(request):
    """أهدافُ التفريق المتاحة — أقسامٌ وعناقيدُ وموظّفو قسمي.

    **الأقسامُ كلُّها لا شجرتي فقط**: التفريق يتجاوز حدودَ القسم بطبيعته
    («إحالةٌ لقسمٍ آخر بالشركة» في مصفوفة الخطّة)، وقصرُها على الشجرة يمنع
    التدفّقَ الذي بُنيت لأجله.
    """
    from core.models import EntityGroup
    from core.scoping import subtree_ids, user_department_id

    mine = set(subtree_ids(user_department_id(request.user)))
    return JsonResponse({
        'departments': [
            {'id': d.pk, 'name': d.name, 'code': d.code, 'is_mine': d.pk in mine}
            for d in Department.objects.filter(is_active=True).order_by('code')
        ],
        'groups': [
            {'id': g.pk, 'name': g.name, 'size': g.resolved_members().count()}
            for g in EntityGroup.objects.filter(is_active=True).order_by('name')
        ],
        'people': [
            {'id': u.pk, 'name': u.get_full_name() or u.get_username()}
            for u in User.objects.filter(is_active=True, profile__department_id__in=mine)
                                 .order_by('username')
        ],
        'events': [{'id': v, 'label': label} for v, label in CustodyEvent.EVENT_CHOICES],
    })


# ───────────────────────────── الداخليّات ─────────────────────────────

def _json(request):
    try:
        return json.loads(request.body or b'{}')
    except (json.JSONDecodeError, ValueError):
        return {}


def _book(request, pk):
    """كتابٌ داخل نطاق المستخدم — والخارجُ عنه «غير موجود» لا «ممنوع»."""
    return scope_books_for(
        request.user, Book.objects.filter(is_deleted=False)).filter(pk=pk).first()


def _targets(raw):
    """أهدافٌ مختلطة: ``dep:3`` قسمٌ · ``ent:7`` جهةٌ خارجيّة."""
    targets = []
    for item in raw:
        kind, _, value = str(item).partition(':')
        if not value.isdigit():
            continue
        obj = (Department.objects.filter(pk=int(value), is_active=True).first()
               if kind == 'dep' else Entity.objects.filter(pk=int(value)).first())
        if obj is not None:
            targets.append(obj)
    return targets


def _group(raw):
    from core.models import EntityGroup

    if not raw or not str(raw).isdigit():
        return None
    return EntityGroup.objects.filter(pk=int(raw), is_active=True).first()


def _department(raw):
    if raw is None or not str(raw).isdigit():
        return None
    return Department.objects.filter(pk=int(raw)).first()


def _user_in_scope(request, raw):
    """المكلَّفُ من شجرتي فقط — إسنادُ عملٍ لموظّفٍ لا أراه لا معنى له."""
    from core.scoping import subtree_ids, user_department_id

    if raw is None or not str(raw).isdigit():
        return None
    return User.objects.filter(
        pk=int(raw), is_active=True,
        profile__department_id__in=subtree_ids(user_department_id(request.user)),
    ).first()


def _date(raw):
    from datetime import datetime

    try:
        return datetime.strptime((raw or '').strip(), '%Y-%m-%d').date() if raw else None
    except (ValueError, TypeError):
        return None


def _datetime(raw):
    """وقتُ التوقيع كما كتبه الكاتبُ على الورقة — أو الآن."""
    from datetime import datetime

    from django.utils import timezone

    if not raw:
        return None
    for fmt in ('%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            return timezone.make_aware(datetime.strptime(raw.strip(), fmt))
        except (ValueError, TypeError):
            continue
    return None


def _without(mapping, key):
    return {k: v for k, v in mapping.items() if k != key}


def _bad(exc):
    return JsonResponse({'success': False, 'message': exc.messages[0]}, status=400)


def _denied(exc):
    return JsonResponse({'success': False, 'message': str(exc)}, status=403)


def _missing(message='الكتاب غير موجود'):
    return JsonResponse({'success': False, 'message': message}, status=404)
