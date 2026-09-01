# -*- coding: utf-8 -*-
"""مسحُ عتبة H6 للأوزان الجديدة على نفس حجز التدريب — إغلاقُ فجوة تكافؤ الصيغة.

مسحُ الدفتر جرى بصيغة الثقة القديمة (متوسّط الرموز) بينما الإنتاج على ثقة السلسلة H6
(`_sequence_confidence`) — والعتبة لا تنتقل بين سُلَّمين. هذا المسح يُعيده محليّاً:
الأوزان الجديدة + صيغة الإنتاج الحقيقيّة + نفس قصاصات الحجز (393)، فتخرج العتبة
المُعلنة لبوّابة e2e-C من نفس الثلاثيّ الذي سيعمل في الإنتاج حرفيّاً.

    python scripts/eval/t24_h6_sweep.py
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
NEW_ONNX = r'D:\migration\lettersys_models\t24_out\crnn_t24.onnx'


def split_of(book_id):
    h = int(hashlib.md5(str(book_id).encode()).hexdigest()[:8], 16)
    return 'holdout' if (h % 100) < 5 else 'train'


import onnxruntime as ort  # noqa: E402
so = ort.SessionOptions()
so.intra_op_num_threads = 1
sess = ort.InferenceSession(NEW_ONNX, so, providers=['CPUExecutionProvider'])
rd = HandwrittenNumberReader(session=sess)      # نفس فكّ الترميز والمعالجة وصيغة H6

seen = set()
rows = []
for line in open(os.path.join(DS, 'manifest.jsonl'), encoding='utf-8'):
    r = json.loads(line)
    if r.get('label') and r['book'] not in seen and split_of(r['book']) == 'holdout':
        seen.add(r['book'])
        rows.append(r)
print('حجز: %d كتاباً' % len(rows), flush=True)

det = []
for i, r in enumerate(rows):
    img = Image.open(os.path.join(DS, 'crops', r['file'])).convert('L')
    t, cf = rd.read_best(img)
    det.append({'book': r['book'], 'truth': r['label'], 'pred': t or '',
                'conf': round(cf, 4), 'hit': (t or '') == r['label']})
    if (i + 1) % 100 == 0:
        print('  %d/%d' % (i + 1, len(rows)), flush=True)

n = len(det)
hits = sum(d['hit'] for d in det)
print('\nالأوزان الجديدة + صيغة H6 + فكّ ترميز الإنتاج: مطابقةٌ تامّة %d/%d = %.1f%%'
      % (hits, n, 100 * hits / n))
print('\nمسحُ العتبة (H6 — السُلَّم الذي يعمل في الإنتاج):')
print('%-6s %-12s %-10s %s' % ('عتبة', 'يُعرض', 'دقّة المعروض', 'إصابة/الكلّ'))
grid = []
for th in (0.50, 0.60, 0.70, 0.80, 0.85, 0.90, 0.95, 0.98):
    em = [d for d in det if d['conf'] >= th and d['pred']]
    prec = (sum(d['hit'] for d in em) / len(em)) if em else 0.0
    grid.append({'th': th, 'emitted': len(em), 'precision': round(prec, 4)})
    print('%-6.2f %3d (%3.0f%%)   %.3f      %.3f'
          % (th, len(em), 100 * len(em) / n, prec, sum(d['hit'] for d in em) / n))
json.dump({'exact': hits / n, 'grid': grid, 'detail': det},
          open(r'D:\migration\lettersys_models\t24_out\h6_sweep.json', 'w',
               encoding='utf-8'), ensure_ascii=False)
print('\nحُفظ ⟵ t24_out/h6_sweep.json')
