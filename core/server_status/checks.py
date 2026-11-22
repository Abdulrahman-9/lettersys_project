"""فحوصُ «حالة الخادم» — المصدرُ الوحيد لحكم كلّ بطاقة وعتباتها.

كلُّ فحصٍ يقرأ ولا يكتب، ويعيد بطاقةً تقول ما حالُها وماذا يُفعل. لا شيءَ هنا يحتاج صلاحيّة
المسؤول: سجلُّ ويندوز يُقرأ بحساب الخدمة، و``sc.exe query`` استعلامٌ لا تحكّم. خارج ويندوز
(الاختبارات والتطوير) تصير بطاقاتُ الخدمات «غيرَ معروفة» بدل أن تكذب.
"""
import ipaddress
import json
import math
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from pathlib import Path
from urllib.parse import urlsplit

from django.conf import settings
from django.core.cache import cache
from django.db import DatabaseError, connection
from django.urls import reverse
from django.utils import timezone

OK, WARN, BAD, INFO, UNKNOWN = 'ok', 'warn', 'bad', 'info', 'unknown'
# ما يحتاج انتباهاً أوّلاً، ثمّ السليم، ثمّ ما هو للعلم (نيلسن 8: التنبيهُ لا يزاحمه السليم).
_RANK = {BAD: 0, WARN: 1, UNKNOWN: 2, OK: 3, INFO: 4}

DISK_BAD_PCT, DISK_WARN_PCT = 5, 10          # نسبةُ المساحة الحرّة
DISK_BAD_GB, DISK_WARN_GB = 2, 10            # وأرضيّةٌ مطلقة: قرصٌ كبير بنسبةٍ مريحة قد يبقى فيه القليل
# حكمُ عمر النسخة ووقتُ تشغيل الحاسوب في ``core.system_ops`` وحده (مركزُ النظام وشارةُ الشريط يقرآنه أيضاً).
DB_SLOW_MS = 500
STRIP_CACHE_KEY = 'server_status:strip'
STRIP_CACHE_SECONDS = 60
_IMPORTED_AT = timezone.now()
_MONTHS = ('يناير', 'فبراير', 'مارس', 'أبريل', 'مايو', 'يونيو', 'يوليو', 'أغسطس', 'سبتمبر',
           'أكتوبر', 'نوفمبر', 'ديسمبر')


@dataclass
class Card:
    key: str
    title: str
    state: str
    label: str
    text: str
    icon: str
    guide: str = ''          # مرسى فقرته في الدليل لما يحتاج انتباهاً
    meter: float = -1.0      # نسبةُ الاستعمال للأقراص؛ ‎-1‎ = لا مقياس
    link_url: str = ''
    link_label: str = ''

    @property
    def needs_attention(self):
        return self.state in (BAD, WARN, UNKNOWN)

    def as_dict(self):
        data = asdict(self)
        data['needs_attention'] = self.needs_attention
        return data


# ─── قراءاتٌ من النظام ──────────────────────────────────────────────────────

def process_started_at():
    """وقتُ بدء هذه العمليّة من ويندوز نفسه (لا psutil في بيئة الإنتاج)؛ وإلّا وقتُ تحميل الوحدة."""
    if sys.platform == 'win32':
        import ctypes
        from ctypes import wintypes
        times = [wintypes.FILETIME() for _ in range(4)]
        kernel32 = ctypes.windll.kernel32
        if kernel32.GetProcessTimes(kernel32.GetCurrentProcess(), *(ctypes.byref(t) for t in times)):
            ticks = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime   # 100ns منذ 1601 UTC
            return datetime.fromtimestamp(ticks / 10_000_000 - 11_644_473_600, tz=dt_timezone.utc)
    return _IMPORTED_AT


def windows_service(name):
    """إعدادُ خدمة ويندوز من السجلّ: ``start`` (2 تلقائيّ · 3 يدويّ · 4 معطَّل) و``delayed``
    و``image`` و``depends``. ‎None‎ خارج ويندوز أو إن لم توجد الخدمة."""
    if sys.platform != 'win32' or not name:
        return None
    import winreg

    def value(key, field, default):
        try:
            return winreg.QueryValueEx(key, field)[0]
        except OSError:
            return default

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf'SYSTEM\CurrentControlSet\Services\{name}') as key:
            return {'start': value(key, 'Start', None), 'delayed': bool(value(key, 'DelayedAutostart', 0)),
                    'image': value(key, 'ImagePath', ''), 'depends': list(value(key, 'DependOnService', []) or [])}
    except OSError:
        return None


