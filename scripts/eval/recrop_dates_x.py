# -*- coding: utf-8 -*-
"""إعادةُ قصّ هندسة `x` لقصاصات التاريخ — بلا إعادة كشفٍ وبلا مساسٍ بالمانيفست.

مفتاحُ استئناف `harvest_dates.py` يتخطّى الكتب المحصودة كلّها، فلا يصلح لإنتاج
هندسةٍ أُضيفت لاحقاً. هذا السكربت يقرأ مانيفست date_ds، يرسم كلَّ صفحةٍ بوصفة
الإنتاج نفسها، ويقصّ `x` وحدها ({book}_x.png)، ويدفق خريطةً جانبيّة x_map.jsonl
(مفتاح الاستئناف «حاولنا»). الدمجُ في المانيفست خطوةٌ منفصلة (--merge) تجري
مرّةً واحدة بعد النضوب — كتابةٌ ذرّيّة عبر ملفٍّ مؤقّت.

    python scripts/eval/recrop_dates_x.py [حجم الدفعة | --merge]
"""
import gc
import json
import os
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJ)
os.chdir(PROJ)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lettersys.settings')
import django  # noqa: E402
django.setup()

from PIL import Image  # noqa: E402
from core.models import Book  # noqa: E402

OUT = r'D:\migration\lettersys_models\date_ds'
IMGD = os.path.join(OUT, 'crops')
MANIFEST = os.path.join(OUT, 'manifest.jsonl')
XMAP = os.path.join(OUT, 'x_map.jsonl')
GEOM_X = (2.0, -0.2, 2.4)   # المُسجَّلة في harvest_dates.GEOMS — تتحرّكان معاً


def _render(path):
    if path.lower().endswith('.pdf'):
        import fitz
        doc = fitz.open(path)
        try:
            page = doc[0]
            z = 175 / 72.0
            lo = max(page.rect.width, page.rect.height) * z
            if lo > 3500:
                z *= 3500 / lo
            px = page.get_pixmap(matrix=fitz.Matrix(z, z))
            return Image.frombytes('RGB', (px.width, px.height), px.samples)
        finally:
            doc.close()
    return Image.open(path).convert('RGB')


rows = [json.loads(l) for l in open(MANIFEST, encoding='utf-8')]
rows = [r for r in rows if 'skip' not in r]

if len(sys.argv) > 1 and sys.argv[1] == '--merge':
    xmap = {}
    for l in open(XMAP, encoding='utf-8'):
        d = json.loads(l)
        if d.get('file'):
            xmap[d['book']] = d['file']
    merged = 0
    tmp = MANIFEST + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        for l in open(MANIFEST, encoding='utf-8'):
            r = json.loads(l)
            if 'skip' not in r and r['book'] in xmap:
                r['files']['x'] = xmap[r['book']]
                merged += 1
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    os.replace(tmp, MANIFEST)
    print('دُمجت x في %d صفّاً' % merged)
    sys.exit(0)

CHUNK = int(sys.argv[1]) if len(sys.argv) > 1 else 100
attempted = set()
if os.path.exists(XMAP):
    for l in open(XMAP, encoding='utf-8'):
        try:
            attempted.add(json.loads(l)['book'])
        except Exception:
            pass

todo = [r for r in rows if r['book'] not in attempted][:CHUNK]
print('متبقّون %d · هذه الدفعة %d' % (len(rows) - len(attempted), len(todo)), flush=True)

ext, top, bot = GEOM_X
with open(XMAP, 'a', encoding='utf-8') as mf:
    for r in todo:
        bid = r['book']
        try:
            b = Book.objects.get(id=bid)
            att = b.attachments.first()
            im = _render(att.file.path)
            W, H = im.size
            gray = im.convert('L')
            del im
            x0, y0, x1, y1 = r['box']
            bw, bh = (x1 - x0), (y1 - y0)
            px0 = max(0, int((x0 - ext * bw) * W))
            px1 = min(W, int((x1 + ext * bw) * W))
            py0 = max(0, int((y1 + top * bh) * H))
            py1 = min(H, int((y1 + bot * bh) * H))
            if (px1 - px0) < 20 or (py1 - py0) < 10:
                mf.write(json.dumps({'book': bid, 'file': None, 'skip': 'tiny'}) + '\n')
            else:
                name = '%d_x.png' % bid
                gray.crop((px0, py0, px1, py1)).save(os.path.join(IMGD, name))
                mf.write(json.dumps({'book': bid, 'file': name}) + '\n')
            del gray
        except Exception as exc:
            mf.write(json.dumps({'book': bid, 'file': None,
                                 'skip': 'error:%s' % type(exc).__name__}) + '\n')
        mf.flush()
        gc.collect()
print('تمّ', flush=True)
