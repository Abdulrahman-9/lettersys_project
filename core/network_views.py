"""
core.network_views
==================
Views and APIs for multi-device LAN network binding.

Architecture
────────────
• Master device  — runs PostgreSQL + Django; all slaves connect to its DB.
• Slave device   — runs Django; DB_HOST in the environment file points to the
  master's IP. That file is edited by the administrator, never by this app.
• Sequential counters  — already protected by F() atomic updates + SELECT FOR UPDATE.
  No extra sync logic needed once all devices share the same PostgreSQL instance.
• NetworkNode table    — stored in the shared DB; every device can see every device.
• Conflict prevention  — DB-level locking (already in place) + heartbeat tracking.
"""

import concurrent.futures
import ipaddress
import json
import logging
import re
import socket
import time
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError, connection
from django.db.models import Q

from core.views.helpers import staff_required
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from .models import NetworkNode, NetworkSettings
from .decorators import rate_limit
from .netaddr import is_lan_peer
from . import device_identity

logger = logging.getLogger('lettersys')

APP_VERSION = '1.0'


# ─── Permission helper ────────────────────────────────────────────────────────


# ─── مُقنِّنات المُدخَل ─────────────────────────────────────────────────────────
# الأسطرُ المعروضةُ للنسخ (``env_lines``) يلصقها مديرُ النظام في ملفّ البيئة
# كما هي. و``.strip()`` وحدَه لا يُخرِج سطراً جديداً **داخل** القيمة: قيمةٌ
# مِثل مضيفٍ تليه فاصلةُ أسطرٍ ثمّ ``DEBUG=True`` كانت تُنتج
# سطرَ ``DEBUG=True`` كاملاً في ما يُنسَخ. فالتقنينُ هنا شرطُ صدقِ ما يُعرَض، لا تجميل.
_HOST_RE = re.compile(r'^[A-Za-z0-9](?:[A-Za-z0-9._\-]{0,98}[A-Za-z0-9])?$')
_IDENT_RE = re.compile(r'^[A-Za-z0-9_][A-Za-z0-9_.$\-]{0,99}$')


def _clean_host(raw):
    """مضيفٌ صالحٌ (IP أو اسم) أو ``None``. الفراغُ يعني «لم يُرسَل»."""
    value = (raw or '').strip()
    if not value:
        return ''
    try:
        ipaddress.ip_address(value)
        return value
    except ValueError:
        pass
    return value if _HOST_RE.match(value) else None


def _clean_identifier(raw, default):
    """اسمُ قاعدةٍ أو مستخدمٍ بلا محارفِ تحكّمٍ ولا سطرٍ جديد، أو ``None``."""
    value = (raw or '').strip()
    if not value:
        return default
    return value if _IDENT_RE.match(value) else None


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
    """يعدّ الجلسات التي لم تنتهِ صلاحيتها بعد."""
    from django.contrib.sessions.models import Session
    return Session.objects.filter(expire_date__gt=timezone.now()).count()


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
@staff_required
def network_settings_page(request):
    """صفحة إعدادات الربط الشبكي الرئيسية."""
    cfg = NetworkSettings.get()
    nodes = NetworkNode.objects.all()
    local_ip = _get_local_ip()
    local_port = int(request.get_port())
    hostname = _get_hostname()
    db = settings.DATABASES.get('default', {})
    current_node_id = nodes.filter(
        ip_address=local_ip,
        app_port=local_port,
    ).values_list('pk', flat=True).first()
    stale_node_ids = set(nodes.filter(
        Q(last_seen__lt=timezone.now() - timedelta(minutes=2))
        | Q(last_seen__isnull=True),
    ).values_list('pk', flat=True))

    return render(request, 'core/network_settings.html', {
        'cfg': cfg,
        'nodes': nodes,
        'local_ip': local_ip,
        'current_node_id': current_node_id,
        'stale_node_ids': stale_node_ids,
        'hostname': hostname,
        'device_name': device_identity.get_device_name(),
        'active_sessions': _active_sessions_count(),
        'current_db_host': db.get('HOST', 'localhost'),
        'current_db_port': db.get('PORT', '5432'),
        'current_db_name': db.get('NAME', ''),
        'current_db_user': db.get('USER', ''),
    })


