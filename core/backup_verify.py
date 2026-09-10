# -*- coding: utf-8 -*-
"""تحقّقُ نسخةِ ``pg_dump`` المشفَّرة — الوحدةُ النقيّة خلف أمر ``verify_backup``.

**لماذا:** الأعدادُ ليست بصمة (Merge9 §10.1، مقيس): نسخةُ 2026-09-08 أعدادُها
تطابق القاعدةَ الحيّة حرفيّاً ومحتواها أقدم — دمجُ الجهات جرى بعدها
(``merged_into`` 198 مقابل 256). فالبوّابةُ **بصماتٌ** لا أعداد.

**وقيمتُها في التناظر:** الأداةُ نفسُها تُشغَّل محلّيّاً (10.d) وعلى الخادم (10.h)،
فبوّابةُ التطابق تصير نسخاً ولصقاً لا اجتهاداً.

الحرّاسُ الخمسة (كلُّها مُطفَّرة في ``core/tests_verify_backup.py``):
1. **المفتاحُ يُقرأ من الملفّ مباشرةً** — لا استدعاءَ لـ``get_or_create_encryption_key``
   أبداً: ذاك يسكّ مفتاحاً جديداً فيُخفي أنّ المفتاحَ الصحيح غائب.
2. الصريحُ إلى ``mkdtemp()`` **خارج** ``BASE_DIR`` بوضع 0600، ويُحذف في ``finally``.
3. ``--write-plain`` يرفض الكتابةَ فوق موجودٍ ويرفض مساراً داخل المستودع.
4. **لا تُقرأ قيمةُ عمودٍ مشفَّرٍ إلى الذاكرة أصلاً** — البادئةُ والطولُ فقط.
5. ``--expect-live`` يقارن بـ``Book.all_objects`` (المديرُ الافتراضيّ يُخفي المحذوف).
"""

from __future__ import annotations

import hashlib
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings

# ── رموزُ الخروج (عقدُ §10.6) ────────────────────────────────────────────────
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_MISMATCH = 2
EXIT_NO_KEY = 3
EXIT_NO_PG_RESTORE = 4

#: رأسُ ملفّ ``pg_dump --format=custom``. التمييزُ به لا بالامتداد.
PGDMP_MAGIC = b'PGDMP'

#: ``\N`` هو NULL في صيغة COPY النصّيّة.
COPY_NULL = r'\N'

_COPY_RE = re.compile(
    r'^COPY\s+(?:(?P<schema>[\w."]+)\.)?(?P<table>[\w"]+)\s*'
    r'\((?P<cols>[^)]*)\)\s+FROM\s+stdin;\s*$'
)


class VerifyError(Exception):
    """فشلٌ يحمل رمزَ خروجه."""

    def __init__(self, message, code=EXIT_ERROR):
        super().__init__(message)
        self.code = code


# ════════════════════════════════════════════════════════════════════════════
#  المفتاح — يُقرأ من الملفّ مباشرةً (حارس 1)
# ════════════════════════════════════════════════════════════════════════════

def default_key_path():
    """المسارُ الافتراضيّ للمفتاح — ثابتُ ``core.encryption`` لا نسخةٌ منه."""
    from core.encryption import ENCRYPTION_KEY_FILE
    return Path(ENCRYPTION_KEY_FILE)


def read_key(key_path=None):
    """يقرأ مفتاحَ Fernet من الملفّ. غيابُه ⟵ ``VerifyError`` برمز 3.

    **لا يستدعي** ``get_or_create_encryption_key``: على خادمٍ بلا مفتاحٍ يسكّ ذاك
    مفتاحاً جديداً فيُنتج ``InvalidToken`` صامتاً بدل «المفتاحُ غائب» صريحاً.
    """
    path = Path(key_path) if key_path else default_key_path()
    if not path.is_file():
        raise VerifyError(
            f"مفتاحُ التعمية غيرُ موجود: {path} — "
            f"انسخ المفتاحَ الصحيح إلى هذا المسار أو مرّر --key.",
            EXIT_NO_KEY,
        )
    data = path.read_bytes().strip()
    if not data:
        raise VerifyError(f"مفتاحُ التعمية فارغ: {path}", EXIT_NO_KEY)
    return data


