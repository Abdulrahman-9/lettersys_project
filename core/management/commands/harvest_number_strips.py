# -*- coding: utf-8 -*-
"""حصاد شرائط الأرقام اليدوية من الكتب المؤكَّدة — مرحلة 2ب من خطة خط اليد.

لكل كتاب برقم جهة رقمي-صرف (1-6 خانات) ومرفق PDF: يرسم الصفحة الأولى، يوجد
شريط الرقم (تسمية «العدد» أو prior الجهة عبر NumberStripLocator)، يقتصّه
ويحفظه PNG مع وسمه الضعيف (sender_number المؤكَّد من المستخدم) في labels.csv —
عدّة تدريب fine-tune لنموذج CRNN. يتعلّم بصمات التخطيط تراكمياً أثناء مروره
(يغني عن تدفئة منفصلة).

    python manage.py harvest_number_strips --limit 200 --offset 0

آمن للذاكرة (8GB): مستند واحد في الذاكرة + gc بعد كلٍّ؛ قابل للاستئناف —
الشرائط الموجودة تُتخطّى والـCSV يُلحَق به والبصمات تُحفَظ كل 10."""
import csv
import gc
import os
import re

from django.core.management.base import BaseCommand, CommandError

from core.extraction.handwriting import EntityLayoutPriors, NumberStripLocator

PRIORS_PATH = os.path.join('var', 'handwriting_layout_priors.json')
HARVEST_DIR = os.path.join('training', 'handwriting', 'harvest')

_AR_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')


def normalize_label(sender_number):
    """رقمي-صرف 1-6 خانات (بعد توحيد الأرقام العربية) وإلا None."""
    s = str(sender_number or '').strip().translate(_AR_DIGITS)
    return s if re.fullmatch(r'[0-9]{1,6}', s) else None