# ─── Public health-check endpoint ────────────────────────────────────────────

# القاعدةُ نفسُها انتقلت إلى ``core.netaddr`` (مصدرٌ وحيد) حين احتاجها حارسُ تشغيل
# وكيل المسح؛ الاسمُ المحلّيُّ باقٍ كي لا يُلمَس نداءاه ولا اختباراتُهما.
_is_lan_peer = is_lan_peer


@require_GET
def network_ping(request):
    """
    نقطة الفحص الصحي — البصمة الدنيا مفتوحة، والتفاصيل لجيران الشبكة الخاصة فقط.

    كانت تكشف الدور واسم الجهاز والإصدار وعدد الجلسات النشطة **لأي طارق**: مسحٌ
    مجّانيّ لخريطة النشر وحجم الاستعمال. اكتشافُ الأقران يحتاج الهوية فعلاً
    (``_ping_node`` يقرأ name/role/version لجدول الأجهزة)، لكنه يجري دائماً داخل
    الشبكة المحلّية — فنقصر التفاصيل عليها. و``active_users`` أُسقط من هنا نهائياً:
    مستهلكه الوحيد صفحة الأجهزة، وهي تأخذه من ``network_devices`` المحميّة.

    ملاحظة لمرحلة ز0: خلف وكيلٍ عكسيّ يصير ``REMOTE_ADDR`` عنوان الوكيل (خاصّ
    دائماً) فيسقط أثر هذا الحارس — عندها تُعطَّل النقطة في وضع الخادم المركزي.
    """
    if not (_is_lan_peer(request) or request.user.is_staff):
        return JsonResponse({'lettersys': True, 'status': 'ok'})

    cfg = NetworkSettings.get()
    return JsonResponse({
        'lettersys':    True,
        'status':       'ok',
        'role':         cfg.role,
        'name':         device_identity.get_device_name(),
        'version':      APP_VERSION,
        'ip':           _get_local_ip(),
        'timestamp':    timezone.now().isoformat(),
    })


# ─── Configuration API ────────────────────────────────────────────────────────

