import hashlib
import json
import logging
import re
import secrets
import uuid
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from core.scoping import can_enroll_workstation, can_manage_accounts

from .models import HEARTBEAT_INTERVAL, PAIRING_TTL, TOKEN_LIFETIME, Workstation

logger = logging.getLogger('lettersys')


def _error(code, message, status=400):
    logger.warning('[Workstations] %s', code)
    return JsonResponse({'ok': False, 'code': code, 'error': message}, status=status)


def _payload(request):
    if request.content_type != 'application/json' or len(request.body) > 8192:
        raise ValueError('Invalid JSON content type or length')
    value = json.loads(request.body)
    if not isinstance(value, dict):
        raise ValueError('Expected JSON object')
    return value


def _text(value, limit, required=False):
    if not isinstance(value, str):
        raise ValueError('Expected text')
    value = value.strip()
    if len(value) > limit or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('Invalid text')
    if required and not value:
        raise ValueError('Missing text')
    return value


def _serialize(device):
    return {
        'id': str(device.pk), 'client_uuid': str(device.client_uuid),
        'name': device.name, 'owner': device.owner.get_username(),
        'connection': device.connection_state,
        'blocked': device.blocked_by_admin,
        'last_seen': device.last_seen.isoformat() if device.last_seen else None,
        'agent_version': device.agent_version, 'machine_name': device.machine_name,
        'scanner': device.current_scanner_state,
        'scanner_names': device.scanner_names if device.current_scanner_state == 'ready' else [],
    }


@login_required
@require_POST
@never_cache
def enroll(request):
    if not request.is_secure() or not can_enroll_workstation(request.user):
        return _error('not_authorized', 'التجهيز يحتاج تسجيل الدخول عبر HTTPS الموثوق.', 403)
    try:
        data = _payload(request)
        if set(data) - {'client_uuid', 'name', 'machine_name', 'replace'}:
            raise ValueError('Unexpected fields')
        client_uuid = uuid.UUID(data.get('client_uuid', ''))
        name = _text(data.get('name'), 80, required=True)
        machine_name = _text(data.get('machine_name', ''), 100)
        replace = data.get('replace', False)
        if not isinstance(replace, bool):
            raise ValueError('Invalid replacement flag')
    except (ValueError, TypeError, AttributeError):
        return _error('invalid_registration', 'أدخل اسم الجهاز الصحيح وأعد فحص أدواته.')

    token = secrets.token_urlsafe(32)
    now = timezone.now()
    try:
        with transaction.atomic():
            device = Workstation.objects.select_for_update().filter(client_uuid=client_uuid).first()
            if device and device.owner_id != request.user.pk:
                return _error('different_owner', 'هذا الجهاز مسجّل لحساب آخر. تواصل مع المسؤول.', 409)
            if device and device.blocked_by_admin:
                return _error('device_blocked', 'المسؤول أوقف هذا الجهاز. اطلب منه رفع الإيقاف.', 403)
            if device and not replace:
                return _error('already_registered', 'الجهاز مسجّل. أكّد تجديد ربطه قبل تغيير بياناته.', 409)
            if Workstation.objects.filter(name__iexact=name).exclude(
                client_uuid=client_uuid
            ).exists():
                return _error('name_in_use', 'اسم الجهاز مستخدم. اختر اسماً يميّزه.', 409)
            if device is None:
                device = Workstation(client_uuid=client_uuid, owner=request.user)
            device.name = name
            device.machine_name = machine_name
            device.state = Workstation.State.PAIRING
            device.token_hash = hashlib.sha256(token.encode('ascii')).hexdigest()
            device.token_issued_at = now
            device.expires_at = now + TOKEN_LIFETIME
            device.last_seen = None
            device.scanner_checked_at = None
            device.scanner_state = 'unknown'
            device.scanner_names = []
            device.save()
    except IntegrityError:
        return _error('registration_conflict', 'تعارض تسجيل الجهاز. أعد المحاولة باسم مختلف.', 409)
    logger.info('[Workstations] enrolled device=%s owner=%s', device.pk, request.user.pk)
    return JsonResponse({'ok': True, 'device': _serialize(device), 'token': token})


