# -*- coding: utf-8 -*-
"""تعبئةُ عدّة تدريب قارئ التاريخ (المسار D، مرحلة D2) لكاغل — نسخٌ وضغطٌ فقط.

**صفرُ تدريبٍ وصفرُ رفع.** هذا السكربت يبني حزمةَ الرفع على القرص لا غير؛ الرفعُ
والتشغيل قرارُ المشرف بعد أن تُغلق بوّابةُ العين D1 وتُثبَّت الهندسة.

مصدرُه مانيفست `date_ds` المحصود (`scripts/eval/harvest_dates.py`) الذي يُخرج لكلّ
كتابٍ **ثلاثَ** قصاصات (n ضيّقة · m وسط · w سخيّة) لأنّ الهندسة **مُعاملٌ يُقاس لا
يُفترض**. هذا السكربت يأخذ واحدةً فقط — الوسيط `geom` — والافتراضيّ `m` ريثما
تحسم بوّابةُ العين. ولا يُنتخَب هنا شيء: الاختيار يُملى من الخارج.

**بنيةُ الحزمة (وصفةُ T2.4 المجرَّبة حرفيّاً — درسُ كاغل: ملفُّ zip واحدٌ لا آلافُ
الملفّات؛ رفعُ 8,566 ملفّاً منفرداً أخفق مراراً):**

    d2_upload/
      d2_ds.zip              crops/<book>_<geom>.png  +  manifest.jsonl  +  pack_meta.json
      warm_start.pt          نسخةُ crnn_t24.pt — الانطلاقةُ الدافئة (رأسُ 11 صنفاً)
      dataset-metadata.json  لـ`kaggle datasets create -p d2_upload`

مجلّدُ `crops/` والمانيفست يُبنيان في مرحلةٍ وسيطة `_stage/` ثمّ يُضغطان ويُمحى
الوسيط (`--keep-stage` يُبقيه للفحص). القصدُ صريح: لو بقي `crops/` مفكوكاً بجانب
الـzip لعاد الرفعُ إلى آلاف الملفّات — وهو بعينه الدرسُ المذكور.

المانيفست المسطَّح: `{book, file, label, split}`. الحقلان الأوّلان يطويان
`files={n,m,w}` إلى قصاصةٍ واحدة، و`label` تاريخُ ISO كما هو (`sender_date` =
حبرُ الجهة بعد هجرة المبادلة 0060). و`split` مُضافٌ عمداً — لا تجميلاً: نواةُ
كاغل **تُعيد حسابه** من هاش الكتاب و**تُقارنه** بالمكتوب وتنهار عند أيّ اختلاف،
وهو الحرزُ الذي يمنع تسرُّبَ كتابٍ إلى ضفّتَي التدريب والحجز معاً.

    python scripts/eval/package_date_ds.py [n|m|w] [--limit N] [--out DIR] [--keep-stage]
"""
import argparse
import collections
import hashlib
import json
import os
import shutil
import sys
import zipfile

BASE = r'D:\migration\lettersys_models'
SRC = os.path.join(BASE, 'date_ds')
SRC_MANIFEST = os.path.join(SRC, 'manifest.jsonl')
SRC_CROPS = os.path.join(SRC, 'crops')
WARM_SRC = os.path.join(BASE, 't24_out', 'crnn_t24.pt')
DEFAULT_OUT = os.path.join(BASE, 'd2_upload')
KAGGLE_ID = 'abdualrhmanahmed/lettersys-d2-date-crops'


def split_of(book_id):
    """هاشُ الحجز — **نفسُه حرفيّاً** في `harvest_t24.py` و`t24.py` و`d2.py`.

    لا يُشتقّ من المانيفست ولا يُخمَّن: الكتابُ الواحد يقع على ضفّةٍ واحدة أبداً،
    فلا تُقاس النتيجةُ على صفحةٍ رآها التدريب.
    """
    h = int(hashlib.md5(str(book_id).encode()).hexdigest()[:8], 16)
    return 'holdout' if (h % 100) < 5 else 'train'