def service_state(name):
    """حالةُ خدمة ويندوز بـ``sc.exe query`` (استعلامٌ يسمح به حسابُ الخدمة): RUNNING · STOPPED ·
    PAUSED … أو ``MISSING`` أو ‎None‎ إن تعذّر السؤال."""
    if sys.platform != 'win32' or not name:
        return None
    try:
        result = subprocess.run(['sc.exe', 'query', name], capture_output=True, text=True, timeout=3,
                                errors='replace', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r'STATE\s*:\s*\d+\s+(\w+)', result.stdout or '')
    if match:
        return match.group(1).upper()
    return 'MISSING' if '1060' in (result.stdout or '') else None


def database_drive(service=None):
    """قرصُ ملفّات قاعدة البيانات من أمر تشغيل خدمتها (``-D "…"``)؛ والخدمةُ هي ما تعتمد عليه خدمةُ
    النظام. ‎''‎ إن تعذّر معرفته."""
    service = service if service is not None else windows_service(settings.SERVER_STATUS_SERVICE)
    for dep in (service or {}).get('depends', []):
        image = (windows_service(dep) or {}).get('image', '')
        match = re.search(r'-D\s+"([^"]+)"', image) or re.search(r'-D\s+(\S+)', image)
        if match:
            return Path(match.group(1)).anchor.upper()
    return ''


