# -*- coding: utf-8 -*-
"""تعبئة عدّة الصقل كداتاسِت كاغل خاص — بعد اكتمال الحصاد والتنقية.

يجمع strips_refined + labels_clean.csv + أوزان v4 في مجلد داتاسِت، يزيل
التكرارات (نفس الصورة بايتياً من إعادة رفع المستند نفسه)، ويطبع أوامر الدفع.

    python training/handwriting/package_real_dataset.py
    ثم:  python -m kaggle datasets create -p training/handwriting/dataset_real  (أول مرة)
    أو:  python -m kaggle datasets version -p training/handwriting/dataset_real -m "vN"
"""
import csv
import hashlib
import json
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
HARVEST = os.path.join(HERE, 'harvest')
DS = os.path.join(HERE, 'dataset_real')
# تعبئة مسطّحة: الصور في جذر الداتاسِت — kaggle CLI على ويندوز يتخطى المجلدات
# الفرعية صامتاً عند الرفع (dir-mode=skip الافتراضي) فيصعد الداتاسِت بلا صور.
DS_STRIPS = DS

os.makedirs(DS, exist_ok=True)

rows = list(csv.DictReader(open(os.path.join(HARVEST, 'labels_clean.csv'), encoding='utf-8')))
seen_md5, kept, dups, missing = set(), [], 0, 0
for r in rows:
    src = os.path.join(HARVEST, 'strips_refined', r['file'])
    if not os.path.exists(src):
        missing += 1
        continue
    with open(src, 'rb') as f:
        h = hashlib.md5(f.read()).hexdigest()
    if h in seen_md5:                      # المستند نفسه رُفع مرتين → شريط مطابق
        dups += 1
        continue
    seen_md5.add(h)
    shutil.copy2(src, os.path.join(DS_STRIPS, r['file']))
    kept.append(r)

with open(os.path.join(DS, 'labels_clean.csv'), 'w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=['file', 'label', 'book_id', 'entity_id', 'source', 'tier'])
    w.writeheader()
    w.writerows(kept)

shutil.copy2(os.path.join(HERE, 'kaggle_out_v4_final', 'crnn_weights.pt'),
             os.path.join(DS, 'crnn_weights.pt'))

meta = {
    'title': 'LetterSys real number strips (private)',
    'id': 'abdualrhmanahmed/lettersys-real-number-strips',
    'licenses': [{'name': 'other'}],
}
with open(os.path.join(DS, 'dataset-metadata.json'), 'w', encoding='utf-8') as f:
    json.dump(meta, f, indent=1)

tiers = {}
for r in kept:
    tiers[r['tier']] = tiers.get(r['tier'], 0) + 1
print(f'عُبّئ {len(kept)} شريطاً فريداً (أسقط {dups} مكرراً، {missing} مفقوداً) | فئات: {tiers}')
print(f'المجلد: {DS}')
print('الدفع (أول مرة):  python -m kaggle datasets create -p training/handwriting/dataset_real')
print('تحديث لاحق:       python -m kaggle datasets version -p training/handwriting/dataset_real -m "v2"')
