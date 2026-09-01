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


def default_backup_dir() -> Path:
    """المجلد الافتراضي للنسخ الاحتياطية (D:/trackbackup أو backups/ داخل المشروع)."""
    directory = Path("D:/trackbackup")
    if not directory.exists():
        directory = settings.BASE_DIR / "backups"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _build_pg_dump_command(db_config, output_path):
    """يبني أمر pg_dump (صيغة custom مشفّرة لاحقاً)."""
    pg_dump_bin = os.environ.get("PG_DUMP_BIN") or shutil.which("pg_dump")
    if not pg_dump_bin:
        raise FileNotFoundError("pg_dump was not found. Install PostgreSQL client tools or set PG_DUMP_BIN.")

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


def prune_old_backups(directory, retention_days: int) -> int:
    """يحذف نسخ ``*.dump.enc`` الأقدم من ``retention_days`` يوماً. يعيد عدد المحذوف."""
    directory = Path(directory)
    if retention_days <= 0 or not directory.exists():
        return 0

    cutoff = timezone.now().timestamp() - retention_days * 86400
    removed = 0
    for f in directory.glob("*.dump.enc"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                removed += 1
        except OSError:
            logger.warning("prune_old_backups: تعذّر حذف %s", f)
    return removed
