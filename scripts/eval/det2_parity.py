# -*- coding: utf-8 -*-
"""البوّابة أ — تكافؤُ صنف العدد بين det2 والكاشف القديم على مجموعة الانحدار.

المجموعة: صفحاتُ e2e-C المئة. نظرتُها **أُنفقت** فصارت مجموعةَ انحدارٍ مشروعة
(حوكمة §3د: تجديدُ الأوزان يُقاس على الانحدار بصفر نظراتٍ مختومة). وهي الشريحةُ
**الصعبة** بعينها — وخطرُ det2 الحقيقيّ تراجعُ عدده عليها، لأنّه دُرِّب على شريحة
التقاطع السهلة.

الحدودُ مُسجَّلةٌ قبل التشغيل (سجلّ التقييم، الخطوة صفر · البوّابة أ):
    مركزٌ داخل صندوق القديم أو IoU>=0.5 على المُطلقة ... >= 90%
    إطلاقُ det2 للعدد ......................... >= 63 / 100   (القديم 65)
    فحصٌ بنيويّ: مركزُ العدد أعلى من الموضوع ... >= 95%
والشقُّ الثاني (إصابةُ e2e ودقّتُها) يجري بسكربت e2e_number_c نفسه.

    python scripts/eval/det2_parity.py
"""
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
from core.models import Book  # noqa: E402

RESULTS = r'D:\migration\lettersys_models\e2e_C_results.json'
OUT = r'D:\migration\lettersys_models\det2_parity.json'
GATE_AGREE, GATE_FIRE, GATE_ORDER = 0.90, 63, 0.95


def render(path):
    """وصفةُ الرسم الإنتاجيّة حرفيّاً — 175dpi خام RGB بسقف 3500."""
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


def center_in(box, ref):
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return ref[0] <= cx <= ref[2] and ref[1] <= cy <= ref[3]


def iou(a, b):
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    inter = (x1 - x0) * (y1 - y0)
    ar = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ar if ar > 0 else 0.0


rows = json.load(open(RESULTS, encoding='utf-8'))
print('صفحاتُ الانحدار: %d' % len(rows), flush=True)

res, agree, fired_new, order_ok, order_n = [], 0, 0, 0, 0
old_fired = new_on_silent = 0
for i, r in enumerate(rows):
    bid = r['book']
    rec = {'book': bid, 'old_box': r.get('box'), 'old_src': r.get('box_src') or ''}
    try:
        b = Book.objects.get(id=bid)
        att = b.attachments.first()
        im = render(att.file.path)
        d = detect_boxes(im)
        del im
    except Exception as exc:
        rec['err'] = type(exc).__name__
        res.append(rec)
        continue

    n, s = d.get('number'), d.get('subject')
    rec['new_box'] = n[0] if n else None
    rec['new_conf'] = round(n[1], 3) if n else None
    rec['subj_box'] = s[0] if s else None
    fired_new += n is not None
    if n and s:
        order_n += 1
        order_ok += ((n[0][1] + n[0][3]) / 2) < ((s[0][1] + s[0][3]) / 2)

    ob = r.get('box')
    if ob:
        old_fired += 1
        if n:
            ok = center_in(n[0], ob) or iou(n[0], ob) >= 0.5
            rec['agree'] = bool(ok)
            agree += ok
        else:
            rec['agree'] = False
    elif n:
        new_on_silent += 1
        rec['new_on_silent'] = True
    res.append(rec)
    if (i + 1) % 20 == 0:
        print('  %d/%d' % (i + 1, len(rows)), flush=True)

json.dump(res, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
agree_rate = agree / max(1, old_fired)
order_rate = order_ok / max(1, order_n)
print('\n=== البوّابة أ ===')
print('القديم أطلق %d · det2 أطلق %d' % (old_fired, fired_new))
print('اتّفاقٌ على المُطلقة: %d/%d = %.1f%%  (الحدّ %.0f%%) %s'
      % (agree, old_fired, 100 * agree_rate, 100 * GATE_AGREE,
         'PASS' if agree_rate >= GATE_AGREE else 'FAIL'))
print('إطلاقُ det2: %d  (الحدّ %d) %s'
      % (fired_new, GATE_FIRE, 'PASS' if fired_new >= GATE_FIRE else 'FAIL'))
print('العددُ أعلى من الموضوع: %d/%d = %.1f%%  (الحدّ %.0f%%) %s'
      % (order_ok, order_n, 100 * order_rate, 100 * GATE_ORDER,
         'PASS' if order_rate >= GATE_ORDER else 'FAIL'))
print('إطلاقٌ جديدٌ حيث صمت القديم: %d — **يُتحقَّق بالعين قبل احتسابه مكسباً**'
      % new_on_silent)
print('حُفظ ⟵ %s' % OUT)
