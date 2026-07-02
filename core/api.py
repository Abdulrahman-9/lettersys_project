"""
API endpoints للبحث السريع والذكي
- بحث في الجهات والعناوين
- PostgreSQL: TrigramSimilarity + Full-Text Search
"""

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Case, Count, When, Value, IntegerField, FloatField, OuterRef, Subquery
from django.db.models.functions import Coalesce, Greatest
from django.contrib.postgres.search import TrigramSimilarity
from django.core.cache import cache
from django.utils.text import slugify
from .models import Entity, Book
from .decorators import rate_limit
import json
import logging

logger = logging.getLogger('lettersys')


# ===== إصدارات الكاش (Cache Versioning) =====
# تُبطَل الاستعلامات المخزّنة تلقائياً عند تعديل/حذف Entity أو Book
# عبر زيادة الإصدار (signals في models.py).
ENTITY_CACHE_VERSION_KEY = 'cache_version_entity'
BOOK_CACHE_VERSION_KEY = 'cache_version_book'


def _get_entity_cache_version():
    v = cache.get(ENTITY_CACHE_VERSION_KEY)
    if v is None:
        cache.set(ENTITY_CACHE_VERSION_KEY, 1, None)
        return 1
    return v


def _get_book_cache_version():
    v = cache.get(BOOK_CACHE_VERSION_KEY)
    if v is None:
        cache.set(BOOK_CACHE_VERSION_KEY, 1, None)
        return 1
    return v


def _format_entity(entity, match_type, priority, similarity=None):
    """Build a result dict for a single Entity."""
    result = {
        'id': entity.id,
        'text': entity.name,
        'code': entity.code or '',
        'type': entity.get_etype_display(),
        'email': entity.email or '',
        'has_email': bool(entity.email),
        'match_type': match_type,
        'priority': priority,
    }
    if similarity is not None:
        result['similarity'] = round(similarity, 3)
    return result


def _pg_entity_search(queryset, search_term, limit):
    """Single-query entity search using pg_trgm TrigramSimilarity."""
    return (
        queryset
        .annotate(
            name_sim=TrigramSimilarity('name', search_term),
            code_sim=Coalesce(
                TrigramSimilarity('code', search_term),
                Value(0.0, output_field=FloatField()),
            ),
            best_sim=Greatest('name_sim', 'code_sim'),
            priority=Case(
                When(name__iexact=search_term, then=Value(1)),
                When(code__iexact=search_term, then=Value(2)),
                When(Q(name__istartswith=search_term) | Q(code__istartswith=search_term), then=Value(3)),
                When(Q(name__icontains=search_term) | Q(code__icontains=search_term), then=Value(4)),
                When(best_sim__gt=0.2, then=Value(5)),
                default=Value(99),
                output_field=IntegerField(),
            ),
        )
        .filter(
            Q(name__iexact=search_term)
            | Q(code__iexact=search_term)
            | Q(name__icontains=search_term)
            | Q(code__icontains=search_term)
            | Q(best_sim__gt=0.2)
        )
        .order_by('priority', '-best_sim')[:limit]
    )


@login_required
@require_http_methods(["GET"])
@rate_limit('search_entities', max_attempts=60, window_seconds=60, by='user')
def search_entities(request):
    """
    البحث المتقدم عن الجهات
    PostgreSQL: استعلام واحد بـ TrigramSimilarity
    """
    search_term = request.GET.get('q', '').strip()
    try:
        limit = min(int(request.GET.get('limit', 10)), 50)
    except (ValueError, TypeError):
        limit = 10
    include_inactive = request.GET.get('include_inactive', 'false').lower() == 'true'

    if not search_term:
        return JsonResponse({'results': []})

    # NOTE: allow_unicode=True is critical — without it, slugify strips Arabic characters
    # and every single-char Arabic query (مثل "د", "ع") collapses to the SAME cache key,
    # which causes wrong/empty results for unrelated queries.
    cache_key = (
        f"entity_search_v{_get_entity_cache_version()}_"
        f"{slugify(search_term, allow_unicode=True)}_{include_inactive}"
    )
    cached_result = cache.get(cache_key)
    if cached_result:
        return JsonResponse(cached_result)

    queryset = Entity.objects.all()
    if not include_inactive:
        queryset = queryset.filter(is_active=True)

    qs = _pg_entity_search(queryset, search_term, limit)
    results = [
        _format_entity(e, e.match_type if hasattr(e, 'match_type') else 'pg_trgm',
                       e.priority, getattr(e, 'best_sim', None))
        for e in qs
    ]

    response = {'results': results[:limit]}
    cache.set(cache_key, response, 3600)
    return JsonResponse(response)


