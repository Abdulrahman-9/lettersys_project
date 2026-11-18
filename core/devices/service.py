"""قواعدُ «الشبكة والأجهزة» — **المصدرُ الوحيد**: الواجهاتُ والوسيطُ والأمرُ تسأل هنا.

قراراتُ المالك (2026-11-18): الخادمُ هو الحاسوبُ الذي يعمل عليه النظام، يعلنه المديرُ العامّ مرّةً
من عليه؛ والأكوادُ تصدر والطلباتُ تُقبل من جهاز الخادم وحده بحساب مديرٍ عامّ؛ والانضمامُ بكودٍ حرّ
من «إضافة جهاز» أو بكودٍ لطلبٍ بعينه؛ والوضعُ عند الإطلاق «تنبيه».

أحكامُ فيبل المطبَّقة: إثباتُ «أنا على الخادم» كودٌ لمرّةٍ واحدة يكتبه الخادمُ في ملفٍّ على قرصه
(خلف Caddy لا يُثبت العنوانُ شيئاً) · التوكِن SHA-256 والكودُ HMAC · المحاولاتُ في القاعدة لا
في الكاش · الاستعمالُ الواحد بتحديثٍ مشروط · صفُّ الاكتشاف عند تنقّل HTML وحده.
"""
import hashlib
import logging
import re
import secrets
import socket
import uuid
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.utils import timezone
from django.utils.crypto import salted_hmac

from core.audit_service import client_ip, record_event, record_settings_change, settings_snapshot
from core.scoping import can_manage_devices

from .models import BrowserDevice, DeviceAttempt, DevicePolicy, PairingCode

logger = logging.getLogger('lettersys')

COOKIE_NAME = 'lx_device'
COOKIE_MAX_AGE = 400 * 24 * 60 * 60          # سقفُ Chrome: 400 يوم، فيُجدَّد دوريّاً
COOKIE_RENEW_AFTER = timedelta(days=30)
TOUCH_EVERY = timedelta(seconds=60)
SEEN_NOW = timedelta(minutes=3)
PRUNE_AFTER = timedelta(days=30)
CODE_LENGTH = 5
CODE_TTL = timedelta(minutes=10)
MAX_OPEN_CODES = 3
DECLARE_LENGTH = 8
DECLARE_TTL = timedelta(minutes=5)
USER_FAIL_LIMIT = 5
USER_LOCK = timedelta(minutes=15)
GLOBAL_FAIL_LIMIT = 30
GLOBAL_WINDOW = timedelta(minutes=10)
REQUEST_REPEAT = timedelta(minutes=2)
NAME_MAX = 60

_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')


class DeviceError(Exception):
    """رفضٌ يُعرض للمستخدم كما هو: ``code`` للواجهة و``message`` بالعربيّة."""
    status = 400

    def __init__(self, code, message, status=None, **extra):
        super().__init__(message)
        self.code = code
        self.message = message
        if status:
            self.status = status
        self.extra = extra


# ─── الهويّة والكوكي ───────────────────────────────────────────────────────────

