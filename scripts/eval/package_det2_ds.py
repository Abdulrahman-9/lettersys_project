# -*- coding: utf-8 -*-
"""تعبئةُ عدّة تدريب **كاشف الصنفين** (0=عدد · 1=موضوع) لكاغل — رسمٌ ووسمٌ وضغط.

**صفرُ تدريبٍ وصفرُ رفع.** هذا السكربت يبني حزمةَ الرفع على القرص لا غير؛ الرفعُ
والتشغيل قرارُ المشرف.

المجموعة = **تقاطعُ** كتب صندوق العدد (`t24_ds`) وكتب صندوق الموضوع (`subj_boxes`)،
مطروحاً منها المجموعات المختومة. والتقاطعُ قرارٌ مُسجَّلٌ في `docs/EVAL_REGISTRY.md`
(«بوّابة عين صناديق الموضوع») **قبل** هذا السكربت، وسببُه بنيويّ لا اقتصاديّ: صفحةٌ
ينقصها أحدُ الصنفين تُعلّم النموذجَ **غياباً كاذباً** — يرى موضوعاً بلا وسمٍ فيتعلّم
كتمَه. اتّحادُ المجموعتين أكبر (10,908) لكنّه يسمّم الصنفين معاً.

العقود الصلبة (نفس أنبوب كاشف العدد حرفيّاً — لا وصفةَ رسمٍ جديدة):
- الرسم 175dpi خام RGB بسقف 3500، حرفيّاً كما في `harvest_dates._render`. انفصالُ
  توزيعِ التدريب عن الإنتاج هو بعينه كارثةُ الرماديّ/RGB التي كلّفتنا دورتَي تدريب.
- الصندوقان مُطبَّعان على **الصفحة الكاملة** في المانيفستَين معاً (عقد الهندسة في
  `core/extraction/handwriting/detector.py`)، ومقاساهما المرجعيّان **متطابقان على
  التقاطع كلّه** (مقيسٌ: 4,072/4,072) — فالوسمُ نسخٌ لا تحويل.
- الصورةُ المحفوظة **صفحةٌ كاملة** لا أعلى 55%. الكاشفُ الحاليّ دُرِّب على أعلى 55%
  (`TRAIN_CROP`)، وشحنُ الصفحة كاملةً يُبقي الخيارين مفتوحين: النواةُ تقصّ في مكانها
  إن أُريد (`TOP_CROP` في `det2.py`)، بينما القصُّ هنا لا يُستردّ. وسبعُ صفحاتٍ فقط
  من 4,072 يمتدّ صندوقُ موضوعها تحت 0.55 — فالقصُّ خيارٌ يُقاس، لا يُفترض.
- الاستئناف بمفتاح «حاولنا» لا «نجحنا» + صفُّ skip بسببٍ لكلّ إخفاق (درسُ الحلقة
  المقفلة في حصاد T2.4)، والمانيفست يُدفَق سطراً سطراً فالانقطاعُ لا يفسد.
- الحجز `md5(book) % 100 < 5` — نفسُه حرفيّاً في `harvest_t24.py` و`package_date_ds.py`
  و`det2.py`. الكتابُ الواحد يقع على ضفّةٍ واحدة أبداً.

**بنيةُ الحزمة (درسُ كاغل: ملفُّ zip واحدٌ لا آلافُ الملفّات):**

    det2_ds/                   المرحلةُ الوسيطة المُقيمة (تتراكم دفعةً بعد دفعة)
      images/<book>.jpg        صفحةٌ كاملة، RGB، جودة 85، الضلعُ الأطول 1280
      labels/<book>.txt        سطرٌ لكلّ صنف: `cls cx cy w h` مُطبَّعاً
      manifest.jsonl           {book, image, split}  ·  أو {book, skip}
    det2_upload/
      det2_ds.zip              images/ + labels/ + manifest.jsonl + pack_meta.json
      warm_start.pt            نسخةُ detB_best.pt — انطلاقةُ الكاشف الحاليّ الدافئة
      dataset-metadata.json    لـ`kaggle datasets create -p det2_upload`

الضغطُ لا يجري إلّا حين ينضب المتبقّي (أو بـ`--zip` صراحةً): ضغطُ آلاف الصور بعد كلّ
دفعةٍ عبثٌ، وحزمةٌ جزئيّةٌ في مجلّد الرفع فخُّ رفعٍ خاطئ (تُوسَم `partial` في pack_meta).

    python scripts/eval/package_det2_ds.py [--limit N] [--zip] [--out DIR]
"""
import argparse
import gc
import hashlib
import json
import os
import shutil
import sys
import zipfile

PROJ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJ)
os.chdir(PROJ)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lettersys.settings')
import django  # noqa: E402
django.setup()

from PIL import Image  # noqa: E402
from core.models import Book  # noqa: E402

BASE = r'D:\migration\lettersys_models'
T24_MANIFEST = os.path.join(BASE, 't24_ds', 'manifest.jsonl')
SUBJ_MANIFEST = os.path.join(BASE, 'subj_boxes', 'manifest.jsonl')
WARM_SRC = os.path.join(BASE, 'detB_best.pt')      # أوزانُ الكاشف الحاليّ (det-b)
STAGE = os.path.join(BASE, 'det2_ds')
IMGD = os.path.join(STAGE, 'images')
LBLD = os.path.join(STAGE, 'labels')
MANIFEST = os.path.join(STAGE, 'manifest.jsonl')
STATS = os.path.join(STAGE, 'stats.json')
DEFAULT_OUT = os.path.join(BASE, 'det2_upload')
KAGGLE_ID = 'abdualrhmanahmed/lettersys-det2-pages'

CLASSES = ('number', 'subject')     # 0, 1 — الترتيبُ عقدٌ مع `det2.py` و`detector.py`
LONG_SIDE = 1280                    # الضلعُ الأطول للصورة المحفوظة = مقاسُ تدريب الكاشف
JPEG_Q = 85
DIMS_TOL = 2                        # ±2 بكسل: فروقُ إصدارِ PyMuPDF لا تُبطل وسماً


def split_of(book_id):
    """هاشُ الحجز — **نفسُه حرفيّاً** في `harvest_t24.py` و`package_date_ds.py` و`det2.py`."""
    h = int(hashlib.md5(str(book_id).encode()).hexdigest()[:8], 16)
    return 'holdout' if (h % 100) < 5 else 'train'


def _sealed_books():
    """المجموعات المختومة — تُقرأ من مانيفستاتها لا من الذاكرة.

    منسوخةٌ حرفيّاً من `scripts/eval/harvest_dates.py`: هذه العدّة تُعيد تدريب صنف
    **العدد** أيضاً، فاستثناءُ كلّ ما سيُقاس عليه لاحقاً شرطُ صدقٍ لا احتياط.
    """
    ids = set()
    try:
        e = json.load(open(os.path.join(BASE, 'e2e_manifest.json'), encoding='utf-8'))
        for k in ('A', 'B', 'C'):
            ids |= set(e['sets'][k])
        ids |= set(json.load(open(os.path.join(BASE, 'subject_corpus',
                                              'subject200_manifest.json'),
                                  encoding='utf-8'))['books'])
        ids |= set(json.load(open(os.path.join(BASE, 'clean_pool.json'), encoding='utf-8')))
        ids |= set(json.load(open(os.path.join(BASE, 'noise100_books.json'), encoding='utf-8')))
        ids |= {r['book'] for r in json.load(open(os.path.join(BASE, 'subject_corpus',
                                                              'corpus.json'), encoding='utf-8'))}
    except Exception as exc:
        raise SystemExit('مانيفست مختومٌ مفقود (%s) — لا حصاد بلا استثناءات' % type(exc).__name__)
    return ids


def _boxes(path, what):
    """{الكتاب: (صندوقٌ مُطبَّع، مقاسٌ مرجعيّ)} — أوّلُ صفٍّ يفوز.

    المانيفست مُلحَقٌ دفعةً بعد دفعة وفيه تكرارٌ مقيس (97 صفّاً في `t24_ds`)؛
    «الأوّلُ يفوز» هو نفسُ اختيار `package_date_ds.py` فلا تتبدّل المجموعةُ بينهما.
    """
    if not os.path.exists(path):
        raise SystemExit('مانيفست %s مفقود — لا مصدرَ للصناديق' % what)
    out = {}
    for line in open(path, encoding='utf-8'):
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        if 'skip' in d or 'box' not in d or not d.get('dims'):
            continue
        out.setdefault(d['book'], (d['box'], d['dims']))
    return out


def _render(path):
    """الرسمُ بوصفة الإنتاج حرفيّاً: خام RGB بـ175dpi وسقفُ 3500 على الضلع الأطول."""
    if path.lower().endswith('.pdf'):
        import fitz
        doc = fitz.open(path)
        try:
            page = doc[0]
            z = 175 / 72.0
            lo = max(page.rect.width, page.rect.height) * z
            if lo > 3500:
                z *= 3500 / lo
            px = page.get_pixmap(matrix=fitz.Matrix(z, z))
            return Image.frombytes('RGB', (px.width, px.height), px.samples)
        finally:
            doc.close()
    return Image.open(path).convert('RGB')


def _yolo_line(cls, box):
    """`cls cx cy w h` مُطبَّعاً — أو None لصندوقٍ منهار.

    الصندوقُ الوارد `[x0, y0, x1, y1]` مُطبَّعٌ على الصفحة الكاملة، والصورةُ المحفوظة
    هي الصفحةُ الكاملة مُصغَّرةً بنسبةٍ محفوظة — فالتطبيعُ ينتقل كما هو بلا حساب.
    """
    x0, y0, x1, y1 = (max(0.0, min(1.0, float(v))) for v in box)
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0
    w, h = x1 - x0, y1 - y0
    if w <= 1e-4 or h <= 1e-4:
        return None
    return '%d %.6f %.6f %.6f %.6f' % (cls, (x0 + x1) / 2, (y0 + y1) / 2, w, h)


def _dims_ok(got, ref):
    """المقاسُ المرسوم يطابق المرجعيّ ±2 بكسل.

    الصندوقُ مُطبَّعٌ فلا يضيره تحجيمٌ منتظم؛ لكنّ اختلافَ المقاس بأكثر من هامشِ
    الإصدار يعني أنّ **المرفق تبدّل** تحت الوسم — وذاك وسمٌ ميّت يجب أن يُطرح لا
    أن يُدرَّب عليه.
    """
    return abs(got[0] - ref[0]) <= DIMS_TOL and abs(got[1] - ref[1]) <= DIMS_TOL


def _human(n):
    return '%.1f ميغابايت' % (n / 1048576.0)


