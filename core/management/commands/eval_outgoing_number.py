# -*- coding: utf-8 -*-
"""بطاقة الصادر — قياسٌ قبل أيّ توصيل (Fable، إيداع 1).

يجيب سؤالاً واحداً بصدق: **ماذا يفعل النظام للصادر اليوم، وهل الرقم المطلوب حاضرٌ
أصلاً في متناول الأنبوب؟** الصادر 16% من الأرشيف ومُهمَلٌ كلّياً: قراءة خطّ اليد
(Step 5.5) تُغذّي sender_number فقط، وbook_number يأتي من regex مطبوع لا يلتقط الرقم
اليدويّ. فالبطاقة تقيس:

  1. هل يُنتج الأنبوب الحيّ book_number للصادر؟ (خطّ الأساس ≈ صفر متوقَّع)
  2. الصادر الداخلي: رقمنا المحجوز هو `our_number` — هل تسلسله حاضرٌ في نصّ OCR
     (مطبوعاً) أو يحتاج قراءة خطّ يد؟ (يحسم إن كان المسار مطابقةً نصّيّة أم قراءة CRNN)
  3. الصادر الخارجي: رقم مكتب المدير العام = ذيل `our_number` — نفس السؤال.

قياسٌ فقط: لا يكتب حقلاً ولا يمسّ الأنبوب. للتشغيل:
  $env:PYTHONIOENCODING="utf-8"; python manage.py eval_outgoing_number --limit 40
"""
import os
import re

from django.core.management.base import BaseCommand

_AR = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')


def _digits(s):
    return ''.join(c for c in (s or '').translate(_AR) if c.isdigit())


class Command(BaseCommand):
    help = 'بطاقة الصادر: ماذا يستخرج الأنبوب اليوم وهل الرقم المحجوز حاضر في النصّ'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=40)
        parser.add_argument('--kind', type=str, default='both',
                            choices=['both', 'outgoing_internal', 'outgoing_external'])

    def handle(self, *args, **opts):
        from core.extraction.pipeline import AIExtractionService
        from core.models import Book

        kinds = (['outgoing_internal', 'outgoing_external']
                 if opts['kind'] == 'both' else [opts['kind']])
        svc = AIExtractionService()

        for kind in kinds:
            qs = (Book.objects.filter(is_deleted=False, kind=kind)
                  .exclude(our_number='').filter(attachments__isnull=False)
                  .order_by('-id').distinct())
            n_total = qs.count()
            rows = []
            for b in qs[:opts['limit']]:
                att = b.attachments.first()
                path = att.file.path if (att and hasattr(att.file, 'path')) else None
                if not path or not os.path.exists(path):
                    continue
                # الرقم المطلوب = ذيل our_number بعد رمز السجلّ (1-4)
                od = _digits(b.our_number)
                target = od[1:].lstrip('0') or od[1:] if (len(od) == 5 and od[0] in '1234') else \
                    (od[-4:].lstrip('0') or od[-4:] if len(od) >= 8 else od.lstrip('0') or od)
                got_bn, in_text = '', False
                try:
                    r = svc.process_image(path)
                    got_bn = _digits(getattr(r, 'book_number', ''))
                    txt = _digits(getattr(r, 'raw_text', '') or getattr(r, 'cleaned_text', ''))
                    in_text = bool(target) and target in txt   # هل هو مطبوعٌ في النصّ؟
                    del r
                except Exception as e:
                    got_bn = f'ERR:{type(e).__name__}'
                rows.append({'book': b.id, 'our': b.our_number, 'target': target,
                             'got_bn': got_bn, 'in_ocr_text': in_text})

            n = len(rows)
            if not n:
                self.stdout.write(f'\n### {kind}: لا عيّنات')
                continue
            got = sum(1 for r in rows if r['got_bn'] and not r['got_bn'].startswith('ERR'))
            bn_match = sum(1 for r in rows if r['got_bn'] == r['target'] and r['target'])
            printed = sum(1 for r in rows if r['in_ocr_text'])
            self.stdout.write(f'\n### {kind} — {n} من {n_total} كتاباً')
            self.stdout.write(f'  الأنبوب يُنتج book_number : {got}/{n} ({100*got//n}%)')
            self.stdout.write(f'  book_number == المحجوز    : {bn_match}/{n} ({100*bn_match//n}%)  <- خطّ الأساس اليوم')
            self.stdout.write(f'  الرقم حاضرٌ في نصّ OCR     : {printed}/{n} ({100*printed//n}%)  '
                              f'<- إن مرتفع=مطبوع (regex يكفي)؛ إن منخفض=خطّ يد (يلزم CRNN)')
            for r in rows[:8]:
                self.stdout.write(f'    #{r["book"]} our={r["our"]:<12} target={r["target"]:<6} '
                                  f'got={r["got_bn"]:<8} in_text={r["in_ocr_text"]}')
