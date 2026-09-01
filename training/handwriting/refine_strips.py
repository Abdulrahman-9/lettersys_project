# -*- coding: utf-8 -*-
"""تنقية الحصاد بمحاذاة CTC: النموذج الأساس يقرأ الشريط الخام؛ إن ظهر الوسمُ
متتاليةً داخل قراءته، نحسب موضعها الزمني→البكسلي ونقتصّ شريطاً ضيّقاً حولها
(أفقياً بمحاذاة CTC وعمودياً بإسقاط الحبر) → عيّنة fine-tune نظيفة.
يجرّب نسختين من كل شريط: الخام + مقصوص صندوق-الحبر (يعالج الشرائط الطويلة)."""
import csv, os
import numpy as np
from PIL import Image
import onnxruntime as ort

# جذر المشروع مُشتقّ من موقع الملف — يعمل من أي مجلد تشغيل
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HARVEST = os.path.join(BASE, 'training', 'handwriting', 'harvest')
REFINED = os.path.join(HARVEST, 'strips_refined')
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
    """(النص المطويّ، مواضع أول إطار لكل محرف)."""
    seq = logits.argmax(-1)[0]
    prev, chars, pos = BLANK, [], []
    for t, k in enumerate(seq):
        if k != BLANK and k != prev:
            chars.append(CHARSET[k - 1])
            pos.append(t)
        prev = k
    return ''.join(chars), pos


def ink_bbox(im, pad=6):
    """صندوق الحبر (عتبة على الأدكن من الخلفية) أو None لصفحة فارغة."""
    a = np.asarray(im, dtype=np.float32)
    dark = a < (a.mean() - 1.2 * a.std())
    if dark.sum() < 40:
        return None
    ys, xs = np.where(dark)
    return (max(0, xs.min() - pad), max(0, ys.min() - pad),
            min(im.width, xs.max() + pad), min(im.height, ys.max() + pad))


def approx_window(pred, label):
    """نافذة متصلة في pred بطول الوسم ±1 تبعد عنه مسافة تحرير ≤ 1 (للأطوال ≥ 4
    فقط — القصير يحتاج تطابقاً حرفياً). ترفض التطابق المبعثر (فخّ التواريخ)."""
    if len(label) < 4:
        return None
    m = len(label)
    best = None
    for wlen in (m, m - 1, m + 1):
        for i in range(0, len(pred) - wlen + 1):
            win = pred[i:i + wlen]
            dp = list(range(m + 1))
            for a, ca in enumerate(win, 1):
                prev, dp[0] = dp[0], a
                for b, cb in enumerate(label, 1):
                    prev, dp[b] = dp[b], min(dp[b] + 1, dp[b - 1] + 1, prev + (ca != cb))
            if dp[-1] <= 1 and (best is None or dp[-1] < best[2]):
                best = (i, i + wlen - 1, dp[-1])
        if best:
            break
    return (best[0], best[1]) if best else None


def _decode_only(im):
    x, _ = preprocess(im)
    pred, _ = decode_with_pos(sess.run(None, {IN: x})[0])
    return pred


def _ed(a, b):
    dp = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev, dp[0] = dp[0], i
        for j, cb in enumerate(b, 1):
            prev, dp[j] = dp[j], min(dp[j] + 1, dp[j - 1] + 1, prev + (ca != cb))
    return dp[-1]


def try_candidate(im, label):
    """يعيد (شريط مُقتصّ بمحاذاة CTC، tier) أو None."""
    x, nw = preprocess(im)
    pred, pos = decode_with_pos(sess.run(None, {IN: x})[0])
    if not pred:
        return None
    idx = pred.find(label)
    if idx >= 0:
        tier = 'A' if pred == label else 'B'
        i0, i1 = idx, idx + len(label) - 1
    else:
        win = approx_window(pred, label)
        if not win:
            return None
        tier = 'C'
        i0, i1 = win
    # هوامش القصّ: من قُبيل أول محرف إلى ما بعد بداية الأخير بعرض محرفٍ كامل
    t0, t1 = pos[i0], pos[i1]
    t_next = pos[i1 + 1] if i1 + 1 < len(pos) else t1 + 14
    scale = im.width / nw                     # إطار CTC = 4 بكسلات من المُعاد تحجيمه
    x0 = max(0, int((t0 * 4 - 16) * scale))
    x1 = min(im.width, int((min(t_next - 1, t1 + 14) * 4 + 10) * scale))
    if x1 - x0 < 12:
        return None
    band = im.crop((x0, 0, x1, im.height))
    bb = ink_bbox(band, pad=8)                # قصّ عمودي على الحبر داخل النطاق
    if bb:
        band = band.crop((0, bb[1], band.width, bb[3]))
    # حارس الكثافة: باركود/أختام مصمتة تُقرأ أرقاماً وهمية
    a = np.asarray(band, dtype=np.float32)
    dark_ratio = float((a < a.mean() - 1.0 * a.std()).mean()) if a.std() > 1 else 0.0
    if dark_ratio > 0.35:
        return None
    # تحقّق ذاتي: إعادة قراءة المقصوص يجب أن تقارب الوسم
    if _ed(_decode_only(band), label) > (0 if len(label) < 4 else 1):
        return None
    return band, tier


rows = list(csv.DictReader(open(os.path.join(HARVEST, 'labels.csv'), encoding='utf-8')))
out, stats = [], {'A': 0, 'B': 0, 'C': 0, 'reject': 0, 'empty': 0}
for r in rows:
    p = os.path.join(HARVEST, 'strips', r['file'])
    if not os.path.exists(p):
        continue
    im = Image.open(p).convert('L')
    if np.asarray(im, dtype=np.float32).std() < 6:
        stats['empty'] += 1
        continue
    got = try_candidate(im, r['label'])
    if got is None:
        bb = ink_bbox(im)                     # الشرائط الطويلة: جرّب صندوق الحبر
        if bb:
            got = try_candidate(im.crop(bb), r['label'])
    if got is None:
        stats['reject'] += 1
        continue
    band, tier = got
    band.save(os.path.join(REFINED, r['file']))
    stats[tier] += 1
    out.append({**r, 'tier': tier})

with open(os.path.join(HARVEST, 'labels_clean.csv'), 'w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=['file', 'label', 'book_id', 'entity_id', 'source', 'tier'])
    w.writeheader()
    w.writerows(out)

total = len(rows)
kept = stats['A'] + stats['B'] + stats['C']
print(f'المجموع {total} | تام A={stats["A"]} | محتوى B={stats["B"]} | جزئي C={stats["C"]} | '
      f'رفض={stats["reject"]} | فارغ={stats["empty"]}')
print(f'الصافي: {kept} ({100 * kept / max(1, total):.0f}%) → strips_refined/ + labels_clean.csv')
