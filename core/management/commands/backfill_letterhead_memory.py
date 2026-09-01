# -*- coding: utf-8 -*-
"""تدريب ذاكرة الترويسة على الكتب الحالية: يمسح الصفحة الأولى لكلّ كتاب له جهة
مؤكَّدة، ويخزّن (ترويسة → جهة) في LetterheadMemory. بذرةٌ فوريّة تمنح النظام قدرة
اقتراح الجهة (hit@3 ≈ 77% مقابل 16%) دون انتظار تراكم الاستخدام.

مبادئ مناعة الذاكرة (جهاز 8GB): تسلسلي، دقّة 200 + سقف أبعاد، إغلاق الاتصال أثناء
المسح، كتابة سجلّ تلو الآخر، قابل الاستئناف (يتخطّى ما خُزّن). آمنٌ بجانب خادم حيّ.

    python manage.py backfill_letterhead_memory            # كل الكتب المؤهَّلة
    python manage.py backfill_letterhead_memory --limit 200
    python manage.py backfill_letterhead_memory --dpi 200 --max-dim 2200
"""
import gc
import os

from django.core.management.base import BaseCommand
from django.db import connection

from core.models import Book, Attachment, LetterheadMemory
from core.extraction.matchers.entity import letterhead_region


class Command(BaseCommand):
    help = 'يدرّب ذاكرة الترويسة (LetterheadMemory) على الكتب الحالية بمسح صفحاتها الأولى.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=0, help='حدّ أقصى للكتب (0 = الكل)')
        parser.add_argument('--dpi', type=int, default=200)
        parser.add_argument('--max-dim', type=int, default=2200, help='سقف أطول بُعد للصورة')

    def handle(self, *args, **opts):
        os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
        os.environ.setdefault('OMP_NUM_THREADS', '1')
        limit, dpi, max_dim = opts['limit'], opts['dpi'], opts['max_dim']

        done_books = set(LetterheadMemory.objects.values_list('book_id', flat=True))

        # اجمع الحقول أولاً ثم افصل المسح عنها تماماً. بثٌّ بـiterator + استعلامات
        # خفيفة لكلّ كتاب (لا prefetch للكلّ) — آمن الذاكرة على داتا بيس بعشرات الآلاف.
        jobs = []   # (book_id, pdf_path, issuing_id, receiving_id)
        qs = Book.objects.filter(is_deleted=False).order_by('-id').only('id')
        for b in qs.iterator(chunk_size=200):
            if b.id in done_books:
                continue
            iss = b.issuing_entities.values_list('id', flat=True).first()
            rec = b.receiving_entities.values_list('id', flat=True).first()
            if not (iss or rec):
                continue
            att = Attachment.objects.filter(book=b).exclude(file='').first()
            if not att:
                continue
            try:
                p = att.file.path
            except Exception:
                continue
            if not (os.path.exists(p) and p.lower().endswith('.pdf')):
                continue
            jobs.append((b.id, p, iss, rec))
            if limit and len(jobs) >= limit:
                break
        connection.close()   # المسح بعدها لا يحتاج الداتا بيس

        self.stdout.write('كتب للتدريب: %d' % len(jobs))
        if not jobs:
            self.stdout.write(self.style.SUCCESS('لا جديد — الذاكرة محدَّثة.'))
            return

        ocr = _make_ocr(dpi, max_dim)
        created = 0
        for i, (book_id, path, iss_id, rec_id) in enumerate(jobs):
            try:
                text = ocr(path)
                head = letterhead_region(text or '')
                if head:
                    LetterheadMemory.objects.create(
                        letterhead=head, issuing_entity_id=iss_id,
                        receiving_entity_id=rec_id, book_id=book_id)
                    created += 1
            except Exception as e:   # noqa: BLE001 — كتابٌ فاسد لا يُوقف الدفعة
                self.stderr.write('تخطّي %s: %s' % (book_id, str(e)[:80]))
            finally:
                gc.collect()
            if (i + 1) % 25 == 0:
                self.stdout.write('  عولج %d/%d (خُزّن %d)' % (i + 1, len(jobs), created))
        self.stdout.write(self.style.SUCCESS('تدرّبت الذاكرة على %d كتاب.' % created))


def _make_ocr(dpi, max_dim):
    """مُنتِج نصّ OCR بأسطر \\n (كالمزوّد الإنتاجي) بمناعة ذاكرة — يُحمّل الثقيل مرّة."""
    import fitz
    import cv2
    import numpy as np
    import pytesseract
    from pytesseract import Output
    from django.conf import settings as dj

    cmd = getattr(dj, 'TESSERACT_CMD', '') or r'C:\Program Files\NAPS2\lib\_win64\tesseract.exe'
    if os.path.exists(cmd):
        pytesseract.pytesseract.tesseract_cmd = cmd
    tessdata = getattr(dj, 'TESSERACT_TESSDATA_DIR', '') or getattr(dj, 'TESSDATA_DIR', '')
    if tessdata:
        os.environ['TESSDATA_PREFIX'] = tessdata
    lang = getattr(dj, 'TESSERACT_LANG', 'ara+eng')

    def ocr(pdf_path):
        doc = fitz.open(pdf_path)
        if doc.page_count == 0:
            doc.close()
            return ''
        page = doc[0]
        rect = page.rect
        zoom = min(dpi / 72.0, max_dim / max(rect.width, rect.height))
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        png = pix.tobytes('png')
        pix = None
        doc.close()
        img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
        d = pytesseract.image_to_data(img, lang=lang, config='--psm 3', output_type=Output.DICT)
        lines = {}
        for j in range(len(d['text'])):
            w = (d['text'][j] or '').strip()
            if not w:
                continue
            key = (d['block_num'][j], d['par_num'][j], d['line_num'][j])
            lines.setdefault(key, []).append(w)
        return '\n'.join(' '.join(ws) for _, ws in sorted(lines.items()))

    return ocr
