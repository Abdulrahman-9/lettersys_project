import json
from functools import wraps
from time import time

from django.contrib import messages
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import redirect

from .roles import get_user_role


def _scan_rate_limit_cache_key(user_id):
    return f"scan_rate_limit_{user_id}"


def _scan_rate_limit_context_key(user_id):
    return f"scan_rate_limit_ctx_{user_id}"


def _scan_request_payload(request):
    """Best-effort payload extraction for normal Django and DRF requests."""
    payload = {}

    request_data = getattr(request, 'data', None)
    if isinstance(request_data, dict):
        payload.update(request_data)

    if hasattr(request, 'POST'):
        try:
            payload.update(request.POST.dict())
        except Exception:
            pass

    if not payload:
        try:
            raw_body = request.body.decode('utf-8') if isinstance(request.body, (bytes, bytearray)) else (request.body or '')
            if raw_body:
                parsed = json.loads(raw_body)
                if isinstance(parsed, dict):
                    payload.update(parsed)
        except Exception:
            pass

    return payload


def get_scan_rate_context(request):
    """
    Returns a stable context signature for scan attempts.
    New attachment/book contexts should start with a fresh rate-limit bucket.
    """
    payload = _scan_request_payload(request)
    attachment_id = payload.get('attachment_id') or request.GET.get('attachment_id')
    book_id = payload.get('book_id') or request.GET.get('book_id')

    if attachment_id:
        return f"attachment:{attachment_id}"
    if book_id:
        return f"book:{book_id}"
    return 'new_book'


def reset_scan_rate_limit(user_id):
    cache.delete(_scan_rate_limit_cache_key(user_id))
    cache.delete(_scan_rate_limit_context_key(user_id))


def reset_scan_rate_limit_for_request(request):
    user_id = getattr(getattr(request, 'user', None), 'id', None)
    if user_id:
        reset_scan_rate_limit(user_id)


def role_required(*allowed_roles):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            role = get_user_role(request.user)
            if role == 'admin' or role in allowed_roles:
                return view_func(request, *args, **kwargs)
            messages.error(request, 'لا تملك صلاحية الوصول إلى هذه الصفحة.')
            return redirect('dashboard')
        return _wrapped
    return decorator


# Rate limiter for scan operations
def rate_limit_scan(max_attempts=3, window_seconds=300):
    """
    Decorator to rate limit scan operations per user.
    Uses Django cache for persistence across restarts and workers.
    - max_attempts: maximum number of attempts within window
    - window_seconds: time window in seconds
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            user_id = request.user.id
            cache_key = _scan_rate_limit_cache_key(user_id)
            context_key = _scan_rate_limit_context_key(user_id)
            current_time = time()
            current_context = get_scan_rate_context(request)

            previous_context = cache.get(context_key)
            if previous_context and previous_context != current_context:
                cache.delete(cache_key)

            cache.set(context_key, current_context, window_seconds)
            
            attempts = cache.get(cache_key, [])
            
            # Remove old attempts outside the window
            attempts = [
                t for t in attempts 
                if current_time - t < window_seconds
            ]
            
            # Check if limit exceeded
            if len(attempts) >= max_attempts:
                return JsonResponse({
                    'status': 'error',
                    'message': f'تم تجاوز الحد المسموح من محاولات المسح ({max_attempts} محاولات في {window_seconds} ثانية)',
                    'message_en': f'Rate limit exceeded ({max_attempts} attempts in {window_seconds}s)',
                    'error_code': 'RATE_LIMIT_EXCEEDED',
                }, status=429)
            
            # Record this attempt
            attempts.append(current_time)
            cache.set(cache_key, attempts, window_seconds)
            
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator


# ─────────────────────────────────────────────────────────────────────────────
# Generic rate limiter
# ─────────────────────────────────────────────────────────────────────────────
def _client_ip(request):
    """Best-effort client IP extraction (respects X-Forwarded-For)."""
    xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '0.0.0.0')


def rate_limit(scope, max_attempts=10, window_seconds=60, by='user'):
    """
    Generic sliding-window rate limiter backed by Django cache.

    Args:
        scope: short identifier used in the cache key (e.g. 'login', 'email_send')
        max_attempts: allowed attempts inside window
        window_seconds: window size
        by: 'user' (auth user id, falls back to IP) or 'ip'

    Returns 429 JsonResponse when exceeded. Designed for both view functions
    and DRF api_view-decorated views — works with any callable taking request.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if by == 'ip':
                ident = _client_ip(request)
            else:
                user = getattr(request, 'user', None)
                if user is not None and getattr(user, 'is_authenticated', False):
                    ident = f"u{user.id}"
                else:
                    ident = f"ip:{_client_ip(request)}"

            cache_key = f"rl:{scope}:{ident}"
            current_time = time()
            attempts = [t for t in cache.get(cache_key, []) if current_time - t < window_seconds]

            if len(attempts) >= max_attempts:
                retry_after = int(window_seconds - (current_time - attempts[0]))
                resp = JsonResponse({
                    'status': 'error',
                    'error_code': 'RATE_LIMIT_EXCEEDED',
                    'message': f'تم تجاوز الحد المسموح، حاول بعد {retry_after} ثانية',
                    'retry_after': max(retry_after, 1),
                }, status=429)
                resp['Retry-After'] = str(max(retry_after, 1))
                return resp

            attempts.append(current_time)
            cache.set(cache_key, attempts, window_seconds)
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator
