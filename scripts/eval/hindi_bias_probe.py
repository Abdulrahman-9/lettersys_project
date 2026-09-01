# -*- coding: utf-8 -*-
"""مسبارُ انحياز الأرقام العربيّة-الهنديّة في قارئ الأعداد (T2.4).

الفرضيّة (تشخيصُ فيبل 2026-08-26): أكبرُ سببٍ لصمت القارئ امتناعُه عن الأرقام
العربيّة-الهنديّة (٠١٢٣…) رغم صحّة الصندوق ووضوح الحبر — 8 من 10 امتناعاتٍ على
صندوقٍ صحيح كانت هنديّة. المشتبهُ الأوّل: انحيازُ حصاد الـ13,200 نحو سطور
«REF NO» اللاتينيّة.

**العينُ هي الحَكَم.** الوسمُ في المانيفست مُطبَّعٌ إلى لاتينيّ دائماً، فلا يدلّ
على طقم الحبر. ولا OCR وسيطاً (قاعدةُ «احتكم لعينيك»): تُبنى لوحاتُ اتّصالٍ
(25 قصاصةً في صورةٍ واحدة برقمٍ فوق كلٍّ) ثمّ تُصنَّف بالنظر إليها.

العتباتُ مُسجَّلةٌ سلفاً في docs/EVAL_REGISTRY.md — «منحاز» يتحقّق باجتماع الثلاثة:
  ① حصّةُ الهنديّة في التدريب ≤ 25%
  ② امتناع(هنديّ) ≥ 2× امتناع(لاتينيّ)
  ③ تامّ(هنديّ) ≤ تامّ(لاتينيّ) − 15 نقطة

الأطوار:
    python scripts/eval/hindi_bias_probe.py sheets     # يبني لوحات الاتّصال
    python scripts/eval/hindi_bias_probe.py read       # يشغّل القارئ على الحجز
    python scripts/eval/hindi_bias_probe.py label --split train --sheet 1 \
        --codes h,l,l,m,u,...                          # تسجيلُ تصنيف العين (25 رمزاً)
    python scripts/eval/hindi_bias_probe.py judge      # الجدول + الحكم

الرموز: h=هنديّ · l=لاتينيّ · m=مختلط · u=غير واضح

الوزنُ خفيف عمداً (الخانة الثقيلة مشغولة): قصاصاتٌ صغيرةٌ محفوظةٌ سلفاً
+ استدلالُ ONNX بخيطٍ واحد. لا Tesseract ولا رسمَ صفحات PDF.
"""
import argparse
import collections
import hashlib
import json
import os
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJ)
os.chdir(PROJ)

DS = r'D:\migration\lettersys_models\t24_ds'
CROPS = os.path.join(DS, 'crops')
MANIFEST = os.path.join(DS, 'manifest.jsonl')
OUT = r'D:\migration\lettersys_models\hindi_probe'
SHEETS = os.path.join(OUT, 'sheets')
LABELS = os.path.join(OUT, 'eye_labels.jsonl')
READS = os.path.join(OUT, 'reader_holdout.jsonl')

N_SAMPLE = 150
PER_SHEET = 25
CLASSES = {'h': 'hindi', 'l': 'latin', 'm': 'mixed', 'u': 'unclear'}

# عتباتُ الحكم — مُسجَّلةٌ قبل القياس، لا تُفاوَض بعده.
T_SHARE = 25.0          # حصّةُ الهنديّة في التدريب (%)
T_ABSTAIN_RATIO = 2.0   # امتناع هنديّ / امتناع لاتينيّ
T_EXACT_GAP = 15.0      # نقاطُ فارق المطابقة التامّة
T_HARVEST_FLOOR = 1500  # الحدُّ المُسجَّل: أقلُّ من ذلك ⟵ حصادٌ موجَّه
CONF_GATE = 0.90        # بوّابةُ الإنتاج (reader.CONF_GATE) — للصمت الفعليّ


# ── العيّنة الحتميّة ────────────────────────────────────────────────────────
def split_of(book_id):
    """قاعدةُ الشقّ الأصليّة (harvest_t24.py) — md5 لأوّل 8 خاناتٍ سُدسيّة % 100 < 5."""
    h = int(hashlib.md5(str(book_id).encode()).hexdigest()[:8], 16)
    return 'holdout' if (h % 100) < 5 else 'train'


def load_rows():
    rows = []
    with open(MANIFEST, encoding='utf-8') as f:
        for line in f:
            r = json.loads(line)
            if 'file' in r:          # صفوفُ `skip` بلا قصاصة
                rows.append(r)
    return rows


