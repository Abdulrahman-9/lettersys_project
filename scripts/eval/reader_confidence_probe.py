# -*- coding: utf-8 -*-
"""مسبارُ ثقة القارئ — تمريرةٌ واحدة تُنتج كلّ المُرشَّحين وإحصاءَ الحذف.

البوّابة والتعريفات مُسجَّلةٌ في `docs/EVAL_REGISTRY.md` **قبل** هذا السكربت.

**العطب المُقاس:** ثقة الإنتاج = متوسّطُ احتماليّة الرمز عند الأطر المُصدَّرة وحدها،
فالحذفُ غيرُ مرئيٍّ لها بالبناء عبر ثلاث قنوات (فراغ · امتداد · انهيارُ مكرّر).

**المُرشَّح الأوّليّ H6:** احتماليّة CTC الأماميّة للسلسلة المُفكَّكة، مُطبَّعةً بالطول —
`P(y|x) ** (1/|y|)`. ترى الحذف مهما كانت قناته: إن بقيت كتلةٌ على «7099» بينما خرج
«799»، انخفضت `P(799)`، والفجوةُ **هي** شكّ الحذف.

المادّة: أزواج الحصاد (قصاصةُ الكاشف ← عددُ الكاتب) بالنموذج **الحاليّ**، وهو غير
ملوَّثٍ بها لأنّه دُرِّب على الشرائط القديمة. تُقاس على شقّ **التدريب** وحده؛ الحجز
يبقى مختوماً لنظرة التحقّق الواحدة.

    python scripts/eval/reader_confidence_probe.py [حدّ أقصى]
"""
import hashlib
import json
import os
import sys

import numpy as np

PROJ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJ)
os.chdir(PROJ)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lettersys.settings')
import django  # noqa: E402
django.setup()

from PIL import Image  # noqa: E402
from core.extraction.handwriting.reader import HandwrittenNumberReader  # noqa: E402

DS = r'D:\migration\lettersys_models\t24_ds'
OUT = r'D:\migration\lettersys_models\reader_probe.json'
LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 10 ** 9
CHARSET = '0123456789'
BLANK = 0


def split_of(book_id):
    h = int(hashlib.md5(str(book_id).encode()).hexdigest()[:8], 16)
    return 'holdout' if (h % 100) < 5 else 'train'


def taxonomy(pred, truth):
    """التعريفات المُسجَّلة: حذفٌ = متتاليةٌ جزئيّةٌ صارمة بأرقامٍ أقلّ."""
    if pred == truth:
        return 'correct'
    if not pred:
        return 'empty'

    def is_sub(a, b):
        it = iter(b)
        return all(c in it for c in a)
    if len(pred) < len(truth) and is_sub(pred, truth):
        return 'deletion'
    if len(pred) > len(truth) and is_sub(truth, pred):
        return 'insertion'
    return 'other'


def missing_glyphs(pred, truth):
    """أيُّ رقمٍ سقط؟ (إحصاءُ الأرقام — يقرّر إن كانت نقطةُ‑الصفر هي الغالب)."""
    if taxonomy(pred, truth) != 'deletion':
        return []
    out, i = [], 0
    for c in truth:
        if i < len(pred) and pred[i] == c:
            i += 1
        else:
            out.append(c)
    return out


def ctc_logp(probs, target):
    """احتماليّة CTC الأماميّة لسلسلةٍ بعينها — log P(y|x). تكرارٌ أماميٌّ قياسيّ.

    الترميز الموسَّع: فراغٌ بين كلّ رمزين وعلى الطرفين. الانتقال يقفز رمزاً واحداً
    فقط إن لم يكن الرمزان متجاورَين متساويَين (شرط CTC للمكرّر)."""
    T = probs.shape[0]
    ext = [BLANK]
    for ch in target:
        ext += [CHARSET.index(ch) + 1, BLANK]
    S = len(ext)
    NEG = -1e30
    a = np.full(S, NEG)
    lp = np.log(np.maximum(probs, 1e-12))
    a[0] = lp[0, ext[0]]
    if S > 1:
        a[1] = lp[0, ext[1]]
    for t in range(1, T):
        prev = a
        cur = np.full(S, NEG)
        for s in range(S):
            best = prev[s]
            if s > 0:
                best = np.logaddexp(best, prev[s - 1])
            if s > 1 and ext[s] != BLANK and ext[s] != ext[s - 2]:
                best = np.logaddexp(best, prev[s - 2])
            cur[s] = best + lp[t, ext[s]]
        a = cur
    return float(np.logaddexp(a[S - 1], a[S - 2])) if S > 1 else float(a[0])


rd = HandwrittenNumberReader()
assert rd.available, 'نموذج القارئ غير متاح'
rows = []
for line in open(os.path.join(DS, 'manifest.jsonl'), encoding='utf-8'):
    r = json.loads(line)
    if r.get('label') and r.get('file') and split_of(r['book']) == 'train':
        rows.append(r)
rows = rows[:LIMIT]
print('أزواجُ التطوير (شقّ التدريب): %d' % len(rows), flush=True)

res = []
for i, r in enumerate(rows):
    try:
        img = Image.open(os.path.join(DS, 'crops', r['file'])).convert('L')
        x = rd.preprocess(img)
        sess = rd._ensure_session()
        logits = sess.run(None, {sess.get_inputs()[0].name: x.astype(np.float32)})[0][0]
        e = np.exp(logits - logits.max(axis=1, keepdims=True))
        probs = e / e.sum(axis=1, keepdims=True)

        best = probs.argmax(1)
        emitted, s, prev = [], [], -1
        for t, k in enumerate(best):
            if k != BLANK and k != prev:
                s.append(CHARSET[k - 1])
                emitted.append(float(probs[t, k]))
            prev = k
        pred = ''.join(s)
        cur_conf = float(np.mean(emitted)) if emitted else 0.0

        allf = probs[np.arange(len(best)), best]
        rec = {
            'book': r['book'], 'truth': r['label'], 'pred': pred,
            'tax': taxonomy(pred, r['label']),
            'missing': missing_glyphs(pred, r['label']),
            'H5_current': round(cur_conf, 5),
            'H1_min': round(float(allf.min()), 5),
            'H1_p10': round(float(np.percentile(allf, 10)), 5),
            'H2_margin': round(float(np.min(np.sort(probs, axis=1)[:, -1]
                                            - np.sort(probs, axis=1)[:, -2])), 5),
            'H3_wpd': round(img.size[0] / max(1, len(pred)), 2) if pred else 0.0,
            'crop_w': img.size[0],
        }
        rec['H6'] = round(float(np.exp(ctc_logp(probs, pred) / max(1, len(pred)))), 5) if pred else 0.0
        res.append(rec)
    except Exception as exc:
        res.append({'book': r['book'], 'truth': r['label'], 'err': type(exc).__name__})
    if (i + 1) % 50 == 0:
        print('  %d/%d' % (i + 1, len(rows)), flush=True)

json.dump(res, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
ok = [x for x in res if 'tax' in x]
import collections
print('\nالتصنيف:', dict(collections.Counter(x['tax'] for x in ok)))
dele = [x for x in ok if x['tax'] == 'deletion']
print('إحصاءُ الأرقام المحذوفة:', dict(collections.Counter(g for x in dele for g in x['missing'])))
print('حُفظ ⟵ %s' % OUT)