def read_release():
    """ما يكتبه النشرُ في ``var/release.json`` (``head`` و``deployed_at``) — لا يُسأل git وقتَ التشغيل."""
    try:
        data = json.loads((Path(settings.BASE_DIR) / 'var' / 'release.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get('head') else None


def format_when(moment):
    """«اليوم 07:51» · «أمس 22:10» · «18 نوفمبر 09:00» بتوقيت النظام."""
    if moment is None:
        return '—'
    if timezone.is_naive(moment):
        moment = timezone.make_aware(moment)
    local = timezone.localtime(moment)
    today = timezone.localdate()
    clock = local.strftime('%H:%M')
    if local.date() == today:
        return f'اليوم {clock}'
    if local.date() == today - timedelta(days=1):
        return f'أمس {clock}'
    return f'{local.day} {_MONTHS[local.month - 1]} {clock}'


def _count(n, one, two, few, many):
    if n == 1:
        return one
    if n == 2:
        return two
    return f'{n} {few if 3 <= n % 100 <= 10 else many}'


# ─── البطاقات ───────────────────────────────────────────────────────────────

def app_card():
    release = read_release()
    if release:
        deployed = ''
        try:
            deployed = ' نُشرت ' + format_when(datetime.fromisoformat(release.get('deployed_at', '')))
        except (TypeError, ValueError):
            pass                          # ‎null‎ أو رقمٌ في الملفّ: الشريطُ يبقى، وإلّا سقطت صفحةُ هبوط المدير (فيبل 11-22)
        version = f' النسخة {str(release["head"])[:7]}{deployed}.'
    else:
        version = ' النسخةُ غيرُ مسجّلة بعد، وتُسجَّل مع النشر القادم.'
    return Card('app', 'التطبيق', OK, 'يعمل', f'بدأ {format_when(process_started_at())}.{version}', 'server')


def database_card(db_drive=''):
    where = f' ملفّاتُها على القرص {db_drive.rstrip(chr(92) + "/")}' if db_drive else ''
    started = time.perf_counter()
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
    except DatabaseError:
        return Card('db', 'قاعدة البيانات', BAD, 'لا تستجيب',
                    'تعذّر الوصول إلى قاعدة البيانات الآن، فلا يستطيع أحدٌ الدخول.', 'database', guide='db')
    elapsed = (time.perf_counter() - started) * 1000
    if elapsed >= DB_SLOW_MS:
        return Card('db', 'قاعدة البيانات', WARN, 'بطيئة',
                    f'تستجيب ببطء ({elapsed:.0f} ms).{where}', 'database', guide='slow')
    return Card('db', 'قاعدة البيانات', OK, 'متّصلة', f'تستجيب الآن.{where}'.rstrip(), 'database')


def autostart_card(service=None, lookup=None):
    """النظامُ وقاعدةُ بياناته (ما تعتمد عليه خدمتُه) — كلاهما يجب أن يبدأ وحده، وإلّا لا يبدأ النظام."""
    name = settings.SERVER_STATUS_SERVICE
    lookup = lookup or windows_service
    service = service if service is not None else lookup(name)
    if not service:
        return Card('autostart', 'التشغيل مع الحاسوب', UNKNOWN, 'غير معروف',
                    f'لم توجد خدمةُ ويندوز «{name}» على هذا الحاسوب، فلا يُعرف هل يبدأ النظام وحده.',
                    'power', guide='autostart')
    if service.get('start') == 4:
        return Card('autostart', 'التشغيل مع الحاسوب', BAD, 'معطَّل',
                    'خدمةُ النظام معطَّلة: لن تبدأ لا وحدها ولا بزرّ «تشغيل».', 'power', guide='autostart')
    if service.get('start') != 2:
        return Card('autostart', 'التشغيل مع الحاسوب', WARN, 'غير مفعّل',
                    'لا يبدأ النظام وحده: إن أُعيد تشغيل الحاسوب بقي متوقّفاً حتّى يشغّله أحد.', 'power',
                    guide='autostart')
    depends = service.get('depends', [])
    # 0 إقلاع · 1 نظام · 2 تلقائيّ: كلُّها تبدأ وحدها — مشغّلٌ بـ0 أو 1 ليس «يدويّاً» (فيبل 11-22)
    manual = [dep for dep in depends if (lookup(dep) or {}).get('start') not in (0, 1, 2)]
    if manual:
        label = 'قاعدةُ البيانات لا تبدأ' if _is_database(manual[0]) else 'خدمةٌ لازمة لا تبدأ'
        return Card('autostart', 'التشغيل مع الحاسوب', BAD, label,
                    f'النظامُ يبدأ وحده لكنّ خدمة «{manual[0]}» التي يحتاجها لا تبدأ معه، فيتوقّف بعد كلّ تشغيلٍ '
                    'للحاسوب.', 'power', guide='autostart')
    what = 'النظامُ وقاعدةُ بياناته وحدهما' if any(_is_database(dep) for dep in depends) else 'النظامُ وحده'
    return Card('autostart', 'التشغيل مع الحاسوب', OK, 'مفعّل',
                f'يبدأ {what} كلّما شُغّل الحاسوب أو عادت الكهرباء.', 'power')


def _is_database(service_name):
    return 'postgres' in service_name.lower()


def backup_dir():
    """مجلّدُ النسخ المضبوط بلا إنشاء (``default_backup_dir`` يُنشئه ويسقط إلى قرص النظام — كتابةٌ لا تجوز هنا)."""
    from core.backup_service import configured_backup_dir
    return Path(configured_backup_dir())


def disk_drives(db_drive=''):
    """الأقراصُ التي يهمّ النظامَ امتلاؤها: قرصُ ويندوز وقرصُ قاعدة البيانات وقرصُ التطبيق وقرصُ النسخ — كلٌّ
    مرّةً (قاعدةٌ على قرصٍ رابع كانت لا تُراقَب: فيبل 11-22)."""
    roots = [db_drive, Path(settings.BASE_DIR).anchor, backup_dir().anchor]
    if sys.platform == 'win32':
        import os
        roots.insert(0, (os.environ.get('SystemDrive') or 'C:') + '\\')
    seen = []
    for root in roots:
        root = root.upper()
        if root and root not in seen:
            seen.append(root)
    return seen


def disk_cards(db_drive='', usage=None):
    usage = usage or shutil.disk_usage
    cards = []
    base_drive = Path(settings.BASE_DIR).anchor.upper()
    for root in disk_drives(db_drive):
        name = root.rstrip('\\/') or root
        try:
            total, _used, free = usage(root)
        except OSError:
            # قرصُ النسخ مفصولٌ مثلاً: هذا عطلٌ لا «غيرُ معروف» (فيبل)
            cards.append(Card(f'disk-{name[:1].lower()}', f'القرص {name}', BAD, 'غير موجود',
                              'لا يُوصَل إلى هذا القرص الآن، وعليه ما يحتاجه النظام.', 'disk', guide='disk'))
            continue
        free_pct = free / total * 100 if total else 0
        free_gb, total_gb = free / 1024 ** 3, total / 1024 ** 3
        # عزلُ الأرقام (LRI…PDI): «10 GB» و«4.3%» داخل جملةٍ عربيّة كانت تُقرأ «GB 10» و«%4.3» (لقطة 11-19).
        # والمعروضُ مقطوعٌ لا مقرَّب: «5.0%» بجوار «ممتلئ تقريباً» عند 4.98% كان يناقض الحدّ «أقلّ من 5» (لقطة 11-22)
        facts = f'⁦{math.floor(free_gb)} GB⁩ حرّة من ⁦{total_gb:.0f}⁩ (⁦{math.floor(free_pct * 10) / 10:.1f}%⁩).'
        holds = []
        if root == db_drive:
            holds.append('قاعدةُ البيانات على هذا القرص: إن امتلأ توقّف النظام')
        elif root == base_drive:
            holds.append('النظامُ ومرفقاتُه على هذا القرص')
        text = facts + (' ' + '. '.join(holds) + '.' if holds else '')
        if free_pct < DISK_BAD_PCT or free_gb < DISK_BAD_GB:
            state, label = BAD, 'ممتلئ تقريباً'
        elif free_pct < DISK_WARN_PCT or free_gb < DISK_WARN_GB:
            state, label = WARN, 'يكاد يمتلئ'
        else:
            state, label = OK, 'مساحةٌ كافية'
        cards.append(Card(f'disk-{name[:1].lower()}', f'القرص {name}', state, label, text, 'disk',
                          guide='disk' if state != OK else '', meter=round(100 - free_pct, 1)))
    return cards


_UNSET = object()


def backup_card(now=None, latest=_UNSET, booted=_UNSET, enabled=None):
    """الحكمُ من ``core.system_ops`` — المصدرُ الوحيد لعمر النسخة؛ هنا العرضُ وحده.
    ``latest``/``booted`` بتوقيتٍ معلوم المنطقة؛ ``booted=None`` = «وقتُ التشغيل غيرُ معروف»."""
    from core import system_ops
    from core.models import BackupSettings
    now = now or timezone.localtime()
    booted = system_ops.system_booted_at() if booted is _UNSET else booted
    link = {'link_url': reverse('backup_database'), 'link_label': 'افتح النسخ الاحتياطيّ'}
    if not (BackupSettings.get().enabled if enabled is None else enabled):
        return Card('backup', 'النسخ الاحتياطيّ', WARN, 'معطَّل',
                    'النسخُ التلقائيّ معطَّل في إعدادات النسخ، فلا تُؤخذ نسخٌ وحدها.', 'clock', guide='backup', **link)
    if latest is _UNSET:
        directory = backup_dir()
        if not directory.is_dir():
            return Card('backup', 'النسخ الاحتياطيّ', BAD, 'المجلّد غير موجود',
                        f'مجلّدُ النسخ {directory} غيرُ موجود، فلا تُحفظ نسخٌ الآن.', 'clock', guide='backup', **link)
        newest = system_ops.newest_backup()
        latest = datetime.fromtimestamp(newest.mtime, tz=now.tzinfo) if newest else None
    if latest is None:
        return Card('backup', 'النسخ الاحتياطيّ', BAD, 'لا نسخ', 'لا نسخةَ لقاعدة البيانات في مجلّد النسخ.',
                    'clock', guide='backup', **link)
    when = format_when(latest)
    if now - latest > timedelta(days=system_ops.BACKUP_MAX_DAYS):
        return Card('backup', 'النسخ الاحتياطيّ', BAD, 'قديمةٌ جدّاً',
                    f'آخرُ نسخة: {when} — مضى عليها أكثرُ من أسبوع.', 'clock', guide='backup', **link)
    if system_ops.backup_is_late(latest, now, booted):
        # «لا نسخةَ منذ التشغيل» حين يصدق وحده: حاسوبٌ شغّالٌ أيّاماً أخذ نسخةً بعد تشغيله ثمّ توقّف النسخ
        text = (f'لم تُؤخذ نسخةٌ منذ تشغيل الحاسوب ({format_when(booted)}). آخرُ نسخة: {when}.'
                if booted is not None and latest < booted else f'آخرُ نسخة: {when} — أقدمُ من يوم.')
        return Card('backup', 'النسخ الاحتياطيّ', WARN, 'متأخّرة', text, 'clock', guide='backup', **link)
    return Card('backup', 'النسخ الاحتياطيّ', OK, 'حديثة', f'آخرُ نسخة: {when}.', 'clock', **link)


def _is_name(host):
    if not host or host == '*' or host.startswith('.') or host in ('localhost',):
        return False
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return True
    return False


def official_url(request):
    """رابطُ الموظّفين: المضبوطُ صراحةً، وإلّا أوّلُ اسمٍ غير رقميّ في ALLOWED_HOSTS بالمنفذ الذي كتبه
    المتصفّح (من ``Host`` لا من منفذ الخادم: خلف Caddy يكون 1312 داخليّاً والرابطُ ‎https://follow2‎)."""
    if settings.LETTERSYS_OFFICIAL_URL:
        return settings.LETTERSYS_OFFICIAL_URL.rstrip('/')
    host = official_host()
    if not host or request is None:
        return ''
    typed = request.get_host()
    port = typed.rsplit(':', 1)[1] if ':' in typed and not typed.endswith(']') else ''
    return f'{request.scheme}://{host}' + (f':{port}' if port else '')


def official_host():
    """اسمُ الخادم الذي يدخل به الموظّفون، من الإعدادات وحدها: الشريطُ (بلا طلب) والصفحةُ يحكمان حكماً واحداً
    (فيبل 11-22). ‎''‎ حين لا يُعرف إلّا عنوانٌ رقميّ."""
    if settings.LETTERSYS_OFFICIAL_URL:
        host = urlsplit(settings.LETTERSYS_OFFICIAL_URL).hostname or ''
        return host if _is_name(host) else ''
    return next((h for h in settings.ALLOWED_HOSTS if _is_name(h)), '')


def link_card(request=None, addresses=None, https_running=False):
    """الحالةُ من ``official_host`` وحده؛ الطلبُ يكمل النصّ (الرابطُ بالمنفذ الذي كتبه المتصفّح)."""
    from core.devices.service import server_addresses
    host = official_host()
    addresses = server_addresses() if addresses is None else addresses
    now_at = f' (الآن {addresses[0]})' if addresses else ''
    if host:
        url = official_url(request)
        secure = '' if https_running or url.startswith('https://') else ' والرابطُ الآمن غيرُ مفعّل بعد.'
        return Card('link', 'الرابط', OK, 'يعمل بالاسم',
                    f'يدخل الموظّفون بالاسم {host}، فيبقى الرابطُ نفسه ولو تغيّر عنوانُ الخادم{now_at}.{secure}',
                    'link')
    return Card('link', 'الرابط', WARN, 'بالأرقام',
                f'يدخل الموظّفون بعنوانٍ رقميّ{now_at}، وقد يتغيّر بعد إعادة تشغيل الحاسوب فيتعطّل الرابط.',
                'link', guide='bad-request')


def https_card(state=None, probe=True):
    """خدمةٌ مثبّتة لا تعمل عطلٌ يُرى (PAUSED منذ تغيّر العنوان، مقيسٌ 11-19) — لا «خطوةً تالية» (فيبل)."""
    if probe:
        state = service_state(settings.SERVER_STATUS_HTTPS_SERVICE)
    if state is None:
        return None                                   # خارج ويندوز أو تعذّر السؤال: لا بطاقةَ تكذب
    if state == 'RUNNING':
        return Card('https', 'الاتّصال الآمن', OK, 'يعمل', 'الرابطُ الآمن يعمل.', 'lock')
    if state == 'MISSING':
        return Card('https', 'الاتّصال الآمن', INFO, 'غير مثبّت',
                    'يُثبَّت مع الرابط الآمن. بعده تظهر للموظّف صفحةُ «لا اتّصال» حين يتوقّف الخادم.', 'lock')
    label = 'موقوفٌ مؤقّتاً' if state == 'PAUSED' else 'متوقّف'
    return Card('https', 'الاتّصال الآمن', BAD, label,
                'خدمةُ الرابط الآمن مثبّتةٌ ولا تعمل، فلا يعمل الرابطُ الآمن ولا صفحةُ «لا اتّصال» عند الموظّفين.',
                'lock', guide='https')


def notify_contact():
    """«من يُبلَّغ حين يتوقّف الخادم» للعرض: الصفحةُ والدليلُ ونسختُه على القرص. قراءةٌ بلا إنشاء — فتحُ صفحةٍ لا
    يكتب صفّاً (فيبل 11-22)؛ ولا صفَّ بعدُ ⟵ اسمٌ ورقمٌ فارغان."""
    from core.devices.service import policy_or_none
    pol = policy_or_none()
    return {'notify_name': pol.notify_name if pol else '', 'notify_phone': pol.notify_phone if pol else ''}


def devices_card():
    from core.devices.models import BrowserDevice
    from core.devices.service import policy_or_none
    url = reverse('network_settings')
    pol = policy_or_none()                # قراءةٌ بلا إنشاء: الشريطُ يُسأل مع كلّ صفحة (فيبل 11-22)
    if not (pol and pol.server_id):
        return Card('devices', 'الأجهزة', INFO, 'الخادم لم يُعلَن',
                    'يُعلَن هذا الحاسوب خادماً بعد الاتّصال الآمن، ثمّ تنضمّ الأجهزة بكود.', 'monitor',
                    link_url=url, link_label='افتح «الشبكة والأجهزة»')
    count = BrowserDevice.objects.filter(status=BrowserDevice.Status.ACTIVE).count()
    return Card('devices', 'الأجهزة', OK, _count(count, 'جهازٌ مسجّل', 'جهازان مسجّلان', 'أجهزة مسجّلة',
                                                  'جهازاً مسجّلاً'),
                'الخادمُ مُعلَن، والأجهزةُ تنضمّ بكودٍ من خمسة أرقام.', 'monitor',
                link_url=url, link_label='افتح «الشبكة والأجهزة»')


# ─── التجميع ────────────────────────────────────────────────────────────────

def summarize(cards):
    bad = sum(1 for c in cards if c.state == BAD)
    warn = sum(1 for c in cards if c.state in (WARN, UNKNOWN))
    parts = []
    if bad:
        parts.append(_count(bad, 'مشكلةٌ تحتاج إصلاحاً', 'مشكلتان تحتاجان إصلاحاً', 'مشكلات تحتاج إصلاحاً',
                            'مشكلةً تحتاج إصلاحاً'))
    if warn:
        parts.append(_count(warn, 'تنبيهٌ واحد يحتاج انتباهك', 'تنبيهان يحتاجان انتباهك', 'تنبيهات تحتاج انتباهك',
                            'تنبيهاً يحتاج انتباهك'))
    headline = 'الخادم يعمل بلا ملاحظات' if not parts else 'الخادم يعمل — و' + ' و'.join(parts)
    state = BAD if bad else WARN if warn else OK
    return {'state': state, 'headline': headline, 'bad': bad, 'warn': warn}


def collect(request=None):
    """كلُّ البطاقات مرتّبةً: ما يحتاج انتباهاً أوّلاً. هي نفسُها في الصفحة والشريط (والشريطُ بلا طلب) كي لا
    يعدّ أحدُهما مشكلةً لا يعدّها الآخر؛ الطلبُ يكمل نصَّ بطاقة الرابط وحده."""
    service = windows_service(settings.SERVER_STATUS_SERVICE)
    db_drive = database_drive(service)
    cards = [app_card(), database_card(db_drive), autostart_card(service), *disk_cards(db_drive), backup_card()]
    https = https_card()
    cards.append(link_card(request, https_running=bool(https and https.state == OK)))
    if https:
        cards.append(https)
    cards.append(devices_card())
    order = {id(c): i for i, c in enumerate(cards)}
    cards.sort(key=lambda c: (_RANK[c.state], order[id(c)]))
    autostart = next(c for c in cards if c.key == 'autostart')
    return {'cards': cards, 'summary': summarize(cards), 'checked_at': timezone.now(),
            'autostart': autostart, 'started': format_when(process_started_at()), 'release': read_release()}


def strip_summary():
    """خلاصةُ الشريط، محفوظةً دقيقة: الصفحةُ تُفتح كثيراً، فيُسأل ويندوز (ومنه ``sc.exe``) مرّةً في الدقيقة."""
    cached = cache.get(STRIP_CACHE_KEY)
    if cached is None:
        report = collect()
        attention = [c for c in report['cards'] if c.needs_attention]
        cached = {**report['summary'], 'first': attention[0].as_dict() if attention else None}
        cache.set(STRIP_CACHE_KEY, cached, STRIP_CACHE_SECONDS)
    return cached