def sample_of(rows, split):
    """ترتيبٌ حتميٌّ بمِلحٍ ثابت ثمّ أوّل 150 — لا عشوائيّةَ نظامٍ ولا وقت."""
    pool = [r for r in rows if split_of(r['book']) == split]
    pool.sort(key=lambda r: hashlib.md5(('hindi-%s' % r['book']).encode()).hexdigest())
    return pool[:N_SAMPLE]


# ── (أ) لوحاتُ الاتّصال ─────────────────────────────────────────────────────
def build_sheets():
    from PIL import Image, ImageDraw, ImageFont
    os.makedirs(SHEETS, exist_ok=True)
    rows = load_rows()
    try:
        font = ImageFont.truetype('arial.ttf', 17)
    except OSError:
        font = ImageFont.load_default()

    cols, cw, ch, hdr, pad = 5, 300, 104, 24, 4
    made = []
    for split in ('train', 'holdout'):
        sample = sample_of(rows, split)
        with open(os.path.join(OUT, 'sample_%s.json' % split), 'w',
                  encoding='utf-8') as f:
            json.dump([{'i': i + 1, 'book': r['book'], 'file': r['file'],
                        'label': r['label']} for i, r in enumerate(sample)],
                      f, ensure_ascii=False, indent=1)
        for s in range((len(sample) + PER_SHEET - 1) // PER_SHEET):
            chunk = sample[s * PER_SHEET:(s + 1) * PER_SHEET]
            nrow = (len(chunk) + cols - 1) // cols
            sheet = Image.new('L', (cols * cw, nrow * (ch + hdr)), 245)
            d = ImageDraw.Draw(sheet)
            for k, r in enumerate(chunk):
                gi = s * PER_SHEET + k + 1
                cx, cy = (k % cols) * cw, (k // cols) * (ch + hdr)
                d.rectangle([cx, cy, cx + cw - 2, cy + ch + hdr - 2], outline=170)
                d.text((cx + 6, cy + 3), '%d' % gi, fill=0, font=font)
                im = Image.open(os.path.join(CROPS, r['file'])).convert('L')
                # تكبيرٌ ملائمٌ للنظر — القصاصةُ الوسيطة 161×43 فتُضاعَف ~1.8×
                bw, bh = cw - 2 * pad, ch - 2 * pad
                sc = min(bw / im.width, bh / im.height)
                im = im.resize((max(1, int(im.width * sc)),
                                max(1, int(im.height * sc))), Image.LANCZOS)
                sheet.paste(im, (cx + (cw - im.width) // 2,
                                 cy + hdr + (ch - im.height) // 2))
            p = os.path.join(SHEETS, '%s_%02d.png' % (split, s + 1))
            sheet.save(p)
            made.append((p, len(chunk)))
    for p, n in made:
        print('%s  (%d قصاصة)' % (p, n))


# ── تسجيلُ تصنيف العين (نقطةُ تفتيشٍ لكلّ لوحة) ─────────────────────────────
def record_labels(split, sheet, codes):
    rows = load_rows()
    sample = sample_of(rows, split)
    codes = [c.strip().lower() for c in codes.replace(' ', ',').split(',') if c.strip()]
    base = (sheet - 1) * PER_SHEET
    expect = len(sample[base:base + PER_SHEET])
    if len(codes) != expect:
        sys.exit('لوحة %s#%d تحتاج %d رمزاً، وصل %d' % (split, sheet, expect, len(codes)))
    bad = [c for c in codes if c not in CLASSES]
    if bad:
        sys.exit('رموزٌ مجهولة: %s (المسموح h/l/m/u)' % ', '.join(sorted(set(bad))))
    os.makedirs(OUT, exist_ok=True)
    kept = []
    if os.path.exists(LABELS):
        with open(LABELS, encoding='utf-8') as f:
            kept = [json.loads(l) for l in f
                    if not (json.loads(l)['split'] == split
                            and base < json.loads(l)['i'] <= base + expect)]
    for k, c in enumerate(codes):
        r = sample[base + k]
        kept.append({'split': split, 'i': base + k + 1, 'book': r['book'],
                     'file': r['file'], 'label': r['label'], 'cls': CLASSES[c]})
    kept.sort(key=lambda x: (x['split'], x['i']))
    with open(LABELS, 'w', encoding='utf-8') as f:
        for x in kept:
            f.write(json.dumps(x, ensure_ascii=False) + '\n')
    c = collections.Counter(x['cls'] for x in kept if x['split'] == split)
    print('سُجّلت لوحة %s#%d — مجموع %s حتّى الآن: %s'
          % (split, sheet, split, dict(c)))


# ── (ب) القارئُ الحاليّ على الحجز ───────────────────────────────────────────
def run_reader():
    import onnxruntime as ort
    from PIL import Image
    from core.extraction.handwriting.reader import HandwrittenNumberReader

    so = ort.SessionOptions()
    so.intra_op_num_threads = 1          # خفيفٌ عمداً — الخانة الثقيلة مشغولة
    so.inter_op_num_threads = 1
    sess = ort.InferenceSession(
        os.path.join('var', 'models', 'handwritten_digits_crnn.onnx'), so,
        providers=['CPUExecutionProvider'])
    rd = HandwrittenNumberReader(session=sess)

    os.makedirs(OUT, exist_ok=True)
    sample = sample_of(load_rows(), 'holdout')
    with open(READS, 'w', encoding='utf-8') as f:
        for i, r in enumerate(sample, 1):
            im = Image.open(os.path.join(CROPS, r['file'])).convert('L')
            text, conf = rd.read_best(im)
            f.write(json.dumps({'i': i, 'book': r['book'], 'file': r['file'],
                                'label': r['label'], 'read': text or '',
                                'conf': round(float(conf), 4)},
                               ensure_ascii=False) + '\n')
            if i % 25 == 0:
                print('  ... %d/%d' % (i, len(sample)))
    print('كُتب %s' % READS)


# ── (ج) الحكم ───────────────────────────────────────────────────────────────
def _pct(a, b):
    return 100.0 * a / b if b else 0.0


def judge():
    if not os.path.exists(LABELS):
        sys.exit('لا تصنيفَ عينٍ بعد — شغّل sheets ثمّ label')
    with open(LABELS, encoding='utf-8') as f:
        labs = [json.loads(l) for l in f]
    by = {(x['split'], x['i']): x for x in labs}
    tr = [x for x in labs if x['split'] == 'train']
    ho = [x for x in labs if x['split'] == 'holdout']

    print('\n══ (أ) حصّةُ الأطقم بالعين ══')
    print('%-10s %6s %8s %8s %8s %8s' % ('الشقّ', 'العدّ', 'هنديّ', 'لاتينيّ',
                                          'مختلط', 'غامض'))
    shares = {}
    for name, grp in (('train', tr), ('holdout', ho)):
        c = collections.Counter(x['cls'] for x in grp)
        n = len(grp)
        shares[name] = {k: _pct(c[k], n) for k in
                        ('hindi', 'latin', 'mixed', 'unclear')}
        print('%-10s %6d %7.1f%% %7.1f%% %7.1f%% %7.1f%%'
              % (name, n, shares[name]['hindi'], shares[name]['latin'],
                 shares[name]['mixed'], shares[name]['unclear']))

    rows = None
    if os.path.exists(READS):
        with open(READS, encoding='utf-8') as f:
            rows = [json.loads(l) for l in f]

    stats = {}
    if rows and ho:
        print('\n══ (ب) أداءُ القارئ على الحجز بحسب الطقم ══')
        print('%-10s %6s %10s %12s %10s' % ('الفئة', 'العدّ', 'امتناع',
                                            'مطابقةٌ تامّة', 'وسطُ الثقة'))
        agg = collections.defaultdict(list)
        for r in rows:
            lab = by.get(('holdout', r['i']))
            if lab:
                agg[lab['cls']].append(r)
        for cls in ('hindi', 'latin', 'mixed', 'unclear'):
            g = agg.get(cls, [])
            if not g:
                continue
            n = len(g)
            ab = sum(1 for r in g if not r['read'])
            ex = sum(1 for r in g if r['read'] == r['label'])
            cf = [r['conf'] for r in g if r['read']]
            stats[cls] = {'n': n, 'abstain': _pct(ab, n), 'exact': _pct(ex, n),
                          'abstain_n': ab, 'exact_n': ex}
            print('%-10s %6d %7d %4.0f%% %8d %4.0f%% %9.3f'
                  % (cls, n, ab, stats[cls]['abstain'], ex, stats[cls]['exact'],
                     sum(cf) / len(cf) if cf else 0.0))
        n = len(rows)
        ab = sum(1 for r in rows if not r['read'])
        ex = sum(1 for r in rows if r['read'] == r['label'])
        print('%-10s %6d %7d %4.0f%% %8d %4.0f%%'
              % ('الكلّ', n, ab, _pct(ab, n), ex, _pct(ex, n)))

        # الصمتُ الفعليّ في الإنتاج: الامتناعُ الصريح + ما تحت البوّابة. القارئُ قد
        # يُخرج نصّاً ثمّ تبتلعه العتبة، فالطقمُ قد ينحاز عبر الثقة لا عبر الإصدار.
        print('\n   الصمتُ الفعليّ عند العتبات (نصٌّ فارغ أو ثقةٌ دون الحدّ):')
        print('   %-10s %10s %10s' % ('الفئة', '<0.65', '<0.90'))
        for cls in ('hindi', 'latin', 'mixed'):
            g = agg.get(cls, [])
            if not g:
                continue
            lo = sum(1 for r in g if not r['read'] or r['conf'] < 0.65)
            hi = sum(1 for r in g if not r['read'] or r['conf'] < CONF_GATE)
            print('   %-10s %6d %3.0f%% %6d %3.0f%%'
                  % (cls, lo, _pct(lo, len(g)), hi, _pct(hi, len(g))))

    # ── الحكم بالعتبات المُسجَّلة ──
    print('\n══ (ج) الحكم ══')
    h, l = stats.get('hindi'), stats.get('latin')
    conds = []
    share = shares.get('train', {}).get('hindi')
    if share is not None:
        conds.append(('① حصّةُ الهنديّة في التدريب ≤ %.0f%%' % T_SHARE,
                      share <= T_SHARE, '%.1f%%' % share))
    if h and l:
        ratio = (h['abstain'] / l['abstain']) if l['abstain'] else (
            float('inf') if h['abstain'] else 0.0)
        conds.append(('② امتناع(هنديّ) ≥ %.0f× امتناع(لاتينيّ)' % T_ABSTAIN_RATIO,
                      ratio >= T_ABSTAIN_RATIO,
                      '%.1f%% مقابل %.1f%% (×%.2f)'
                      % (h['abstain'], l['abstain'], ratio)))
        gap = l['exact'] - h['exact']
        conds.append(('③ تامّ(هنديّ) ≤ تامّ(لاتينيّ) − %.0f نقطة' % T_EXACT_GAP,
                      gap >= T_EXACT_GAP,
                      '%.1f%% مقابل %.1f%% (فارق %.1f نقطة)'
                      % (h['exact'], l['exact'], gap)))
    for name, ok, val in conds:
        print('  [%s] %s  ⟵ %s' % ('✓' if ok else '✗', name, val))
    met = sum(1 for _, ok, _ in conds if ok)
    if not conds:
        verdict = 'لا حكم — تصنيفٌ ناقص'
    elif met == len(conds) == 3:
        verdict = '**منحاز** — الشروط الثلاثة تحقّقت ⟵ T2.5 برفع وزن الهنديّة 45–50%'
    elif met == 0:
        verdict = '**غير منحاز** — لم يتحقّق أيُّ شرط'
    else:
        verdict = '**نتيجةٌ مختلطة** — تحقّق %d من %d' % (met, len(conds))
    print('\nالحكم: %s' % verdict)

    # ── حصادُ الهنديّة المتاح في كامل شقّ التدريب ──
    if tr:
        allrows = load_rows()
        n_train = sum(1 for r in allrows if split_of(r['book']) == 'train')
        p = shares['train']['hindi'] / 100.0
        n = len(tr)
        se = (p * (1 - p) / n) ** 0.5 if n else 0.0
        est = p * n_train
        lo, hi = max(0.0, p - 1.96 * se) * n_train, min(1.0, p + 1.96 * se) * n_train
        print('\n══ الهنديّةُ المتاحة في كامل مانيفست التدريب ══')
        print('صفوفُ التدريب: %d · الحصّةُ المقيسة %.1f%% (n=%d)'
              % (n_train, shares['train']['hindi'], n))
        print('تقديرٌ: %.0f قصاصةً هنديّة  [مجالُ ثقة 95%%: %.0f – %.0f]'
              % (est, lo, hi))
        print('الحدُّ المُسجَّل %d ⟵ %s' % (
            T_HARVEST_FLOOR,
            'يكفي لإعادة الترجيح' if lo >= T_HARVEST_FLOOR else
            ('كافٍ على الأرجح (الحدُّ داخل المجال)' if hi >= T_HARVEST_FLOOR
             else 'لا يكفي — حصادٌ موجَّه')))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='mode', required=True)
    sub.add_parser('sheets')
    sub.add_parser('read')
    sub.add_parser('judge')
    p = sub.add_parser('label')
    p.add_argument('--split', required=True, choices=('train', 'holdout'))
    p.add_argument('--sheet', required=True, type=int)
    p.add_argument('--codes', required=True)
    a = ap.parse_args()
    if a.mode == 'sheets':
        build_sheets()
    elif a.mode == 'read':
        run_reader()
    elif a.mode == 'label':
        record_labels(a.split, a.sheet, a.codes)
    else:
        judge()


if __name__ == '__main__':
    main()
