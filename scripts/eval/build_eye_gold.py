# -*- coding: utf-8 -*-
"""ذهبُ العين — تجميعُ ما رأته العين في ملفٍّ واحدٍ يستهلكه التدريب والتقييم.

**لماذا لا يُغذَّى في حلقة `capture` مباشرةً:** تلك الحلقةُ تلتقط ما يجري في
الاستعمال الحقيقيّ (اقتراحٌ ⟵ تصحيحُ كاتب) على مرفقاتٍ محفوظة، ودسُّ قياساتٍ
مخبريّةٍ فيها يفسدها بوصفها **شاهدَ استعمال**. فالعينُ تسكن ملفّاً منفصلاً
بدورين واضحين:
  1. **تنقيةُ وسوم** — الأزواج التي خالف فيها الحبرُ عمودَ القاعدة تُستبعَد من
     التدريب (سقفُ ضجيج الوسوم هو ما يحدّ النموذج، لا قدرتُه).
  2. **رايةُ التباس** — القصاصات التي دخلها ختمُ الوارد: تدريبٌ عليها يُعلّم
     قراءةَ ختمِنا بدل حبر الجهة.

**والحدُّ الصارم:** لا يدخل هذا الملفَّ إلّا ما رُئي على **شقّ التدريب**؛ ما
رُئي على مجموعةٍ مختومة يبقى حَكَماً ولا يعود مادّةَ تعلّمٍ أبداً (وإلّا ضاع
الحَكَم النزيه). يُفرَض هنا بالهاش لا بالنيّة.

    python scripts/eval/build_eye_gold.py
"""
import hashlib
import json
import os

BASE = r'D:\migration\lettersys_models'
DATE_DS = os.path.join(BASE, 'date_ds')
SUBJ = os.path.join(BASE, 'subj_boxes', 'eye_sample')
OUT = os.path.join(BASE, 'eye_gold.json')


def split_of(book_id):
    return 'holdout' if int(hashlib.md5(str(book_id).encode()).hexdigest()[:8], 16) % 100 < 5 else 'train'


def _load(path):
    if not os.path.exists(path):
        return []
    out = []
    for line in open(path, encoding='utf-8'):
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


dates = {}
for name in ('d1_eye_a.jsonl', 'd1_eye_b.jsonl', 'd1_eye_x_a.jsonl', 'd1_eye_x_b.jsonl'):
    for d in _load(os.path.join(DATE_DS, name)):
        b = d.get('book')
        if b is None:
            continue
        cur = dates.setdefault(b, {'book': b})
        for k, v in d.items():
            if v is not None:
                cur[k] = v

labels = {}
for line in open(os.path.join(DATE_DS, 'manifest.jsonl'), encoding='utf-8'):
    r = json.loads(line)
    if 'skip' not in r:
        labels[r['book']] = r['label']

date_rows, leaked = [], 0
for b, d in sorted(dates.items()):
    if split_of(b) != 'train':
        leaked += 1          # رُئي على الحجز ⟵ يبقى حَكَماً، لا مادّةَ تعلّم
        continue
    date_rows.append({
        'book': b,
        'eye_read': d.get('ink_read'),
        'db_label': labels.get(b),
        'label_ok': d.get('label_match'),
        'ink_full': d.get('ink_full'),
        'stamp_clutter': bool(d.get('clutter')),
        'script': d.get('script'),
    })

boxes = []
for name in ('eye_a.jsonl', 'eye_b.jsonl'):
    for d in _load(os.path.join(SUBJ, name)):
        if d.get('book') is not None and split_of(d['book']) == 'train':
            boxes.append({'book': d['book'], 'box_ok': bool(d.get('box_ok')),
                          'issue': d.get('issue')})

bad_label = [r['book'] for r in date_rows if r['label_ok'] is False]
clutter = [r['book'] for r in date_rows if r['stamp_clutter']]
bad_box = [r['book'] for r in boxes if not r['box_ok']]
gold = {
    'note': 'ذهبُ العين — تنقيةُ وسومٍ ورايةُ التباس. شقُّ التدريب حصراً.',
    'dates': date_rows,
    'subject_boxes': boxes,
    'exclude_from_date_training': sorted(set(bad_label)),
    'flag_stamp_clutter': sorted(set(clutter)),
    'exclude_from_box_training': sorted(set(bad_box)),
}
json.dump(gold, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('تواريخُ عينٍ (تدريبٌ فقط): %d · مُستبعَدٌ للحجز: %d' % (len(date_rows), leaked))
print('  وسمٌ مخالفٌ للحبر : %d %s' % (len(bad_label), bad_label))
print('  ختمٌ دخيلٌ في القصاصة: %d (%.0f%%)'
      % (len(clutter), 100 * len(clutter) / max(1, len(date_rows))))
print('صناديقُ موضوعٍ محكومة: %d · مرفوضة: %d %s' % (len(boxes), len(bad_box), bad_box))
print('حُفظ ⟵ %s' % OUT)
