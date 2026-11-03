# -*- coding: utf-8 -*-
"""حقائقُ تشغيل النظام: المهامّ المجدولة وأسطرُ السجلّ — لمدير النظام وحده.

**حالةُ المهمّة من عمر نتيجتها وملفّ التنبيه، لا من رمز الخروج.** عطلُ النسخ في
2026‑11 كان يخرج بـ``rc=0`` وهو لم ينسخ شيئاً منذ أيّام.
"""
import re
import shutil
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.utils import timezone

OK, STALE, UNKNOWN = 'ok', 'stale', 'unknown'

# (المفتاح، الاسم، ملفّ السجلّ، أقصى عمرٍ بالساعات) — من جدولة مهامّ الجهاز الحيّ.
JOBS = (
    ('verify', 'التحقّق من النسخة', 'task_verify.log', 8 * 24 + 12),
    ('disk', 'مساحة القرص', 'task_disk.log', 72),
    ('sessions', 'تنظيف الجلسات', 'task_clearsessions.log', 8 * 24 + 12),
    ('overdue', 'تنبيهات التأخّر', 'task_overdue.log', 72),
)
BACKUP_MAX_AGE_HOURS = 26

# مفتاحٌ ⟵ ملفّ: الاسمُ لا يأتي من الطلب أبداً.
LOG_TAIL_BYTES = 256 * 1024
LOG_MAX_LINES = 500
LOG_SOURCES = {
    'system': ('النظام', lambda: Path(settings.BASE_DIR) / 'logs' / 'lettersys.log'),
    'server': ('الخادم', lambda: ops_log_dir() / 'waitress.err.log'),
    'tasks': ('المهامّ', lambda: ops_log_dir() / 'task_backup.log'),
}
_LEVEL_RE = re.compile(r'\b(CRITICAL|ERROR|WARNING|WARN)\b')
_STAMP_RE = re.compile(r'(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})')
_MASKS = (
    (re.compile(r'(/share/attachment/)[^/\s]+'), r'\1•••'),
    (re.compile(r'(/api/scan/(?:serve|preview|manifest|edit)/)[^/\s]+'), r'\1•••'),
    (re.compile(r'((?:token|signature|sig|password|passwd|secret|key)=)[^&\s]+', re.I), r'\1•••'),
    (re.compile(r'[\w.+-]+@[\w-]+(?:\.[\w-]+)+'), '•••@•••'),
)
# بادئةُ المسجِّل ⟵ اسمُ الخدمة في سطر الأخطاء.
_SERVICES = (('core.messaging', 'مزامنة البريد'), ('core.extraction', 'الاستخراج'),
             ('core.tasks', 'المهامّ المجدولة'))


def ops_log_dir() -> Path:
    return Path(getattr(settings, 'OPS_LOG_DIR', Path(settings.BASE_DIR).parent / 'logs'))


def _age_hours(path, now):
    try:
        return (now - datetime.fromtimestamp(path.stat().st_mtime, tz=now.tzinfo)).total_seconds() / 3600
    except OSError:
        return None


def age_text(hours) -> str:
    """العمرُ بالعربيّة كما يقرؤه المدير: ساعتان، 3 ساعات، 20 ساعة، يومان."""
    if hours is None:
        return 'لا سجلّ'
    if hours < 1:
        return 'قبل أقلّ من ساعة'
    if hours < 48:
        n = round(hours)
        if n == 1:
            return 'قبل ساعة'
        if n == 2:
            return 'قبل ساعتين'
        return f'قبل {n} ساعات' if n <= 10 else f'قبل {n} ساعة'
    days = round(hours / 24)
    if days == 2:
        return 'قبل يومين'
    return f'قبل {days} أيام' if days <= 10 else f'قبل {days} يوماً'


def newest_backup():
    """أحدثُ نسخة قاعدةٍ مشفَّرة، أو None."""
    from core.backup_service import default_backup_dir

    try:
        files = list(default_backup_dir().glob('pg_backup_*.dump.enc'))
    except OSError:
        return None
    return max(files, key=lambda p: p.stat().st_mtime, default=None)


def _backup_job(now):
    from core.models import BackupSettings

    latest = newest_backup()
    age = _age_hours(latest, now) if latest else None
    if not BackupSettings.get().enabled:
        state, note = UNKNOWN, 'النسخ التلقائيّ معطَّل'
    elif age is None:
        state, note = STALE, 'لا توجد نسخة'
    else:
        state = OK if age <= BACKUP_MAX_AGE_HOURS else STALE
        note = f'آخر نسخة {age_text(age)} · الحدّ {BACKUP_MAX_AGE_HOURS} ساعة'
    return {'key': 'backup', 'name': 'النسخ الاحتياطيّ', 'state': state, 'note': note, 'age': age,
            'next_step': 'settings_backup' if state == STALE else ''}