@login_required
@require_http_methods(["GET"])
@rate_limit('search_titles', max_attempts=60, window_seconds=60, by='user')
def search_titles(request):
    """
    البحث عن عناوين الكتب
    PostgreSQL: TrigramSimilarity على العنوان — يدعم الأخطاء الإملائية
    """
    search_term = request.GET.get('q', '').strip()
    try:
        limit = min(int(request.GET.get('limit', 10)), 50)
    except (ValueError, TypeError):
        limit = 10
    entity_id = request.GET.get('entity_id', None)

    if not search_term or len(search_term) < 2:
        return JsonResponse({'results': []})

    cache_key = (
        f"title_search_v{_get_book_cache_version()}_"
        f"{slugify(search_term, allow_unicode=True)}_{entity_id}"
    )
    cached_result = cache.get(cache_key)
    if cached_result:
        return JsonResponse(cached_result)

    queryset = Book.objects.filter(is_deleted=False)

    if entity_id:
        queryset = queryset.filter(
            Q(issuing_entities__id=entity_id)
            | Q(receiving_entities__id=entity_id)
        )

    titles = (
        queryset
        .annotate(sim=TrigramSimilarity('title', search_term))
        .filter(Q(sim__gt=0.15) | Q(title__icontains=search_term))
        .order_by('-sim')
        .values_list('title', flat=True)
        .distinct()[:limit]
    )

    response = {
        'results': [
            {'id': i, 'text': title}
            for i, title in enumerate(titles)
        ]
    }
    cache.set(cache_key, response, 1800)
    return JsonResponse(response)


@login_required
@require_http_methods(["GET"])
def title_autocomplete(request):
    """
    API للتنبؤ بعناوين الكتب — ثلاثي الطبقات:
    1. full: اقتراحات كاملة مرتبة بالتكرار (trigram / icontains)
    2. next_word: الكلمة التالية الأكثر شيوعاً (bigram model)
    3. kind: فلترة حسب نوع الكتاب (اختياري)
    """
    q = request.GET.get('q', '').strip()
    mode = request.GET.get('mode', 'full')  # full | next_word
    kind = request.GET.get('kind', '')

    if not q or len(q) < 2:
        return JsonResponse({'suggestions': [], 'next_word': None})

    cache_key = f"title_ac_{slugify(q[:60])}_{mode}_{kind}"
    cached = cache.get(cache_key)
    if cached:
        return JsonResponse(cached)

    qs = Book.objects.filter(is_deleted=False)
    if kind:
        qs = qs.filter(kind=kind)

    if mode == 'next_word':
        # ─── Bigram: يبحث عن الكلمات التي تلي النص الحالي ───
        words = q.split()
        last_words = ' '.join(words[-2:]) if len(words) >= 2 else words[-1] if words else ''

        matching = (
            qs.filter(title__icontains=last_words)
            .values_list('title', flat=True)[:300]
        )

        # استخراج الكلمة التالية بعد آخر جزء من النص
        from collections import Counter
        next_words = Counter()
        q_lower = q.lower()
        for title in matching:
            t_lower = title.lower()
            idx = t_lower.find(last_words.lower())
            if idx == -1:
                continue
            rest = title[idx + len(last_words):].strip()
            if rest:
                next_token = rest.split()[0]
                if next_token and len(next_token) > 1:
                    next_words[next_token] += 1

        top_word = next_words.most_common(1)
        result = {'suggestions': [], 'next_word': top_word[0][0] if top_word else None}
        cache.set(cache_key, result, 300)
        return JsonResponse(result)

    # ─── full mode: اقتراحات كاملة مرتبة بالتكرار ───
    suggestions = (
        qs.annotate(sim=TrigramSimilarity('title', q))
        .filter(Q(sim__gt=0.12) | Q(title__icontains=q))
        .values('title')
        .annotate(freq=Count('title'))
        .order_by('-sim', '-freq')
        .values_list('title', 'freq')[:10]
    )

    result = {
        'suggestions': [
            {'text': t, 'freq': f}
            for t, f in suggestions
        ],
        'next_word': None
    }
    cache.set(cache_key, result, 300)
    return JsonResponse(result)


