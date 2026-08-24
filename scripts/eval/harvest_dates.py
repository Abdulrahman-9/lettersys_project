# -*- coding: utf-8 -*-
"""حصادُ قصاصات التاريخ (المسار D، مرحلة D1) — بصفر كشفٍ وصفر GPU.

البروتوكول والبوّابات مُسجَّلةٌ في `docs/EVAL_REGISTRY.md` قسم «خطّة قارئ التاريخ
(المسار D)» **قبل** هذا السكربت. وهذه بنودُه حرفيّاً:

1. **لا إعادةَ كشف** — صندوق العدد يُقرأ من مانيفست `t24_ds` المحصود سلفاً (مُطبَّع
   للصفحة الكاملة مع مقاسٍ مرجعيّ). قصاصةُ التاريخ تُشتقّ منه هندسيّاً. الفائدة
   ليست السرعة وحدها: الصندوق نفسُه الذي دُرِّب عليه قارئُ العدد ⇒ توزيعٌ واحد.
2. **مسارُ الرسم الإنتاجيّ نفسه** — خام RGB بـ175dpi وسقفٌ 3500 على الضلع الأطول،
   حرفيّاً كما في `harvest_t24.py`. انفصالُ توزيعِ التدريب عن الإنتاج هو بعينه
   كارثةُ الرماديّ/RGB التي كلّفتنا دورتَي تدريب.
3. **هندسةُ القصاصة مُعاملٌ يُقاس لا يُفترض** — يُخرَج لكلّ كتابٍ **ثلاثُ** قصاصات
   (ضيّقة/وسط/سخيّة) وبوّابةُ العين D1 هي التي تختار. السخيّةُ الحاليّة في الواجهة
   مصمَّمةٌ للعين البشريّة لا للقارئ، فلا تصلح افتراضاً.
4. **استثناءاتٌ بالكتاب مفروضةٌ هنا لا بالنيّة**: e2e-A/B/C · subject-200 ·
   الـ276 · noise-100 · corpus-40.
5. صفّ `_skip` بسببٍ لكلّ إخفاق، ودفقُ المانيفست سطراً سطراً — الانقطاعُ لا يفسد،
   وأقصى ضررٍ إعادةُ كتبٍ قليلة. ومفتاحُ الاستئناف «حاولنا» لا «نجحنا»، وإلّا دارت
   الكتبُ المرفوضة في حلقةٍ مقفلة كلَّ دفعة (وقعت في حصاد T2.4).

**الوسم — موحَّدٌ بعد هجرة المبادلة 0060 (2026-08-23):**
انقلابُ عمودَي التاريخ في الوارد المستورد اكتُشف (D0) وأُكّد عدائيّاً ثمّ **صُوِّب
جذريّاً**: هجرةُ 0060 بادلت العمودين لـ11,048 صفّاً وأُصلح تعيينُ الاستيراد نفسُه
(`_legacy_dates`). فالدلالة الآن مستقيمةٌ في القاعدة كلّها بلا استثناء:
`sender_date` = حبرُ الجهة (الوسم) و`date` = تاريخُ قيدنا، والفارق
`date − sender_date` = زمنُ الوصول (موجبٌ 92.5%، وسيطُه +3).
`label` = `sender_date` دوماً، وبوّابةُ العين n=100 تصادق على مطابقة الحبر ≥85%
قبل أيّ تدريب. التفاصيل والأدلّة في سجلّ التقييم قسم D.

    python scripts/eval/harvest_dates.py [عدد الكتب في الدفعة]
"""
import datetime
import gc
import json
import os
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJ)
os.chdir(PROJ)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lettersys.settings')
import django  # noqa: E402
django.setup()

from django.utils import timezone  # noqa: E402
from PIL import Image  # noqa: E402
from core.models import Book  # noqa: E402

BASE = r'D:\migration\lettersys_models'
T24_MANIFEST = os.path.join(BASE, 't24_ds', 'manifest.jsonl')
OUT = os.path.join(BASE, 'date_ds')
IMGD = os.path.join(OUT, 'crops')
MANIFEST = os.path.join(OUT, 'manifest.jsonl')
STATS = os.path.join(OUT, 'stats.json')
os.makedirs(IMGD, exist_ok=True)
CHUNK = int(sys.argv[1]) if len(sys.argv) > 1 else 50

