# -*- coding: utf-8 -*-
"""دراسة هندسية لكتب كل جهة — «لكل جهة تصميمُ كتابٍ ثابت» (رؤية المالك).

لكل جهة من أكثر الجهات مراسلةً: عيّنة من كتبها المؤكَّدة تُرسَم وتُقرأ بصندوقيات
Tesseract، فنقيس **كيف تكتب هذه الجهة كتابها**:
  • علامة الرقم المستخدَمة (العدد / Ref / No.) وموضعها المُطبَّع (x,y)
  • علامة التاريخ (التاريخ / Date) وصيغتها المكتوبة
  • علامة الموضوع (م/ / الموضوع / Subject) وموضعها
  • علامة المُخاطَب (الى/ / To)
  • هل الرقم مطبوعٌ (أرقام قرب العلامة) أم بخط اليد (لا أرقام)
  • لغة الكتاب الغالبة، وقالب رقمها المؤكَّد من قاعدة البيانات
المخرَج: var/entity_doc_profiles.json + تقرير مقروء. لا يغيّر سلوك الاستخراج —
قياسٌ يسبق أي قاعدة (مبدأ المشروع: لا قاعدة بلا قياس).

    python manage.py study_entity_layouts --top 12 --per-entity 6
"""
import gc
import json
import os
import re
from collections import Counter

from django.core.management.base import BaseCommand

OUT_PATH = os.path.join('var', 'entity_doc_profiles.json')

# علامات الحقول التي نبحث عنها في صندوقيات OCR (تُطابَق على الكلمة المفردة)
_MARKERS = {
    'number': re.compile(r'^(العدد|الرقم|ref|reference|no)\b', re.I),
    'date': re.compile(r'^(الت[أا]ريخ|date|dated)\b', re.I),
    'subject': re.compile(r'^(م|الموضوع|subject|subj)\b', re.I),
    'recipient': re.compile(r'^(الى|إلى|to)\b', re.I),
}
_AR_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')