def _pack(out, rows_n, partial):
    """يجمع المرحلةَ الوسيطة في zip واحدٍ داخل مجلّد الرفع + ميتاداتا + انطلاقةٌ دافئة."""
    os.makedirs(out, exist_ok=True)
    meta = {'classes': list(CLASSES), 'rows': rows_n['total'],
            'train': rows_n['train'], 'holdout': rows_n['holdout'],
            'geometry': 'full page, RGB 175dpi cap3500, long side %d, JPEG q%d'
                        % (LONG_SIDE, JPEG_Q),
            'box_space': 'normalized to FULL page (detector.py contract)',
            'source_manifests': [T24_MANIFEST, SUBJ_MANIFEST],
            'membership': 'intersection(t24_ds, subj_boxes) minus sealed sets',
            'split_rule': 'md5(book)%100 < 5 -> holdout',
            'partial': bool(partial)}
    json.dump(meta, open(os.path.join(STAGE, 'pack_meta.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)

    zpath = os.path.join(out, 'det2_ds.zip')
    with zipfile.ZipFile(zpath, 'w', zipfile.ZIP_DEFLATED) as z:
        for root, _dirs, files in os.walk(STAGE):
            for fn in sorted(files):
                if fn == 'stats.json':
                    continue
                full = os.path.join(root, fn)
                arc = os.path.relpath(full, STAGE).replace(os.sep, '/')
                # JPEG مضغوطٌ سلفاً: الترميزُ المخزون يوفّر دقائق ولا يكلّف بايتات.
                z.write(full, arc,
                        compress_type=zipfile.ZIP_STORED if fn.lower().endswith('.jpg')
                        else zipfile.ZIP_DEFLATED)
    sha = hashlib.sha256()
    with open(zpath, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            sha.update(chunk)
    json.dump({'title': KAGGLE_ID.split('/')[1], 'id': KAGGLE_ID,
               'licenses': [{'name': 'CC0-1.0'}]},
              open(os.path.join(out, 'dataset-metadata.json'), 'w', encoding='utf-8'))
    warm = None
    if os.path.exists(WARM_SRC):
        warm = os.path.join(out, 'warm_start.pt')
        shutil.copy2(WARM_SRC, warm)
    return zpath, sha.hexdigest(), warm


def main():
    ap = argparse.ArgumentParser(description='تعبئةُ عدّة كاشف الصنفين — رسمٌ ووسمٌ وضغط')
    ap.add_argument('--limit', type=int, default=0,
                    help='حدُّ الدفعة (0 = كلُّ المتبقّي)؛ استعمله للدخان')
    ap.add_argument('--zip', action='store_true',
                    help='اضغط ولو بقي متبقٍّ (الحزمةُ تُوسَم partial)')
    ap.add_argument('--out', default=DEFAULT_OUT, help='مجلّدُ الرفع')
    a = ap.parse_args()

    os.makedirs(IMGD, exist_ok=True)
    os.makedirs(LBLD, exist_ok=True)

    sealed = _sealed_books()
    num = _boxes(T24_MANIFEST, 't24_ds')
    subj = _boxes(SUBJ_MANIFEST, 'subj_boxes')
    pool = sorted((set(num) & set(subj)) - sealed)

    # مفتاحُ الاستئناف «حاولنا لا نجحنا» — يُسجَّل الصفّ ولو أخفق، بسببه.
    attempted, done = set(), {'train': 0, 'holdout': 0}
    if os.path.exists(MANIFEST):
        for line in open(MANIFEST, encoding='utf-8'):
            try:
                r = json.loads(line)
            except Exception:
                continue
            attempted.add(r['book'])
            if 'skip' not in r:
                done[r['split']] = done.get(r['split'], 0) + 1

    todo = [b for b in pool if b not in attempted]
    if a.limit:
        todo = todo[:a.limit]
    print('عددٌ %d · موضوعٌ %d · مختومٌ %d ⟵ التقاطع %d · حوولوا %d · هذه الدفعة %d'
          % (len(num), len(subj), len(sealed), len(pool), len(attempted), len(todo)),
          flush=True)

    kept = no_file = drift = bad_box = failed = 0
    with open(MANIFEST, 'a', encoding='utf-8') as mf:
        for bid in todo:
            def _skip(reason):
                mf.write(json.dumps({'book': bid, 'skip': reason}, ensure_ascii=False) + '\n')
                mf.flush()

            b = Book.objects.filter(id=bid).first()
            att = b.attachments.first() if b else None
            p = att.file.path if (att and hasattr(att.file, 'path')) else None
            if not (p and os.path.exists(p)):
                no_file += 1
                _skip('no_file')
                continue
            try:
                nbox, nref = num[bid]
                sbox, sref = subj[bid]
                im = _render(p)
                W, H = im.size
                if not (_dims_ok((W, H), nref) and _dims_ok((W, H), sref)):
                    del im
                    drift += 1
                    _skip('dims_drift:%dx%d vs %s/%s' % (W, H, nref, sref))
                    continue
                lines = [ln for ln in (_yolo_line(0, nbox), _yolo_line(1, sbox)) if ln]
                if len(lines) < 2:
                    del im
                    bad_box += 1
                    _skip('bad_box')
                    continue
                scale = LONG_SIDE / float(max(W, H))
                if scale < 1.0:      # تصغيرٌ فقط — تكبيرُ صفحةٍ صغيرة بايتاتٌ بلا معلومة
                    im = im.resize((max(1, int(round(W * scale))),
                                    max(1, int(round(H * scale)))), Image.LANCZOS)
                name = '%d.jpg' % bid
                ipath = os.path.join(IMGD, name)
                im.save(ipath, 'JPEG', quality=JPEG_Q)
                del im
                # **تحقّقٌ بعد الكتابة** — كتابةٌ انقطعت تُخلّف ملفّاً بحجمٍ معقول
                # لا يُفتَح، فيموت التدريبُ بعد رفعِ مئات الميغابايتات (وقع فعلاً:
                # 7 صورٍ تالفة أسقطت نواة det2 عند الصورة 9061 بعد رفعٍ كامل).
                try:
                    with Image.open(ipath) as _v:
                        _v.verify()
                except Exception:
                    os.remove(ipath)
                    lbl = os.path.join(LBLD, '%d.txt' % bid)
                    if os.path.exists(lbl):
                        os.remove(lbl)
                    _skip('corrupt_write')
                    continue
                with open(os.path.join(LBLD, '%d.txt' % bid), 'w', encoding='utf-8') as lf:
                    lf.write('\n'.join(lines) + '\n')
                sp = split_of(bid)
                mf.write(json.dumps({'book': bid, 'image': 'images/' + name, 'split': sp},
                                    ensure_ascii=False) + '\n')
                mf.flush()
                done[sp] = done.get(sp, 0) + 1
                kept += 1
            except Exception as exc:
                failed += 1
                _skip('error:%s' % type(exc).__name__)
                print('  %s: %s' % (bid, type(exc).__name__), flush=True)
            gc.collect()

    remaining = len(pool) - len(attempted) - len(todo)
    total = done['train'] + done['holdout']
    print('حُفظ %d · بلا ملفّ %d · مقاسٌ منجرف %d · صندوقٌ منهار %d · خطأ %d'
          % (kept, no_file, drift, bad_box, failed), flush=True)
    print('المجموع المحفوظ %d (تدريب %d · حجز %d = %.1f%%) · المتبقّي %d'
          % (total, done['train'], done['holdout'],
             100.0 * done['holdout'] / max(1, total), remaining), flush=True)
    json.dump({'pool': len(pool), 'kept_total': total, 'train': done['train'],
               'holdout': done['holdout'], 'no_file': no_file, 'dims_drift': drift,
               'bad_box': bad_box, 'error': failed, 'remaining': remaining},
              open(STATS, 'w', encoding='utf-8'))

    if total and (remaining == 0 or a.zip):
        zpath, sha, warm = _pack(a.out, {'total': total, 'train': done['train'],
                                         'holdout': done['holdout']}, remaining > 0)
        print('الحزمة: %s%s' % (os.path.abspath(a.out),
                                ' [جزئيّةٌ للفحص لا للرفع]' if remaining else ''))
        print('  det2_ds.zip = %s · sha256 %s' % (_human(os.path.getsize(zpath)), sha[:16]))
        if warm:
            print('  warm_start.pt = %s (من %s)' % (_human(os.path.getsize(warm)), WARM_SRC))
        else:
            print('  بلا warm_start.pt — %s مفقود (النواةُ تسقط إلى yolov8n)' % WARM_SRC)
        if remaining == 0:
            print('  الرفع (بأمر المشرف لا هنا): kaggle datasets create -p "%s"'
                  % os.path.abspath(a.out))
    elif remaining:
        print('لا ضغطَ قبل النضوب (المتبقّي %d) — أعد التشغيل، أو --zip لحزمةٍ جزئيّة'
              % remaining)


if __name__ == '__main__':
    sys.exit(main())