def _verify_alert_active(now):
    """ملفُّ التنبيه يعني عطلاً ما لم تأتِ بعده نسخةٌ أحدث منه."""
    alert = ops_log_dir() / 'ALERT_VERIFY.txt'
    if not alert.exists():
        return False
    latest = newest_backup()
    return latest is None or latest.stat().st_mtime <= alert.stat().st_mtime


def job_statuses(now=None):
    now = now or timezone.localtime()
    jobs = [_backup_job(now)]
    for key, name, filename, max_hours in JOBS:
        age = _age_hours(ops_log_dir() / filename, now)
        if age is None:
            state, note = UNKNOWN, 'لا سجلّ على هذا الجهاز'
        else:
            state = OK if age <= max_hours else STALE
            note = f'آخر تشغيل {age_text(age)}'
        if key == 'verify' and _verify_alert_active(now):
            state, note = STALE, 'نبّه التحقّق إلى نسخة قديمة'
        jobs.append({'key': key, 'name': name, 'state': state, 'note': note, 'age': age,
                     'next_step': 'scheduler' if state == STALE else ''})
    return jobs


def failing_job_count(now=None) -> int:
    return sum(1 for job in job_statuses(now) if job['state'] == STALE)


def disk_percent():
    """نسبةُ امتلاء قرص النسخ، أو None إن تعذّر القياس."""
    from core.backup_service import default_backup_dir

    try:
        usage = shutil.disk_usage(default_backup_dir())
    except OSError:
        return None
    return round(usage.used * 100 / usage.total)


def mask(line: str) -> str:
    """يُخفي الروابط الموقَّعة والرموز والعناوين — السجلُّ يُعرض، فلا يصير نسخةً منها."""
    for pattern, repl in _MASKS:
        line = pattern.sub(repl, line)
    return line


def _tail_lines(path):
    """آخرُ 256 ك.ب ثمّ يُغلق الملفّ فوراً (تدويرُ ويندوز يتعثّر بالملفّ المفتوح)."""
    size = path.stat().st_size
    with open(path, 'rb') as handle:
        if size > LOG_TAIL_BYTES:
            handle.seek(size - LOG_TAIL_BYTES)
        raw = handle.read()
    text = raw.decode('utf-8', errors='replace').lstrip('﻿')
    lines = text.splitlines()
    return lines[1:] if size > LOG_TAIL_BYTES else lines   # الأوّلُ مبتور


def read_log(key, *, errors_only=False, query=''):
    """أسطرُ السجلّ الأحدثُ أوّلاً. يعيد ``(lines, error)``؛ والمفتاحُ المجهول يعود إلى «النظام»."""
    _label, resolve = LOG_SOURCES.get(key) or LOG_SOURCES['system']
    path = resolve()
    if not path.exists():
        return [], 'لا يوجد هذا الملفّ على هذا الجهاز.'
    try:
        lines = _tail_lines(path)
    except OSError as exc:
        return [], f'تعذّرت قراءة الملفّ: {exc.strerror or exc}'
    out = []
    for raw in reversed(lines):
        if not raw.strip():
            continue
        match = _LEVEL_RE.search(raw)
        level = (match.group(1) if match else '').replace('WARNING', 'WARN')
        if errors_only and not level:
            continue
        shown = mask(raw)
        if query and query.lower() not in shown.lower():
            continue
        out.append({'text': shown, 'level': {'ERROR': 'e', 'CRITICAL': 'e', 'WARN': 'w'}.get(level, 't')})
        if len(out) >= LOG_MAX_LINES:
            break
    return out, ''


def service_errors(now=None):
    """أخطاءُ آخر 24 ساعة لكلّ خدمة من سجلّ النظام — لا بطاقةَ مهمّةٍ للبريد والاستخراج."""
    now = now or timezone.localtime()
    path = LOG_SOURCES['system'][1]()
    if not path.exists():
        return []
    cutoff = (now - timedelta(hours=24)).replace(tzinfo=None)
    try:
        lines = _tail_lines(path)
    except OSError:
        return []
    counts = Counter()
    for raw in lines:
        if ' ERROR ' not in raw and ' CRITICAL ' not in raw:
            continue
        stamp = _STAMP_RE.search(raw)
        if not stamp or datetime.fromisoformat(f'{stamp.group(1)} {stamp.group(2)}') < cutoff:
            continue
        for prefix, label in _SERVICES:
            if prefix in raw:
                counts[label] += 1
                break
    return [{'label': label, 'count': n} for label, n in counts.most_common()]
