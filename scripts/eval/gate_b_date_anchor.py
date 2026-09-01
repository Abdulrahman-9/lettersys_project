# -*- coding: utf-8 -*-
"""البوّابة ب — مرساةُ التاريخ لا تنكسر بتبديل الكاشف (خطّة فيبل، S0).

قصاصةُ التاريخ تُشتقّ من **صندوق العدد**، فتبديلُ الكاشف يُزيحها. الحدّان
مُسجَّلان قبل التشغيل (سجلّ التقييم · الخطوة صفر · البوّابة ب):
    تامٌّ ≥ 68%   (الأساسُ بصندوق det1: 71.1% مع سماح CI)
    دقّةُ الأخضر (ثقة ≥0.98) ≥ 90%
العيّنة: n=150 حتميّةً من كتب حجز D2 — وسومُها حقيقةُ القاعدة بعد المبادلة.

    python scripts/eval/gate_b_date_anchor.py
"""
import hashlib
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
from core.extraction.handwriting.detector import detect_boxes  # noqa: E402
from core.extraction.handwriting.date_parse import parse_drawn_date  # noqa: E402
from core.extraction.handwriting.date_reader import (  # noqa: E402
    DATE_CONF_GREEN, get_date_reader)
from core.models import Book  # noqa: E402

MAN = r'D:\migration\lettersys_models\date_ds\manifest.jsonl'
OUT = r'D:\migration\lettersys_models\gate_b_date.json'
N = 150
GATE_EXACT, GATE_GREEN = 0.68, 0.90
GREEN_TH = None   # يُقرأ من الوحدة — لا يُكرَّر رقماً
GEOM_X = (2.0, -0.2, 2.4)      # الهندسةُ المعتمدة — تتحرّك مع الحصاد معاً


def split_of(b):
    return 'holdout' if int(hashlib.md5(str(b).encode()).hexdigest()[:8], 16) % 100 < 5 else 'train'


def render(path):
    if path.lower().endswith('.pdf'):
        import fitz
        doc = fitz.open(path)
        try:
            pg = doc[0]
            z = 175 / 72.0
            lo = max(pg.rect.width, pg.rect.height) * z
            if lo > 3500:
                z *= 3500 / lo
            px = pg.get_pixmap(matrix=fitz.Matrix(z, z))
            return Image.frombytes('RGB', (px.width, px.height), px.samples)
        finally:
            doc.close()
    return Image.open(path).convert('RGB')


rows = [json.loads(l) for l in open(MAN, encoding='utf-8')]
rows = [r for r in rows if 'skip' not in r and split_of(r['book']) == 'holdout']
rows.sort(key=lambda r: hashlib.md5(('gateb-%s' % r['book']).encode()).hexdigest())
rows = rows[:N]
print('عيّنةُ الحجز: %d' % len(rows), flush=True)

rd = get_date_reader()
assert rd.available, 'قارئُ التاريخ غير متاح'
res = []
for i, r in enumerate(rows):
    rec = {'book': r['book'], 'truth': r['label']}
    try:
        b = Book.objects.get(id=r['book'])
        im = render(b.attachments.first().file.path)
        W, H = im.size
        n = detect_boxes(im).get('number')
        rec['fired'] = n is not None
        if n:
            x0, y0, x1, y1 = n[0]
            bw, bh = (x1 - x0), (y1 - y0)
            ext, top, bot = GEOM_X
            px0 = max(0, int((x0 - ext * bw) * W))
            px1 = min(W, int((x1 + ext * bw) * W))
            py0 = max(0, int((y1 + top * bh) * H))
            py1 = min(H, int((y1 + bot * bh) * H))
            if (px1 - px0) >= 20 and (py1 - py0) >= 10:
                crop = im.convert('L').crop((px0, py0, px1, py1))
                raw, conf = rd.read(crop)
                # **تاريخُ القيد الحقيقيّ للكتاب** لا «اليوم» — نافذةُ الحسم
                # تنزاح مع الكتاب، وإلّا امتنع المحلّل على كلّ أرشيفٍ قديم.
                iso, status = parse_drawn_date(raw, entry_date=b.date) if raw else (None, 'empty')
                rec.update({'raw': raw, 'iso': iso, 'parse': status,
                            'conf': round(float(conf or 0), 4)})
                del crop
        del im
    except Exception as exc:
        rec['err'] = type(exc).__name__
    rec['hit'] = bool(rec.get('iso')) and rec['iso'] == rec['truth']
    res.append(rec)
    if (i + 1) % 25 == 0:
        print('  %d/%d' % (i + 1, len(rows)), flush=True)

json.dump(res, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
n = len(res)
hit = sum(1 for r in res if r['hit'])
green = [r for r in res if r.get('conf', 0) >= DATE_CONF_GREEN and r.get('parse') == 'ok']
gh = sum(1 for r in green if r['hit'])
fired = sum(1 for r in res if r.get('fired'))
print('\n=== البوّابة ب ===')
print('أطلق الكاشف: %d/%d' % (fired, n))
print('تامٌّ: %d/%d = %.1f%%  (الحدّ %.0f%%) %s'
      % (hit, n, 100 * hit / n, 100 * GATE_EXACT, 'PASS' if hit / n >= GATE_EXACT else 'FAIL'))
gp = gh / max(1, len(green))
print('دقّةُ الأخضر: %d/%d = %.1f%%  (الحدّ %.0f%%) %s · تغطية %.0f%%'
      % (gh, len(green), 100 * gp, 100 * GATE_GREEN,
         'PASS' if gp >= GATE_GREEN else 'FAIL', 100 * len(green) / n))
print('حُفظ ⟵ %s' % OUT)
