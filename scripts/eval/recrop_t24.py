# -*- coding: utf-8 -*-
"""يُعيد اشتقاق قصاصات T2.4 عند صفر حشو من الصناديق المحفوظة — بلا إعادة كشف.

الغالي هو **الكشف**، والقصّ اشتقاقٌ رخيص. فالمانيفست يحمل `box` و`dims` لكلّ زوج،
ومنهما يُولَّد أيّ حشوٍ لاحقاً. مقيسٌ (2026-08-19، عيّنتان مستقلّتان): صفرُ حشوٍ يعطي
**66.5%** مطابقةً تامّة مقابل **51.5%** للحشو الموروث 0.30/0.40.

يتخطّى ما أُعيد اشتقاقه سلفاً (بصمةُ حجمٍ في `recrop_done.json`)، فيؤمَن الانقطاع.

    python scripts/eval/recrop_t24.py [عدد]
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

DS = r'D:\migration\lettersys_models\t24_ds'
IMGD = os.path.join(DS, 'crops')
STATE = os.path.join(DS, 'recrop_done.json')
LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 10 ** 9
PAD_X, PAD_Y = 0.0, 0.0        # يجب أن يطابق harvest_t24.py — توزيعٌ واحد


def render(p, dpi=175, cap=3500):
    if p.lower().endswith('.pdf'):
        import fitz
        d = fitz.open(p)
        pg = d[0]
        z = dpi / 72.0
        lo = max(pg.rect.width, pg.rect.height) * z
        if lo > cap:
            z *= cap / lo
        px = pg.get_pixmap(matrix=fitz.Matrix(z, z))
        im = Image.frombytes('RGB', (px.width, px.height), px.samples)
        d.close()
        return im
    return Image.open(p).convert('RGB')


done = set(json.load(open(STATE, encoding='utf-8'))) if os.path.exists(STATE) else set()
rows = [json.loads(l) for l in open(os.path.join(DS, 'manifest.jsonl'), encoding='utf-8')]
todo = [r for r in rows if r.get('label') and r.get('box') and r['book'] not in done][:LIMIT]
print('موسومٌ %d · أُعيد سلفاً %d · هذه الدفعة %d' % (
    sum(1 for r in rows if r.get('label')), len(done), len(todo)), flush=True)

ok = fail = 0
for r in todo:
    b = Book.objects.filter(id=r['book']).first()
    att = b.attachments.first() if b else None
    p = att.file.path if (att and hasattr(att.file, 'path')) else None
    if not (p and os.path.exists(p)):
        fail += 1
        done.add(r['book'])
        continue
    try:
        im = render(p)
        W, H = im.size
        x0, y0, x1, y1 = r['box']
        ex, ey = PAD_X * (x1 - x0), PAD_Y * (y1 - y0)
        L, T = max(0, int((x0 - ex) * W)), max(0, int((y0 - ey) * H))
        R, B = min(W, int((x1 + ex) * W)), min(H, int((y1 + ey) * H))
        if R - L < 12 or B - T < 8:
            fail += 1
            done.add(r['book'])
            del im
            continue
        crop = im.convert('L').crop((L, T, R, B))
        del im
        crop.save(os.path.join(IMGD, r['file']))
        del crop
        ok += 1
    except Exception:
        fail += 1
    done.add(r['book'])
    gc.collect()

json.dump(sorted(done), open(STATE, 'w', encoding='utf-8'))
print('أُعيد اشتقاقه %d · تعذّر %d · المجموع المُنجَز %d' % (ok, fail, len(done)), flush=True)
