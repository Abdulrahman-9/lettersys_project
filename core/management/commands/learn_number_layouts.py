# -*- coding: utf-8 -*-
"""يتعلّم بصمات تخطيط الجهات (موضع تسمية «العدد») من الكتب المؤكَّدة ويقيس
نسبة إصابة التموضع — مرحلة 1 من خطة أرقام خط اليد.

    python manage.py learn_number_layouts --limit 60        # تعلّم + قياس
    python manage.py learn_number_layouts --limit 60 --measure-only

آمنٌ للذاكرة (جهاز 8GB): مستندٌ واحد في الذاكرة، gc بعد كلٍّ، وقابل للإيقاف —
الـpriors تُحفَظ تراكمياً. شغّله والجهاز خامل."""
import gc
import os

from django.core.management.base import BaseCommand

from core.extraction.handwriting import EntityLayoutPriors, NumberStripLocator

PRIORS_PATH = os.path.join('var', 'handwriting_layout_priors.json')


class Command(BaseCommand):
    help = 'تعلّم مواضع تسمية «العدد» لكل جهة من الكتب المؤكَّدة + قياس إصابة التموضع.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=60, help='عدد الكتب (افتراضي 60)')
        parser.add_argument('--measure-only', action='store_true',
                            help='قياس فقط دون تحديث الـpriors')

    def handle(self, *args, **opts):
        import fitz
        from PIL import Image
        from core.models import AIIntegrationSettings, Book
        from core.extraction.ocr.providers import build_offline_provider_from_settings

        prov = build_offline_provider_from_settings(AIIntegrationSettings.get_active_settings())
        pt = prov._pytesseract
        pt.pytesseract.tesseract_cmd = prov.cmd
        if prov.tessdata_dir:
            os.environ['TESSDATA_PREFIX'] = prov.tessdata_dir

        priors = EntityLayoutPriors(PRIORS_PATH)
        locator = NumberStripLocator(priors)

        qs = (Book.objects.filter(is_deleted=False, attachments__isnull=False,
                                  issuing_entities__isnull=False)
              .exclude(sender_number__isnull=True).exclude(sender_number='')
              .order_by('-id').distinct()[:opts['limit']])

        seen = hit_label = hit_prior = 0
        for b in qs.iterator():
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
                if longer > 3500:
                    zoom *= 3500 / longer
                pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom),
                                      colorspace=fitz.csGRAY, alpha=False)
                img = Image.frombytes('L', (pix.width, pix.height), pix.samples)
                doc.close()
                del pix
                tsv = pt.image_to_data(img, lang=prov.lang, config=f'--psm {prov.psm}',
                                       output_type=pt.Output.DICT)
                label = locator.find_label(tsv, img.width, img.height, entity_id=eid)
                if label is not None:
                    if label.source == 'label':
                        hit_label += 1
                        if not opts['measure_only']:
                            priors.learn(eid, (label.left + label.width / 2) / img.width,
                                         (label.top + label.height / 2) / img.height)
                    else:
                        hit_prior += 1
                del img, tsv
            except Exception as exc:
                self.stdout.write(f'  تخطّي #{b.id}: {type(exc).__name__}: {str(exc)[:60]}')
            finally:
                gc.collect()
            if seen % 10 == 0:
                if not opts['measure_only']:
                    priors.save()
                self.stdout.write(f'  {seen} مستنداً — تسمية {hit_label} + prior {hit_prior}')

        if not opts['measure_only']:
            priors.save()
        total_hit = hit_label + hit_prior
        self.stdout.write(self.style.SUCCESS(
            f'\nالإصابة: {total_hit}/{seen} ({100 * total_hit / max(1, seen):.0f}%) '
            f'[تسمية {hit_label} + سقوط prior {hit_prior}] — priors لـ{len(priors)} جهة في {PRIORS_PATH}'))
