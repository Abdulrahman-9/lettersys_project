# -*- coding: utf-8 -*-
"""تعبئة عدّة تواريخ v6 كداتاسِت كاغل — **أرشيف واحد** (درس معارك الرفع:
1,186 طلباً منفصلاً يموت على شبكة متقطعة؛ zip واحد يصعد في ثوانٍ).

    python training/handwriting/package_date_dataset.py
    python -m kaggle datasets create -p training/handwriting/dataset_dates
"""
import csv
import hashlib
import json
import os
import shutil
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
HARVEST = os.path.join(HERE, 'harvest')
DS = os.path.join(HERE, 'dataset_dates')
os.makedirs(DS, exist_ok=True)

rows = list(csv.DictReader(open(os.path.join(HARVEST, 'labels_date_clean.csv'), encoding='utf-8')))
seen, kept, dups, missing = set(), [], 0, 0
zip_path = os.path.join(DS, 'dates.zip')
with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
    for r in rows:
        src = os.path.join(HARVEST, 'strips_date_refined', r['file'])
        if not os.path.exists(src):
            missing += 1
            continue
        with open(src, 'rb') as f:
            h = hashlib.md5(f.read()).hexdigest()
        if h in seen:                      # المستند نفسه رُفع مرتين → شريط مطابق
            dups += 1
            continue
        seen.add(h)
        zf.write(src, r['file'])
        kept.append(r)

with open(os.path.join(DS, 'labels_date_clean.csv'), 'w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=['file', 'label', 'iso', 'book_id', 'entity_id', 'source', 'tier'])
    w.writeheader()
    w.writerows(kept)

shutil.copy2(os.path.join(HERE, 'kaggle_out_v5_final', 'crnn_weights_v5.pt'),
             os.path.join(DS, 'crnn_weights_v5.pt'))

with open(os.path.join(DS, 'dataset-metadata.json'), 'w', encoding='utf-8') as f:
    json.dump({'title': 'LetterSys real date strips (private)',
               'id': 'abdualrhmanahmed/lettersys-real-date-strips',
               'licenses': [{'name': 'other'}]}, f, indent=1)

tiers = {}
for r in kept:
    tiers[r['tier']] = tiers.get(r['tier'], 0) + 1
size = os.path.getsize(zip_path) / 1e6
print(f'عُبّئ {len(kept)} شريط تاريخ فريداً (أسقط {dups} مكرراً، {missing} مفقوداً) | فئات: {tiers}')
print(f'الأرشيف: {size:.1f}MB → {DS}')
print('الدفع: python -m kaggle datasets create -p training/handwriting/dataset_dates')