def key_fingerprint(key_bytes):
    """sha256[:8] للمفتاح — بصمةٌ تُطبع، لا محتوىً (C29: المتوقَّع 1e639b05)."""
    return hashlib.sha256(key_bytes).hexdigest()[:8]


# ════════════════════════════════════════════════════════════════════════════
#  الفكّ والتمييز
# ════════════════════════════════════════════════════════════════════════════

def decrypt_if_needed(raw_bytes, key_path=None):
    """يُعيد ``(plain_bytes, key_sha8_or_None)``.

    الخام (``PGDMP``) يمرّ بلا مفتاح؛ وما سواه يُفكّ بـFernet. والتمييزُ بالرأس
    لا بالامتداد — ملفٌّ اسمُه ``.enc`` وهو خامٌّ (أو العكس) يمرّ على أيّة حال.
    """
    if raw_bytes.startswith(PGDMP_MAGIC):
        return raw_bytes, None

    from cryptography.fernet import Fernet, InvalidToken

    key = read_key(key_path)
    try:
        plain = Fernet(key).decrypt(raw_bytes)
    except InvalidToken:
        raise VerifyError(
            f"فشل الفكّ (InvalidToken) — المفتاحُ sha={key_fingerprint(key)} "
            f"لا يفكّ هذا الملفّ. تأكّد من المفتاح الصحيح.",
            EXIT_ERROR,
        )
    return plain, key_fingerprint(key)


# ════════════════════════════════════════════════════════════════════════════
#  المجلّدُ المؤقّت (حارس 2) و --write-plain (حارس 3)
# ════════════════════════════════════════════════════════════════════════════

def _base_dir():
    return Path(settings.BASE_DIR).resolve()


def is_inside_repo(path):
    """هل ``path`` داخل ``BASE_DIR``؟ (المستودعُ عامٌّ — لا صريحَ فيه.)"""
    resolved = Path(path).resolve()
    base = _base_dir()
    return resolved == base or base in resolved.parents


def make_secure_tempdir():
    """مجلّدٌ مؤقّتٌ **خارج المستودع** للصريح.

    ``mkdtemp`` يقرأ ``TMPDIR``/``TEMP`` من البيئة — فإن أشارت إلى داخل الشجرة
    (أو ضبطها أحدٌ سهواً) لكُتب الصريحُ في مستودعٍ عامّ. الحارسُ يمنع ذلك.
    """
    directory = Path(tempfile.mkdtemp(prefix='verify_backup_'))
    if is_inside_repo(directory):
        shutil.rmtree(directory, ignore_errors=True)
        raise VerifyError(
            f"المجلّدُ المؤقّت وقع داخل المستودع ({directory}) — "
            f"اضبط TMPDIR/TEMP خارج {_base_dir()}.",
            EXIT_ERROR,
        )
    return directory


def check_write_plain_target(target):
    """يرفض الكتابةَ فوق موجودٍ ويرفض أيَّ مسارٍ داخل المستودع."""
    path = Path(target)
    if path.exists():
        raise VerifyError(
            f"--write-plain: الملفُّ موجودٌ سلفاً ولن يُكتَب فوقه: {path}",
            EXIT_ERROR,
        )
    if is_inside_repo(path):
        raise VerifyError(
            f"--write-plain: المسارُ داخل المستودع ({path}) — "
            f"الصريحُ لا يُكتَب في شجرةِ git. اختر مساراً خارج {_base_dir()}.",
            EXIT_ERROR,
        )
    return path


def write_private(path, data):
    """يكتب بايتاتٍ بوضع 0600 (مالكٌ فقط)."""
    path = Path(path)
    path.write_bytes(data)
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:                      # ويندوز لا يطبّق البتّات — لا يُسقط العمل
        pass
    return path


def sha256_of(path):
    """sha256 كاملاً لملفّ — يُقرأ على دفعات (النسخةُ قد تبلغ مئاتِ الميغا)."""
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


# ════════════════════════════════════════════════════════════════════════════
#  تشغيل pg_restore (نقطةُ المحاكاة في الاختبارات)
# ════════════════════════════════════════════════════════════════════════════

