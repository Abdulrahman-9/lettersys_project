# -*- coding: utf-8 -*-
"""مسحُ عتبة قارئ التاريخ محليّاً بصيغة الإنتاج H6 — الخطوة الملزمة قبل D3.

**لماذا لا يُقتبس جدول النواة:** مسحُها جرى بمتوسّط احتماليّة الرمز (الصيغة
القديمة)، والإنتاج على `_sequence_confidence` (احتماليّة CTC الأماميّة مُطبَّعةً
بالطول) — **سُلَّمان مختلفان**. هذا بعينه ما لدغَنا في T2.4 وسُجّل قانوناً:
«صيغةُ الدفتر == صيغةُ الإنتاج، وإلّا فالعتبةُ من مسحٍ محليّ».

**والمسح يقيس أيضاً فخّاً بنيويّاً محتملاً:** النواة حشت الدفعة إلى عرضٍ أدنى
128 بكسل (≈32 إطاراً زمنيّاً) بينما الإنتاج يمرّر القصاصة بعرضها الطبيعيّ. وCTC
لا يستطيع إخراج n رمزاً بأقلّ من 2n−1 إطاراً — فقصاصةٌ ضيّقة **تعجز بالبناء**
عن إخراج تاريخٍ كامل. يُقاس الفرق هنا بأرضيّتين (32 = الإنتاج الساذج · 128 =
تكافؤ التدريب)، ويُختار ما يُثبته الرقم لا الحدس.

المطابقة متعدّدة المراجع كما سُجّل: التنبّؤ صحيحٌ إن طابق أيّاً من ثمانية
مرشّحاتٍ للوسم (سنةٌ بأربع خاناتٍ أو خانتين × سنةٌ أوّلاً أو يومٌ أوّلاً ×
بحشوٍ صفريّ أو بلا).

    python scripts/eval/d2_h6_sweep.py [أرضيّة العرض]
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

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from core.extraction.handwriting.reader import HandwrittenNumberReader  # noqa: E402

DS = r'D:\migration\lettersys_models\date_ds'
OUT = r'D:\migration\lettersys_models\d2_out\h6_sweep.json'
GEOM = 'x'                       # الهندسة المعتمدة ببوّابة العين D1
FLOOR = int(sys.argv[1]) if len(sys.argv) > 1 else 32


def split_of(book_id):
    return 'holdout' if int(hashlib.md5(str(book_id).encode()).hexdigest()[:8], 16) % 100 < 5 else 'train'


def candidates(iso):
    """المرشّحات الثمانية المُسجَّلة — الشهر في الوسط دوماً بكلا الاتّجاهين."""
    y, m, d = iso.split('-')
    yy, mm, dd = y[2:], m.lstrip('0') or '0', d.lstrip('0') or '0'
    return {
        '%s/%s/%s' % (y, mm, dd), '%s/%s/%s' % (dd, mm, y),
        '%s/%s/%s' % (y, m, d), '%s/%s/%s' % (d, m, y),
        '%s/%s/%s' % (yy, mm, dd), '%s/%s/%s' % (dd, mm, yy),
        '%s/%s/%s' % (yy, m, d), '%s/%s/%s' % (d, m, yy),
    }


class _FloorReader(HandwrittenNumberReader):
    """قارئٌ بأرضيّة عرضٍ — حشوٌ يمينيٌّ بصفرٍ كما في تدريب النواة تماماً."""

    floor = 32

    def preprocess(self, pil_gray):
        x = HandwrittenNumberReader.preprocess(pil_gray)
        w = x.shape[-1]
        if w < self.floor:
            pad = np.zeros(x.shape[:-1] + (self.floor - w,), dtype=x.dtype)
            x = np.concatenate([x, pad], axis=-1)
        return x


rows = []
for line in open(os.path.join(DS, 'manifest.jsonl'), encoding='utf-8'):
    r = json.loads(line)
    if 'skip' in r or GEOM not in r.get('files', {}):
        continue
    if split_of(r['book']) == 'holdout':
        rows.append(r)
print('حجز التاريخ: %d كتاباً · أرضيّة العرض %d' % (len(rows), FLOOR), flush=True)

rd = _FloorReader(model_path=os.path.join('var', 'models', 'handwritten_dates_crnn.onnx'),
                  charset_path=os.path.join('var', 'models', 'handwritten_dates_charset.json'))
rd.floor = FLOOR
assert rd.available, 'أوزان قارئ التاريخ غير متاحة'

detail, widths = [], []
for i, r in enumerate(rows):
    img = Image.open(os.path.join(DS, 'crops', r['files'][GEOM])).convert('L')
    w, h = img.size
    widths.append(max(32, min(512, int(w * 64 / max(1, h)))))
    text, conf = rd.read(img)
    ok = bool(text) and text in candidates(r['label'])
    detail.append({'book': r['book'], 'truth': r['label'], 'pred': text or '',
                   'conf': round(float(conf), 4), 'hit': ok})
    if (i + 1) % 100 == 0:
        print('  %d/%d' % (i + 1, len(rows)), flush=True)

n = len(detail)
hits = sum(1 for d in detail if d['hit'])
print('\nمطابقةٌ تامّة (متعدّدة المراجع) %d/%d = %.1f%%' % (hits, n, 100 * hits / n))
print('عرضُ القصاصة بعد التقييس: وسيط %d · دون 128: %d (%.0f%%)'
      % (int(np.median(widths)), sum(1 for w in widths if w < 128),
         100 * sum(1 for w in widths if w < 128) / n))

print('\nمسحُ العتبة بصيغة H6 (سُلَّم الإنتاج):')
print('عتبة   يُعرض        دقّة المعروض تغطية')
grid = []
for th in (0.50, 0.60, 0.70, 0.80, 0.85, 0.90, 0.95, 0.98):
    em = [d for d in detail if d['pred'] and d['conf'] >= th]
    p = (sum(1 for d in em if d['hit']) / len(em)) if em else 0.0
    grid.append({'th': th, 'emitted': len(em), 'coverage': len(em) / n, 'precision': p})
    print('%.2f   %3d (%3.0f%%)   %.3f' % (th, len(em), 100 * len(em) / n, p))

gate = [g for g in grid if g['precision'] >= 0.90 and g['coverage'] >= 0.40]
print('\nبوّابة D3 (دقّة ≥0.90 بتغطية ≥0.40): %s'
      % ('PASS عند عتبة %.2f (دقّة %.3f · تغطية %.0f%%)'
         % (gate[0]['th'], gate[0]['precision'], 100 * gate[0]['coverage']) if gate else 'FAIL'))
os.makedirs(os.path.dirname(OUT), exist_ok=True)
json.dump({'floor': FLOOR, 'exact': hits / n, 'n': n, 'grid': grid, 'detail': detail},
          open(OUT.replace('.json', '_f%d.json' % FLOOR), 'w', encoding='utf-8'), ensure_ascii=False)
print('حُفظ ⟵ %s' % OUT.replace('.json', '_f%d.json' % FLOOR))
