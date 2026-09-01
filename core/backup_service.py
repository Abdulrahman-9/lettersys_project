# -*- coding: utf-8 -*-
"""
خدمة النسخ الاحتياطي المشتركة — يستعملها العرض اليدوي (dashboard.backup_database)
والمهمة المجدولة (tasks.scheduled_backup) معاً، فلا تكرار لمنطق pg_dump/التشفير.
"""

import logging
import os
import shutil
import subprocess
from pathlib import Path

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


#: وجهةُ النسخ الافتراضيّة — قرصٌ منفصلٌ عن قرص النظام بقرار المالك.
DEFAULT_BACKUP_DIR = Path("D:/trackbackup")


def default_backup_dir() -> Path:
    """مجلّدُ النسخ — ``BACKUP_DIR`` في البيئة، وإلّا ``D:/trackbackup``.

    **والسقوطُ إلى داخل المشروع يصرخ ولا يصمت**: قرصُ النظام هنا مقيسٌ على
    حافّة الامتلاء (بَتَر ملفّاً فعلاً)، فنسخةٌ تُكتب عليه بهدوءٍ بدل القرص
    المنفصل هي أسوأ من فشلٍ صريح — تبدو ناجحةً حتى يوم الحاجة.
    """
    configured = os.environ.get("BACKUP_DIR", "").strip()
    directory = Path(configured) if configured else DEFAULT_BACKUP_DIR

    if not directory.exists():
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            fallback = settings.BASE_DIR / "backups"
            logger.error(
                "وجهةُ النسخ %s غيرُ متاحة — السقوطُ إلى %s على قرص النظام. "
                "اضبط BACKUP_DIR أو أعِد توصيل القرص.", directory, fallback)
            fallback.mkdir(parents=True, exist_ok=True)
            return fallback

    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _find_pg_dump():
    """مسارُ ``pg_dump`` — من البيئة، أو المسار، أو تنصيبِ PostgreSQL على ويندوز.

    **مقيسٌ على هذا الجهاز:** ``pg_dump`` ليس في PATH و``PG_DUMP_BIN`` غيرُ
    مضبوط — فكانت كلُّ نسخةٍ ترمي ``FileNotFoundError``. البحثُ عن التنصيب
    يجعل الميزةَ تعمل بلا إعدادٍ يدويّ، وأحدثُ إصدارٍ أوّلاً لأنّ ``pg_dump``
    الأقدم يرفض قاعدةً أحدث منه.
    """
    explicit = os.environ.get("PG_DUMP_BIN")
    if explicit and Path(explicit).exists():
        return explicit

    found = shutil.which("pg_dump")
    if found:
        return found

    roots = [Path(r"C:/Program Files/PostgreSQL"),
             Path(r"C:/Program Files (x86)/PostgreSQL")]
    candidates = []
    for root in roots:
        if not root.is_dir():
            continue
        for child in root.iterdir():
            binary = child / "bin" / "pg_dump.exe"
            if binary.exists():
                # الترتيبُ بالرقم لا بالنصّ: "9" > "16" نصّيّاً.
                version = int(child.name) if child.name.isdigit() else 0
                candidates.append((version, str(binary)))
    if candidates:
        return max(candidates)[1]
    return None


def _build_pg_dump_command(db_config, output_path):
    """يبني أمر pg_dump (صيغة custom مشفّرة لاحقاً)."""
    pg_dump_bin = _find_pg_dump()
    if not pg_dump_bin:
        raise FileNotFoundError(
            "تعذّر العثور على pg_dump — ثبّت أدوات PostgreSQL أو اضبط PG_DUMP_BIN.")

    command = [
        pg_dump_bin,
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        f"--file={output_path}",
    ]
    if db_config.get("HOST"):
        command.append(f"--host={db_config['HOST']}")
    if db_config.get("PORT"):
        command.append(f"--port={db_config['PORT']}")
    if db_config.get("USER"):
        command.append(f"--username={db_config['USER']}")
    command.append(f"--dbname={db_config['NAME']}")
    return command


