# -*- coding: utf-8 -*-
"""تعبئة داتاسِت v6-الأرقام — وصفة المتانة (2026-07-19، فحص بصري للمالك):
الفجوة المقيسة هشاشةُ v5 أمام القصّ الواسع (97.6% ضيّق مقابل 35% واسع)، فيتدرّب v6
على **النسختين معاً** + توسعة ثلاثية المصدر:
  1) الـ1,185 المُثبَتة: الضيّقة (strips_refined) + الواسعة (strips، باسم w_*)
  2) 242 قبول آليّ بشاهدَين (v5==DB): الواسعة + قصّ حبرٍ ضيّق (t_*)
  3) 169 ذهبُ المنجم (نافذة v5==DB، دُقّق بصرياً 12/12): الواسعة + النافذة الرابحة (m_*)

متوافق حرفياً مع صيغة v5 (labels_clean.csv بنفس الأعمدة + الصور بجذر الداتاسِت +
أوزان v5 أساساً للصقل) — نوتبوك finetune_crnn_real يعمل بلا أي تعديل.

    python training/handwriting/package_v6_dataset.py
"""
import csv
import hashlib
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, PROJ)
os.chdir(PROJ)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lettersys.settings')
import django

django.setup()

from PIL import Image
from core.extraction.handwriting.reader import HandwrittenNumberReader

HARVEST = os.path.join(HERE, 'harvest')
STRIPS = os.path.join(HARVEST, 'strips')
REFINED = os.path.join(HARVEST, 'strips_refined')
DS = os.path.join(HERE, 'dataset_v6')
os.makedirs(DS, exist_ok=True)
rdr = HandwrittenNumberReader()


def windows(img):
    """نفس نوافذ mine_contested حرفياً — لإعادة توليد النافذة الرابحة بفهرسها."""
    W, Hh = img.size
    cands = [img]
    bb = rdr._ink_bbox(img)
    if bb:
        cands.append(img.crop(bb))
    cands.append(img.crop((0, 0, W // 2, Hh)))
    cands.append(img.crop((W // 2, 0, W, Hh)))
    cands.append(img.crop((0, Hh // 3, W, Hh)))
    for k in range(3):
        cands.append(img.crop((k * W // 3, 0, (k + 1) * W // 3, Hh)))
    out = []
    for c in cands:
        if c.width >= 24 and c.height >= 14:
            bb2 = rdr._ink_bbox(c)
            out.append(c.crop(bb2) if bb2 else c)
    return out


kept, seen_md5 = [], set()


def put(src_img_path, ds_name, label, book, ent, tier, pil_img=None):
    """يضيف صورةً للداتاسِت (بإسقاط التكرار البايتي كما في v5)."""
    global kept, seen_md5
    dst = os.path.join(DS, ds_name)
    if pil_img is not None:
        pil_img.save(dst)
    else:
        shutil.copy2(src_img_path, dst)
    with open(dst, 'rb') as f:
        h = hashlib.md5(f.read()).hexdigest()
    if h in seen_md5:
        os.remove(dst)
        return
    seen_md5.add(h)
    kept.append({'file': ds_name, 'label': label, 'book_id': book,
                 'entity_id': ent, 'source': 'label', 'tier': tier})


# 1) الأساس المُثبَت بنسختيه
base = list(csv.DictReader(open(os.path.join(HARVEST, 'labels_clean.csv'), encoding='utf-8')))
for r in base:
    tight = os.path.join(REFINED, r['file'])
    wide = os.path.join(STRIPS, r['file'])
    if os.path.exists(tight):
        put(tight, r['file'], r['label'], r['book_id'], r['entity_id'], r['tier'])
    if os.path.exists(wide):
        put(wide, 'w_' + r['file'], r['label'], r['book_id'], r['entity_id'], r['tier'])

# 2) القبول الآليّ بشاهدَين: واسعة + قصّ حبرٍ ضيّق
for r in csv.DictReader(open(os.path.join(HARVEST, 'expand_v6.csv'), encoding='utf-8')):
    wide = os.path.join(STRIPS, r['file'])
    if not os.path.exists(wide):
        continue
    tier = 'A' if r['tier'] == 'A2' else 'B'
    put(wide, 'w_' + r['file'], r['label'], '', '', tier)
    img = Image.open(wide).convert('L')
    bb = rdr._ink_bbox(img)
    if bb:
        put(None, 't_' + r['file'], r['label'], '', '', tier, pil_img=img.crop(bb))

# 3) ذهب المنجم: واسعة + النافذة الرابحة
for r in csv.DictReader(open(os.path.join(HARVEST, 'mined_v6.csv'), encoding='utf-8')):
    wide = os.path.join(STRIPS, r['file'])
    if not os.path.exists(wide):
        continue
    put(wide, 'w_' + r['file'], r['label'], '', '', 'B')
    img = Image.open(wide).convert('L')
    wins = windows(img)
    wi = int(r['win'])
    if wi < len(wins):
        put(None, 'm_' + r['file'], r['label'], '', '', 'B', pil_img=wins[wi])

with open(os.path.join(DS, 'labels_clean.csv'), 'w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=['file', 'label', 'book_id', 'entity_id', 'source', 'tier'])
    w.writeheader()
    w.writerows(kept)

# أساس الصقل: أوزان v5 (الأقوى) — النوتبوك يتوقع الاسم crnn_weights.pt
shutil.copy2(os.path.join(HERE, 'kaggle_out_v5_final', 'crnn_weights_v5.pt'),
             os.path.join(DS, 'crnn_weights.pt'))

with open(os.path.join(DS, 'dataset-metadata.json'), 'w', encoding='utf-8') as f:
    json.dump({'title': 'LetterSys number strips v6 (private)',
               'id': 'abdualrhmanahmed/lettersys-strips-v6',
               'licenses': [{'name': 'other'}]}, f, indent=1)

tiers = {}
for r in kept:
    tiers[r['tier']] = tiers.get(r['tier'], 0) + 1
print(f'v6 dataset: {len(kept)} صورة تدريب (فريدة بايتياً) | فئات: {tiers}')
print(f'المجلد: {DS}')
print('الرفع:  python -m kaggle datasets create -p training/handwriting/dataset_v6')