def resolve_pg_restore():
    """مسارُ ``pg_restore`` أو ``VerifyError`` برمز 4 — **قبل أيّ فكّ**."""
    from core.backup_service import find_pg_restore

    found = find_pg_restore()
    if not found:
        raise VerifyError(
            "pg_restore غيرُ موجود — لا يمكن قراءةُ النسخة. "
            "ثبّت أدوات PostgreSQL أو اضبط PG_RESTORE_BIN إلى مسار pg_restore.",
            EXIT_NO_PG_RESTORE,
        )
    return found


def iter_restore_sql(pg_restore_bin, dump_path):
    """يُولّد أسطرَ SQL من ``pg_restore -f - <dump>``.

    مولِّدٌ لا قائمة: صريحُ 13 ألف كتابٍ عشراتُ الميغا، والجهازُ 8GB.
    وهي **نقطةُ المحاكاة**: الاختباراتُ تستبدلها فتعمل بلا PostgreSQL.
    """
    command = [str(pg_restore_bin), '-f', '-', str(dump_path)]
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding='utf-8', errors='replace',
    )
    try:
        for line in process.stdout:
            yield line
    finally:
        process.stdout.close()
        stderr = process.stderr.read()
        process.stderr.close()
        code = process.wait()
        if code != 0:
            raise VerifyError(
                f"pg_restore خرج برمز {code}: {stderr.strip()[:300]}", EXIT_ERROR)


# ════════════════════════════════════════════════════════════════════════════
#  التحليلُ النقيّ — parse_copy_stats
# ════════════════════════════════════════════════════════════════════════════
#
#  لكلّ جدولٍ «مِسبار»: دالّةٌ تُستدعى لكلّ صفٍّ ببيانات (اسمُ العمود ⟵ قيمته)
#  فتُراكم البصمات. ما لا مِسبارَ له يُعَدُّ صفوفاً فقط.
#
#  **حارس 4**: مِسبارُ البريد لا يُخزّن القيمةَ أبداً — بادئةً وطولاً فقط. لو
#  خُزّنت لطُبعت (الصياغةُ تعرض ما تجد)، فالمنعُ هنا لا في المُنسّق.

def _probe_entity(acc, row):
    merged = row.get('merged_into_id', COPY_NULL)
    if merged != COPY_NULL and merged != '':
        acc['merged_into'] = acc.get('merged_into', 0) + 1
    else:
        acc['merged_into_null'] = acc.get('merged_into_null', 0) + 1
    if row.get('is_active') == 't':
        acc['is_active'] = acc.get('is_active', 0) + 1


def _probe_book(acc, row):
    if row.get('is_training') == 't':
        acc['is_training'] = acc.get('is_training', 0) + 1
    if row.get('is_deleted') == 't':
        acc['is_deleted'] = acc.get('is_deleted', 0) + 1


def _probe_attachment(acc, row):
    if row.get('is_deleted') == 't':
        acc['is_deleted'] = acc.get('is_deleted', 0) + 1


def _probe_emailsettings(acc, row):
    """بادئةُ كلّ كلمةِ مرورٍ وطولُها — **ولا قيمة**."""
    from core.encryption import ENCRYPTED_PREFIX

    for column in ('smtp_password', 'imap_password'):
        value = row.get(column, COPY_NULL)
        if value == COPY_NULL:
            acc[column] = {'null': True}
            continue
        acc[column] = {
            'prefix': ENCRYPTED_PREFIX if value.startswith(ENCRYPTED_PREFIX) else 'plain',
            'len': len(value),
        }
    acc['imap_sync_enabled'] = row.get('imap_sync_enabled')
    acc['is_active'] = row.get('is_active')


def _probe_migrations(acc, row):
    """آخرُ هجرةِ ``core`` = الأعلى ``id``."""
    if row.get('app') != 'core':
        return
    try:
        row_id = int(row.get('id', '0'))
    except ValueError:
        return
    if row_id >= acc.get('core_head_id', -1):
        acc['core_head_id'] = row_id
        acc['core_head'] = row.get('name')


def _probe_user(acc, row):
    acc.setdefault('usernames', []).append(row.get('username', ''))
    if row.get('is_active') == 't':
        acc['is_active'] = acc.get('is_active', 0) + 1