def hash_token(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def code_digest(code, purpose='join'):
    return salted_hmac(f'core.devices.{purpose}.v1', code, algorithm='sha256').hexdigest()


def digits(raw, length):
    """الأرقامُ وحدها، والعربيّةُ والفارسيّةُ تُقبل — أو ``''`` إن لم تكن ``length`` بالضبط."""
    value = re.sub(r'\D', '', str(raw or '').translate(_DIGITS))
    return value if len(value) == length else ''


def device_for_token(token):
    if not token or len(token) > 100:
        return None
    return BrowserDevice.objects.filter(token_hash=hash_token(token)).first()


def set_cookie(response, request, token):
    response.set_cookie(
        COOKIE_NAME, token, max_age=COOKIE_MAX_AGE, httponly=True, samesite='Lax',
        secure=bool(settings.SESSION_COOKIE_SECURE or request.is_secure()),
    )


_BROWSERS = (('Edg/', 'Edge'), ('OPR/', 'Opera'), ('Firefox/', 'Firefox'), ('Chrome/', 'Chrome'),
             ('Safari/', 'Safari'))
_SYSTEMS = (('Windows NT 10', 'Windows'), ('Windows', 'Windows'), ('Android', 'Android'),
            ('iPhone', 'iPhone'), ('iPad', 'iPad'), ('Mac OS X', 'macOS'), ('Linux', 'Linux'))


def platform_of(user_agent):
    """عائلةُ المتصفّح والنظام فقط — لا يُخزَّن وكيلُ المستخدم كاملاً."""
    ua = user_agent or ''
    browser = next((name for mark, name in _BROWSERS if mark in ua), '')
    system = next((name for mark, name in _SYSTEMS if mark in ua), '')
    return browser, system


def is_phone(device):
    return device.os in ('Android', 'iPhone')


def first_token(request):
    """التوكِنُ الأوّل لمتصفّحٍ بلا كوكي **مشتقٌّ من مفتاح جلسته**: الطلباتُ المتزامنة الأولى (صفحةٌ
    وإطارٌ أو جزءُ HTML — وعلى HTTP لا يرسل المتصفّح Sec-Fetch-Dest) تصل إلى الصفّ نفسه بالكوكي
    نفسه، فلا صفَّ يتيماً يصدر له المسؤولُ كوداً لا يعمل (حكمُ فيبل). المخزَّنُ بصمتُه وحدها."""
    key = getattr(getattr(request, 'session', None), 'session_key', None)
    if not key:
        return secrets.token_urlsafe(32)
    return salted_hmac('core.devices.first-token.v1', key, algorithm='sha256').hexdigest()


def new_device(request):
    """صفُّ «جهازٍ غير مسجّل» لمتصفّحٍ بلا كوكي، وتوكِنُه الصريح للكوكي."""
    token = first_token(request)
    browser, system = platform_of(request.META.get('HTTP_USER_AGENT'))
    now = timezone.now()
    user = request.user
    device, created = BrowserDevice.objects.get_or_create(token_hash=hash_token(token), defaults={
        'cookie_renewed_at': now, 'browser': browser, 'os': system,
        'last_ip': _ip(request), 'last_seen': now, 'last_user': user,
    })
    if created:
        device.users.add(user)
    return device, token


def touch(device, request):
    """آخرُ ظهورٍ وآخرُ مستخدم، مرّةً في الدقيقة على الأكثر. يعيد True إن حان تجديدُ الكوكي."""
    now = timezone.now()
    user = request.user
    renew = not device.cookie_renewed_at or now - device.cookie_renewed_at >= COOKIE_RENEW_AFTER
    changed_user = device.last_user_id != user.pk
    if not renew and not changed_user and device.last_seen and now - device.last_seen < TOUCH_EVERY:
        return False
    fields = {'last_seen': now, 'last_ip': _ip(request), 'last_user_id': user.pk}
    if renew:
        fields['cookie_renewed_at'] = now
    BrowserDevice.objects.filter(pk=device.pk).update(**fields)
    if changed_user:
        device.users.add(user)
    return renew


def _ip(request):
    value = client_ip(request) or ''
    try:
        import ipaddress
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


# ─── السياسة والخادم ────────────────────────────────────────────────────────────

def policy():
    return DevicePolicy.get()


def policy_or_none():
    return DevicePolicy.objects.filter(pk=1).first()


def server_device(pol=None):
    pol = pol if pol is not None else policy_or_none()
    if pol is None or not pol.server_id:
        return None
    device = pol.server
    return device if device and device.is_active else None


def is_server_device(request):
    device = getattr(request, 'lx_device', None)
    pol = getattr(request, 'lx_policy', None) or policy_or_none()
    return bool(device and pol and pol.server_id == device.pk and device.is_active)


def can_approve(request):
    """إصدارُ الأكواد وقبولُ الطلبات وتغييرُ الوضع: مديرٌ عامّ **على جهاز الخادم**."""
    return can_manage_devices(request.user) and is_server_device(request)


def require_approver(request):
    if not can_manage_devices(request.user):
        raise DeviceError('forbidden', 'هذا للمدير العامّ وحده.', status=403)
    if not is_server_device(request):
        raise DeviceError('not_server', 'تصدر الأكوادُ وتُقبل الطلباتُ من جهاز الخادم وحده.', status=403)


def declare_code_path():
    return Path(getattr(settings, 'DEVICES_DECLARE_CODE_FILE', '')
                or Path(settings.BASE_DIR) / 'var' / 'server_declare_code.txt')


def start_declare(request):
    """يكتب الخادمُ كوداً من ثمانية أرقام في ملفٍّ على قرصه: مَن يقرؤه جالسٌ على الخادم (أو مديرٌ
    عليه). يعمل على أيّ عنوان، ويُعاد إن ضاع الكوكي."""
    if not can_manage_devices(request.user):
        raise DeviceError('forbidden', 'إعلانُ الخادم للمدير العامّ وحده.', status=403)
    code = f'{secrets.randbelow(10 ** DECLARE_LENGTH):0{DECLARE_LENGTH}d}'
    expires = timezone.now() + DECLARE_TTL
    path = declare_code_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f'LetterSys - server code: {code}\r\nValid until {timezone.localtime(expires):%H:%M}. '
            f'Type it on the "Network and devices" page, then this file is cleared.\r\n',
            encoding='utf-8',
        )
    except OSError:
        logger.warning('[Devices] cannot write the declare-code file %s', path, exc_info=True)
        raise DeviceError('write_failed', 'تعذّر على النظام كتابةُ الكود على قرص الخادم. شغّل على الخادم: '
                                          'python manage.py devices_gate --declare-code', status=503)
    pol = policy()
    pol.declare_code_hash = code_digest(code, 'declare')
    pol.declare_code_expires = expires
    pol.save(update_fields=['declare_code_hash', 'declare_code_expires', 'updated_at'])
    record_event(request, 'EDIT_SETTINGS', metadata={
        'section': 'الشبكة والأجهزة', 'summary': 'طُلب كودُ إعلان الخادم (كُتب على قرص الخادم)'})
    return code, path, expires