@login_required
@staff_required
@require_POST
def network_save_config(request):
    """يحفظ الإعدادات في قاعدة البيانات — **ولا يكتب في ملفّ البيئة**.

    كانت الدالّةُ تكتب ``DB_*`` (ومعها كلمةُ المرور صريحةً) في ملفّ البيئة ثمّ
    تَعِد بإعادة تشغيلٍ «تُطبّق» التغيير — والكتابةُ يبتلع فشلَها ``except``
    واسع، فتحت ACL الإنتاج (svc:R) كان الوعدُ كاذباً دائماً. الآن تُعاد
    الأسطرُ للنسخ ويُقال صراحةً إنّ التحرير بيد مدير النظام.
    """
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

    # لا يكتب هذا المُعالِجُ في ملفّ البيئة — لا سطرَ واحداً. الأربعةُ غيرُ
    # السرّيّة مخزَّنةٌ في ``NetworkSettings`` كسجلٍّ مرجعيّ، والكتابةُ كانت
    # نسخةً ثانيةً مكشوفةً تدخل كلَّ نسخةٍ احتياطيّة عبر
    # ``CONFIG_FILES = ('.env',)``. الأسطرُ تُعرَض لمدير النظام لينسخها بيده.
    #
    # **وكلمةُ المرور لا تُخزَّن إطلاقاً.** كان السطرُ ``cfg.set_db_password(pw)``
    # يُمرّرها على ``django.core.signing.dumps`` — وذلك **توقيعٌ لا تعمية**:
    # القطعةُ الأولى base64 عاديّة تُفكّ بلا مفتاح، فالكلمةُ كانت مقروءةً في
    # ``core_networksettings`` وفي كلّ ``pg_dump``. ولا قارئَ لها في الإنتاج
    # أصلاً (``get_db_password`` كان بلا نداءٍ واحد) ⟵ سرٌّ مخزَّنٌ بلا فائدةٍ
    # وبلا حماية. صار العمودُ يُفرَّغ عند كلّ حفظ.
    needs_admin_env = False
    env_lines = []

    if role == NetworkSettings.ROLE_SLAVE:
        host = _clean_host(data.get('master_host', ''))
        db_name = _clean_identifier(data.get('master_db_name', ''), 'lettersys')
        db_user = _clean_identifier(data.get('master_db_user', ''), 'lettersys_user')
        bad = [name for name, value in (('master_host', host),
                                        ('master_db_name', db_name),
                                        ('master_db_user', db_user))
               if value is None]
        if bad:
            return JsonResponse({
                'ok': False,
                'error': 'قيمةٌ غيرُ صالحة: ' + '، '.join(bad)
                         + ' — يُسمح بحروفٍ وأرقامٍ و. _ - فقط، بلا فراغاتٍ ولا أسطر.',
            }, status=400)
        cfg.master_host = host
        try:
            cfg.master_db_port = int(data.get('master_db_port', 5432))
        except (ValueError, TypeError):
            cfg.master_db_port = 5432
        cfg.master_db_name = db_name
        cfg.master_db_user = db_user
        pw = data.get('master_db_password', '')

        # إقلاعُ الاتّصال يبقى في ملفّ البيئة بيد مدير النظام، ولا يجوز نقلُه
        # إلى القاعدة: جهازٌ تابعٌ يحتاج ``DB_HOST`` **قبل** أن يفتح أيَّ
        # اتّصال، وصفُّ ``NetworkSettings`` يقيم في قاعدة الماستر ⟵ دورٌ مغلق.
        env_lines = [
            f'DB_HOST={cfg.master_host}',
            f'DB_PORT={cfg.master_db_port}',
            f'DB_NAME={cfg.master_db_name}',
            f'DB_USER={cfg.master_db_user}',
        ]
        if pw:
            # **اسمٌ لا قيمة**: الكلمةُ لا تُصدَّر في JSON ولا تُطبع في سجلّ.
            env_lines.append('DB_PASSWORD=<الكلمة التي أدخلتها>')
        needs_admin_env = True

    # تفريغُ العمود الموروث في كلّ حفظ — أوّلُ زيارةٍ للصفحة تمحو أيَّ نسخةٍ
    # قديمةٍ «موقَّعةٍ» كانت تُقرأ بـbase64 وحدَها.
    cfg.master_db_password_enc = ''

    cfg.is_configured = True
    cfg.configured_at = timezone.now()
    cfg.configured_by = request.user
    cfg.save()

    _register_self(cfg)
    logger.info('[NetworkSettings] saved by %s — role=%s', request.user.username, role)

    return JsonResponse({
        'ok':              True,
        'needs_admin_env': needs_admin_env,
        # يُبقى المفتاحُ القديم بالقيمة نفسها كي لا تُكسَر نسخةٌ قديمةٌ مُكاشة
        # من ``static/network_settings.js``.
        'needs_restart':   needs_admin_env,
        'env_lines':       env_lines,
        'message':         (
            'حُفظت إعداداتُ الماستر في قاعدة البيانات. لتحويل هذا الجهاز إلى '
            'تابعٍ فعلاً، على مدير النظام وضعُ هذه الأسطر في ملفّ البيئة ثمّ '
            'إعادةُ تشغيل الخدمة.'
            if needs_admin_env else 'تم حفظ الإعدادات.'
        ),
    })


# ─── Test endpoints ───────────────────────────────────────────────────────────

