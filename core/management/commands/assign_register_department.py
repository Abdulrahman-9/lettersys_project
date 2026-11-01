# -*- coding: utf-8 -*-
"""ينسب كتبَ الدفتر القديم اليتيمة (بلا قسم) إلى قسم السجلّ — معاينةٌ افتراضاً، و``--undo``.

دمجُ 2026‑10‑27 أنشأ 2,622 كتاباً من جداول 2026 (IIMAIL/IOMAIL/OIMAIL) بلا قسم: لا
يراها أحدٌ في قسم المتابعة سوى مدير النظام، ولا تدخل لوحاتِه. الكودُ أُصلح
(``LegacyRestoreEngine._register_department``)، وهذا الأمرُ يُصلح ما دخل قبله.

لا يلمس إلّا ما جاء من المصدر القديم (``source_ref`` غيرُ فارغ): كتابُ التطبيق بلا قسم
شأنٌ آخر يُفحص باليد. والتقريرُ يُكتب **قبل** التنفيذ، فالتراجعُ ممكنٌ دائماً.
"""
import csv
from collections import Counter
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from core.models import Book, BookSequence, Department


class Command(BaseCommand):
    help = 'ينسب كتب الدفتر القديم بلا قسم إلى قسم السجلّ (معاينة افتراضاً).'

    def add_arguments(self, parser):
        parser.add_argument('--department', default=None,
                            help='رمز قسم السجلّ (افتراضاً: القسم الافتراضيّ للعدّادات).')
        parser.add_argument('--source', action='append', default=None, metavar='PREFIX',
                            help='بادئةُ جدول المصدر (IIMAIL_2026…) — تتكرّر. بدونها: كلُّ القديم اليتيم.')
        parser.add_argument('--report', default='var/assign_register_department.csv')
        parser.add_argument('--yes', action='store_true', help='تنفيذ فعلي (بدونه: معاينة)')
        parser.add_argument('--undo', metavar='CSV', default=None, help='يُرجع ما نسبه تقريرٌ سابق.')

    def handle(self, *args, **options):
        if options['undo']:
            return self._undo(Path(options['undo']), options['yes'])

        department = self._department(options['department'])
        books = self._orphans(options['source'])
        ids = list(books.values_list('pk', flat=True))
        self.stdout.write(f'قسمُ السجلّ: {department}')
        self.stdout.write(f'كتبٌ قديمةٌ بلا قسم: {len(ids)}')
        for (source, kind), count in sorted(Counter(
                (ref.split('#', 1)[0], kind) for ref, kind in books.values_list('source_ref', 'kind')
        ).items()):
            self.stdout.write(f'  {source} · {kind}: {count}')
        untouched = Book.all_objects.filter(department__isnull=True, source_ref='').count()
        self.stdout.write(f'كتبُ التطبيق بلا قسم (لا تُلمَس): {untouched}')

        if not options['yes']:
            self.stdout.write('معاينةٌ فقط — أعِد التشغيل بـ --yes للتنفيذ.')
            return
        if not ids:
            return

        report = Path(options['report'])
        report.parent.mkdir(parents=True, exist_ok=True)
        with report.open('w', newline='', encoding='utf-8') as fh:
            writer = csv.writer(fh)
            writer.writerow(['book_id', 'department_id'])
            writer.writerows((pk, department.pk) for pk in ids)
        with transaction.atomic():
            done = (Book.all_objects.filter(pk__in=ids, department__isnull=True)
                    .update(department=department))
        self.stdout.write(self.style.SUCCESS(f'نُسب {done} كتاباً إلى {department} — التقرير: {report}'))

    def _department(self, code):
        department = (Department.objects.filter(code=code).first() if code
                      else BookSequence.resolve_department())
        if department is None:
            raise CommandError(f'لا قسمَ بالرمز «{code}».' if code else 'لا قسمَ نشطاً في القاعدة.')
        if not department.is_active:
            raise CommandError(f'القسمُ «{department}» معطَّل.')
        return department

    def _orphans(self, sources):
        books = Book.all_objects.filter(department__isnull=True).exclude(source_ref='')
        if sources:
            prefixes = Q()
            for source in sources:
                prefixes |= Q(source_ref__startswith=f'{source}#')
            books = books.filter(prefixes)
        return books.order_by('pk')

    def _undo(self, report, execute):
        if not report.exists():
            raise CommandError(f'لا تقرير في {report}.')
        with report.open(encoding='utf-8') as fh:
            rows = [(int(r['book_id']), int(r['department_id'])) for r in csv.DictReader(fh)]
        # يُرجَع ما زال على القسم الذي نسبه التقرير وحدَه — لا ما غيّره أحدٌ بعده
        reverted = Q()
        for department_id in {d for _, d in rows}:
            reverted |= Q(department_id=department_id,
                          pk__in=[pk for pk, d in rows if d == department_id])
        books = Book.all_objects.filter(reverted) if rows else Book.all_objects.none()
        self.stdout.write(f'في التقرير: {len(rows)} · قابلٌ للإرجاع: {books.count()}')
        if not execute:
            self.stdout.write('معاينةٌ فقط — أعِد التشغيل بـ --yes للإرجاع.')
            return
        with transaction.atomic():
            done = books.update(department=None)
        self.stdout.write(self.style.SUCCESS(f'أُرجع {done} كتاباً إلى «بلا قسم».'))