@login_required
@require_http_methods(["GET"])
def title_words_api(request):
    """
    يعيد أكثر كلمات العناوين شيوعاً من قاعدة البيانات — لتغذية قاموس الإكمال التلقائي.
    يُفرز الكلمات العربية والإنجليزية ويُصفّي الكلمات المساعدة القصيرة.
    كاش ساعة واحدة — يُمسح تلقائياً عند تغيير الكتب.
    """
    import re
    from collections import Counter

    cache_key = 'title_words_dict_v1'
    cached = cache.get(cache_key)
    if cached:
        return JsonResponse(cached)

    # كلمات يُجب تجاهلها (حروف ربط / ضمائر / حروف جر بلا قيمة تنبؤية)
    AR_STOP = {
        'من','في','على','إلى','عن','مع','هذا','هذه','ذلك','تلك',
        'التي','الذي','التي','اللذين','اللتين','اللواتي',
        'وقد','وقت','قد','لا','ما','هو','هي','هم','هن','نحن','أنتم',
        'أن','إن','إلا','كان','كانت','كل','بعد','قبل','حتى',
        'لكن','لأن','بأن','أو','ثم','ولا','كذلك','أيضاً','أيضا',
        'لم','لن','بل','كما','منذ','عند','لدى','خلال','حول',
        'هنا','هناك','الآن','اليوم','وقت','ومن','وفي','وعلى','وإلى',
        'بين','فوق','تحت','أمام','خلف','يمين','يسار',
        'هذان','ذانك','هؤلاء','أولئك',
        'جميع','بعض','كثير','قليل','أكثر','أقل','غير',
        'نفس','ذات','حيث','إذا','لو','لولا',
        'حيث','منه','منها','منهم','منهن','فيه','فيها','فيهم',
        'عليه','عليها','عليهم','إليه','إليها','إليهم',
    }
    EN_STOP = {
        'a','an','the','and','but','or','for','of','to','in','at',
        'by','with','as','on','is','was','be','been','has','have',
        'had','are','were','it','its','this','that','these','those',
        'we','our','i','you','he','she','they','their','his','her',
        'not','no','yes','do','did','does','will','would','can',
        'could','should','may','might','shall','from','into','about',
        'also','than','then','when','where','which','who','whom','how',
    }

    titles = list(
        Book.objects.filter(is_deleted=False)
        .values_list('title', flat=True)
        .distinct()[:8000]
    )

    ar_counter = Counter()
    en_counter = Counter()

    _ar_re = re.compile(r'[\u0600-\u06FF]+')
    _en_re = re.compile(r'[a-zA-Z]{4,}')  # إنجليزي ≥ 4 أحرف فقط
    _strip = re.compile(r'[\u064B-\u065F\u0670]')  # إزالة تشكيل

    for title in titles:
        # عربية
        for w in _ar_re.findall(title):
            w = _strip.sub('', w)
            if len(w) >= 3 and w not in AR_STOP:
                ar_counter[w] += 1
        # إنجليزية
        for w in _en_re.findall(title):
            wl = w.lower()
            if wl not in EN_STOP:
                en_counter[wl] += 1

    result = {
        'ar': [w for w, _ in ar_counter.most_common(400)],
        'en': [w for w, _ in en_counter.most_common(200)],
    }
    cache.set(cache_key, result, 3600)
    return JsonResponse(result)
