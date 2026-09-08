#!/usr/bin/env python
"""
PostgreSQL Migration Helper - أداة استيراد البيانات إلى PostgreSQL

الاستخدام (بعد الانتهاء من الترحيل عن SQLite):
  1. تصدير البيانات (من قاعدة بيانات django dumpdata):
       python manage.py dumpdata --all --natural-primary --natural-foreign --indent=2 \\
           -e contenttypes -e auth.Permission -o data_backup.json

     ⚠️ ``--all`` **إلزاميّ**: منذ صار للحذف الناعم مديرٌ افتراضيّ
     (``SoftDeleteManager`` على Book وAttachment)، يقرأ ``dumpdata`` المديرَ
     الافتراضيّ فيُسقط كلّ المحذوف ناعماً **بصمت** — أي تُفقد سلّة
     المحذوفات كاملةً في النقل. ``--all`` يُجبره على ``_base_manager``.

  2. تثبيت PostgreSQL 16 وإنشاء قاعدة البيانات (مرة واحدة):
       شغّل activate_postgresql.bat

  3. تطبيق الهجرات:
       python manage.py migrate

  4. استيراد البيانات:
       python manage.py loaddata data_backup.json

  5. التحقق:
       python pg_migrate.py  ← اختر "2"
"""

import os
import sys
import subprocess


def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lettersys.settings')

    steps = [
        ("1", "تطبيق هجرات PostgreSQL", migrate_pg),
        ("2", "استيراد البيانات إلى PostgreSQL", import_pg),
        ("3", "التحقق من النتائج", verify),
    ]

    print("=" * 60)
    print("  أداة إعداد قاعدة بيانات PostgreSQL")
    print("=" * 60)

    for num, desc, _ in steps:
        print(f"  {num}. {desc}")

    print("\n  0. تنفيذ جميع الخطوات")
    choice = input("\n اختر الخطوة (0-3): ").strip()

    if choice == "0":
        for _, desc, func in steps:
            print(f"\n{'─'*40}\n ▶ {desc}...")
            func()
    else:
        for num, desc, func in steps:
            if num == choice:
                func()
                break


def _run(cmd):
    print(f"  $ {cmd}")
    subprocess.run(cmd, shell=True, check=True)


def migrate_pg():
    """Step 1: Run migrations on PostgreSQL."""
    _run(f'"{sys.executable}" manage.py migrate --run-syncdb')
    print("  ✅ تم تطبيق الهجرات على PostgreSQL")


def import_pg():
    """Step 2: Load data into PostgreSQL."""
    _run(f'"{sys.executable}" manage.py loaddata data_backup.json')
    print("  ✅ تم استيراد البيانات إلى PostgreSQL")


def verify():
    """Step 3: Quick verification."""
    import django
    django.setup()

    from django.db import connection
    from core.models import Book, Entity

    print(f"  Backend : {connection.vendor}")
    print(f"  Books   : {Book.objects.count()}")
    print(f"  Entities: {Entity.objects.count()}")

    with connection.cursor() as cur:
        cur.execute("SELECT extname FROM pg_extension WHERE extname='pg_trgm'")
        row = cur.fetchone()
        print(f"  pg_trgm : {'✅ مفعّل' if row else '❌ غير مفعّل'}")
    print("  ✅ التحقق ناجح — PostgreSQL + FTS جاهز")


if __name__ == '__main__':
    main()
