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


def system_settings(request):
    """هوية التطبيق المعروضة (اسم النظام + سطر الوصف) — تُتاح لكل القوالب."""
    from .models import SystemSettings
    obj = cache.get(SystemSettings.CACHE_KEY)
    if obj is None:
        try:
            obj = SystemSettings.get()
            cache.set(SystemSettings.CACHE_KEY, obj, 300)
        except Exception:
            # قاعدة البيانات/الهجرة غير جاهزة — القوالب تستخدم قيَماً افتراضية.
            obj = None
    return {'system_settings': obj}


def embed_mode(request):
    """وضع التضمين لمركز الإعدادات (?embed=1): تُعرَض الأداة وحدها بلا قشرة التطبيق.

    نجعله «لاصقاً» عبر ترويسة ``Sec-Fetch-Dest: iframe`` التي يرسلها المتصفح مع
    كل تنقّل داخل الإطار — بما فيه ما بعد إعادة التوجيه (302) عند حفظ النماذج —
    كي لا تعود قشرة التطبيق للظهور داخل الإطار بعد أوّل حفظ.
    """
    is_embed = (
        request.GET.get('embed') == '1'
        or request.headers.get('Sec-Fetch-Dest') == 'iframe'
    )
    return {'is_embed': is_embed}


def mail_unread(request):
    """عدد الإيميلات الواردة غير المقروءة — يظهر في badge الـ sidebar.

    كان يُحسب على النظام كلّه بمفتاح كاشٍ **واحد مشترك**، فيرى كلّ مستخدمٍ عدّاد
    بريد الجميع في كلّ صفحة (سجلّ العيوب ح1). صار على مجموعته المرئيّة نفسها،
    والمفتاح لكلّ مستخدم كي لا يتسرّب العدّ عبر الكاش.
    """
    if not request.user.is_authenticated:
        return {'mail_inbox_unread': 0}
    cache_key = f'mail_inbox_unread_{request.user.pk}'
    count = cache.get(cache_key)
    if count is None:
        try:
            from .models import IncomingEmail
            from .messaging.scoping import scope_incoming
            count = scope_incoming(
                IncomingEmail.objects.filter(is_read=False), request.user
            ).count()
        except Exception:
            count = 0
        cache.set(cache_key, count, 60)  # كاش لمدة دقيقة
    return {'mail_inbox_unread': count}
