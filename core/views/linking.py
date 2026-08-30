# -*- coding: utf-8 -*-
"""
منتقي الربط `@` ونسيجُ الوثائق — نقاطُ الواجهة.

الفكرةُ التي طلبها المالك (`@2433`) عمليّةٌ **بوصفها إيماءةَ نداءٍ لا طريقةَ
تخزين**: الرقمُ عندنا **ليس معرِّفاً** — فريدٌ داخل القسم فقط، والمنقولُ من
الورق مستثنى من التفرّد أصلاً (٨٢٥ مرّتين حقيقةً مقيسة)، ورقمُ الجهة يشابك
رقمَنا. فالنصُّ المفسَّر **يخطئ بصمت**، والضلعُ المختار بالعين مفتاحٌ أجنبيّ لا
يلتبس.

فالمنتقي يعرض **بطاقاتِ إزالةِ التباس** (الرقم بعرض `numbering` + القسم + وسم
السنة + العنوان + الجهة)، ويسقط إلى **البحث بالعنوان** إن لم يجد رقماً — وهو
طلبُ المالك الثالث محقَّقاً في الأداة نفسها.
"""

import json

from django.core.exceptions import PermissionDenied, ValidationError
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from core.decorators import rate_limit
from core.linking_service import add_link, remove_link
from core.models import Book, BookLink
from core.scoping import can_open_content, scope_books_for

#: سقفُ نتائج المنتقي — حواريّةٌ لا صفحةُ بحث.
PICKER_LIMIT = 12


def _json(request):
    try:
        return json.loads(request.body or b'{}')
    except (json.JSONDecodeError, ValueError):
        return {}


@login_required
@require_http_methods(['GET'])
def api_link_picker(request):
    """يبحث عن كتابٍ للربط — برقمه أو بعنوانه — داخل نطاق المستخدم.

    ``exclude`` يُخرج الكتابَ الحاليَّ من النتائج (لا يُربط بنفسه).
    والترتيب: **قسمُ المستخدم أوّلاً** ثمّ الأحدث — لأنّ الكاتب يبحث عن كتابٍ
    من دفتره في الغالب، والالتباسُ بين الأقسام هو ما نُزيله.
    """
    from core.views.helpers import apply_search_filters
    from core.scoping import guard_secret_text_search, user_department_id

    query = (request.GET.get('q') or '').strip()
    if not query:
        return JsonResponse({'success': True, 'results': []})

    qs = scope_books_for(request.user, Book.objects.filter(is_deleted=False))
    exclude_id = request.GET.get('exclude')
    if exclude_id and str(exclude_id).isdigit():
        qs = qs.exclude(pk=int(exclude_id))

    qs = apply_search_filters(qs, query)
    qs = guard_secret_text_search(qs, request.user, query)

    my_department = user_department_id(request.user)
    results = []
    for book in qs.select_related('department').prefetch_related('issuing_entities')[:PICKER_LIMIT]:
        issuer = book.issuing_entities.all()[:1]
        results.append({
            'id': book.id,
            'number': book.our_number_display or '—',
            'year_tag': book.our_number_year or '',
            'title': book.title if can_open_content(book, request.user) else '— سرّي —',
            'date': book.date.strftime('%Y/%m/%d') if book.date else '',
            'kind_label': book.get_kind_display(),
            'department': str(book.department) if book.department_id else '',
            'entity': issuer[0].name if issuer else '',
            'is_mine': bool(my_department and book.department_id == my_department),
        })

    # قسمي أوّلاً — إزالةُ الالتباس تبدأ من الأقرب احتمالاً
    results.sort(key=lambda r: (not r['is_mine'],))
    return JsonResponse({'success': True, 'results': results, 'query': query})


@login_required
@require_http_methods(['POST'])
@rate_limit('book_link', max_attempts=60, window_seconds=300, by='user')
def api_add_link(request, pk):
    """يثبّت ضلعاً بعد أن اختاره إنسانٌ بعينه من المنتقي."""
    data = _json(request)
    target_id, relation = data.get('to_book'), data.get('relation', '')

    from_book = _get_or_404(request, pk)
    to_book = _get_or_404(request, target_id)
    if from_book is None or to_book is None:
        return JsonResponse({'success': False, 'message': 'الكتاب غير موجود'}, status=404)

    try:
        link = add_link(from_book, to_book, relation, by=request.user,
                        note=data.get('note', ''))
    except ValidationError as exc:
        return JsonResponse({'success': False, 'message': exc.messages[0]}, status=400)
    except PermissionDenied as exc:
        return JsonResponse({'success': False, 'message': str(exc)}, status=403)

    return JsonResponse({'success': True, 'id': link.id,
                         'relation_label': link.get_relation_display()})


@login_required
@require_http_methods(['POST'])
def api_remove_link(request, pk, link_id):
    link = BookLink.objects.filter(pk=link_id, from_book_id=pk).first()
    if link is None:
        return JsonResponse({'success': False, 'message': 'الربط غير موجود'}, status=404)
    try:
        remove_link(link, by=request.user)
    except PermissionDenied as exc:
        return JsonResponse({'success': False, 'message': str(exc)}, status=403)
    return JsonResponse({'success': True})


def _get_or_404(request, pk):
    """كتابٌ داخل نطاق المستخدم — والخارجُ عنه «غير موجود» لا «ممنوع»."""
    if not pk or not str(pk).isdigit():
        return None
    return scope_books_for(
        request.user, Book.objects.filter(is_deleted=False)
    ).filter(pk=int(pk)).first()
