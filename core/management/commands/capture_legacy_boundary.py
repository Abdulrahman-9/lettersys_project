# -*- coding: utf-8 -*-
"""
يلتقط «حدّ» قاعدة المصدر: أكبر معرّف في كل جدول بريد وقت التشغيل.

لماذا يلزم
----------
بعد المزامنة يصير كل ما في المصدر موجوداً عندنا، فأي معرّف أكبر من الحدّ لاحقاً
هو صفٌّ **استجدّ** يقيناً — وأي معرّف أصغر منه ولم يُستورد فهو صفٌّ قديم تُرك
عمداً (تعميم مكرَّر مثلاً) ولا يصحّ إضافته تلقائياً كنسخةٍ ثانية.

متى تُشغّله
-----------
  • **قبل** أي `RESTORE ... WITH REPLACE` تمحو نسخة المصدر الحالية — بعدها يستحيل
    قياس الحدّ القديم.
  • **بعد** كل دمج ناجح، ليُصبح الحدّ الجديد أساس المقارنة التالية.

    python manage.py capture_legacy_boundary --database ARCHMDOC
    python manage.py capture_legacy_boundary --database ARCHMDOC --note "قبل استعادة تمّوز"

كلمة السرّ: عبر --password أو متغيّر البيئة LEGACY_SQL_PASSWORD.
ملاحظة ويندوز: صدّر PYTHONIOENCODING=utf-8 قبل التشغيل.
"""
import os

from django.core.management.base import BaseCommand, CommandError

from core.legacy_restore import LegacyRestoreEngine


class Command(BaseCommand):
    help = 'التقاط حدّ قاعدة المصدر (أكبر معرّف لكل جدول) لتمييز الجديد عن القديم لاحقاً.'

    def add_arguments(self, parser):
        parser.add_argument('--server', default='localhost')
        parser.add_argument('--database', required=True, help='اسم قاعدة المصدر (مثل ARCHMDOC)')
        parser.add_argument('--user', default='sa')
        parser.add_argument('--password', default=None,
                            help='أو عبر متغيّر البيئة LEGACY_SQL_PASSWORD')
        parser.add_argument('--note', default='', help='ملاحظة تُحفظ مع اللقطة')
        parser.add_argument('--force', action='store_true',
                            help='الكتابة فوق لقطة موجودة دون سؤال')

    def handle(self, *args, **options):
        password = options['password'] or os.environ.get('LEGACY_SQL_PASSWORD', '')
        if not password:
            raise CommandError('كلمة السرّ مطلوبة: --password أو LEGACY_SQL_PASSWORD.')

        db = options['database']
        w = self.stdout.write
        path = LegacyRestoreEngine.boundary_path(db)

        old = LegacyRestoreEngine.load_boundary(db)
        if old and not options['force']:
            w(self.style.WARNING(f'توجد لقطة سابقة: {path}'))
            w('  الحدود الحالية: ' + '، '.join(f'{t}={v}' for t, v in sorted(old.items()) if v))
            w(self.style.ERROR(
                'لم يُكتب شيء. الكتابة فوقها تُفقد القدرة على تمييز ما لم يُستورد '
                'من الصفوف القديمة — أضِف --force إن كنتَ متأكّداً (بعد دمجٍ ناجح مثلاً).'))
            return

        engine = LegacyRestoreEngine(options['server'], db, options['user'], password)
        try:
            payload = engine.capture_boundary(note=options['note'])
        except Exception as exc:
            raise CommandError(f'فشل الالتقاط: {exc}')

        w('=' * 66)
        w(f"قاعدة المصدر: {payload['database']}   —   وقت الالتقاط: {payload['captured_at']}")
        w('-' * 66)
        for tbl, v in sorted(payload['tables'].items()):
            w('  %-16s صفوف=%-7s أكبر معرّف=%-7s آخر تاريخ=%s'
              % (tbl, v['rows'], v['max_id'], v['max_date'] or '—'))
        w('-' * 66)
        w(f"إجمالي صفوف المصدر : {payload['source_rows_total']:,}")
        w(f"كتب النظام          : {payload['books_in_lettersys']:,}"
          f"  (مربوطة بالمصدر: {payload['books_stamped']:,})")
        w('=' * 66)
        w(self.style.SUCCESS(f"حُفظت اللقطة: {payload['path']}"))
