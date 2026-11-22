"""صفحةُ «الشبكة والأجهزة» وصفحةُ الانضمام وواجهاتُهما — عرضٌ وقراءةُ مُدخَلٍ فقط؛ الحكمُ في ``service``."""
import json
import socket
from datetime import timedelta
from functools import wraps

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from core.netaddr import approved_https_origin
from core.scoping import can_manage_devices, can_open_admin_pages, can_set_up_scanner

from . import service
from .middleware import gate_exempt
from .models import DevicePolicy

ADDRESS_NOTE_DAYS = 14


def _body(request):
    if request.content_type == 'application/json':
        try:
            data = json.loads(request.body or b'{}')
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}
    return request.POST


def _api(view):
    """يحوّل رفضَ الخدمة إلى JSON بحالته؛ ولا يبتلع غيرَه."""
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            response = view(request, *args, **kwargs)
        except service.DeviceError as exc:
            response = JsonResponse({'ok': False, 'error': exc.code, 'message': exc.message, **exc.extra},
                                    status=exc.status)
        token = getattr(request, 'lx_new_token', None)
        if token:                                        # الكوكي يُكتب مع الرفض أيضاً: لا صفَّ يتيماً لكلّ محاولة
            service.set_cookie(response, request, token)
        response['Cache-Control'] = 'no-store'
        return response
    return wrapped


def _device(request):
    """جهازُ هذا المتصفّح كما عرفه الوسيط، أو None: قبل الإعلان، أو حين يُستدعى العرضُ بلا وسيط
    (حارسُ صفحات النشر يعرضها كذلك، وكان سيعدّ صفحةَ الشبكة عطباً فيُرجع النشر)."""
    return getattr(request, 'lx_device', None)


def _ensure_device(request):
    """جهازُ هذا المتصفّح، يُنشأ إن لم يكن (قبل إعلان الخادم لا يُنشئه الوسيط)؛ و`_api` يكتب كوكيه."""
    device = _device(request)
    if device is None:
        device, request.lx_new_token = service.new_device(request)
        request.lx_device = device
    return device


def _package_available():
    from core.views.device_setup import _package_path
    return _package_path().is_file()


def _this_device(request, pol):
    device = _device(request)
    if device is None:
        return None
    row = service.device_row(device, pol, timezone.now(), here=device)
    row['status'] = device.status
    row['joined'] = service.ago(device.joined_at) if device.joined_at else ''
    row['requested'] = service.is_requested(device)
    return row


def _common(request, pol):
    return {
        'server_name': socket.gethostname(),
        'approved_origin': approved_https_origin(request),
        'current_origin': request.build_absolute_uri('/').rstrip('/'),
        'server_declared': service.server_device(pol) is not None,
        'is_server_here': service.is_server_device(request),
        'kit_version': service.kit_version(),
        'package_available': request.is_secure() and _package_available(),
        'agent_port': settings.LETTERSYS_AGENT_PORT,
        'declare_path': str(service.declare_code_path()),
        'can_declare': can_manage_devices(request.user),
        'scanner_settings_url': reverse('scan_settings') if can_set_up_scanner(request.user) else '',
    }


@login_required
@require_GET
@never_cache
def network_page(request):
    """المديرُ العامّ يرى السجلَّ كلَّه؛ وغيرُه يرى جهازَه وحده."""
    pol = service.policy()
    is_admin = can_manage_devices(request.user)
    context = _common(request, pol)
    context.update({
        'is_admin': is_admin,
        'can_open_settings': can_open_admin_pages(request.user),
        'mode': pol.mode,
        'modes': DevicePolicy.MODE_CHOICES,
        'this_device': _this_device(request, pol),
        'share_path': getattr(settings, 'WORKSTATION_SHARE_PATH', ''),
    })
    if is_admin:
        service.prune()
        pol = service.track_addresses(pol)
        recent = pol.addresses_changed_at and timezone.now() - pol.addresses_changed_at < timedelta(days=ADDRESS_NOTE_DAYS)
        context.update({
            'board': service.board(here=_device(request)),
            'addresses': pol.server_addresses,
            'address_change': {
                'old': '، '.join(pol.previous_addresses), 'new': '، '.join(pol.server_addresses),
                'at': timezone.localtime(pol.addresses_changed_at),
            } if recent and pol.previous_addresses else None,
            'can_approve': service.can_approve(request),
        })
    return render(request, 'core/devices/page.html', context)


@gate_exempt
@login_required
@require_GET
@never_cache
def join_page(request):
    pol = service.policy()
    context = _common(request, pol)
    device = _device(request)
    context.update({
        'this_device': _this_device(request, pol),
        'registered': bool(device and device.is_active),
        'requested': bool(device and service.is_requested(device)),
    })
    return render(request, 'core/devices/join.html', context)