def create_encrypted_pg_backup(target_dir=None, file_name=None) -> Path:
    """
    ينشئ نسخة pg_dump مشفّرة ويعيد مسار الملف المشفّر (``*.dump.enc``).
    يرمي ``FileNotFoundError`` (pg_dump مفقود) أو ``subprocess.CalledProcessError``
    (فشل الاستخراج) أو ``OSError`` (فشل كتابة/تشفير) — يلتقطها المُستدعي.
    """
    from .encryption import encrypt_file

    db_config = settings.DATABASES["default"]
    directory = Path(target_dir) if target_dir else default_backup_dir()
    directory.mkdir(parents=True, exist_ok=True)

    if not file_name:
        file_name = f"pg_backup_{timezone.now().strftime('%Y%m%d_%H%M')}.dump"
    file_name = Path(file_name).name
    if not file_name.endswith(".dump"):
        file_name += ".dump"
    target_path = directory / file_name

    env = os.environ.copy()
    if db_config.get("PASSWORD"):
        env["PGPASSWORD"] = str(db_config["PASSWORD"])

    subprocess.run(
        _build_pg_dump_command(db_config, target_path),
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return Path(encrypt_file(target_path))


#: أنماطُ ما يُشذَّب. المرآةُ ليست منها: هي نسخةٌ حيّةٌ للحالة الراهنة لا
#: لقطةٌ مؤرَّخة — تشذيبها بالعمر يحذف مرفقاتٍ ما زالت مستعملة.
PRUNABLE_PATTERNS = ('*.dump.enc', '*.tar.enc')


def prune_old_backups(directory, retention_days: int) -> int:
    """يحذف اللقطات المؤرَّخة الأقدم من ``retention_days`` يوماً. يعيد عدد المحذوف."""
    directory = Path(directory)
    if retention_days <= 0 or not directory.exists():
        return 0

    cutoff = timezone.now().timestamp() - retention_days * 86400
    removed = 0
    candidates = [f for pattern in PRUNABLE_PATTERNS for f in directory.glob(pattern)]
    for f in candidates:
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                removed += 1
        except OSError:
            logger.warning("prune_old_backups: تعذّر حذف %s", f)
    return removed


# ══════════════════════════════════════════════════════════════════
#  ما وراء قاعدة البيانات — سجلّ العيوب ح8
#
#  كان النسخ يغطّي `pg_dump` وحده. وقياسٌ على التنصيب الحيّ: **15.8 غيغا في
#  14,041 ملفاً** من المرفقات لا يحميها شيء — أي أنّ استعادةً «ناجحة» من نسخةٍ
#  احتياطية كانت تُعيد نظاماً بكتبٍ بلا مستنداتها. ومعها `.env` (اعتماد القاعدة)
#  و`var/models/` (أوزان القارئ) و`.encryption_key` الذي يفتح كلّ ما سبق.
# ══════════════════════════════════════════════════════════════════

#: ملفّات الإعداد الصغيرة التي تُحفظ مشفّرةً مع كلّ نسخة.
CONFIG_FILES = ('.env',)


def mirror_tree(src, dst, *, dry_run: bool = False) -> dict:
    """يُطابق شجرة ملفّاتٍ تدريجيّاً — ينسخ الجديد والمتغيّر فقط.

    النسخ الكامل غير وارد: 15.8 غيغا لا تُنسخ كلّ ساعة. والتدريجيّ صحيحٌ هنا
    بطبيعة البيانات — المرفق لا يُعدَّل بعد كتابته (التعديل يُنشئ ``AttachmentVersion``
    بملفٍّ جديد)، فمقارنةُ (الحجم، زمن التعديل) كافيةٌ ولا تحتاج هاشاً.

    مقيس: مسحُ الشجرة كاملةً 0.4 ثانية — فالتشغيل كلّ ساعةٍ رخيص.

    **لا تشفير هنا عمداً:** المصدر نفسه غير مشفَّر على القرص، فتشفير المرآة
    المحلّية لا يضيف حاجزاً — يضيف كلفةَ 15.8 غيغا كلّ دورة. التشفير يلزم
    للنسخة التي **تغادر** المبنى، وذلك بندُ مرحلة ز0.
    """
    src, dst = Path(src), Path(dst)
    stats = {'scanned': 0, 'copied': 0, 'bytes': 0, 'errors': 0, 'skipped_missing_src': False}

    if not src.is_dir():
        stats['skipped_missing_src'] = True
        return stats

    for dirpath, _dirnames, filenames in os.walk(src):
        rel_dir = Path(dirpath).relative_to(src)
        for name in filenames:
            stats['scanned'] += 1
            source = Path(dirpath) / name
            target = dst / rel_dir / name
            try:
                s_stat = source.stat()
                if target.exists():
                    t_stat = target.stat()
                    # هامشُ ثانيتين: أنظمة ملفّاتٍ مختلفة تُدوّر زمن التعديل.
                    if t_stat.st_size == s_stat.st_size and abs(t_stat.st_mtime - s_stat.st_mtime) <= 2:
                        continue
                if dry_run:
                    stats['copied'] += 1
                    stats['bytes'] += s_stat.st_size
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                stats['copied'] += 1
                stats['bytes'] += s_stat.st_size
            except OSError as exc:
                stats['errors'] += 1
                logger.warning("mirror_tree: تعذّر نسخ %s — %s", source, exc)

    return stats


def create_encrypted_config_backup(target_dir=None, file_name=None) -> Path | None:
    """يحفظ ملفّات الإعداد الصغيرة (`.env`) في أرشيفٍ مشفَّر.

    ``.env`` يحمل اعتماد قاعدة البيانات ومسار الوسائط — بدونه لا تقوم استعادةٌ
    على جهازٍ نظيف. و**لا يُضمّ إليه `.encryption_key`**: مفتاحٌ بجانب المعمّى
    الذي يفتحه ليس تشفيراً (انظر ``encryption_key_status``).
    """
    import tarfile

    from .encryption import encrypt_file

    directory = Path(target_dir) if target_dir else default_backup_dir()
    directory.mkdir(parents=True, exist_ok=True)

    present = [settings.BASE_DIR / name for name in CONFIG_FILES]
    present = [p for p in present if p.exists()]
    if not present:
        logger.warning("create_encrypted_config_backup: لا ملفّات إعدادٍ لحفظها")
        return None

    if not file_name:
        file_name = f"config_{timezone.now().strftime('%Y%m%d_%H%M')}.tar"
    file_name = Path(file_name).name
    if not file_name.endswith('.tar'):
        file_name += '.tar'
    archive = directory / file_name

    with tarfile.open(archive, 'w') as tar:
        for path in present:
            tar.add(path, arcname=path.name)

    return Path(encrypt_file(archive))


def encryption_key_status(backup_dir=None) -> dict:
    """حالةُ مفتاح التشفير — نقطةُ الفشل الواحدة في كلّ هذه المنظومة.

    فقدانُ ``.encryption_key`` يعني فقدان كلمات سرّ البريد **وكلّ** النسخ
    المشفَّرة معاً. ومع ذلك لا ينسخه هذا الكود تلقائيّاً إلى وجهة النسخ: وضعُ
    المفتاح بجانب ما يفتحه يُلغي التشفير من أصله. فالواجب نقلُه يدويّاً إلى
    خزانةٍ أو جهازٍ منفصل — وهذه الدالّة تُعطي بصمته للتحقّق، وتصرخ إن وجدته
    مُلقىً في وجهة النسخ.
    """
    import hashlib

    from .encryption import ENCRYPTION_KEY_FILE

    key_path = Path(ENCRYPTION_KEY_FILE)
    status = {'exists': key_path.exists(), 'path': str(key_path),
              'fingerprint': None, 'leaked_into_backup_dir': False}

    if status['exists']:
        status['fingerprint'] = hashlib.sha256(key_path.read_bytes()).hexdigest()[:16]

    directory = Path(backup_dir) if backup_dir else default_backup_dir()
    if directory.exists():
        for candidate in directory.rglob('.encryption_key'):
            status['leaked_into_backup_dir'] = True
            logger.error(
                "encryption_key_status: المفتاح موجودٌ داخل وجهة النسخ (%s) — "
                "هذا يُلغي تشفير النسخ كلّها. انقله إلى خزانةٍ منفصلة واحذفه من هنا.",
                candidate,
            )
            break

    return status
