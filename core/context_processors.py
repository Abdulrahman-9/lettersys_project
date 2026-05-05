from django.core.cache import cache


def notifications(request):
    if request.user.is_authenticated and request.user.is_superuser:
        cache_key = f'unread_notif_{request.user.pk}'
        unread = cache.get(cache_key)
        if unread is None:
            unread = request.user.notifications.filter(is_read=False).count()
            cache.set(cache_key, unread, 30)
        return {'navbar_unread_notifications': unread}
    return {'navbar_unread_notifications': 0}


def mail_unread(request):
    """عدد الإيميلات الواردة غير المقروءة — يظهر في badge الـ sidebar."""
    if not request.user.is_authenticated:
        return {'mail_inbox_unread': 0}
    cache_key = 'mail_inbox_unread'
    count = cache.get(cache_key)
    if count is None:
        try:
            from .models import IncomingEmail
            count = IncomingEmail.objects.filter(is_read=False).count()
        except Exception:
            count = 0
        cache.set(cache_key, count, 60)  # كاش لمدة دقيقة
    return {'mail_inbox_unread': count}