def candidates(iso):
    """المرشّحاتُ الثمانية لوسمٍ بصيغة ISO — **نسخةٌ طبق الأصل من `d2.py`**.

    الترتيبُ البصريّ للحبر غير معلومٍ لكلّ عيّنة (لاتينيّ ⟵ يوم/شهر/سنة، هنديّ
    ⟵ سنة/شهر/يوم بحكم اتّجاه الكتابة)، والسنةُ تُكتب بأربع خاناتٍ أو بخانتين.
    فالوسمُ الواحد ثمانيةُ رسومٍ محتملة: {سنةٌ أوّلاً، يومٌ أوّلاً} × {٤ خانات،
    خانتان} × {بحشوٍ صفريّ، بلا حشو}. والشهرُ في الوسط في الثمانية جميعاً.

    تُستعمل هنا للإحصاء فقط؛ وفي النواة هدفاً لخسارة CTC ومرجعاً للمطابقة.
    """
    y, m, d = iso.split('-')
    yy = y[-2:]
    out = []
    for year in (y, yy):
        out += ['%s/%d/%d' % (year, int(m), int(d)),          # سنةٌ أوّلاً، بلا حشو
                '%d/%d/%s' % (int(d), int(m), year),          # يومٌ أوّلاً، بلا حشو
                '%s/%02d/%02d' % (year, int(m), int(d)),      # سنةٌ أوّلاً، بحشو
                '%02d/%02d/%s' % (int(d), int(m), year)]      # يومٌ أوّلاً، بحشو
    return out


def _human(n):
    return '%.1f ميغابايت' % (n / 1048576.0)