def issue_declare_code_console():
    """الطريقُ البديل من الخادم نفسه (``manage.py devices_gate --declare-code``)."""
    code = f'{secrets.randbelow(10 ** DECLARE_LENGTH):0{DECLARE_LENGTH}d}'
    pol = policy()
    pol.declare_code_hash = code_digest(code, 'declare')
    pol.declare_code_expires = timezone.now() + DECLARE_TTL
    pol.save(update_fields=['declare_code_hash', 'declare_code_expires', 'updated_at'])
    return code


def finish_declare(request, raw_code, device, name=''):
    """يعلن متصفّحَ هذا الطلب جهازَ الخادم: مديرٌ عامّ + الكودُ المكتوبُ على قرص الخادم."""
    if not can_manage_devices(request.user):
        raise DeviceError('forbidden', 'إعلانُ الخادم للمدير العامّ وحده.', status=403)
    _check_lock(request.user, DeviceAttempt.DECLARE)
    code = digits(raw_code, DECLARE_LENGTH)
    if not code:
        raise DeviceError('bad_format', 'الكودُ ثمانيةُ أرقام.')
    now = timezone.now()
    if device is None:
        raise DeviceError('no_device', 'أعد تحميل الصفحة ثمّ حاول من جديد.')
    pol = policy()
    valid = bool(pol.declare_code_hash and pol.declare_code_expires and pol.declare_code_expires > now
                 and secrets.compare_digest(pol.declare_code_hash, code_digest(code, 'declare')))
    _record_attempt(request, DeviceAttempt.DECLARE, device, ok=valid)
    if not valid:
        left = _attempts_left(request.user, DeviceAttempt.DECLARE)
        raise DeviceError('bad_code', 'الكودُ غير صحيح أو انتهت مدّته. اطلب كوداً جديداً.', left=left)
    with transaction.atomic():
        pol = DevicePolicy.objects.select_for_update().get(pk=1)
        before = settings_snapshot(pol, ('server',))
        if pol.server_id and pol.server_id != device.pk:
            # نقلُ الخادم (أو ضياعُ كوكيه): المتصفّحُ القديم لم يعد الخادم، ويعود بكودٍ إن احتيج.
            BrowserDevice.objects.filter(pk=pol.server_id).update(
                status=BrowserDevice.Status.REVOKED, revoked_at=now, revoked_by=request.user)
        device.status = BrowserDevice.Status.ACTIVE
        device.name = _clean_name(name or device.name or 'الخادم', exclude=device)
        if not device.joined_at:
            device.joined_at, device.joined_by = now, request.user
        device.approved_by = request.user
        _save_named(device, ['status', 'name', 'joined_at', 'joined_by', 'approved_by'])
        pol.server = device
        pol.server_declared_at = now
        pol.declare_code_hash, pol.declare_code_expires = '', None
        pol.save(update_fields=['server', 'server_declared_at', 'declare_code_hash',
                                'declare_code_expires', 'updated_at'])
    _clear_declare_file()
    record_settings_change(request, 'الشبكة والأجهزة', pol, before)
    return device


