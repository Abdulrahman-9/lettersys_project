"""صفحةُ «حالة الخادم» وواجهتُها والدليل — عرضٌ وقراءةُ مُدخَلٍ فقط؛ الحكمُ في ``checks`` والقاعدةُ في ``scoping``."""
import json
import logging

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from core.audit_service import record_settings_change, settings_snapshot
from core.devices.models import DevicePolicy
from core.scoping import can_view_server_status

from . import checks
from .offline_guide import write_offline_guide

logger = logging.getLogger(__name__)
NAME_MAX, PHONE_MAX = 80, 40


def _context(request):
    report = checks.collect(request)
    return {**report, **checks.notify_contact(), 'official_url': checks.official_url(request),
            'autostart_command': f'sc.exe config {checks.settings.SERVER_STATUS_SERVICE} start= auto'}


@login_required
@require_GET
@never_cache
def status_page(request):
    if not can_view_server_status(request.user):
        raise PermissionDenied
    return render(request, 'core/server_status/page.html', _context(request))


@login_required
@require_GET
@never_cache
def status_api(request):
    """التحديثُ كلّ 30 ثانية: البطاقاتُ مصيَّرةً من القالب نفسه (مصدرٌ واحد للعرض) والخلاصةُ للإعلان."""
    if not can_view_server_status(request.user):
        return JsonResponse({'ok': False, 'error': 'forbidden', 'message': 'هذه الصفحة للمدير العامّ وحده.'},
                            status=403)
    ctx = _context(request)
    return JsonResponse({
        'ok': True,
        'summary': ctx['summary'],
        'autostart_state': ctx['autostart'].state,
        'cards_html': render_to_string('core/server_status/_cards.html', ctx, request=request),
        'checked_at': ctx['checked_at'].isoformat(),
    })


def _payload(request):
    if request.content_type == 'application/json':
        try:
            data = json.loads(request.body or b'{}')
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}
    return request.POST


@login_required
@require_POST
def contact_api(request):
    """«من يُبلَّغ حين يتوقّف الخادم» — يُحفظ في سياسة الأجهزة ويُسجَّل في سجلّ التدقيق."""
    if not can_view_server_status(request.user):
        return JsonResponse({'ok': False, 'error': 'forbidden', 'message': 'هذا للمدير العامّ وحده.'}, status=403)
    data = _payload(request)
    name = str(data.get('name') or '').strip()
    phone = str(data.get('phone') or '').strip()
    if len(name) > NAME_MAX or len(phone) > PHONE_MAX:
        return JsonResponse({'ok': False, 'error': 'too_long',
                             'message': f'الاسمُ حتّى {NAME_MAX} حرفاً والرقمُ حتّى {PHONE_MAX}.'}, status=400)
    pol = DevicePolicy.get()                  # الحفظُ وحده يُنشئ الصفّ؛ القراءةُ في ``checks.notify_contact``
    before = settings_snapshot(pol, ('notify_name', 'notify_phone'))
    pol.notify_name, pol.notify_phone = name, phone
    pol.save(update_fields=['notify_name', 'notify_phone', 'updated_at'])
    record_settings_change(request, 'حالة الخادم', pol, before)
    # النسخةُ على القرص تحمل جهةَ التبليغ، وهي ما يراه المديرُ حين يتوقّف النظام: تُعاد كتابتُها الآن لا مع النشر
    try:
        write_offline_guide(checks.official_url(request) or f'{request.scheme}://{request.get_host()}')
    except OSError as exc:
        logger.warning('server status: contact saved, offline guide not rewritten: %s', exc)
        return JsonResponse({'ok': True, 'guide_written': False,
                             'message': 'حُفظ، ولم تُحدَّث نسخةُ الدليل على القرص.'})
    return JsonResponse({'ok': True, 'guide_written': True, 'message': 'حُفظ.'})


@login_required
@require_GET
def guide_page(request):
    """الدليلُ لكلّ مستخدم: فيه ما يفعله الموظّف حين لا يعمل الماسحُ أو يظهر «Bad Request»."""
    return render(request, 'core/server_status/guide.html', {
        'official_url': checks.official_url(request), **checks.notify_contact(),
        'can_view_status': can_view_server_status(request.user)})