@login_required
@staff_required
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
@staff_required
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
@staff_required
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
@staff_required
@require_GET
def network_devices(request):
    """يعيد قائمة الأجهزة المسجّلة مع حالتها الحالية."""
    local_ip = _get_local_ip()
    local_port = int(request.get_port())
    current_identity = (local_ip, local_port)
    checked_at = timezone.now()

    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            database_online = cursor.fetchone()[0] == 1
    except DatabaseError:
        logger.exception('[NetworkHealth] database connectivity check failed')
        database_online = False

    # Remote nodes are online only while their heartbeat is recent. The current
    # HTTP request itself proves that this application node is reachable.
    cutoff = timezone.now() - timedelta(minutes=2)
    stale_nodes = NetworkNode.objects.filter(is_online=True).filter(
        Q(last_seen__lt=cutoff) | Q(last_seen__isnull=True),
    ).exclude(
        ip_address=local_ip,
        app_port=local_port,
    )
    stale_nodes.update(is_online=False)

    nodes = NetworkNode.objects.all()
    devices = []
    for n in nodes:
        is_current = (n.ip_address, n.app_port) == current_identity
        is_stale = not is_current and (
            n.last_seen is None or n.last_seen < cutoff
        )
        devices.append({
            'id':         n.pk,
            'name':       n.name,
            'ip':         n.ip_address,
            'port':       n.app_port,
            'role':       n.role,
            'is_online':  True if is_current else (n.is_online and not is_stale),
            'is_stale':   is_stale,
            'is_current': is_current,
            'last_seen':  checked_at.isoformat() if is_current else (
                n.last_seen.isoformat() if n.last_seen else None
            ),
            'ping_ms':    n.last_ping_ms,
            'version':    n.app_version,
        })

    return JsonResponse({
        'ok':           True,
        'devices':      devices,
        'active_sessions': _active_sessions_count(),
        'local_ip':     local_ip,
        'database': {
            'is_online': database_online,
            'checked_at': checked_at.isoformat(),
            'host': settings.DATABASES.get('default', {}).get('HOST', 'localhost'),
        },
    })


@login_required
@staff_required
@require_POST
def network_ping_all(request):
    """يختبر الاتصال بجميع الأجهزة المسجّلة بالتوازي."""
    local_ip = _get_local_ip()
    local_port = int(request.get_port())
    nodes = list(
        NetworkNode.objects.exclude(
            ip_address=local_ip,
            app_port=local_port,
        )
    )
    results = []

    def _ping_one(node):
        result = _ping_node(node.ip_address, node.app_port)
        node.update_status(bool(result), result.get('ping_ms') if result else None)
        return {
            'id': node.pk,
            'name': node.name,
            'is_online': node.is_online,
            'status': 'online' if node.is_online else 'offline',
            'ping_ms': node.last_ping_ms,
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as ex:
        futures = {ex.submit(_ping_one, node): node for node in nodes}
        for future in concurrent.futures.as_completed(futures):
            node = futures[future]
            try:
                results.append(future.result())
            except Exception:
                logger.exception('[NetworkHealth] failed to check node %s', node.pk)
                results.append({
                    'id': node.pk,
                    'name': node.name,
                    'is_online': False,
                    'status': 'error',
                    'ping_ms': None,
                })

    online = sum(1 for result in results if result['is_online'])
    offline = sum(1 for result in results if result['status'] == 'offline')
    errors = sum(1 for result in results if result['status'] == 'error')
    return JsonResponse({
        'ok': True,
        'checked': len(results),
        'online': online,
        'offline': offline,
        'errors': errors,
        'results': results,
    })


@login_required
@staff_required
@require_POST
def network_delete_device(request, pk):
    """يحذف جهازاً من السجل (لا يمكن حذف الجهاز الحالي)."""
    current_identity = (_get_local_ip(), int(request.get_port()))
    deleted, _ = NetworkNode.objects.filter(pk=pk).exclude(
        ip_address=current_identity[0],
        app_port=current_identity[1],
    ).delete()
    if deleted:
        return JsonResponse({'ok': True})
    return JsonResponse({'ok': False, 'error': 'لا يمكن حذف الجهاز الحالي أو الجهاز غير موجود'}, status=400)


@login_required
@staff_required
@require_GET
def network_get_local_ip(request):
    """يعيد IP هذا الجهاز المكتشف تلقائياً."""
    return JsonResponse({'ip': _get_local_ip(), 'hostname': _get_hostname()})


# ─── SSE: Real-time device status stream ─────────────────────────────────────

@login_required
@staff_required
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
