# -*- coding: utf-8 -*-
"""تنقية شرائط التواريخ اليدوية (v2) بمحاذاة CTC — بنموذج الأرقام v5 نفسه.

الفكرة: القارئ الرقمي-الصرف يقرأ شريط «٧/٧/٢٠٢٦» سيلَ أرقامٍ (الفواصل تسقط
أو تتشوش)؛ نولّد من التاريخ المؤكد (ISO) صيغَه الرقمية المكتوبة المحتملة
(ي ش سسسس، سسسس ش ي، بحشو وبدونه، وبسنة مختصرة) ونبحث عنها نافذةً متصلة
في القراءة (خطأ ≤1 للطويلة) — عند الإصابة: قصّ span بمواضع CTC + تشذيب حبر،
والوسم التدريبي يُعاد بناؤه بالفواصل على حدود الصيغة المطابِقة (افتراض «/»
الأشيع؛ ضجيج فئة الفاصل مقبول — التاريخ المفكوك هو الناتج النهائي لا رسمه).

    python training/handwriting/refine_date_strips.py
"""
import csv
import os

import numpy as np
import onnxruntime as ort
from PIL import Image

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HARVEST = os.path.join(BASE, 'training', 'handwriting', 'harvest')
REFINED = os.path.join(HARVEST, 'strips_date_refined')
CHARSET, BLANK, STRIP_H, MAX_W = '0123456789', 0, 64, 512
os.makedirs(REFINED, exist_ok=True)

sess = ort.InferenceSession(os.path.join(BASE, 'var', 'models', 'handwritten_digits_crnn.onnx'),
                            providers=['CPUExecutionProvider'])
IN = sess.get_inputs()[0].name


def preprocess(pil_gray):
    w, h = pil_gray.size
    nw = max(32, min(MAX_W, int(w * STRIP_H / max(1, h))))
    img = pil_gray.resize((nw, STRIP_H), Image.BILINEAR)
    arr = 255.0 - np.asarray(img, dtype=np.float32)
    arr = (arr - arr.mean()) / (arr.std() + 1e-6)
    return arr[None, None], nw


def decode_with_pos(logits):
    seq = logits.argmax(-1)[0]
    prev, chars, pos = BLANK, [], []
    for t, k in enumerate(seq):
        if k != BLANK and k != prev:
            chars.append(CHARSET[k - 1])
            pos.append(t)
        prev = k
    return ''.join(chars), pos


def ink_bbox(im, pad=8):
    a = np.asarray(im, dtype=np.float32)
    dark = a < (a.mean() - 1.2 * a.std())
    if dark.sum() < 40:
        return None
    ys, xs = np.where(dark)
    return (max(0, xs.min() - pad), max(0, ys.min() - pad),
            min(im.width, xs.max() + pad), min(im.height, ys.max() + pad))


def date_variants(iso):
    """من ISO إلى (سيل رقمي، وسم مكتوب بفواصل) — الصيغ العراقية الشائعة."""
    y, m, d = iso.split('-')
    y2 = y[2:]
    mi, di = int(m), int(d)
    out = []
    for dd, mm, yy in ((str(di), str(mi), y), (f'{di:02}', f'{mi:02}', y),
                       (str(di), str(mi), y2), (f'{di:02}', f'{mi:02}', y2)):
        out.append((dd + mm + yy, f'{dd}/{mm}/{yy}'))
        out.append((yy + mm + dd, f'{yy}/{mm}/{dd}'))
    seen, uniq = set(), []
    for seq, written in out:
        if seq not in seen:
            seen.add(seq)
            uniq.append((seq, written))
    return uniq


def find_window(pred, target):
    """نافذة متصلة في pred تبعد ≤1 عن target (تطابق تام للقصيرة <6)."""
    m = len(target)
    tol = 0 if m < 6 else 1
    best = None
    for wlen in {m, m - 1, m + 1} if tol else {m}:
        if wlen < 1:
            continue
        for i in range(0, len(pred) - wlen + 1):
            win = pred[i:i + wlen]
            dp = list(range(m + 1))
            for a, ca in enumerate(win, 1):
                prev, dp[0] = dp[0], a
                for b, cb in enumerate(target, 1):
                    prev, dp[b] = dp[b], min(dp[b] + 1, dp[b - 1] + 1, prev + (ca != cb))
            if dp[-1] <= tol and (best is None or dp[-1] < best[2]):
                best = (i, i + wlen - 1, dp[-1])
    return best


rows = list(csv.DictReader(open(os.path.join(HARVEST, 'labels_date.csv'), encoding='utf-8')))
out_rows, stats = [], {'exact': 0, 'near': 0, 'reject': 0, 'empty': 0}
for r in rows:
    p = os.path.join(HARVEST, 'strips_date', r['file'])
    if not os.path.exists(p):
        continue
    im = Image.open(p).convert('L')
    if np.asarray(im, dtype=np.float32).std() < 6:
        stats['empty'] += 1
        continue
    candidates = [im]
    bb = ink_bbox(im)
    if bb:
        candidates.append(im.crop(bb))
    hit = None
    for cand in candidates:
        x, nw = preprocess(cand)
        pred, pos = decode_with_pos(sess.run(None, {IN: x})[0])
        if not pred:
            continue
        for seq, written in date_variants(r['label']):
            win = find_window(pred, seq)
            if win:
                hit = (cand, nw, pos, win, written, win[2] == 0)
                break
        if hit:
            break
    if hit is None:
        stats['reject'] += 1
        continue
    cand, nw, pos, (i0, i1, _dist), written, exact = hit
    t0, t1 = pos[i0], pos[i1]
    t_next = pos[i1 + 1] if i1 + 1 < len(pos) else t1 + 14
    scale = cand.width / nw
    x0 = max(0, int((t0 * 4 - 16) * scale))
    x1 = min(cand.width, int((min(t_next - 1, t1 + 14) * 4 + 10) * scale))
    if x1 - x0 < 24:
        stats['reject'] += 1
        continue
    band = cand.crop((x0, 0, x1, cand.height))
    bb2 = ink_bbox(band, pad=8)
    if bb2:
        band = band.crop((0, bb2[1], band.width, bb2[3]))
    band.save(os.path.join(REFINED, r['file']))
    tier = 'A' if exact else 'B'
    stats['exact' if exact else 'near'] += 1
    out_rows.append({'file': r['file'], 'label': written, 'iso': r['label'],
                     'book_id': r['book_id'], 'entity_id': r['entity_id'],
                     'source': r['source'], 'tier': tier})

with open(os.path.join(HARVEST, 'labels_date_clean.csv'), 'w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=['file', 'label', 'iso', 'book_id', 'entity_id', 'source', 'tier'])
    w.writeheader()
    w.writerows(out_rows)

total = len(rows)
kept = stats['exact'] + stats['near']
print(f'المجموع {total} | تام={stats["exact"]} | قريب={stats["near"]} | '
      f'رفض={stats["reject"]} | فارغ={stats["empty"]}')
print(f'الصافي: {kept} ({100 * kept / max(1, total):.0f}%) → strips_date_refined/ + labels_date_clean.csv')