def _probe_booksequence(acc, row):
    acc.setdefault('sequences', []).append({
        'department_id': row.get('department_id'),
        'kind': row.get('kind'),
        'next_number': row.get('next_number'),
    })


def _probe_bookemaillog(acc, row):
    by_status = acc.setdefault('by_status', {})
    status = row.get('status', '?')
    by_status[status] = by_status.get(status, 0) + 1


#: القيمُ الابتدائيّة لكلّ مِسبار — كي يُبلِّغ الجدولُ الفارغُ **صفراً** لا «غائباً».
#: بلا هذا يصير «لا صفوف» و«العمودُ غيرُ مقيس» شيئاً واحداً في المقارنة.
PROBE_DEFAULTS = {
    'core_entity': lambda: {'merged_into': 0, 'merged_into_null': 0, 'is_active': 0},
    'core_book': lambda: {'is_training': 0, 'is_deleted': 0},
    'core_attachment': lambda: {'is_deleted': 0},
    'auth_user': lambda: {'usernames': [], 'is_active': 0},
    'core_booksequence': lambda: {'sequences': []},
    'core_bookemaillog': lambda: {'by_status': {}},
    'django_migrations': lambda: {'core_head': None},
}

PROBES = {
    'core_entity': _probe_entity,
    'core_book': _probe_book,
    'core_attachment': _probe_attachment,
    'core_emailsettings': _probe_emailsettings,
    'django_migrations': _probe_migrations,
    'auth_user': _probe_user,
    'core_booksequence': _probe_booksequence,
    'core_bookemaillog': _probe_bookemaillog,
}

#: ما يُعرَض في التقرير النصّيّ بالترتيب (وما سواه في ``--json``).
REPORT_TABLES = (
    'core_book', 'core_entity', 'core_attachment', 'core_bookhistory',
    'auth_user', 'core_letterheadmemory', 'core_bookemaillog',
    'core_booksequence', 'core_emailsettings', 'django_session',
    'django_migrations',
)


def parse_copy_stats(lines):
    """يقرأ كتلَ ``COPY public.<جدول> (<أعمدة>) FROM stdin;`` … ``\\.``.

    دالّةٌ **نقيّة**: تأخذ أسطراً وتُعيد ``{جدول: {'rows': n, …بصمات}}``.
    لا قرصَ ولا شبكةَ ولا قاعدة — فتُختبَر بنصٍّ محضَّرٍ بلا PostgreSQL.
    """
    stats = {}
    table = None
    columns = None
    acc = None

    for raw in lines:
        line = raw.rstrip('\n').rstrip('\r')

        if table is None:
            match = _COPY_RE.match(line)
            if match:
                table = match.group('table').strip('"')
                columns = [c.strip().strip('"') for c in match.group('cols').split(',')]
                acc = stats.setdefault(table, {'rows': 0})
                acc['columns'] = columns
                defaults = PROBE_DEFAULTS.get(table)
                if defaults:
                    for key, value in defaults().items():
                        acc.setdefault(key, value)
            continue

        if line == '\\.':
            table, columns, acc = None, None, None
            continue

        acc['rows'] += 1
        probe = PROBES.get(table)
        if probe:
            probe(acc, dict(zip(columns, line.split('\t'))))

    return stats


# ════════════════════════════════════════════════════════════════════════════
#  القاعدةُ الحيّة — للمقارنة (--expect-live)
# ════════════════════════════════════════════════════════════════════════════