@login_required
@require_http_methods(["POST"])
@rate_limit('add_entity', max_attempts=30, window_seconds=60, by='user')
def add_new_entity(request):
    """
    إضافة جهة جديدة من خلال الـ AJAX
    
    البيانات المتوقعة (JSON):
    {
        "name": "اسم الجهة",
        "code": "رمز الجهة (اختياري)",
        "etype": "issuer|receiver|both"
    }
    
    الاستجابة:
    {
        "success": true/false,
        "id": معرف الجهة,
        "message": "رسالة الخطأ أو النجاح"
    }
    """
    
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({
            'success': False,
            'message': 'البيانات المرسلة غير صحيحة (JSON)'
        }, status=400)
    
    name = data.get('name', '').strip()
    code = data.get('code', '').strip()
    etype = data.get('etype', 'both')
    
    # التحقق من البيانات
    if not name:
        return JsonResponse({
            'success': False,
            'message': 'اسم الجهة مطلوب'
        }, status=400)
    
    if len(name) > 255:
        return JsonResponse({
            'success': False,
            'message': 'اسم الجهة طويل جداً (الحد الأقصى: 255 حرف)'
        }, status=400)
    
    # التحقق من الازدواجية
    if Entity.objects.filter(name__iexact=name).exists():
        existing = Entity.objects.get(name__iexact=name)
        return JsonResponse({
            'success': True,
            'id': existing.id,
            'message': 'الجهة موجودة بالفعل',
            'is_existing': True
        })
    
    if code and Entity.objects.filter(code__iexact=code).exists():
        return JsonResponse({
            'success': False,
            'message': f'رمز الجهة "{code}" موجود بالفعل'
        }, status=400)
    
    # إنشاء الجهة الجديدة
    try:
        entity = Entity.objects.create(
            name=name,
            code=code,
            etype=etype,
            is_active=True
        )
        
        # إبطال cache البحث عبر زيادة الإصدار (متوافق مع LocMemCache وRedis)
        _current = cache.get(ENTITY_CACHE_VERSION_KEY, 1)
        cache.set(ENTITY_CACHE_VERSION_KEY, _current + 1, None)
        
        return JsonResponse({
            'success': True,
            'id': entity.id,
            'message': 'تم إضافة الجهة بنجاح'
        })
    
    except Exception as e:
        logger.exception('Failed to create entity: %s', e)
        return JsonResponse({
            'success': False,
            'message': 'حدث خطأ أثناء إنشاء الجهة. يرجى المحاولة مرة أخرى.'
        }, status=500)


@login_required
@require_http_methods(["GET"])
def get_entity_stats(request):
    """
    إحصائيات عن الجهات والعناوين
    مفيدة للتحليل والتحسين
    """
    
    # عدّ كتب كل جهة عبر استعلامين فرعيين مستقلّين — يتجنّب الضرب الديكارتي
    # الناتج عن ضمّ علاقتَي M2M (issued/received) في استعلام واحد.
    _issued_sq = (
        Book.objects.filter(issuing_entities=OuterRef('pk'), is_deleted=False)
        .order_by().values('issuing_entities').annotate(c=Count('id')).values('c')
    )
    _received_sq = (
        Book.objects.filter(receiving_entities=OuterRef('pk'), is_deleted=False)
        .order_by().values('receiving_entities').annotate(c=Count('id')).values('c')
    )

    stats = {
        'total_entities': Entity.objects.count(),
        'active_entities': Entity.objects.filter(is_active=True).count(),
        'total_titles': Book.objects.filter(is_deleted=False).values('title').distinct().count(),
        'total_books': Book.objects.filter(is_deleted=False).count(),
        'most_used_entities': list(
            Entity.objects.annotate(
                book_count=(
                    Coalesce(Subquery(_issued_sq, output_field=IntegerField()), 0)
                    + Coalesce(Subquery(_received_sq, output_field=IntegerField()), 0)
                )
            ).order_by('-book_count').values('id', 'name', 'book_count')[:5]
        ),
        'most_used_titles': list(
            Book.objects.filter(is_deleted=False)
            .values('title')
            .annotate(count=Count('title'))
            .order_by('-count')[:5]
        )
    }
    
    return JsonResponse(stats)
