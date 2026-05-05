# optimize_startup.py - تحسين سرعة بدء الخادم
# =====================================================

import argparse
import os
import subprocess
import sys

import django
from django.conf import settings

def optimize_django():
    """تحسين الإعدادات لتسريع البدء"""
    
    # تعطيل بعض الميزات في development للسرعة
    if not settings.DEBUG:
        return
    
    # تحسين الـ Cache
    if 'default' in settings.CACHES:
        settings.CACHES['default']['TIMEOUT'] = 300  # تقليل timeout
    
    # تحسين Database
    settings.CONN_MAX_AGE = 600  # إعادة استخدام الاتصالات
    
    # تعطيل بعض الـ Middleware للسرعة (في development فقط)
    if settings.DEBUG:
        if 'core.middleware.logging_middleware.RequestLoggingMiddleware' in settings.MIDDLEWARE:
            # تقليل logging
            settings.LOGGING['level'] = 'WARNING'

def _run_manage(command_args):
    """Run a manage.py command with the current interpreter."""
    cmd = [sys.executable, 'manage.py', *command_args]
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout.strip())
    if result.stderr:
        print(result.stderr.strip())
    return result.returncode


def check_migrations(apply_migrations=False):
    """التحقق من صحة الهجرات، مع تطبيقها اختيارياً عند الطلب."""
    rc = _run_manage(['db_healthcheck'])
    if rc != 0:
        print("⚠️  فشل فحص صحة قاعدة البيانات/الهجرات")
        return

    if apply_migrations:
        rc = _run_manage(['migrate', '--noinput'])
        if rc == 0:
            print("✓ تم تطبيق Migrations بنجاح")
        else:
            print("⚠️  فشل تطبيق Migrations")
    else:
        print("✓ تم التحقق من Migrations (بدون تطبيق)")

def collect_static():
    """جمع الملفات الثابتة"""
    if settings.DEBUG:
        print("⏭️  تم تخطي collectstatic في mode Development")
    else:
        os.system('python manage.py collectstatic --noinput')
        print("✓ تم جمع الملفات الثابتة")

def check_database():
    """التحقق من قاعدة البيانات"""
    try:
        from django.db import connection
        connection.ensure_connection()
        print("✓ قاعدة البيانات تعمل بنجاح")
    except Exception as e:
        print(f"⚠️  خطأ في قاعدة البيانات: {e}")

def main():
    parser = argparse.ArgumentParser(description='Optimize startup and run DB checks safely.')
    parser.add_argument(
        '--apply-migrations',
        action='store_true',
        help='Apply pending migrations after healthcheck succeeds.',
    )
    args = parser.parse_args()

    print("\n🔧 تحسين إعدادات Django...")
    print("=" * 60)
    
    django.setup()
    
    optimize_django()
    check_migrations(apply_migrations=args.apply_migrations)
    collect_static()
    check_database()
    
    print("=" * 60)
    print("✅ تم إكمال التحسينات!\n")

if __name__ == '__main__':
    main()
