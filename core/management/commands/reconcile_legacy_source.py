# -*- coding: utf-8 -*-
"""
أمر المطابقة: يختم `source_ref` على الكتب المستوردة سابقاً من قاعدة ARCHMDOC.

المشكلة التي يحلّها
-------------------
`source_ref` هو المفتاح الوحيد الدقيق للدمج ("هذا الصفّ عندي أصلاً")، وهو **فارغ**
في كل الكتب التي استوردتها الأدوات السابقة. بدونه يسقط الدمج على مطابقة
(kind, legacy_number)، و`legacy_number` للوارد هو **رقم الجهة المرسِلة** لا رقمنا،
وهو مكرَّر بطبيعته. النتيجة المقيسة على البيانات الفعلية: الدمج يتبنّى ~36% فقط
بشكل سليم، ويربط ~28% بكتابٍ خاطئ (تلف صامت)، ويُكرّر ~37%.

بعد تشغيل هذا الأمر مرّةً واحدة يصبح الدمج اللاحق مطابقةً بمفتاحٍ فريد: بلا التباس،
بلا تكرار، وبلا مسٍّ لكتبٍ أدخلتها داخل التطبيق.

الاستخدام
---------
    # معاينة (لا يكتب شيئاً)
    python manage.py reconcile_legacy_source --database ARCHMDOC

    # تنفيذ فعلي + تحقّق بالبايتات على 20 زوجاً
    python manage.py reconcile_legacy_source --database ARCHMDOC --yes --verify-bytes 20

كلمة السرّ: عبر --password أو متغيّر البيئة LEGACY_SQL_PASSWORD.

ملاحظة ويندوز: صدّر PYTHONIOENCODING=utf-8 قبل التشغيل لتفادي كسر cp1256.
"""
import os

from django.core.management.base import BaseCommand, CommandError

from core.legacy_restore import LegacyRestoreEngine
from core.models import Book


class Command(BaseCommand):
    help = 'ختم source_ref على الكتب المستوردة سابقاً بمطابقتها بصفوفها في قاعدة المصدر.'

    def add_arguments(self, parser):
        parser.add_argument('--server', default='localhost', help='خادم SQL Server')
        parser.add_argument('--database', required=True, help='اسم قاعدة المصدر (مثل ARCHMDOC)')
        parser.add_argument('--user', default='sa', help='مستخدم SQL Server')
        parser.add_argument('--password', default=None,
                            help='كلمة السرّ (أو عبر متغيّر البيئة LEGACY_SQL_PASSWORD)')
        parser.add_argument('--years', default='', help='سنوات محدّدة مفصولة بفواصل (فارغ = الكل)')
        parser.add_argument('--verify-bytes', type=int, default=0, metavar='N',
                            help='تحقّق ببصمة SHA-256 على N زوجاً مطابقاً (يسحب مرفقاتها)')
        parser.add_argument('--yes', action='store_true',
                            help='تنفيذ الختم فعلياً (بدونه: معاينة فقط)')

    def handle(self, *args, **options):
        password = options['password'] or os.environ.get('LEGACY_SQL_PASSWORD', '')
        if not password:
            raise CommandError(
                'كلمة السرّ مطلوبة: مرّرها بـ --password أو صدّرها في LEGACY_SQL_PASSWORD.')

        years = [y.strip() for y in options['years'].split(',') if y.strip()] or None
        engine = LegacyRestoreEngine(options['server'], options['database'],
                                     options['user'], password, years=years)

        w = self.stdout.write
        before = Book.objects.exclude(source_ref='').count()
        total = Book.objects.count()
        w('=' * 66)
        w(f'الكتب في النظام: {total}  —  المختومة بـ source_ref قبل التشغيل: {before}')
        w('-' * 66)

        try:
            report = engine.reconcile(
                apply=options['yes'],
                verify_bytes=options['verify_bytes'],
                progress_cb=lambda m: w(f'  … {m}'),
            )
        except Exception as exc:
            raise CommandError(f'فشل الاتصال أو المطابقة: {exc}')

        w('-' * 66)
        w(f"صفوف المصدر           : {report['source_rows']:,}")
        w(f"كتب بلا source_ref     : {report['books_without_ref']:,}")
        w(f"مُطابَقة بمفتاح فريد    : {report['matched']:,}"
          f"  (بالحجم {report.get('matched_by_size', 0):,}"
          f" · بالعنوان {report.get('matched_by_title', 0):,})")
        w(f"ملتبسة (تُركت)         : {report['ambiguous']:,}")
        w(f"كتب بلا مطابقة        : {report['unmatched_books']:,}")
        w(f"صفوف مصدر بلا مطالبة  : {report['unclaimed_source_rows']:,}")

        if report['verified_bytes']:
            bad = report['verify_mismatches']
            w('-' * 66)
            w(f"تحقّق البصمات على مطابقات الحجم: قُورن {report['verified_bytes']} زوجاً — "
              f"{'تطابق تامّ' if not bad else f'{len(bad)} اختلاف'}")
            if report.get('unverifiable'):
                w(f"    (تُخطّي {report['unverifiable']} كتاباً بلا مرفق محلي — لا بصمة تُقارَن)")
            for bid, sref in bad[:10]:
                w(f'    اختلاف: كتاب {bid} ↔ {sref}')

        attention = report.get('attention') or []
        if attention:
            w('-' * 66)
            w(f"تحتاج نظرك — رُبطت بالعنوان والتاريخ لا بالحجم ({len(attention)}):")
            for a in attention[:10]:
                w(f"    كتاب {a['book']} ↔ {a['source_ref']}"
                  f"  (محلي {a['local_bytes']:,} بايت · مصدر {a['source_bytes']:,})")
            if len(attention) > 10:
                w(f"    … و{len(attention) - 10} غيرها")
            w("    الفارق طبيعي إن كنتَ استبدلت المرفق داخل التطبيق.")

        w('=' * 66)
        if report.get('aborted'):
            w(self.style.ERROR(report['aborted']))
        elif report['applied']:
            after = Book.objects.exclude(source_ref='').count()
            w(self.style.SUCCESS(
                f'خُتِم source_ref على {report["matched"]:,} كتاباً '
                f'(المجموع الآن {after:,} من {total:,}).'))
        else:
            w(self.style.WARNING('معاينة فقط — لم يُكتب شيء. أضِف --yes للتنفيذ الفعلي.'))
