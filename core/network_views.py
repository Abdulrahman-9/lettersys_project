"""
core.network_views
==================
Views and APIs for multi-device LAN network binding.

Architecture
────────────
• Master device  — runs PostgreSQL + Django; all slaves connect to its DB.
• Slave device   — runs Django; DB_HOST in .env points to master's IP.
• Sequential counters  — already protected by F() atomic updates + SELECT FOR UPDATE.
  No extra sync logic needed once all devices share the same PostgreSQL instance.
• NetworkNode table    — stored in the shared DB; every device can see every device.
• Conflict prevention  — DB-level locking (already in place) + heartbeat tracking.
"""

import concurrent.futures
import json
import logging
import os
import re
import socket
import time
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from .models import NetworkNode, NetworkSettings
from .decorators import rate_limit
from . import device_identity

logger = logging.getLogger('lettersys')

APP_VERSION = '1.0'


# ─── Permission helper ────────────────────────────────────────────────────────

def _is_staff(user):
    return user.is_staff


# ─── Network utility functions ───────────────────────────────────────────────

def _get_local_ip() -> str:
    """يكتشف IP هذا الجهاز على الشبكة المحلية."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


def _get_hostname() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return 'unknown'


def _ping_node(ip: str, port: int = 8000, timeout: float = 1.5) -> dict | None:
    """
    يختبر الاتصال بجهاز LetterSys آخر عبر HTTP.
    يعيد dict بمعلومات الجهاز، أو None إذا تعذّر الاتصال.
    """
    import urllib.request
    t0 = time.monotonic()
    url = f'http://{ip}:{port}/books/api/network/ping/'
    try:
        req = urllib.request.Request(url, headers={'X-Requested-With': 'XMLHttpRequest'})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ping_ms = int((time.monotonic() - t0) * 1000)
            data = json.loads(resp.read().decode('utf-8'))
            if data.get('lettersys') is True:
                data['ping_ms'] = ping_ms
                data['ip'] = ip
                data['port'] = port
                return data
    except Exception:
        pass
    return None


def _test_db_connection(host: str, port: int, db_name: str, user: str, password: str) -> tuple:
    """
    يختبر الاتصال المباشر بـ PostgreSQL.
    يعيد (True, version_string) أو (False, error_message).
    """
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=host, port=port, dbname=db_name,
            user=user, password=password, connect_timeout=5,
        )
        cur = conn.cursor()
        cur.execute('SELECT version();')
        ver = cur.fetchone()[0]
        conn.close()
        return True, ver
    except ImportError:
        # psycopg2 not directly importable — use Django's wrapper
        try:
            from django.db.backends.postgresql.base import DatabaseWrapper
            params = {
                'ENGINE': 'django.db.backends.postgresql',
                'NAME': db_name, 'USER': user, 'PASSWORD': password,
                'HOST': host, 'PORT': str(port),
                'TIME_ZONE': settings.TIME_ZONE,
                'CONN_MAX_AGE': 0, 'AUTOCOMMIT': True,
                'OPTIONS': {'connect_timeout': 5},
                'ATOMIC_REQUESTS': False, 'TEST': {},
                'DISABLE_SERVER_SIDE_CURSORS': False,
            }
            wrapper = DatabaseWrapper(params, alias='_net_test')
            conn = wrapper.get_new_connection(wrapper.get_connection_params())
            conn.close()
            return True, 'اتصال ناجح'
        except Exception as exc:
            return False, str(exc)
    except Exception as exc:
        return False, str(exc)


def _write_env_value(key: str, value: str):
    """يكتب / يحدّث مفتاحاً في ملف .env ."""
    env_path = os.path.join(settings.BASE_DIR, '.env')
    new_line = f'{key}={value}'
    try:
        if os.path.exists(env_path):
            content = open(env_path, 'r', encoding='utf-8').read()
            pattern = rf'^{re.escape(key)}=.*'
            if re.search(pattern, content, re.MULTILINE):
                content = re.sub(pattern, new_line, content, flags=re.MULTILINE)
            else:
                sep = '' if content.endswith('\n') else '\n'
                content = content + sep + new_line + '\n'
            open(env_path, 'w', encoding='utf-8').write(content)
        else:
            open(env_path, 'w', encoding='utf-8').write(new_line + '\n')
    except Exception as exc:
        logger.warning('[NetworkSettings] cannot write .env [%s]: %s', key, exc)


def _scan_subnet(subnet_base: str, port: int = 8000, timeout: float = 0.8) -> list:
    """
    يمسح الشبكة الفرعية subnet_base.1-254 بحثاً عن نُسَخ LetterSys.
    يُنفَّذ بـ 64 خيطاً متوازياً مع timeout إجمالي 15 ثانية.
    """
    local_ip = _get_local_ip()
    found = []

    def _check(i):
        ip = f'{subnet_base}.{i}'
        if ip == local_ip:
            return None
        # 1) فحص منفذ TCP سريع
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout * 0.35)
            open_port = s.connect_ex((ip, port)) == 0
            s.close()
            if not open_port:
                return None
        except Exception:
            return None
        # 2) التحقق من هوية LetterSys
        return _ping_node(ip, port, timeout=timeout * 0.65)

    with concurrent.futures.ThreadPoolExecutor(max_workers=64) as ex:
        futs = [ex.submit(_check, i) for i in range(1, 255)]
        for fut in concurrent.futures.as_completed(futs, timeout=15):
            try:
                result = fut.result()
                if result:
                    found.append(result)
            except Exception:
                pass

    return found


def _active_sessions_count() -> int:
    """يعدّ الجلسات النشطة (غير المنتهية)."""
    try:
        from django.contrib.sessions.models import Session
        return Session.objects.filter(expire_date__gt=timezone.now()).count()
    except Exception:
        return 0


def _register_self(cfg: NetworkSettings):
    """يسجّل هذا الجهاز في جدول NetworkNode ويُميّزه بـ is_current=True."""
    local_ip = _get_local_ip()
    role = cfg.role if cfg.role != NetworkSettings.ROLE_STANDALONE else NetworkNode.ROLE_MASTER
    node, _ = NetworkNode.objects.update_or_create(
        ip_address=local_ip,
        app_port=cfg.app_port,
        defaults={
            'name':       device_identity.get_device_name(),
            'role':       role,
            'is_online':  True,
            'is_current': True,
            'last_seen':  timezone.now(),
            'app_version': APP_VERSION,
        },
    )
    NetworkNode.objects.exclude(pk=node.pk).filter(is_current=True).update(is_current=False)
    return node


# ─── Page view ────────────────────────────────────────────────────────────────

@login_required
@user_passes_test(_is_staff)
def network_settings_page(request):
    """صفحة إعدادات الربط الشبكي الرئيسية."""
    cfg = NetworkSettings.get()
    nodes = NetworkNode.objects.all()
    local_ip = _get_local_ip()
    hostname = _get_hostname()
    db = settings.DATABASES.get('default', {})

    return render(request, 'core/network_settings.html', {
        'cfg': cfg,
        'nodes': nodes,
        'local_ip': local_ip,
        'hostname': hostname,
        'device_name': device_identity.get_device_name(),
        'active_users': _active_sessions_count(),
        'current_db_host': db.get('HOST', 'localhost'),
        'current_db_port': db.get('PORT', '5432'),
        'current_db_name': db.get('NAME', ''),
        'current_db_user': db.get('USER', ''),
    })


# ─── Public health-check endpoint ────────────────────────────────────────────

@require_GET
def network_ping(request):
    """
    نقطة الفحص الصحي — مفتوحة بلا تسجيل دخول.
    تُستخدم من أجهزة أخرى لاكتشاف هذه النسخة والتحقق منها.
    """
    cfg = NetworkSettings.get()
    return JsonResponse({
        'lettersys':    True,
        'status':       'ok',
        'role':         cfg.role,
        'name':         device_identity.get_device_name(),
        'version':      APP_VERSION,
        'ip':           _get_local_ip(),
        'active_users': _active_sessions_count(),
        'timestamp':    timezone.now().isoformat(),
    })


# ─── Configuration API ────────────────────────────────────────────────────────

@login_required
@user_passes_test(_is_staff)
@require_POST
def network_save_config(request):
    """يحفظ الإعدادات ويكتبها إلى .env إذا احتاجت إعادة تشغيل."""
    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({'ok': False, 'error': 'بيانات غير صالحة'}, status=400)

    cfg = NetworkSettings.get()
    role = data.get('role', 'standalone')
    cfg.role        = role
    # اسم الجهاز يُخزَّن محلياً (لكل جهاز) — المصدر الموثوق؛ ونُبقي نسخة في cfg للتوافق.
    device_name     = device_identity.set_device_name(data.get('device_name', ''))
    cfg.device_name = device_name
    cfg.this_host   = data.get('this_host', '').strip() or None
    try:
        cfg.app_port = int(data.get('app_port', 8000))
    except (ValueError, TypeError):
        cfg.app_port = 8000

    needs_restart = False

    if role == NetworkSettings.ROLE_SLAVE:
        cfg.master_host     = data.get('master_host', '').strip()
        try:
            cfg.master_db_port = int(data.get('master_db_port', 5432))
        except (ValueError, TypeError):
            cfg.master_db_port = 5432
        cfg.master_db_name  = data.get('master_db_name', 'lettersys').strip()
        cfg.master_db_user  = data.get('master_db_user', 'lettersys_user').strip()
        pw = data.get('master_db_password', '')
        if pw:
            cfg.set_db_password(pw)

        # كتابة إعدادات DB إلى .env لتُقرأ عند إعادة التشغيل
        _write_env_value('DB_HOST',     cfg.master_host)
        _write_env_value('DB_PORT',     str(cfg.master_db_port))
        _write_env_value('DB_NAME',     cfg.master_db_name)
        _write_env_value('DB_USER',     cfg.master_db_user)
        if pw:
            _write_env_value('DB_PASSWORD', pw)
        needs_restart = True

    cfg.is_configured = True
    cfg.configured_at = timezone.now()
    cfg.configured_by = request.user
    cfg.save()

    _register_self(cfg)
    logger.info('[NetworkSettings] saved by %s — role=%s', request.user.username, role)

    return JsonResponse({
        'ok':            True,
        'needs_restart': needs_restart,
        'message':       (
            'تم الحفظ. يرجى إعادة تشغيل الخادم لتطبيق إعدادات قاعدة البيانات الجديدة.'
            if needs_restart else 'تم حفظ الإعدادات.'
        ),
    })


# ─── Test endpoints ───────────────────────────────────────────────────────────

@login_required
@user_passes_test(_is_staff)
@require_POST
@rate_limit('network_test_db', max_attempts=5, window_seconds=300, by='user')
def network_test_db(request):
    """يختبر الاتصال بـ PostgreSQL خارجي."""
    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({'ok': False, 'error': 'بيانات غير صالحة'}, status=400)

    host     = data.get('host', '').strip()
    port     = int(data.get('port', 5432) or 5432)
    db_name  = data.get('db_name', 'lettersys').strip()
    user     = data.get('user', '').strip()
    password = data.get('password', '').strip()

    if not host:
        return JsonResponse({'ok': False, 'error': 'أدخل عنوان IP الماستر'})

    ok, msg = _test_db_connection(host, port, db_name, user, password)
    return JsonResponse({
        'ok':      ok,
        'message': msg if ok else f'فشل الاتصال: {msg}',
    })


@login_required
@user_passes_test(_is_staff)
@require_POST
@rate_limit('network_test_ping', max_attempts=10, window_seconds=60, by='user')
def network_test_ping(request):
    """يختبر الاتصال بجهاز LetterSys آخر ويحدّث سجله."""
    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({'ok': False, 'error': 'بيانات غير صالحة'}, status=400)

    ip   = data.get('ip', '').strip()
    port = int(data.get('port', 8000) or 8000)
    if not ip:
        return JsonResponse({'ok': False, 'error': 'عنوان IP مطلوب'})

    result = _ping_node(ip, port)
    if result:
        node, _ = NetworkNode.objects.update_or_create(
            ip_address=ip, app_port=port,
            defaults={
                'name':       result.get('name', ip),
                'role':       result.get('role', NetworkNode.ROLE_SLAVE),
                'is_online':  True,
                'last_seen':  timezone.now(),
                'last_ping_ms': result.get('ping_ms'),
                'app_version': result.get('version', ''),
            },
        )
        return JsonResponse({'ok': True, 'data': result})
    else:
        NetworkNode.objects.filter(ip_address=ip, app_port=port).update(is_online=False)
        return JsonResponse({
            'ok': False,
            'error': f'تعذّر الاتصال بـ {ip}:{port} — تأكد من تشغيل LetterSys على ذلك الجهاز.',
        })


# ─── Subnet scanner ──────────────────────────────────────────────────────────

@login_required
@user_passes_test(_is_staff)
@require_POST
@rate_limit('network_scan_subnet', max_attempts=3, window_seconds=300, by='user')
def network_scan_subnet(request):
    """
    يمسح الشبكة المحلية بحثاً عن أجهزة LetterSys (8–15 ثانية).
    """
    try:
        data = json.loads(request.body) if request.body else {}
    except Exception:
        data = {}

    port = int(data.get('port', 8000) or 8000)
    local_ip = _get_local_ip()
    subnet_base = '.'.join(local_ip.split('.')[:3])

    found = _scan_subnet(subnet_base, port=port)

    for node_data in found:
        NetworkNode.objects.update_or_create(
            ip_address=node_data.get('ip'),
            app_port=node_data.get('port', port),
            defaults={
                'name':       node_data.get('name', node_data.get('ip')),
                'role':       node_data.get('role', NetworkNode.ROLE_SLAVE),
                'is_online':  True,
                'last_seen':  timezone.now(),
                'last_ping_ms': node_data.get('ping_ms'),
                'app_version': node_data.get('version', ''),
            },
        )

    return JsonResponse({
        'ok':     True,
        'found':  found,
        'count':  len(found),
        'subnet': f'{subnet_base}.0/24',
    })


# ─── Device registry APIs ─────────────────────────────────────────────────────

@login_required
@user_passes_test(_is_staff)
@require_GET
def network_devices(request):
    """يعيد قائمة الأجهزة المسجّلة مع حالتها الحالية."""
    # تعليم الأجهزة القديمة (لم تُرَ منذ > دقيقتين) كغير متصلة
    cutoff = timezone.now() - timedelta(minutes=2)
    NetworkNode.objects.filter(last_seen__lt=cutoff, is_online=True).update(is_online=False)

    nodes = NetworkNode.objects.all()
    devices = []
    for n in nodes:
        devices.append({
            'id':         n.pk,
            'name':       n.name,
            'ip':         n.ip_address,
            'port':       n.app_port,
            'role':       n.role,
            'is_online':  n.is_online,
            'is_current': n.is_current,
            'last_seen':  n.last_seen.isoformat() if n.last_seen else None,
            'ping_ms':    n.last_ping_ms,
            'version':    n.app_version,
        })

    return JsonResponse({
        'ok':           True,
        'devices':      devices,
        'active_users': _active_sessions_count(),
        'local_ip':     _get_local_ip(),
    })


@login_required
@user_passes_test(_is_staff)
@require_POST
def network_ping_all(request):
    """يختبر الاتصال بجميع الأجهزة المسجّلة بالتوازي."""
    nodes = list(NetworkNode.objects.filter(is_current=False))
    results = []

    def _ping_one(node):
        result = _ping_node(node.ip_address, node.app_port)
        node.update_status(bool(result), result.get('ping_ms') if result else None)
        return {'id': node.pk, 'is_online': node.is_online, 'ping_ms': node.last_ping_ms}

    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as ex:
        futs = [ex.submit(_ping_one, n) for n in nodes]
        for f in concurrent.futures.as_completed(futs, timeout=10):
            try:
                results.append(f.result())
            except Exception:
                pass

    return JsonResponse({'ok': True, 'results': results})


@login_required
@user_passes_test(_is_staff)
@require_POST
def network_delete_device(request, pk):
    """يحذف جهازاً من السجل (لا يمكن حذف الجهاز الحالي)."""
    deleted, _ = NetworkNode.objects.filter(pk=pk, is_current=False).delete()
    if deleted:
        return JsonResponse({'ok': True})
    return JsonResponse({'ok': False, 'error': 'لا يمكن حذف الجهاز الحالي أو الجهاز غير موجود'}, status=400)


@login_required
@user_passes_test(_is_staff)
@require_GET
def network_get_local_ip(request):
    """يعيد IP هذا الجهاز المكتشف تلقائياً."""
    return JsonResponse({'ip': _get_local_ip(), 'hostname': _get_hostname()})


# ─── SSE: Real-time device status stream ─────────────────────────────────────

@login_required
@user_passes_test(_is_staff)
@require_GET
def network_devices_stream(request):
    """
    Server-Sent Events — يُرسل حدث 'refresh' عند أي تغيير في حالة الأجهزة.
    المتصفح يُعيد الاتصال تلقائياً عبر EventSource عند انتهاء الـ stream.
    الـ stream يُغلق من تلقاء نفسه بعد 10 دقائق لتحرير workers.
    """
    def _stream():
        last_signature = ''
        # فحص كل 5 ثوانٍ، يُغلق بعد 120 دورة (10 دقائق)
        for _ in range(120):
            try:
                nodes = list(
                    NetworkNode.objects.values('id', 'is_online', 'last_ping_ms', 'last_seen')
                )
                # توقيع خفيف: id + online + ping + last_seen
                sig = '|'.join(
                    f"{n['id']},{int(n['is_online'])},{n['last_ping_ms']},{n['last_seen']}"
                    for n in sorted(nodes, key=lambda x: x['id'])
                )
                if sig != last_signature:
                    last_signature = sig
                    yield 'data: {"type":"refresh"}\n\n'
                else:
                    yield ': keep-alive\n\n'   # تعليق SSE — يمنع timeout المتصفح
            except Exception:
                yield ': error\n\n'
            time.sleep(5)

    response = StreamingHttpResponse(_stream(), content_type='text/event-stream')
    response['Cache-Control']    = 'no-cache'
    response['X-Accel-Buffering'] = 'no'    # تعطيل Nginx buffering
    return response
