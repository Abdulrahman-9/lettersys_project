import logging
import socket
from pathlib import Path
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, HttpResponse, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from core.scoping import can_manage_accounts

logger = logging.getLogger('lettersys')


def _package_path():
    return Path(settings.WORKSTATION_SETUP_PACKAGE)


@login_required
@require_GET
@never_cache
def device_setup(request):
    setup_url = reverse('device_setup')
    secure_setup_url = request.build_absolute_uri(setup_url) if request.is_secure() else ''
    if not secure_setup_url:
        host = urlsplit(request.build_absolute_uri('/')).hostname
        origins = set()
        for origin in settings.CSRF_TRUSTED_ORIGINS:
            parsed = urlsplit(origin)
            if (parsed.scheme == 'https' and parsed.hostname == host
                    and not parsed.username and not parsed.password
                    and parsed.path in ('', '/') and not parsed.query and not parsed.fragment):
                origins.add(origin.rstrip('/'))
        if len(origins) == 1:
            secure_setup_url = origins.pop() + setup_url
    return render(request, 'core/device_setup.html', {
        'package_available': _package_path().is_file(),
        'agent_port': settings.LETTERSYS_AGENT_PORT,
        'can_manage_workstations': can_manage_accounts(request.user),
        'server_name': socket.gethostname(),
        'server_url': request.build_absolute_uri('/'),
        'secure_setup_url': secure_setup_url,
    })


@login_required
@require_GET
@never_cache
def device_setup_health(request):
    return JsonResponse({'ok': True})


@login_required
@require_GET
@never_cache
def device_setup_download(request):
    if not request.is_secure():
        logger.warning('[DeviceSetup] Refused workstation package download over HTTP')
        return HttpResponse(
            'افتح عنوان HTTPS الموثوق لتنزيل حزمة التجهيز، أو احصل عليها من مسؤول النظام مباشرةً.',
            status=400,
            content_type='text/plain; charset=utf-8',
        )
    path = _package_path()
    if path.suffix.lower() not in ('.exe', '.zip'):
        logger.error('[DeviceSetup] Unsupported workstation package format')
        return HttpResponse('حزمة التجهيز مضبوطة بصيغة غير مدعومة. تواصل مع المسؤول.',
                            status=503, content_type='text/plain; charset=utf-8')
    try:
        package = path.open('rb')
    except FileNotFoundError:
        logger.warning('[DeviceSetup] Workstation package is not available')
        return HttpResponse(
            'حزمة تجهيز الأجهزة غير متوفرة حالياً. تواصل مع مسؤول النظام.',
            status=503,
            content_type='text/plain; charset=utf-8',
        )
    return FileResponse(
        package, as_attachment=True,
        filename='LetterSys-Workstation-Setup.exe' if path.suffix.lower() == '.exe' else 'LetterSys-Workstation.zip',
        content_type='application/octet-stream' if path.suffix.lower() == '.exe' else 'application/zip',
    )
