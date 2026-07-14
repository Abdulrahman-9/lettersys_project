"""
management/commands/import_legacy.py
=====================================
أمر Django لاستيراد البيانات القديمة

الاستخدام:
    # معاينة بدون تطبيق فعلي
    python manage.py import_legacy --file export/sample_data.json --dry-run

    # استيراد كامل مع تأكيد
    python manage.py import_legacy --file export/full_data.json --user admin --confirm
"""

import json
from pathlib import Path

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from core.import_engine import LegacyImportEngine


class Command(BaseCommand):
    help = 'استيراد البيانات القديمة من ملف JSON مُصدَّر من النظام السابق'

    def add_arguments(self, parser):
        parser.add_argument(
            '--file', required=True,
            help='مسار ملف JSON المُصدَّر من النظام القديم'
        )
        parser.add_argument(
            '--map', default=None,
            help='مسار ملف JSON لخريطة الحقول (import_config.json). إذا لم يُحدَّد يُحاول التخمين التلقائي'
        )
        parser.add_argument(
            '--user', default='admin',
            help='اسم المستخدم الذي سيُسجَّل كمنشئ للسجلات (افتراضي: admin)'
        )
        parser.add_argument(
            '--prefix', default='',
            help='بادئة اختيارية لأرقام الكتب المتعارضة (فارغة افتراضياً — التعارض يُتخطّى)'
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='معاينة بدون حفظ فعلي في قاعدة البيانات'
        )
        parser.add_argument(
            '--confirm', action='store_true',
            help='تأكيد الاستيراد الفعلي (مطلوب إذا لم يكن --dry-run)'
        )

    def handle(self, *args, **options):
        json_file = Path(options['file'])
        if not json_file.exists():
            raise CommandError(f"الملف غير موجود: {json_file}")

        dry_run = options['dry_run']
        confirm = options['confirm']

        if not dry_run and not confirm:
            raise CommandError(
                "يجب تحديد --dry-run للمعاينة أو --confirm للاستيراد الفعلي"
            )

        # المستخدم
        try:
            import_user = User.objects.get(username=options['user'])
        except User.DoesNotExist:
            raise CommandError(f"المستخدم غير موجود: {options['user']}")

        # خريطة الحقول
        field_map = {}
        if options['map']:
            map_file = Path(options['map'])
            if map_file.exists():
                with open(map_file, encoding='utf-8') as f:
                    config = json.load(f)
                # استخراج أول field_map من أول جدول
                for table_config in config.get('tables', {}).values():
                    field_map = {
                        v.split('.')[-1]: k
                        for k, v in table_config.get('field_map', {}).items()
                        if '.' in v and '❓' not in v
                    }
                    break

        mode = "معاينة (dry-run)" if dry_run else "استيراد فعلي"
        self.stdout.write(f"\n🚀 بدء {mode}")
        self.stdout.write(f"   الملف: {json_file}")
        self.stdout.write(f"   المستخدم: {import_user.username}")
        self.stdout.write(f"   البادئة: {options['prefix']}")
        self.stdout.write("")

        engine = LegacyImportEngine(
            field_map=field_map,
            import_user=import_user,
            dry_run=dry_run,
            number_prefix=options['prefix'],
        )

        summary = engine.import_from_file(json_file)
        summary.print_report()

        if dry_run:
            self.stdout.write(self.style.WARNING(
                "\n⚠️  هذه معاينة فقط - لم يُحفظ أي شيء."
                "\n   لتطبيق الاستيراد: أضف --confirm وأزل --dry-run"
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"\n✅ اكتمل الاستيراد: {summary.created} سجل جديد"
            ))