def main():
    ap = argparse.ArgumentParser(description='تعبئةُ عدّة D2 — نسخٌ وضغطٌ فقط')
    ap.add_argument('geom', nargs='?', default='m', choices=('n', 'm', 'w', 'x'),
                    help='هندسةُ القصاصة (تُحسم ببوّابة العين D1؛ الافتراضيّ m)')
    ap.add_argument('--out', default=DEFAULT_OUT, help='مجلّدُ الحزمة')
    ap.add_argument('--limit', type=int, default=0, help='تعبئةٌ جزئيّةٌ للفحص لا للرفع')
    ap.add_argument('--keep-stage', action='store_true', help='أبقِ `_stage/` بعد الضغط')
    a = ap.parse_args()

    for p in (SRC_MANIFEST, SRC_CROPS, WARM_SRC):
        if not os.path.exists(p):
            raise SystemExit('مفقود: %s' % p)

    rows, skipped, no_geom, no_file, bad_label = [], 0, 0, 0, 0
    seen = set()
    for line in open(SRC_MANIFEST, encoding='utf-8'):
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        if 'skip' in r or not r.get('label') or not r.get('files'):
            skipped += 1
            continue
        name = r['files'].get(a.geom)
        if not name:                      # القصاصةُ ضئيلةٌ بهذه الهندسة (`tiny`)
            no_geom += 1
            continue
        if not os.path.exists(os.path.join(SRC_CROPS, name)):
            no_file += 1
            continue
        try:
            candidates(r['label'])        # وسمٌ لا يُرسَم = وسمٌ لا يُدرَّب عليه
        except Exception:
            bad_label += 1
            continue
        if r['book'] in seen:             # المانيفست مُلحَقٌ دفعةً بعد دفعة
            continue
        seen.add(r['book'])
        rows.append({'book': r['book'], 'file': name, 'label': r['label'],
                     'split': split_of(r['book'])})
    rows.sort(key=lambda x: x['book'])
    if a.limit:
        rows = rows[:a.limit]
    if not rows:
        raise SystemExit('صفرُ صفوفٍ مؤهَّلة — لا حزمة')

    out = os.path.abspath(a.out)
    stage = os.path.join(out, '_stage')
    if os.path.isdir(stage):
        shutil.rmtree(stage)
    os.makedirs(os.path.join(stage, 'crops'))

    for r in rows:
        shutil.copy2(os.path.join(SRC_CROPS, r['file']),
                     os.path.join(stage, 'crops', r['file']))
    with open(os.path.join(stage, 'manifest.jsonl'), 'w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')

    tr = sum(1 for r in rows if r['split'] == 'train')
    ho = len(rows) - tr
    meta = {'geom': a.geom, 'rows': len(rows), 'train': tr, 'holdout': ho,
            'source_manifest': SRC_MANIFEST, 'charset': '0123456789/',
            'label_field': 'sender_date (حبرُ الجهة بعد هجرة 0060)',
            'partial': bool(a.limit), 'split_rule': 'md5(book)%100 < 5 -> holdout'}
    json.dump(meta, open(os.path.join(stage, 'pack_meta.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)

    zpath = os.path.join(out, 'd2_ds.zip')
    with zipfile.ZipFile(zpath, 'w', zipfile.ZIP_DEFLATED) as z:
        for root, _dirs, files in os.walk(stage):
            for fn in sorted(files):
                full = os.path.join(root, fn)
                arc = os.path.relpath(full, stage).replace(os.sep, '/')
                # PNG مضغوطٌ سلفاً: الترميزُ المخزون يوفّر دقائق ولا يكلّف بايتات.
                z.write(full, arc,
                        compress_type=zipfile.ZIP_STORED if fn.lower().endswith('.png')
                        else zipfile.ZIP_DEFLATED)

    sha = hashlib.sha256()
    with open(zpath, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            sha.update(chunk)
    warm = os.path.join(out, 'warm_start.pt')
    shutil.copy2(WARM_SRC, warm)
    json.dump({'title': KAGGLE_ID.split('/')[1], 'id': KAGGLE_ID,
               'licenses': [{'name': 'CC0-1.0'}]},
              open(os.path.join(out, 'dataset-metadata.json'), 'w', encoding='utf-8'))
    if not a.keep_stage:
        shutil.rmtree(stage)

    iso_len = collections.Counter(len(r['label']) for r in rows)
    cand_len = collections.Counter()
    distinct = collections.Counter()
    years = collections.Counter()
    for r in rows:
        c = candidates(r['label'])
        cand_len.update(len(x) for x in c)
        distinct[len(set(c))] += 1
        years[r['label'][:4]] += 1

    print('الحزمة: %s' % out)
    print('  الهندسة %s%s · صفوف %d (تدريب %d · حجز %d = %.1f%%)'
          % (a.geom, ' [جزئيّةٌ للفحص]' if a.limit else '', len(rows), tr, ho,
             100.0 * ho / len(rows)))
    print('  مُستبعَد: صفُّ skip %d · بلا هذه الهندسة %d · ملفٌّ مفقود %d · وسمٌ معطوب %d'
          % (skipped, no_geom, no_file, bad_label))
    print('  d2_ds.zip = %s · sha256 %s' % (_human(os.path.getsize(zpath)),
                                            sha.hexdigest()[:16]))
    print('  warm_start.pt = %s (من %s)' % (_human(os.path.getsize(warm)), WARM_SRC))
    print('  أطوالُ الوسم (ISO): %s' % dict(sorted(iso_len.items())))
    print('  أطوالُ المرشّحات الثمانية: %s' % dict(sorted(cand_len.items())))
    print('  مرشّحاتٌ متمايزةٌ لكلّ صفّ: %s' % dict(sorted(distinct.items())))
    print('  سنواتُ الوسم: %s' % dict(sorted(years.items())))
    print('  الرفع (بأمر المشرف لا هنا): kaggle datasets create -p "%s"' % out)


if __name__ == '__main__':
    sys.exit(main())