def live_fingerprints():
    """بصماتُ القاعدة الحيّة بالشكل نفسِه الذي يُنتجه ``parse_copy_stats``.

    ``Book``/``Attachment`` بـ``all_objects``: المديرُ الافتراضيّ يُخفي المحذوفَ
    ناعماً فتُقارَن 13,194 بـ13,239 وتُعلَن «نسخةٌ ناقصة» وهي سليمة.
    """
    from django.contrib.auth.models import User

    from core.encryption import ENCRYPTED_PREFIX
    from core.models import (Attachment, Book, BookEmailLog, BookHistory,
                             BookSequence, EmailSettings, Entity,
                             LetterheadMemory)

    live = {
        'core_book': {
            'rows': Book.all_objects.count(),
            'is_training': Book.all_objects.filter(is_training=True).count(),
            'is_deleted': Book.all_objects.filter(is_deleted=True).count(),
        },
        'core_entity': {
            'rows': Entity.objects.count(),
            'merged_into': Entity.objects.filter(merged_into__isnull=False).count(),
            'merged_into_null': Entity.objects.filter(merged_into__isnull=True).count(),
            'is_active': Entity.objects.filter(is_active=True).count(),
        },
        'core_attachment': {
            'rows': Attachment.all_objects.count(),
            'is_deleted': Attachment.all_objects.filter(is_deleted=True).count(),
        },
        'core_bookhistory': {'rows': BookHistory.objects.count()},
        'core_letterheadmemory': {'rows': LetterheadMemory.objects.count()},
        'auth_user': {
            'rows': User.objects.count(),
            'usernames': sorted(User.objects.values_list('username', flat=True)),
            'is_active': User.objects.filter(is_active=True).count(),
        },
    }

    from django.db.models import Count
    by_status = {row['status']: row['n'] for row in
                 BookEmailLog.objects.values('status').annotate(n=Count('id'))}
    live['core_bookemaillog'] = {
        'rows': BookEmailLog.objects.count(), 'by_status': by_status}

    live['core_booksequence'] = {
        'rows': BookSequence.objects.count(),
        'sequences': [
            {'department_id': str(s.department_id) if s.department_id else COPY_NULL,
             'kind': s.kind, 'next_number': str(s.next_number)}
            for s in BookSequence.objects.order_by('department_id', 'kind')
        ],
    }

    # البريد: بادئةٌ وطولٌ من الخام في القاعدة (لا عبر ``from_db`` الذي يفكّ).
    mail = {'rows': EmailSettings.objects.count()}
    raw = EmailSettings.objects.values(
        'smtp_password', 'imap_password', 'imap_sync_enabled', 'is_active').first()
    if raw:
        for column in ('smtp_password', 'imap_password'):
            value = raw[column] or ''
            mail[column] = {
                'prefix': ENCRYPTED_PREFIX if value.startswith(ENCRYPTED_PREFIX) else 'plain',
                'len': len(value),
            }
        mail['imap_sync_enabled'] = 't' if raw['imap_sync_enabled'] else 'f'
        mail['is_active'] = 't' if raw['is_active'] else 'f'
    live['core_emailsettings'] = mail

    from django.db import connection
    with connection.cursor() as cur:
        cur.execute("select name from django_migrations "
                    "where app='core' order by id desc limit 1")
        row = cur.fetchone()
    live['django_migrations'] = {'core_head': row[0] if row else None}

    return live


#: البصماتُ التي تُقارَن في ``--expect-live`` — (جدول، مفتاح).
LIVE_COMPARED = (
    ('core_book', 'rows'), ('core_book', 'is_training'), ('core_book', 'is_deleted'),
    ('core_entity', 'rows'), ('core_entity', 'merged_into'),
    ('core_entity', 'merged_into_null'), ('core_entity', 'is_active'),
    ('core_attachment', 'rows'), ('core_attachment', 'is_deleted'),
    ('core_bookhistory', 'rows'), ('core_letterheadmemory', 'rows'),
    ('auth_user', 'rows'), ('auth_user', 'usernames'), ('auth_user', 'is_active'),
    ('core_bookemaillog', 'rows'), ('core_bookemaillog', 'by_status'),
    ('core_booksequence', 'rows'), ('core_booksequence', 'sequences'),
    ('core_emailsettings', 'smtp_password'), ('core_emailsettings', 'imap_password'),
    ('core_emailsettings', 'imap_sync_enabled'), ('core_emailsettings', 'is_active'),
    ('django_migrations', 'core_head'),
)


def _normalise(value):
    """قيمُ COPY نصوصٌ وقيمُ ORM أنواع — تُقارَن على شكلٍ واحد."""
    if isinstance(value, list):
        return sorted(_normalise(v) for v in value)
    if isinstance(value, dict):
        return tuple(sorted((k, _normalise(v)) for k, v in value.items()))
    if value is None:
        return COPY_NULL
    return str(value)