class Command(BaseCommand):
    help = 'حصاد شرائط الأرقام اليدوية الموسومة ضعيفاً لتدريب fine-tune (مرحلة 2ب).'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=200)
        parser.add_argument('--offset', type=int, default=0)
        parser.add_argument('--field', choices=('number', 'date'), default='number',
                            help='الحقل المحصود: رقم الجهة (افتراضي) أو تاريخها (v2). '
                                 'وسم التاريخ يُخزَّن ISO وتولِّد التنقيةُ صيغَه المكتوبة.')

    def handle(self, *args, **opts):
        if options.get('field') == 'date':
            raise CommandError(
                'مسار --field date أُوقف (2026-08-24): بقايا v6 بلا حارس فارقٍ ولا '
                'استثناء المجموعات المختومة — يُنتج مجموعةً أدنى بصمت. البديل '
                'المعتمد: scripts/eval/harvest_dates.py (سجلّ التقييم قسم D).')
        import fitz
        from PIL import Image
        from core.models import AIIntegrationSettings, Book
        from core.extraction.ocr.providers import build_offline_provider_from_settings

        prov = build_offline_provider_from_settings(AIIntegrationSettings.get_active_settings())
        pt = prov._pytesseract
        pt.pytesseract.tesseract_cmd = prov.cmd
        if prov.tessdata_dir:
            os.environ['TESSDATA_PREFIX'] = prov.tessdata_dir

        field = opts['field']
        suffix = '' if field == 'number' else '_date'
        # بصمات منفصلة لكل حقل — موضع «التاريخ» غير موضع «العدد» في ترويسة الجهة
        priors = EntityLayoutPriors(PRIORS_PATH.replace('.json', f'{suffix}.json'))
        locator = NumberStripLocator(priors, field=field)

        strips_dir = os.path.join(HARVEST_DIR, f'strips{suffix}')
        os.makedirs(strips_dir, exist_ok=True)
        csv_path = os.path.join(HARVEST_DIR, f'labels{suffix}.csv')
        new_csv = not os.path.exists(csv_path)
        csv_f = open(csv_path, 'a', newline='', encoding='utf-8')
        writer = csv.writer(csv_f)
        if new_csv:
            writer.writerow(['file', 'label', 'book_id', 'entity_id', 'source'])

        # سجلّ المُعالَج: يمنع إعادة رسم المستندات المرفوضة عند كل استئناف
        # (الشرائط المحفوظة تُتخطّى بوجود ملفها؛ هذا يغطي الباقي).
        done_path = os.path.join(HARVEST_DIR, f'processed{suffix}.txt')
        done = set()
        if os.path.exists(done_path):
            with open(done_path, encoding='utf-8') as f:
                done = {ln.strip() for ln in f if ln.strip()}
        done_f = open(done_path, 'a', encoding='utf-8')

        lo, hi = opts['offset'], opts['offset'] + opts['limit']
        qs = Book.objects.filter(is_deleted=False, attachments__isnull=False,
                                 issuing_entities__isnull=False)
        if field == 'number':
            qs = qs.exclude(sender_number__isnull=True).exclude(sender_number='')
        else:
            qs = qs.exclude(sender_date__isnull=True)
        qs = qs.order_by('-id').distinct()[lo:hi]

        seen = saved = skipped = 0
        for b in qs.iterator():
            if field == 'number':
                label_txt = normalize_label(b.sender_number)
            else:
                label_txt = b.sender_date.isoformat() if b.sender_date else None
            if not label_txt:
                continue
            out_png = os.path.join(strips_dir, f'{b.id}.png')
            if os.path.exists(out_png) or str(b.id) in done:
                skipped += 1
                continue
            att = b.attachments.filter(is_deleted=False).order_by('-uploaded_at').first()
            eid = b.issuing_entities.values_list('id', flat=True).first()
            try:
                path = att.file.path if att else None
            except Exception:
                path = None
            if not (path and eid and os.path.exists(path) and path.lower().endswith('.pdf')):
                continue
            seen += 1
            try:
                doc = fitz.open(path)
                page = doc[0]
                zoom = 300 / 72.0
                longer = max(page.rect.width, page.rect.height) * zoom
                # سقف 3500 بكسل يفجّر الذاكرة على 8GB مع صفحات كبيرة/ممسوحة
                # (MemoryError جمّد حصاد التواريخ): 2600 ≈ 220DPI لصفحة A4 —
                # يكفي Tesseract لتحديد التسمية، والشريط يُقصّ من نفس الرسم.
                if longer > 2600:
                    zoom *= 2600 / longer
                pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom),
                                      colorspace=fitz.csGRAY, alpha=False)
                img = Image.frombytes('L', (pix.width, pix.height), pix.samples)
                doc.close()
                del pix
                tsv = pt.image_to_data(img, lang=prov.lang, config=f'--psm {prov.psm}',
                                       output_type=pt.Output.DICT)
                located = locator.locate(img, tsv, entity_id=eid)
                if located is not None:
                    strip, label = located
                    strip.save(out_png)
                    writer.writerow([f'{b.id}.png', label_txt, b.id, eid, label.source])
                    saved += 1
                    if label.source == 'label':
                        priors.learn(eid, (label.left + label.width / 2) / img.width,
                                     (label.top + label.height / 2) / img.height)
                del img, tsv
            except (Exception, MemoryError) as exc:
                # MemoryError لا يرث Exception في كل المسارات (تخصيصات C) —
                # التقاطه صراحةً يمنع تجميد الحصاد كله على مستندٍ ضخم واحد.
                self.stdout.write(f'  تخطّي #{b.id}: {type(exc).__name__}: {str(exc)[:60]}')
            finally:
                done_f.write(f'{b.id}\n')
                gc.collect()
            if seen % 10 == 0:
                priors.save()
                csv_f.flush()
                done_f.flush()
                self.stdout.write(f'  {seen} مستنداً — حُصد {saved}')

        priors.save()
        csv_f.close()
        done_f.close()
        self.stdout.write(self.style.SUCCESS(
            f'\nحُصد {saved} شريطاً من {seen} مستنداً (تخطّى {skipped} موجوداً سلفاً) '
            f'— {csv_path} | بصمات {len(priors)} جهة'))
