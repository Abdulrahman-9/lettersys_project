# -*- coding: utf-8 -*-
"""استعادةُ نسخةِ هذا النظام المشفّرة — **إلى قاعدةٍ جديدة، لا فوق الحيّة** (قرارُ المالك
2026‑10‑07، البند 3؛ تصميمُ فيبل).

لماذا قاعدةٌ جديدة: الاستعادةُ فوق القاعدة الحيّة (``--clean``) تجري تحت خادمٍ يعمل،
وصفُّ المهمّة نفسُه يسكن القاعدةَ التي تُمحى، والفشلُ في منتصفها يترك نصفَ قاعدة.
هنا لا يُكتب في القاعدة الحيّة شيء: تُنشأ قاعدةٌ باسمٍ مؤرَّخ، ويُبدّل المالكُ إليها
بسطرٍ واحدٍ في ``.env`` (``DB_NAME=…``) ثمّ إعادةِ تشغيل الخادم — والرجوعُ بإعادة السطر.

الحرّاسُ بالترتيب، وكلُّها **قبل** أيّ كتابة: اسمُ ملفٍّ آمنٌ داخل مجلّد النسخ وحده ·
اسمُ قاعدةٍ مؤرَّخٌ ليس الحيّةَ ولا موجوداً · ``pg_restore`` موجود · المحتوى نسخةُ
``PGDMP`` بعد الفكّ. ثمّ الصريحُ في مجلّدٍ مؤقّتٍ خارج المستودع يُحذف في ``finally``.
"""
import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.utils import timezone

from core import backup_verify as bv
from core.backup_service import DB_BACKUP_PATTERN, default_backup_dir

logger = logging.getLogger(__name__)

#: اسمُ القاعدة الجديدة: مؤرَّخٌ وبأحرفٍ آمنة — لا يُبنى من مدخلات المستخدم أبداً.
TARGET_RE = re.compile(r'^lettersys_r_\d{8}_\d{4}$')

#: ما يُطبع للمالك حين يعوز الدورَ حقُّ إنشاء القواعد — سطرُ DDL يُنفّذه بيده مرّةً واحدة.
CREATEDB_HINT = 'ALTER ROLE {user} CREATEDB;'


class RestoreRefused(Exception):
    """رفضٌ مقصود بلغة المدير — يُكتب في المهمّة كما هو."""


def target_name(now=None):
    now = now or timezone.localtime()
    return 'lettersys_r_' + now.strftime('%Y%m%d_%H%M')


def safe_backup_path(name, directory=None):
    """مسارُ نسخةٍ **في مجلّد النسخ وحده** من اسم ملفٍّ مجرّد — أو ``RestoreRefused``.

    الاسمُ يأتي من المتصفّح: لا فواصلَ مسار ولا ``..``، ويطابق نمطَ نسخ القاعدة،
    ويقع بعد الحلّ داخل المجلّد، وموجود.
    """
    name = (name or '').strip()
    if not name or name != Path(name).name or '/' in name or '\\' in name or '..' in name:
        raise RestoreRefused('اسمُ الملفّ غيرُ صالح.')
    if not Path(name).match(DB_BACKUP_PATTERN):
        raise RestoreRefused('هذا ليس ملفَّ نسخةٍ مشفّرةٍ من قاعدة النظام.')
    base = Path(directory) if directory else default_backup_dir()
    path = (base / name).resolve()
    if base.resolve() not in path.parents or not path.is_file():
        raise RestoreRefused('الملفُّ غيرُ موجودٍ في مجلّد النسخ.')
    return path


def database_exists(name):
    with connection.cursor() as cursor:
        cursor.execute('SELECT 1 FROM pg_database WHERE datname = %s', [name])
        return cursor.fetchone() is not None


def check_target(target):
    """القاعدةُ الجديدة ليست الحيّةَ ولا موجودة، واسمُها من صنعنا."""
    if not TARGET_RE.match(target or ''):
        raise RestoreRefused('اسمُ القاعدة الجديدة غيرُ صالح.')
    if target == settings.DATABASES['default']['NAME']:
        raise RestoreRefused('لن تُستعاد النسخةُ فوق القاعدة الحيّة.')
    if database_exists(target):
        raise RestoreRefused(f'القاعدةُ «{target}» موجودةٌ سلفاً — انتظر دقيقةً وأعد المحاولة باسمٍ جديد.')


def create_database(target):
    """``CREATE DATABASE`` — والدورُ بلا CREATEDB يُعطى سطرَ المالك بدل خطأٍ غامض."""
    from django.db import DatabaseError

    try:
        with connection.cursor() as cursor:
            cursor.execute('CREATE DATABASE "%s"' % target)   # الاسمُ من TARGET_RE لا من المستخدم
    except DatabaseError as exc:
        user = settings.DATABASES['default'].get('USER') or '<db_user>'
        raise RestoreRefused(
            'تعذّر إنشاءُ القاعدة الجديدة — دورُ القاعدة لا يملك حقَّ الإنشاء. '
            f'نفّذ مرّةً واحدةً بحسابٍ إداريّ في PostgreSQL: {CREATEDB_HINT.format(user=user)} '
            f'({type(exc).__name__})') from exc


def _pg_env():
    """كلمةُ مرور القاعدة في **بيئة** العمليّة الابنة لا في سطر الأوامر."""
    env = dict(os.environ)
    password = settings.DATABASES['default'].get('PASSWORD')
    if password:
        env['PGPASSWORD'] = password
    return env


