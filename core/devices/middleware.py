"""يعرف متصفّحَ كلِّ طلبٍ مُصادَق، ويطبّق وضعَ البوّابة.

لا يفعل شيئاً قبل أن يُعلَن خادم: بلا خادمٍ لا أحدَ يقبل طلباً، فالتنبيهُ والاكتشافُ بلا معنى.
وبعده:
  - المتصفّحُ بلا كوكي يُنشأ له صفُّ «غير مسجّل» عند **تنقّل HTML علويّ** وحده (لا API ولا إطار):
    الطلباتُ المتزامنة الأولى كانت ستُنشئ عدّةَ صفوفٍ لمتصفّحٍ واحد (حكمُ فيبل).
  - آخرُ ظهورٍ يُحدَّث مرّةً في الدقيقة، والكوكي يُجدَّد كلّ 30 يوماً (Chrome يقصّه إلى 400 يوم).
  - «المسجّلة فقط»: غيرُ المسجّل يُحوَّل إلى صفحة الانضمام (كلُّ تنقّلٍ، ومنه ما يمرّ بعامل الخدمة)،
    والسكربتاتُ تردّ JSON 403. يُستثنى:
    الدخولُ والخروجُ وتغييرُ كلمة المرور وصفحةُ عدم الاتّصال وعاملُ الخدمة، والعروضُ الموسومة
    ``gate_exempt`` (صفحةُ الانضمام وواجهاتُها، ومنها إعلانُ الخادم: ضياعُ كوكي الخادم لا يوقف
    كلَّ موافقة). ولا يُستثنى Django admin.
"""
from django.http import JsonResponse
from django.shortcuts import redirect

from . import service

EXEMPT_URL_NAMES = frozenset({'login', 'logout', 'password_change', 'offline', 'service_worker_root'})


def gate_exempt(view):
    """يُعلّم عرضاً يبقى مفتوحاً للجهاز غير المسجّل في وضع «المسجّلة فقط»."""
    view.device_gate_exempt = True
    return view


def _wants_json(request):
    """طلبٌ من سكربتٍ لا تنقّلٌ: يُردّ JSON لا صفحةُ الانضمام (كان `/books/mail/api/…` يستلم HTML
    فيفشل ``r.json()`` بلا رسالة — فيبل).

    التنقّلُ يُعرف بـ ``Sec-Fetch-Mode: navigate`` لا بالوجهة: حين يتحكّم عاملُ الخدمة بالصفحة يعيد
    إرسالَ التنقّل بـ ``fetch(request)`` فيصل بـ ``Sec-Fetch-Dest: empty`` كأيّ fetch، والوضعُ وحده
    يبقى ``navigate`` (مقيسٌ في Chromium 11-18) — وإلّا رأت الموظّفةُ JSON خاماً بدل صفحة الانضمام."""
    headers = request.headers
    if headers.get('Sec-Fetch-Mode') == 'navigate':
        return False
    return ('/api/' in request.path_info
            or 'application/json' in headers.get('Accept', '')
            or headers.get('X-Requested-With') == 'XMLHttpRequest'
            or headers.get('Sec-Fetch-Dest') == 'empty')


def _top_level_html(request, response):
    """تنقّلُ صفحةٍ أجاب بـ HTML. على HTTP لا ترويساتِ Fetch Metadata أصلاً فيُعدّ تنقّلاً، وعبر عامل
    الخدمة تصير الوجهةُ ``empty`` (انظر ``_wants_json``) — فالإطارُ يُستبعد حين يُعرف وحده."""
    if request.method != 'GET' or response.status_code != 200:
        return False
    if not response.get('Content-Type', '').startswith('text/html'):
        return False
    headers = request.headers
    return (headers.get('Sec-Fetch-Mode', 'navigate') == 'navigate'
            and headers.get('Sec-Fetch-Dest', 'document') in ('document', 'empty'))


class DeviceMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.lx_device = None
        request.lx_policy = None
        user = getattr(request, 'user', None)
        if user is None or not user.is_authenticated:
            return self.get_response(request)

        token = request.COOKIES.get(service.COOKIE_NAME)
        device = service.device_for_token(token) if token else None
        pol = service.policy_or_none()
        request.lx_device = device
        request.lx_policy = pol

        response = self.get_response(request)

        # الخروجُ يجعل الطالبَ مجهولاً في منتصف الطلب: لا لمسَ ولا اكتشافَ بعده.
        if not (pol and pol.server_id) or not request.user.is_authenticated:
            return response
        if device is None:
            if _top_level_html(request, response):
                device, token = service.new_device(request)
                service.set_cookie(response, request, token)
        elif service.touch(device, request):
            service.set_cookie(response, request, token)
        return response

    def process_view(self, request, view_func, view_args, view_kwargs):
        pol = getattr(request, 'lx_policy', None)
        if pol is None or not pol.server_id or pol.mode != pol.MODE_ONLY:
            return None
        device = request.lx_device
        if device is not None and device.is_active:
            return None
        match = request.resolver_match
        if getattr(view_func, 'device_gate_exempt', False) or (
                match is not None and match.url_name in EXEMPT_URL_NAMES):
            return None
        if _wants_json(request):
            response = JsonResponse({'ok': False, 'error': 'device_not_registered',
                                     'message': 'هذا الجهاز غير مسجّل. سجّله بكودٍ من المسؤول.'},
                                    status=403)
            response['Cache-Control'] = 'no-store'
            return response
        return redirect('device_join')