FIX_DATE = datetime.date(2026, 8, 19)   # إيداع 978ccdf — إزالةُ ملء «اليوم» التلقائيّ
MAX_DELTA = 45                          # حارسُ الفارق المُسجَّل (الختم يلي الجهة، لا يسبقها)

# ── هندساتُ القصاصة الثلاث تحت صندوق العدد ──────────────────────────────────
# (لاحقة، مُعامل التمدّد الأفقيّ ×عرض الصندوق، بدءُ الرأسيّ، نهايةُ الرأسيّ ×ارتفاعه)
# لا يُنتخَب أيٌّ منها هنا: الاختيار لبوّابة العين في D1، والقيمةُ الفائزة تُثبَّت
# عندها في الحصاد ومسار القراءة الإنتاجيّ **معاً في إيداعٍ واحد**.
GEOMS = (
    ('n', 0.5, 0.1, 1.6),    # ضيّقة
    ('m', 1.0, 0.1, 2.2),    # وسط
    ('w', 2.0, 0.1, 3.2),    # سخيّة
    # 'x' سُجّلت 2026-08-24 **قبل** رؤية أيّ نتيجةٍ لها، علاجاً لعطبَي العين المقيسَين
    # في m (بتر أعلى السطر الملاصق لأسفل العدد ⟵ البدء داخل الصندوق قليلاً −0.2،
    # وبتر السنة أفقيّاً ⟵ ±2.0) مع سقفٍ سفليّ +2.4 يُبقي حلقة الختم خارجاً غالباً.
    ('x', 2.0, -0.2, 2.4),
)


def _sealed_books():
    """المجموعات المختومة — تُقرأ من مانيفستاتها لا من الذاكرة."""
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


def _t24_boxes():
    """صناديقُ العدد المحصودة سلفاً: {الكتاب: (صندوقٌ مُطبَّع، مقاسٌ مرجعيّ)}."""
    boxes = {}
    if not os.path.exists(T24_MANIFEST):
        raise SystemExit('مانيفست t24_ds مفقود — لا مصدرَ للصناديق')
    for line in open(T24_MANIFEST, encoding='utf-8'):
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        if 'skip' in d or 'box' not in d:
            continue
        boxes[d['book']] = (d['box'], d.get('dims'))
    return boxes


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


def _crop_box(box, W, H, ext, top, bot):
    """قصاصةٌ تحت الصندوق: تمدّدٌ أفقيّ ext×عرضه، ورأسيّاً من +top إلى +bot ×ارتفاعه."""
    x0, y0, x1, y1 = box
    bw, bh = (x1 - x0), (y1 - y0)
    px0 = max(0, int((x0 - ext * bw) * W))
    px1 = min(W, int((x1 + ext * bw) * W))
    py0 = max(0, int((y1 + top * bh) * H))
    py1 = min(H, int((y1 + bot * bh) * H))
    return px0, py0, px1, py1


sealed = _sealed_books()
boxes = _t24_boxes()

# مفتاحُ الاستئناف «حاولنا لا نجحنا» — يُسجَّل الصفّ ولو أخفق، بسببه.
attempted = set()
if os.path.exists(MANIFEST):
    for line in open(MANIFEST, encoding='utf-8'):
        try:
            attempted.add(json.loads(line)['book'])
        except Exception:
            pass

# ── المجمّعان (دلالة ما بعد هجرة 0060: sender_date=الحبر · date=قيدُنا) ──────
# 'clean'    — كاتبيٌّ (source_ref فارغ) بعد إصلاح الافتراضيّ (978ccdf). (مقيسٌ
#              صفراً حتّى 2026-08-23 — الفرع للتراكم القادم.)
# 'filtered' — مستورَدٌ بحارس الفارق: 0 < قيدُنا(date) − حبرُ الجهة(sender_date)
#              ≤ 45 يوماً.
#
# **فخّان مقيسان (D0):** `created_at` لصفٍّ مستورد هو زمنُ الاستيراد (دفعةُ 2,037
# صفّاً هبطت في 17 دقيقة يوم 2026-08-19) فلا يصلح مرجعاً زمنيّاً؛ والكاتبيُّ قبل
# الإصلاح مسمومٌ بافتراضيّ «اليوم» فلا يدخل أصلاً. حارسُ الفارق يستبعد أيضاً
# صفوف الفارق صفر (7.2%) والسالب (0.3%) كما سُجّل — لا توسيعَ بعد النظر.
pool_of, delta_of, clerk_of = {}, {}, {}
rows = (Book.objects.filter(is_deleted=False, sender_date__isnull=False,
                            attachments__isnull=False)
        .exclude(id__in=sealed)
        .values_list('id', 'date', 'sender_date', 'created_at', 'source_ref').distinct())