def diff_against_live(stats, live=None):
    """قائمةُ الاختلافات ``(جدول.مفتاح, في النسخة, حيّاً)`` — فارغةٌ = مطابقة."""
    live = live if live is not None else live_fingerprints()
    differences = []
    for table, key in LIVE_COMPARED:
        if table not in live or key not in live[table]:
            continue
        expected = _normalise(live[table][key])
        actual = _normalise(stats.get(table, {}).get(key))
        if expected != actual:
            differences.append((f'{table}.{key}',
                                stats.get(table, {}).get(key, '(غائب)'),
                                live[table][key]))
    return differences


def diff_against_expect(stats, expectations):
    """``--expect جدول=عدد`` — قائمةُ ما خالف."""
    differences = []
    for table, expected in expectations.items():
        actual = stats.get(table, {}).get('rows')
        if actual is None:
            differences.append((f'{table}.rows', '(الجدولُ غيرُ موجود)', expected))
        elif int(actual) != int(expected):
            differences.append((f'{table}.rows', actual, expected))
    return differences


# ════════════════════════════════════════════════════════════════════════════
#  الصياغة
# ════════════════════════════════════════════════════════════════════════════

def _fmt_password(entry):
    if not isinstance(entry, dict):
        return '(غيرُ موجود)'
    if entry.get('null'):
        return 'NULL'
    return f"prefix={entry['prefix']} len={entry['len']}"


def format_report(stats):
    """التقريرُ النصّيّ — أسطرٌ تُنسَخ وتُلصَق بين 10.d و10.h."""
    lines = []
    for table in REPORT_TABLES:
        data = stats.get(table)
        if data is None:
            lines.append(f'{table:<26} غيرُ موجود')
            continue

        rows = data['rows']
        if table == 'core_book':
            lines.append(f'{table:<26} rows={rows} · is_training='
                         f'{data.get("is_training", 0)} · is_deleted={data.get("is_deleted", 0)}')
        elif table == 'core_entity':
            lines.append(f'{table:<26} rows={rows} · merged_into='
                         f'{data.get("merged_into", 0)} · merged_into_null='
                         f'{data.get("merged_into_null", 0)} · is_active='
                         f'{data.get("is_active", 0)}')
        elif table == 'core_attachment':
            lines.append(f'{table:<26} rows={rows} · is_deleted={data.get("is_deleted", 0)}')
        elif table == 'auth_user':
            names = ' '.join(sorted(data.get('usernames', [])))
            lines.append(f'{table:<26} rows={rows} · is_active={data.get("is_active", 0)}')
            lines.append(f'{"":<26} usernames: {names}')
        elif table == 'core_bookemaillog':
            by_status = data.get('by_status', {})
            detail = ' '.join(f'{k}={v}' for k, v in sorted(by_status.items())) or '(لا صفوف)'
            lines.append(f'{table:<26} rows={rows} · {detail}')
        elif table == 'core_booksequence':
            lines.append(f'{table:<26} rows={rows}')
            for seq in data.get('sequences', []):
                lines.append(f'{"":<26}   dept={seq["department_id"]} '
                             f'{seq["kind"]} ⟵ next={seq["next_number"]}')
        elif table == 'core_emailsettings':
            lines.append(f'{table:<26} rows={rows} · imap_sync_enabled='
                         f'{data.get("imap_sync_enabled")} · is_active={data.get("is_active")}')
            lines.append(f'{"":<26}   smtp_password: {_fmt_password(data.get("smtp_password"))}')
            lines.append(f'{"":<26}   imap_password: {_fmt_password(data.get("imap_password"))}')
        elif table == 'django_migrations':
            lines.append(f'{table:<26} rows={rows} · core_head={data.get("core_head")}')
        else:
            lines.append(f'{table:<26} rows={rows}')

    extra = sorted(set(stats) - set(REPORT_TABLES))
    lines.append(f'(+{len(extra)} جدولاً آخر — الكلُّ في --json)')
    return lines


def json_payload(stats):
    """كلُّ ما قِيس بصيغةٍ آليّة. ``columns`` تُحذف (ضجيجٌ لا بصمة)."""
    payload = {}
    for table, data in sorted(stats.items()):
        payload[table] = {k: v for k, v in data.items() if k != 'columns'}
    return payload