class Command(BaseCommand):
    help = 'يقيس البنية الهندسية لكتب كل جهة (مواضع العلامات، الصيغ، اللغة).'

    def add_arguments(self, parser):
        parser.add_argument('--top', type=int, default=12, help='عدد الجهات الأكثر مراسلةً')
        parser.add_argument('--per-entity', type=int, default=6, help='كتب لكل جهة')
        parser.add_argument('--names', nargs='*', default=None,
                            help='جهات محدَّدة بالاسم (جزئي) بدل الأكثر مراسلةً — مثل EBS NK')
        parser.add_argument('--all', action='store_true',
                            help='كل الجهات التي لها ≥ min-books كتاباً (مسح شامل)')
        parser.add_argument('--min-books', type=int, default=3,
                            help='حدّ أدنى لكتب الجهة كي تُقاس بصمتها (افتراضي 3)')
        parser.add_argument('--resume', action='store_true',
                            help='يكمل فوق ملف البصمات الموجود (لا يعيد الجهات المقيسة)')

    def handle(self, *args, **opts):
        import fitz
        from PIL import Image
        from django.db.models import Count, Q
        from core.models import AIIntegrationSettings, Book, Entity
        from core.extraction.ocr.providers import build_offline_provider_from_settings
        from core.extraction.matchers.profile import induce_template
        from core.extraction.handwriting.localize import NumberStripLocator

        prov = build_offline_provider_from_settings(AIIntegrationSettings.get_active_settings())
        pt = prov._pytesseract
        pt.pytesseract.tesseract_cmd = prov.cmd
        if prov.tessdata_dir:
            os.environ['TESSDATA_PREFIX'] = prov.tessdata_dir

        if opts['names']:
            q = Q()
            for nm in opts['names']:
                q |= Q(name__icontains=nm)
            top = Entity.objects.filter(is_active=True).filter(q)
        elif opts['all']:
            top = (Entity.objects.filter(is_active=True)
                   .annotate(n=Count('issued_books', distinct=True))
                   .filter(n__gte=opts['min_books']).order_by('-n'))
        else:
            top = (Entity.objects.filter(is_active=True)
                   .annotate(n=Count('issued_books', distinct=True))
                   .filter(n__gt=0).order_by('-n')[:opts['top']])

        profiles = {}
        if opts['resume'] and os.path.exists(OUT_PATH):
            with open(OUT_PATH, encoding='utf-8') as fh:
                profiles = json.load(fh)
            self.stdout.write(f'استئناف: {len(profiles)} جهة مقيسة سلفاً')
        total = top.count() if hasattr(top, 'count') else len(top)
        self.stdout.write(f'جهات للقياس: {total}')
        done = 0
        for ent in top:
            if opts['resume'] and str(ent.id) in profiles:
                continue
            books = (Book.objects.filter(is_deleted=False, issuing_entities=ent,
                                         attachments__isnull=False)
                     .order_by('-id').distinct()[:opts['per_entity'] * 3])
            seen = 0
            stat = {
                'entity_id': ent.id, 'entity_name': ent.name, 'entity_code': ent.code,
                'markers': {k: Counter() for k in _MARKERS},
                'positions': {k: [] for k in _MARKERS},
                'number_printed': 0, 'number_handwritten': 0,
                'lang': Counter(), 'db_templates': Counter(), 'docs': 0,
            }
            for b in books:
                if seen >= opts['per_entity']:
                    break
                att = b.attachments.filter(is_deleted=False).order_by('-uploaded_at').first()
                try:
                    path = att.file.path if att else None
                except Exception:
                    path = None
                if not (path and os.path.exists(path) and path.lower().endswith('.pdf')):
                    continue
                if b.sender_number:
                    stat['db_templates'][induce_template(b.sender_number)] += 1
                try:
                    doc = fitz.open(path)
                    page = doc[0]
                    zoom = 300 / 72.0
                    longer = max(page.rect.width, page.rect.height) * zoom
                    if longer > 2600:
                        zoom *= 2600 / longer
                    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom),
                                          colorspace=fitz.csGRAY, alpha=False)
                    img = Image.frombytes('L', (pix.width, pix.height), pix.samples)
                    doc.close()
                    del pix
                    tsv = pt.image_to_data(img, lang=prov.lang, config=f'--psm {prov.psm}',
                                           output_type=pt.Output.DICT)
                    W, H = img.width, img.height
                    words = tsv.get('text', [])
                    ar = sum(1 for w in words if w and re.search(r'[؀-ۿ]', w))
                    en = sum(1 for w in words if w and re.search(r'[A-Za-z]', w))
                    stat['lang']['ar' if ar >= en else 'en'] += 1
                    for i, raw in enumerate(words):
                        t = (raw or '').strip().strip(':.ـ /')
                        if not t:
                            continue
                        # خلايا جدول ترويسة الجودة («Date Rev»، «Rev No.») ليست
                        # تسميات حقول — لولا استبعادها لقاس القياسُ الجدولَ نفسه
                        # (تلوّث كشفته الجولة الأولى: كل «Date» كانت خليّة جدول).
                        if NumberStripLocator._in_qms_table(tsv, i):
                            continue
                        for field, rx in _MARKERS.items():
                            if not rx.match(t):
                                continue
                            x = (tsv['left'][i] + tsv['width'][i] / 2) / W
                            y = (tsv['top'][i] + tsv['height'][i] / 2) / H
                            if y > 0.45:            # الرأس فقط — لا إحالات المتن
                                continue
                            stat['markers'][field][t] += 1
                            stat['positions'][field].append((round(x, 3), round(y, 3)))
                            # الرقم مطبوعٌ إن ظهرت أرقامٌ بجوار العلامة في سطرها —
                            # **على أيّ الجهتين**: العربية تكتبه يساراً (RTL) والشركات
                            # الإنكليزية يميناً (LTR). افتراضُ اليسار وحده كان يقرأ
                            # أرقام EBS/NK المطبوعة «يدويةً» خطأً.
                            if field == 'number':
                                near = [
                                    (tsv['text'][j] or '').translate(_AR_DIGITS)
                                    for j in range(len(words))
                                    if j != i
                                    and abs(tsv['top'][j] - tsv['top'][i]) < max(8, tsv['height'][i])
                                    and abs(tsv['left'][j] - tsv['left'][i]) < 0.35 * W
                                ]
                                has_digits = any(re.search(r'\d{2,}', s) for s in near)
                                stat['number_printed' if has_digits else 'number_handwritten'] += 1
                    del img, tsv
                    seen += 1
                    stat['docs'] += 1
                except (Exception, MemoryError) as exc:
                    self.stdout.write(f'  تخطّي #{b.id}: {type(exc).__name__}')
                finally:
                    gc.collect()

            if not stat['docs']:
                continue
            # تلخيص: العلامة الأشيع لكل حقل + متوسّط موضعها + نمط الرقم
            summary = {'entity_id': ent.id, 'entity_name': ent.name,
                       'entity_code': ent.code, 'docs': stat['docs'],
                       'lang': stat['lang'].most_common(1)[0][0],
                       'number_style': ('handwritten'
                                        if stat['number_handwritten'] > stat['number_printed']
                                        else 'printed'),
                       'db_template': (stat['db_templates'].most_common(1)[0][0]
                                       if stat['db_templates'] else None),
                       'fields': {}}
            for field in _MARKERS:
                pos = stat['positions'][field]
                if not pos:
                    continue
                summary['fields'][field] = {
                    'marker': stat['markers'][field].most_common(1)[0][0],
                    'seen_in_docs': len(pos),
                    'x': round(sum(p[0] for p in pos) / len(pos), 3),
                    'y': round(sum(p[1] for p in pos) / len(pos), 3),
                }
            profiles[str(ent.id)] = summary
            done += 1
            if done % 10 == 0:          # حفظ دوري — مسحٌ طويل لا يُهدَر بانقطاع
                os.makedirs('var', exist_ok=True)
                with open(OUT_PATH, 'w', encoding='utf-8') as fh:
                    json.dump(profiles, fh, ensure_ascii=False, indent=1)
                self.stdout.write(f'  … حُفظت {len(profiles)} بصمة ({done}/{total})')

            f = summary['fields']
            self.stdout.write(
                f"\n■ {ent.name}  [{ent.code or '—'}]  ({summary['docs']} كتاب، "
                f"لغة={summary['lang']}، رقم={summary['number_style']}، قالب={summary['db_template']})")
            for field in ('number', 'date', 'subject', 'recipient'):
                if field in f:
                    d = f[field]
                    self.stdout.write(
                        f"    {field:>9}: «{d['marker']}» في {d['seen_in_docs']} كتاباً "
                        f"عند (x={d['x']}, y={d['y']})")
                else:
                    self.stdout.write(f"    {field:>9}: — لا علامة مقروءة")

        os.makedirs('var', exist_ok=True)
        with open(OUT_PATH, 'w', encoding='utf-8') as fh:
            json.dump(profiles, fh, ensure_ascii=False, indent=1)
        self.stdout.write(self.style.SUCCESS(f'\n✓ حُفظت بصمات {len(profiles)} جهة → {OUT_PATH}'))