for bid, bdate, sdate, created, sref in rows:
    if bid not in boxes:
        continue
    clerk = not (sref or '').strip()
    if clerk:
        if timezone.localtime(created).date() < FIX_DATE:
            continue                      # كاتبيٌّ قبل الإصلاح = وسمٌ مسموم
        pool_of[bid] = 'clean'
        delta_of[bid] = (bdate - sdate).days if bdate else None
    else:
        if bdate is None:
            continue
        delta = (bdate - sdate).days      # قيدُنا − حبرُ الجهة = زمنُ الوصول
        if not (0 < delta <= MAX_DELTA):
            continue
        pool_of[bid], delta_of[bid] = 'filtered', delta
    clerk_of[bid] = clerk

todo = sorted(b for b in pool_of if b not in attempted)[:CHUNK]
print('مؤهَّلون %d (نظيف %d منها كاتبيٌّ %d · مرشَّح %d) · منجَز %d · هذه الدفعة %d'
      % (len(pool_of), sum(1 for v in pool_of.values() if v == 'clean'),
         sum(1 for b, v in pool_of.items() if v == 'clean' and clerk_of[b]),
         sum(1 for v in pool_of.values() if v == 'filtered'), len(attempted), len(todo)),
      flush=True)

kept = no_file = tiny = failed = 0
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
            im = _render(p)
            W, H = im.size
            gray = im.convert('L')
            del im
            box, ref_dims = boxes[bid]
            files, small = {}, []
            for tag, ext, top, bot in GEOMS:
                px0, py0, px1, py1 = _crop_box(box, W, H, ext, top, bot)
                if (px1 - px0) < 20 or (py1 - py0) < 10:
                    small.append(tag)
                    continue
                name = '%d_%s.png' % (bid, tag)
                gray.crop((px0, py0, px1, py1)).save(os.path.join(IMGD, name))
                files[tag] = name
            del gray
            if not files:
                tiny += 1
                _skip('tiny_crop')
                continue
            mf.write(json.dumps({
                'book': bid,
                'files': files,
                # الدلالة موحَّدةٌ بعد هجرة 0060: sender_date هو الحبر دوماً.
                'label': b.sender_date.isoformat(),
                'db_date': b.date.isoformat() if b.date else None,
                'db_sender_date': b.sender_date.isoformat(),
                'stamp_minus_doc': (b.date - b.sender_date).days if b.date else None,
                'delta_days': delta_of[bid],
                'pool': pool_of[bid],
                'clerk': clerk_of[bid],   # source_ref فارغ ⇒ إدخالُ كاتبٍ لا استيراد
                'kind': b.kind,
                'box': [round(v, 4) for v in box],
                'dims': [W, H],
                'ref_dims': ref_dims,
                'dims_match': (list(ref_dims) == [W, H]) if ref_dims else None,
                'tiny': small or None,
            }, ensure_ascii=False) + '\n')
            mf.flush()
            kept += 1
        except Exception as exc:
            failed += 1
            _skip('error:%s' % type(exc).__name__)
            print('  %s: %s' % (bid, type(exc).__name__), flush=True)
        gc.collect()

total = sum(1 for _ in open(MANIFEST, encoding='utf-8')) if os.path.exists(MANIFEST) else 0
print('حُفظ %d · بلا ملفّ %d · قصاصةٌ ضئيلة %d · خطأ %d · المجموع %d'
      % (kept, no_file, tiny, failed, total), flush=True)
json.dump({'total': total, 'kept': kept, 'no_file': no_file, 'tiny_crop': tiny,
           'error': failed, 'geoms': [g[0] for g in GEOMS]},
          open(STATS, 'w', encoding='utf-8'))
