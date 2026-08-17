# -*- coding: utf-8 -*-
"""
أمر حذف كتب فترة التدريب عند تدشين النظام — قرار المالك.

خلال فترة التدريب أُدخِلت كتبٌ عبر التطبيق، وأصلُها كلّه موجودٌ في النظام القديم
ويصل عبر الدمج. فتُحذف كلّها عند التدشين كي لا تُزدوج ولا تستهلك من السلسلة.

المُميِّز هو الوسم `is_training` الذي يضعه `rebase_book_numbers`، وأرقامها في فضاء
`T` المنفصل خارج السلسلة الرسمية أصلاً. الشرط القديم (`legacy_number=''` و
`source_ref=''`) كان يُخطئ في الاتّجاهين معاً — مقيساً: يُفلت 73 كتاب تدريب
لأنّها اكتسبت `legacy_number`، ويلتقط 55 كتاباً حقيقياً مستورداً بلا رقم قديم.

يحذف الأمر كتب التدريب **مع الحفاظ على القيمة التدريبية**:
  • LetterheadMemory و DataExtractionResult و OCRResult مرتبطة بـ on_delete=SET_NULL
    ⇒ الحذف يفصلها فقط ولا يمحوها (الترويسة/الجهة/النصّ الخام تبقى للتعلّم).
  • العائق الوحيد Attachment.book=PROTECT ⇒ نفكّ مرفقات الكتب التجريبية أولاً
    (نصّها محفوظ في OCRResult؛ ملفاتها تجريبية زائلة).
ثم يعيد بذر العدّادات على أكبر تسلسل دائم حقيقي + 1.

آمن افتراضياً: لا يحذف شيئاً دون --yes (يعرض تقرير معاينة فقط).

    python manage.py purge_dev_seed_books            # معاينة
    python manage.py purge_dev_seed_books --yes      # تنفيذ فعلي

ملاحظة ويندوز: صدّر PYTHONIOENCODING=utf-8 قبل التشغيل لتفادي كسر cp1256.
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count

from core.models import (Attachment, Book, DataExtractionResult,
                         LetterheadMemory)


class Command(BaseCommand):
    help = 'حذف كتب فترة التدريب (is_training) عند التدشين، مع حفظ القيمة التدريبية وإعادة بذر العدّادات.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--yes', action='store_true',
            help='تنفيذ الحذف فعلياً (بدونه: معاينة فقط)',
        )
        parser.add_argument(
            '--no-reseed', action='store_true',
            help='عدم إعادة بذر العدّادات بعد الحذف',
        )

    def handle(self, *args, **options):
        dev = Book.objects.filter(is_training=True)
        total = dev.count()

        w = self.stdout.write
        w('=' * 60)
        w(f'كتب فترة التدريب المرشّحة للحذف (is_training=True): {total}')
        for row in dev.values('kind').order_by('kind').annotate(n=Count('id')):
            w(f'  {row["kind"]}: {row["n"]}')

        # حارس: الوسم يضعه `rebase_book_numbers`. إن لم يُوسَم شيء بعد، الحذف
        # بلا وسمٍ يعني حذف صفر — نُبلّغ بدل الصمت.
        if not total:
            w('لا كتب موسومة بالتدريب. شغّل rebase_book_numbers أوّلاً إن كنت تتوقّع غير ذلك.')
            return

        dev_ids = list(dev.values_list('id', flat=True))
        att_count = Attachment.objects.filter(book_id__in=dev_ids).count()
        lm_linked = LetterheadMemory.objects.filter(book_id__in=dev_ids).count()
        der_linked = DataExtractionResult.objects.filter(book_id__in=dev_ids).count()
        w('-' * 60)
        w(f'مرفقات ستُحذف (نصّها محفوظ في OCRResult): {att_count}')
        w(f'ذاكرة ترويسة ستبقى (تُفصَل فقط): {lm_linked} من {LetterheadMemory.objects.count()}')
        w(f'التقاطات استخراج ستبقى (تُفصَل فقط): {der_linked} من {DataExtractionResult.objects.count()}')

        if not options['yes']:
            w('=' * 60)
            w('معاينة فقط — لم يُحذف شيء. أضِف --yes للتنفيذ الفعلي.')
            return

        with transaction.atomic():
            # فكّ المرفقات أولاً (PROTECT) — يُبقي OCRResult عبر SET_NULL
            Attachment.objects.filter(book_id__in=dev_ids).delete()
            deleted, _detail = Book.objects.filter(id__in=dev_ids).delete()

        w('=' * 60)
        w(f'حُذف {len(dev_ids)} كتاباً تجريبياً (+ سجلات مرتبطة متتالية).')
        w(f'ذاكرة الترويسة الباقية: {LetterheadMemory.objects.count()} '
          f'(المفصولة الآن book=NULL: {LetterheadMemory.objects.filter(book__isnull=True).count()})')

        if not options['no_reseed']:
            from core.views.dashboard import _reseed_book_sequences
            _reseed_book_sequences()
            from core.models import BookSequence
            w('-' * 60)
            w('أُعيد بذر العدّادات على أكبر تسلسل دائم + 1:')
            for s in BookSequence.objects.all().order_by('kind'):
                w(f'  {s.kind}: next_number={s.next_number}')
        w('=' * 60)