# ─── واجهاتُ الجهاز نفسه (مفتوحةٌ لغير المسجّل) ──────────────────────────────

@gate_exempt
@login_required
@require_GET
@_api
def api_me(request):
    device = _device(request)
    pol = service.policy_or_none()
    return JsonResponse({
        'ok': True,
        'server_time': int(timezone.now().timestamp() * 1000),
        'registered': bool(device and device.is_active),
        'name': device.name if device else '',
        'requested': bool(device and service.is_requested(device)),
        'is_server': bool(device and pol and pol.server_id == device.pk),
    })


@gate_exempt
@login_required
@require_POST
@_api
def api_join_check(request):
    if service.server_device() is None:
        raise service.DeviceError('no_server', 'لم يُعلَن خادمٌ بعد. اطلب من المدير العامّ إعلانه.')
    service.check_code(request, _body(request).get('code'), _ensure_device(request))
    return JsonResponse({'ok': True})


@gate_exempt
@login_required
@require_POST
@_api
def api_join_finish(request):
    if service.server_device() is None:
        raise service.DeviceError('no_server', 'لم يُعلَن خادمٌ بعد. اطلب من المدير العامّ إعلانه.')
    data = _body(request)
    device = _ensure_device(request)
    raw = data.get('has_scanner')
    has_scanner = None if raw in (None, '') else str(raw).lower() in ('1', 'true', 'yes', 'on')
    device = service.finish_join(request, data.get('code'), device, data.get('name'), has_scanner)
    return JsonResponse({'ok': True, 'name': device.name})


@gate_exempt
@login_required
@require_POST
@_api
def api_join_request(request):
    if service.server_device() is None:
        raise service.DeviceError('no_server', 'لم يُعلَن خادمٌ بعد. اطلب من المدير العامّ إعلانه.')
    service.request_join(request, _ensure_device(request))
    return JsonResponse({'ok': True})


@gate_exempt
@login_required
@require_POST
@_api
def api_declare_start(request):
    code, path, expires = service.start_declare(request)
    del code                                             # الكودُ في الملفّ وحده، لا في الردّ
    return JsonResponse({'ok': True, 'path': str(path),
                         'expires_in': int((expires - timezone.now()).total_seconds())})


@gate_exempt
@login_required
@require_POST
@_api
def api_declare_finish(request):
    data = _body(request)
    device = service.finish_declare(request, data.get('code'), _ensure_device(request),
                                    data.get('name') or '')
    return JsonResponse({'ok': True, 'name': device.name})


@login_required
@require_POST
@_api
def api_report(request):
    service.report(request, _device(request), _body(request))
    return JsonResponse({'ok': True})


# ─── واجهاتُ المسؤول ────────────────────────────────────────────────────────

@login_required
@require_GET
@_api
def api_board(request):
    if not can_manage_devices(request.user):
        raise service.DeviceError('forbidden', 'هذا للمدير العامّ وحده.', status=403)
    data = service.board(here=_device(request))
    data['ok'] = True
    data['can_approve'] = service.can_approve(request)
    return JsonResponse(data)


@login_required
@require_POST
@_api
def api_issue_code(request):
    code, plain = service.issue_code(request, _body(request).get('device') or None)
    return JsonResponse({'ok': True, 'id': code.pk, 'code': plain,
                         'seconds_left': int((code.expires_at - timezone.now()).total_seconds()),
                         'ttl': int(service.CODE_TTL.total_seconds()),
                         'for_device': str(code.for_device_id or '')})


@login_required
@require_GET
@_api
def api_code_state(request, pk):
    service.require_approver(request)
    data = service.code_state(pk)
    data['ok'] = True
    return JsonResponse(data)


@login_required
@require_POST
@_api
def api_cancel_code(request, pk):
    return JsonResponse({'ok': service.cancel_code(request, pk)})


@login_required
@require_POST
@_api
def api_device_action(request, pk, action):
    if action == 'dismiss':
        service.dismiss(request, pk)
    elif action == 'revoke':
        service.revoke(request, pk)
    elif action == 'rename':
        service.rename(request, pk, _body(request).get('name'))
    else:
        raise service.DeviceError('bad_action', 'إجراءٌ غير معروف.', status=404)
    return JsonResponse({'ok': True})


@login_required
@require_POST
@_api
def api_mode(request):
    pol = service.set_mode(request, str(_body(request).get('mode') or ''))
    return JsonResponse({'ok': True, 'mode': pol.mode})