def _pg_args(target):
    db = settings.DATABASES['default']
    args = ['--no-owner', '--no-privileges', '--exit-on-error', f'--dbname={target}']
    if db.get('HOST'):
        args.append(f'--host={db["HOST"]}')
    if db.get('PORT'):
        args.append(f'--port={db["PORT"]}')
    if db.get('USER'):
        args.append(f'--username={db["USER"]}')
    return args


def count_books(target):
    """عددُ الكتب في القاعدة الجديدة — دليلٌ أنّ الاستعادةَ لم تنتهِ فارغة."""
    import psycopg2

    db = settings.DATABASES['default']
    conn = psycopg2.connect(dbname=target, user=db.get('USER') or None, password=db.get('PASSWORD') or None,
                            host=db.get('HOST') or None, port=db.get('PORT') or None)
    try:
        with conn.cursor() as cursor:
            cursor.execute('SELECT count(*) FROM core_book')
            return cursor.fetchone()[0]
    finally:
        conn.close()


def restore_into_new_database(file_name, target, *, directory=None, report=None):
    """يستعيد ``file_name`` إلى قاعدة ``target`` الجديدة ويعيد خلاصةً بلا أسرار.

    ``report(phase)`` اختياريّ لتحديث المهمّة. لا يُكتب في القاعدة الحيّة شيء.
    """
    report = report or (lambda phase: None)
    source = safe_backup_path(file_name, directory)
    check_target(target)
    pg_restore = bv.resolve_pg_restore()          # VerifyError قبل أيّ فكّ

    report('فكُّ التشفير')
    plain, _key = bv.decrypt_if_needed(source.read_bytes())
    if not plain.startswith(bv.PGDMP_MAGIC):
        raise RestoreRefused('المحتوى ليس نسخةَ قاعدةٍ صالحة (رأسُ PGDMP غائب).')

    tempdir = bv.make_secure_tempdir()
    created = False
    try:
        dump = bv.write_private(tempdir / 'restore.dump', plain)
        del plain
        report('إنشاءُ القاعدة الجديدة')
        create_database(target)
        created = True
        report('استعادةُ الجداول')
        subprocess.run([str(pg_restore), *_pg_args(target), str(dump)], env=_pg_env(),
                       check=True, capture_output=True, timeout=6 * 3600)
        report('عدُّ الكتب')
        books = count_books(target)
        if not books:
            raise RestoreRefused(f'انتهت الاستعادةُ والقاعدةُ «{target}» بلا كتب.')
    except Exception as exc:
        # ما أنشأه هذا الاستدعاءُ يُزال قبل أن يُرفع الفشل (11-22): كانت تبقى قاعدةٌ نصفُ مستعادة
        # و«احذفها بيدك». ما لم يُنشأ بعدُ لا يُمسّ — والرفعُ يمضي في الحالين.
        if not created:
            raise
        note = discard_new_database(target)
        if isinstance(exc, subprocess.CalledProcessError):
            logger.error('pg_restore into %s rc=%s stderr=%s', target, exc.returncode, (exc.stderr or b'')[-4000:])
            raise RestoreRefused(f'توقّفت الاستعادةُ برمز {exc.returncode} — التفصيلُ في سجلّ الخادم. {note}') from exc
        if isinstance(exc, RestoreRefused):
            raise RestoreRefused(f'{exc} {note}') from exc
        logger.exception('restore into %s failed', target)
        raise RestoreRefused(f'فشلت الاستعادة ({type(exc).__name__}) — التفصيلُ في سجلّ الخادم. {note}') from exc
    finally:
        shutil.rmtree(tempdir, ignore_errors=True)

    return {'target': target, 'books': books, 'command': switch_command(target)}


def drop_restored_database(target) -> bool:
    """يُسقط قاعدةَ استعادةٍ فاشلة — بحارسَين قبل أيّ ``DROP``: الاسمُ مؤرَّخٌ من صنعنا (``TARGET_RE``)،
    وليس القاعدةَ الحيّة. يعيد ``True`` إن سقطت."""
    from django.db import DatabaseError

    if not TARGET_RE.match(target or '') or target == settings.DATABASES['default']['NAME']:
        return False
    try:
        with connection.cursor() as cursor:
            cursor.execute('DROP DATABASE IF EXISTS "%s"' % target)   # الاسمُ من TARGET_RE لا من المستخدم
    except DatabaseError:
        logger.exception('drop_restored_database: تعذّر إسقاط %s', target)
        return False
    return True


def discard_new_database(target) -> str:
    """يُزيل القاعدةَ الناقصة ويقول ما جرى بلغة المدير."""
    if drop_restored_database(target):
        return f'أُزيلت القاعدةُ الناقصة «{target}»، والقاعدةُ الحاليّة لم تُمسّ — أعد المحاولة.'
    return (f'وتعذّرت إزالةُ القاعدة الناقصة «{target}» — لا تبدّل إليها، واحذفها من PostgreSQL. '
            'القاعدةُ الحاليّة لم تُمسّ.')


def switch_command(target) -> str:
    """سطرُ التبديل كما يُلصق في موجّه الأوامر على الخادم (``use_restored_database``)."""
    return f'"{sys.executable}" "{Path(settings.BASE_DIR) / "manage.py"}" use_restored_database {target}'