def _clear_declare_file():
    try:
        declare_code_path().write_text('', encoding='utf-8')
    except OSError:
        logger.warning('[Devices] could not clear the declare-code file', exc_info=True)


def set_mode(request, mode):
    require_approver(request)
    valid = {m for m, _ in DevicePolicy.MODE_CHOICES}
    if mode not in valid:
        raise DeviceError('bad_mode', 'وضعٌ غير معروف.')
    pol = policy()
    before = settings_snapshot(pol, ('mode',))
    pol.mode = mode
    pol.save(update_fields=['mode', 'updated_at'])
    record_settings_change(request, 'الشبكة والأجهزة', pol, before)
    return pol


def server_addresses():
    """عنوانُ واجهة المسار الافتراضيّ وحده — للعرض ولكشف التغيّر.

    كلُّ عناوين المضيف تشمل محوّلاتٍ وهميّة (WSL و«الاتّصال المحلّيّ» لـWi-Fi Direct) تظهر وتختفي
    بتشغيلها، فكانت تُنذر «تغيّر العنوان» زوراً وتكتب فوق السابق (مقيسٌ على FOLLOW2، فيبل).
    ``connect`` على UDP يختار الواجهة من جدول المسارات **ولا يرسل شيئاً**."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(('8.8.8.8', 9))
        address = probe.getsockname()[0]
    except OSError:
        return []
    finally:
        probe.close()
    return [] if address.startswith(('127.', '0.')) else [address]


def track_addresses(pol=None):
    """يسجّل العناوينَ الحاليّة ويحفظ السابقة إن تغيّرت. يعيد السياسة."""
    pol = pol or policy()
    current = server_addresses()
    if current and current != (pol.server_addresses or []):
        if pol.server_addresses:
            pol.previous_addresses = pol.server_addresses
            pol.addresses_changed_at = timezone.now()
        pol.server_addresses = current
        pol.save(update_fields=['server_addresses', 'previous_addresses', 'addresses_changed_at',
                                'updated_at'])
    return pol


# ─── الأكواد ───────────────────────────────────────────────────────────────────

def _open_codes():
    return PairingCode.objects.filter(used_at__isnull=True, cancelled_at__isnull=True)


def _close_expired(now):
    _open_codes().filter(expires_at__lte=now).update(cancelled_at=now)


def issue_code(request, for_device_id=None):
    """كودٌ من خمسة أرقام. ``for_device_id`` = لطلبٍ بعينه (لا يعمل على غيره)."""
    require_approver(request)
    now = timezone.now()
    target = None
    if for_device_id:
        try:
            target = BrowserDevice.objects.filter(pk=uuid.UUID(str(for_device_id))).first()
        except ValueError:
            target = None
        if target is None or target.is_active:
            raise DeviceError('bad_target', 'هذا الجهاز مسجّلٌ أصلاً أو لم يعد موجوداً.')
    with transaction.atomic():
        _close_expired(now)
        if target is not None:
            _open_codes().filter(for_device=target).update(cancelled_at=now)
        if _open_codes().count() >= MAX_OPEN_CODES:
            raise DeviceError('too_many', f'لديك {MAX_OPEN_CODES} أكوادٍ سارية. ألغِ أحدها أو انتظر انتهاءه.')
        for _ in range(20):
            plain = f'{secrets.randbelow(10 ** CODE_LENGTH):0{CODE_LENGTH}d}'
            try:
                with transaction.atomic():
                    code = PairingCode.objects.create(
                        code_hash=code_digest(plain), issued_by=request.user, issued_at=now,
                        expires_at=now + CODE_TTL, for_device=target)
                break
            except IntegrityError:
                continue
        else:                                                    # pragma: no cover - 20 تصادماً متتالياً
            raise DeviceError('busy', 'تعذّر إصدار كود. حاول مرّةً أخرى.')
    record_event(request, 'EDIT_SETTINGS', metadata={
        'section': 'الشبكة والأجهزة',
        'summary': 'أُصدر كودُ انضمام' + (f' لجهاز {target}' if target else ' (إضافةٌ مباشرة)')})
    return code, plain


def cancel_code(request, code_id):
    require_approver(request)
    return _open_codes().filter(pk=code_id).update(cancelled_at=timezone.now()) == 1


def code_state(code_id):
    code = PairingCode.objects.select_related('used_device', 'used_by').filter(pk=code_id).first()
    if code is None:
        return {'state': 'missing'}
    if code.used_at:
        return {'state': 'used', 'device': str(code.used_device or ''),
                'user': _person(code.used_by), 'at': code.used_at.isoformat()}
    if code.cancelled_at:
        return {'state': 'cancelled'}
    if code.expires_at <= timezone.now():
        return {'state': 'expired'}
    return {'state': 'waiting', 'seconds_left': int((code.expires_at - timezone.now()).total_seconds())}


# ─── المحاولات ─────────────────────────────────────────────────────────────────

def _record_attempt(request, kind, device, ok):
    DeviceAttempt.objects.create(kind=kind, user=request.user, device=device, ip=_ip(request), ok=ok)


def _attempts_left(user, kind):
    since = timezone.now() - USER_LOCK
    failed = DeviceAttempt.objects.filter(kind=kind, user=user, ok=False, at__gte=since).count()
    return max(0, USER_FAIL_LIMIT - failed)


def lock_seconds(user, kind=DeviceAttempt.JOIN):
    """ثوانٍ باقيةٌ من الإيقاف (لحسابه أو للجميع)، أو 0."""
    now = timezone.now()
    mine = list(DeviceAttempt.objects.filter(kind=kind, user=user, ok=False, at__gte=now - USER_LOCK)
                .order_by('-at').values_list('at', flat=True)[:USER_FAIL_LIMIT])
    if len(mine) >= USER_FAIL_LIMIT:
        return max(1, int((mine[USER_FAIL_LIMIT - 1] + USER_LOCK - now).total_seconds()))
    everyone = list(DeviceAttempt.objects.filter(kind=kind, ok=False, at__gte=now - GLOBAL_WINDOW)
                    .order_by('-at').values_list('at', flat=True)[:GLOBAL_FAIL_LIMIT])
    if len(everyone) >= GLOBAL_FAIL_LIMIT:
        return max(1, int((everyone[GLOBAL_FAIL_LIMIT - 1] + GLOBAL_WINDOW - now).total_seconds()))
    return 0


def _check_lock(user, kind):
    seconds = lock_seconds(user, kind)
    if seconds:
        minutes = max(1, round(seconds / 60))
        raise DeviceError('locked', f'توقّف إدخالُ الكود {minutes} دقيقة بعد محاولاتٍ خاطئة. '
                                    'اطلب من المسؤول كوداً جديداً.', status=429, retry_after=seconds)


# ─── الانضمام ─────────────────────────────────────────────────────────────────

def _matching_code(plain, device, now):
    code = _open_codes().filter(code_hash=code_digest(plain), expires_at__gt=now).first()
    if code is None or (code.for_device_id and code.for_device_id != device.pk):
        return None
    return code


def check_code(request, raw_code, device):
    """يتحقّق من الكود بلا استهلاك (الخطوةُ الأولى). الخاطئُ يُعدّ محاولة."""
    _guard_joinable(request, device)
    _check_lock(request.user, DeviceAttempt.JOIN)
    plain = digits(raw_code, CODE_LENGTH)
    if not plain:
        raise DeviceError('bad_format', 'الكودُ خمسةُ أرقام.')
    code = _matching_code(plain, device, timezone.now())
    if code is None:
        _fail(request, device)
    return code


def finish_join(request, raw_code, device, name, has_scanner):
    """يستهلك الكودَ ويسجّل الجهاز — بتحديثٍ مشروط يمنع استعمالَه مرّتين."""
    code = check_code(request, raw_code, device)
    clean = _clean_name(name, exclude=device)
    now = timezone.now()
    try:
        with transaction.atomic():
            taken = _open_codes().filter(pk=code.pk, expires_at__gt=now).update(
                used_at=now, used_by=request.user, used_device=device)
            if taken == 1:
                device.status = BrowserDevice.Status.ACTIVE
                device.name = clean
                device.joined_at, device.joined_by = now, request.user
                device.approved_by_id = code.issued_by_id
                device.has_scanner = has_scanner
                device.dismissed_at = None
                device.save(update_fields=['status', 'name', 'joined_at', 'joined_by', 'approved_by',
                                           'has_scanner', 'dismissed_at'])
    except IntegrityError:
        # سباقُ اسمٍ مع جهازٍ آخر: يُلغى الاستهلاكُ مع الحفظ، فالكودُ يبقى صالحاً لاسمٍ آخر.
        raise DeviceError('name_taken', 'هذا الاسم لجهازٍ مسجّلٍ آخر. اختر اسماً غيره.')
    if taken != 1:
        _fail(request, device)
    _record_attempt(request, DeviceAttempt.JOIN, device, ok=True)
    record_event(request, 'EDIT_SETTINGS', metadata={
        'section': 'الشبكة والأجهزة', 'summary': f'انضمّ الجهاز «{clean}»'})
    return device


def _guard_joinable(request, device):
    if device is None:
        raise DeviceError('no_device', 'أعد تحميل الصفحة ثمّ حاول من جديد.')
    if device.is_active:
        raise DeviceError('already', f'هذا الجهاز مسجّلٌ باسم «{device.name}».')


def _fail(request, device):
    _record_attempt(request, DeviceAttempt.JOIN, device, ok=False)
    left = _attempts_left(request.user, DeviceAttempt.JOIN)
    if left <= 0:
        _check_lock(request.user, DeviceAttempt.JOIN)
    raise DeviceError('bad_code', 'الكودُ غير صحيح أو انتهت مدّته.', left=left)


def _clean_name(name, exclude=None):
    clean = re.sub(r'\s+', ' ', str(name or '')).strip()[:NAME_MAX]
    if not clean:
        raise DeviceError('bad_name', 'اكتب اسماً للجهاز.')
    clash = BrowserDevice.objects.filter(status=BrowserDevice.Status.ACTIVE, name__iexact=clean)
    if exclude is not None:
        clash = clash.exclude(pk=exclude.pk)
    if clash.exists():
        raise DeviceError('name_taken', 'هذا الاسم لجهازٍ مسجّلٍ آخر. اختر اسماً غيره.')
    return clean


def request_join(request, device):
    _guard_joinable(request, device)
    now = timezone.now()
    if device.requested_at and now - device.requested_at < REQUEST_REPEAT and not device.dismissed_at:
        return device
    device.requested_at, device.requested_by, device.dismissed_at = now, request.user, None
    device.save(update_fields=['requested_at', 'requested_by', 'dismissed_at'])
    return device


# ─── إدارة الأجهزة ────────────────────────────────────────────────────────────

def _target(device_id):
    device = BrowserDevice.objects.filter(pk=device_id).first()
    if device is None:
        raise DeviceError('missing', 'هذا الجهاز لم يعد موجوداً.', status=404)
    return device


def dismiss(request, device_id):
    require_approver(request)
    device = _target(device_id)
    device.dismissed_at = timezone.now()
    device.save(update_fields=['dismissed_at'])
    return device


def revoke(request, device_id):
    require_approver(request)
    device = _target(device_id)
    if policy().server_id == device.pk:
        raise DeviceError('is_server', 'هذا جهازُ الخادم. أعلن خادماً غيره أوّلاً.')
    device.status = BrowserDevice.Status.REVOKED
    device.revoked_at, device.revoked_by = timezone.now(), request.user
    device.save(update_fields=['status', 'revoked_at', 'revoked_by'])
    _open_codes().filter(for_device=device).update(cancelled_at=timezone.now())
    record_event(request, 'EDIT_SETTINGS', metadata={
        'section': 'الشبكة والأجهزة', 'summary': f'أُلغي تسجيلُ الجهاز «{device.name}»'})
    return device


def rename(request, device_id, name):
    require_approver(request)
    device = _target(device_id)
    if not device.is_active:
        raise DeviceError('not_active', 'يُسمّى الجهازُ المسجّلُ وحده.')
    old = device.name
    device.name = _clean_name(name, exclude=device)
    _save_named(device, ['name'])
    record_event(request, 'EDIT_SETTINGS', metadata={
        'section': 'الشبكة والأجهزة', 'summary': f'الجهاز «{old}» صار «{device.name}»'})
    return device


def _save_named(device, fields):
    """حفظٌ يحمل الاسم: سباقٌ مع جهازٍ أخذ الاسمَ نفسَه بعد الفحص ⟵ رسالةٌ لا 500."""
    try:
        with transaction.atomic():
            device.save(update_fields=fields)
    except IntegrityError:
        raise DeviceError('name_taken', 'هذا الاسم لجهازٍ مسجّلٍ آخر. اختر اسماً غيره.')


_VERSION_RE = re.compile(r'^\d{1,3}(\.\d{1,3}){0,3}$')
_SCANNER_STATES = {'ok', 'none', 'error', 'off'}


def report(request, device, data):
    """ما فحصته صفحةُ الجهاز على وكيله (للعرض عند المسؤول) — نصوصٌ مقصوصةٌ مُتحقَّق منها.

    يُحدَّث **ما جاء في الطلب وحده**: «هذا الجهاز» يرسل نسخةَ الوكيل بلا سرد الماسحات، فكان
    يمسح حالةَ الماسح التي سجّلها الانضمام (فيبل)."""
    if device is None or not device.is_active:
        raise DeviceError('not_active', 'سجّل هذا الجهاز أوّلاً.')
    fields = ['reported_at']
    if 'agent_version' in data:
        version = str(data.get('agent_version') or '')[:20]
        device.agent_version = version if _VERSION_RE.match(version) else ''
        fields.append('agent_version')
    if 'scanner_state' in data:
        state = str(data.get('scanner_state') or '')
        device.scanner_state = state if state in _SCANNER_STATES else ''
        fields.append('scanner_state')
    if 'scanner_label' in data:
        device.scanner_label = re.sub(r'[\x00-\x1f]', '', str(data.get('scanner_label') or ''))[:120]
        fields.append('scanner_label')
    device.reported_at = timezone.now()
    device.save(update_fields=fields)
    return device


ATTEMPTS_KEEP = timedelta(days=90)


def prune(now=None):
    """غيرُ المسجَّل الذي لم يظهر 30 يوماً يُحذف (التصفّحُ الخفيّ ومسحُ البيانات يُنشئان صفوفاً)،
    ومحاولاتُ الكود أقدمُ من 90 يوماً. يُستدعى عند فتح المسؤول صفحتَه وبالأمر."""
    now = now or timezone.now()
    stale = BrowserDevice.objects.filter(status=BrowserDevice.Status.PENDING).filter(
        Q(last_seen__lt=now - PRUNE_AFTER) | Q(last_seen__isnull=True, created_at__lt=now - PRUNE_AFTER))
    removed = stale.delete()[1].get(BrowserDevice._meta.label, 0)
    DeviceAttempt.objects.filter(at__lt=now - ATTEMPTS_KEEP).delete()
    return removed


# ─── العرض ─────────────────────────────────────────────────────────────────────

def _person(user):
    if user is None:
        return ''
    return (user.get_full_name() or user.get_username()).strip()


def kit_version():
    return (getattr(settings, 'WORKSTATION_KIT_VERSION', '') or '').strip()


def _version_tuple(value):
    try:
        return tuple(int(p) for p in value.split('.'))
    except (TypeError, ValueError):
        return ()


def agent_outdated(version, kit=None):
    """أقدمُ من نسخة العُدّة الموزَّعة؟ — لا مقارنةَ بلا عُدّةٍ معروفة (حكمُ فيبل)."""
    kit = kit if kit is not None else kit_version()
    mine, theirs = _version_tuple(version), _version_tuple(kit)
    return bool(mine and theirs and mine < theirs)


def ago(when, now=None):
    if when is None:
        return '—'
    now = now or timezone.now()
    delta = now - when
    minutes = int(delta.total_seconds() // 60)
    if delta < SEEN_NOW:
        return 'الآن'
    if minutes < 60:
        return f'قبل {minutes} ' + ('دقائق' if minutes <= 10 else 'دقيقة')
    hours = minutes // 60
    local = timezone.localtime(when)
    if hours < 24 and timezone.localtime(now).date() == local.date():
        return f'اليوم {local:%H:%M}'
    if timezone.localtime(now).date() - local.date() == timedelta(days=1):
        return f'أمس {local:%H:%M}'
    return f'{local:%Y-%m-%d}'


def device_row(device, pol, now, here=None):
    seen_now = bool(device.last_seen and now - device.last_seen < SEEN_NOW)
    users = [_person(u) for u in device.users.all()]
    if device.has_scanner is False:
        scanner, scanner_tone = 'لا يمسح', 'mute'
    elif device.scanner_state == 'ok':
        scanner, scanner_tone = (device.scanner_label or 'ماسحٌ جاهز'), 'done'
    elif device.scanner_state in ('error', 'none', 'off'):
        scanner, scanner_tone = {'error': 'الماسح لا يردّ', 'none': 'لا ماسحَ موصول',
                                 'off': 'الوكيل متوقّف'}[device.scanner_state], 'late'
    else:
        scanner, scanner_tone = 'لم يُفحص بعد', 'mute'
    if device.agent_version:
        outdated = agent_outdated(device.agent_version)
        kit = device.agent_version + (' · تحديثٌ متاح' if outdated else '')
        kit_tone = 'wait' if outdated else 'done'
    else:
        kit, kit_tone, outdated = '—', 'mute', False
    return {
        'id': str(device.pk),
        'name': device.name or 'جهازٌ بلا اسم',
        'platform': ' · '.join(p for p in (device.os, device.browser) if p),
        'users': '، '.join(users[:3]) + (f' و{len(users) - 3}' if len(users) > 3 else '') or '—',
        'shared': len(users) > 1,
        'ip': device.last_ip or '—',
        'seen': ago(device.last_seen, now),
        'seen_now': seen_now,
        'scanner': scanner,
        'scanner_tone': scanner_tone,
        'has_scanner': device.scanner_state == 'ok',
        'kit': kit,
        'kit_tone': kit_tone,
        'attention': scanner_tone == 'late' or outdated,
        'is_server': pol is not None and pol.server_id == device.pk,
        'is_here': here is not None and here.pk == device.pk,
        'is_phone': is_phone(device),
    }


def is_requested(device):
    """طلبٌ قائم: أرسله الجهاز ولم يُتجاهَل بعد إرساله."""
    return bool(device.requested_at and (not device.dismissed_at
                                         or device.requested_at > device.dismissed_at))


def request_row(device, now):
    requested = is_requested(device)
    who = _person(device.requested_by if requested else device.last_user) or '—'
    kind = 'هاتف' if is_phone(device) else ('أُلغي تسجيلُه' if device.status == 'revoked'
                                            else 'حاسوبٌ لم يُسجَّل')
    return {
        'id': str(device.pk),
        'title': f'{kind} — ' + (' · '.join(p for p in (device.os, device.browser) if p) or 'متصفّح'),
        'who': who,
        'ip': device.last_ip or '—',
        'when': ago(device.requested_at if requested else device.last_seen, now),
        'requested': requested,
        'is_phone': is_phone(device),
    }


def board(here=None):
    """كلُّ ما تعرضه صفحةُ المسؤول — للقالب أوّلاً ثمّ لتحديثها الحيّ."""
    now = timezone.now()
    pol = policy()
    active = list(BrowserDevice.objects.filter(status=BrowserDevice.Status.ACTIVE)
                  .prefetch_related('users').order_by('name'))
    rows = [device_row(d, pol, now, here) for d in active]
    waiting = list(BrowserDevice.objects.exclude(status=BrowserDevice.Status.ACTIVE)
                   .filter(last_seen__gte=now - PRUNE_AFTER)
                   .select_related('requested_by', 'last_user')
                   .order_by(F('requested_at').desc(nulls_last=True), '-last_seen'))
    shown = [request_row(d, now) for d in waiting if is_requested(d)]
    others = [request_row(d, now) for d in waiting if not is_requested(d) and not d.dismissed_at][:10]
    _close_expired(now)
    open_codes = _open_codes().count()
    return {
        'rows': rows,
        'requests': shown,
        'seen': others,
        'counts': {
            'registered': len(rows),
            'now': sum(1 for r in rows if r['seen_now']),
            'attention': sum(1 for r in rows if r['attention']),
            'scanners': sum(1 for r in rows if r['has_scanner']),
            'requests': len(shown),
        },
        'open_codes': open_codes,
        'max_codes': MAX_OPEN_CODES,
        'mode': pol.mode,
    }