@csrf_exempt
@require_POST
@never_cache
def heartbeat(request):
    # This credential authenticates this endpoint only, never a browser session.
    if not request.is_secure():
        return _error('https_required', 'HTTPS required', 403)
    authorization = request.headers.get('Authorization', '')
    if not re.fullmatch(r'Bearer [A-Za-z0-9_-]{43}', authorization):
        return _error('invalid_token', 'Device authorization required', 401)
    digest = hashlib.sha256(authorization[7:].encode('ascii')).hexdigest()
    now = timezone.now()
    with transaction.atomic():
        device = Workstation.objects.select_for_update().select_related('owner').filter(
            token_hash=digest
        ).first()
        if not device or not device.owner.is_active or device.state == Workstation.State.REVOKED:
            return _error('device_disabled', 'Device authorization disabled', 401)
        if device.expires_at <= now or (
            device.state == Workstation.State.PAIRING and now - device.token_issued_at > PAIRING_TTL
        ):
            return _error('device_expired', 'Sign in and pair this device again', 401)
        try:
            data = _payload(request)
            if set(data) - {'client_uuid', 'agent_version', 'naps2_available',
                            'scanner_state', 'scanner_names', 'scanner_age_seconds'}:
                raise ValueError('Unexpected fields')
            if uuid.UUID(data.get('client_uuid', '')) != device.client_uuid:
                raise ValueError('Wrong client identity')
            version = _text(data.get('agent_version'), 20, required=True)
            available = data.get('naps2_available')
            state = data.get('scanner_state', 'unknown')
            names = data.get('scanner_names', [])
            age = data.get('scanner_age_seconds')
            if type(available) is not bool or state not in ('unknown', 'ready', 'no_device', 'error'):
                raise ValueError('Invalid capabilities')
            if not isinstance(names, list) or len(names) > 20:
                raise ValueError('Invalid device names')
            names = [_text(name, 100, required=True) for name in names]
            if (state == 'ready') != bool(names) or (state == 'ready' and not available):
                raise ValueError('Inconsistent scanner readiness')
            if age is not None and (type(age) is not int or not 0 <= age <= 86400):
                raise ValueError('Invalid scanner age')
            if state != 'unknown' and age is None:
                raise ValueError('Scanner check timestamp required')
        except (ValueError, TypeError, AttributeError):
            return _error('invalid_status', 'Invalid device status')
        device.state = Workstation.State.ACTIVE
        device.last_seen = now
        device.agent_version = version
        device.naps2_available = available
        device.scanner_state = state
        device.scanner_names = names
        device.scanner_checked_at = now - timedelta(seconds=age) if age is not None else None
        device.save(update_fields=['state', 'last_seen', 'agent_version', 'naps2_available',
                                   'scanner_state', 'scanner_names', 'scanner_checked_at'])
    return JsonResponse({'ok': True, 'heartbeat_seconds': HEARTBEAT_INTERVAL})


@login_required
@require_GET
@never_cache
def my_devices(request):
    devices = Workstation.objects.filter(owner=request.user).select_related('owner')
    return JsonResponse({'ok': True, 'devices': [_serialize(d) for d in devices]})


@login_required
@require_GET
@never_cache
def device_board(request):
    if not can_manage_accounts(request.user):
        raise PermissionDenied('متابعة أجهزة الموظفين لمدير النظام.')
    return render(request, 'core/workstations.html')


@login_required
@require_GET
@never_cache
def device_status(request):
    if not can_manage_accounts(request.user):
        raise PermissionDenied('متابعة أجهزة الموظفين لمدير النظام.')
    devices = Workstation.objects.select_related('owner')
    return JsonResponse({'ok': True, 'devices': [_serialize(d) for d in devices]})


@login_required
@require_POST
@never_cache
def revoke(request, pk):
    if not request.is_secure():
        return _error('https_required', 'إيقاف الربط يحتاج اتصال HTTPS الموثوق.', 403)
    with transaction.atomic():
        device = get_object_or_404(Workstation.objects.select_for_update(), pk=pk)
        if device.owner_id != request.user.pk and not can_manage_accounts(request.user):
            raise PermissionDenied('لا يمكنك تغيير ربط جهاز حساب آخر.')
        device.state = Workstation.State.REVOKED
        device.blocked_by_admin = device.blocked_by_admin or can_manage_accounts(request.user)
        device.save(update_fields=['state', 'blocked_by_admin'])
    logger.info('[Workstations] revoked device=%s actor=%s', device.pk, request.user.pk)
    return JsonResponse({'ok': True})


@login_required
@require_POST
@never_cache
def unblock(request, pk):
    if not request.is_secure() or not can_manage_accounts(request.user):
        raise PermissionDenied('رفع إيقاف الجهاز لمدير النظام عبر HTTPS.')
    device = get_object_or_404(Workstation, pk=pk)
    device.blocked_by_admin = False
    device.save(update_fields=['blocked_by_admin'])
    logger.info('[Workstations] unblocked device=%s actor=%s', device.pk, request.user.pk)
    return JsonResponse({'ok': True})
