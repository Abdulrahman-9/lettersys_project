# -*- coding: utf-8 -*-
"""حصادُ T2.4: أزواج (قصاصةُ الكاشف ← عددُ الكاتب) من القاعدة، بصفر GPU.

البروتوكول مُسجَّلٌ في `docs/EVAL_REGISTRY.md` **قبل** هذا السكربت، وهذه بنوده حرفيّاً:

1. **مسار التغذية الإنتاجيّ نفسه** — `_detector_box_from_file` (خام RGB بـ175dpi
   ومقاسٌ مرجعيّ). لا سكربتَ رسمٍ خاصّاً: انفصالُ توزيعِ التدريب عن الإنتاج هو بعينه
   كارثةُ الرماديّ/RGB التي كلّفتنا دورتَي تدريب.
2. **لا تبويبَ باتّفاق القارئ إطلاقاً** — التبويب على ثقة الكاشف وحدها، وتُسجَّل مع
   كلّ زوج. التبويب بالاتّفاق هو ما أفسد وسومَ تدريبَين: بوّب النصّ لا الصندوق فانحاز
   لما يُتقنه النموذج أصلاً.
3. **استثناءاتٌ بالكتاب مفروضةٌ هنا لا بالنيّة**: e2e-A/B/C · subject-200 · الـ276.
4. تطبيعٌ مُعلَن: عربيّة‑هنديّة ⟵ لاتينيّة، وتُقبل القيم الرقميّة الصرفة 1–6 خانات.
5. حجزٌ **بالكتاب** ~5% (قسمةُ الهاش، حتميّة) — لا بالقصاصة، وإلّا تسرّبت صفحةٌ إلى
   قسمَيها معاً.

    python scripts/eval/harvest_t24.py [عدد الكتب في الدفعة]
"""
import gc
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

from PIL import Image  # noqa: E402
from core.extraction.pipeline import AIExtractionService  # noqa: E402
from core.models import Book  # noqa: E402

OUT = r'D:\migration\lettersys_models\t24_ds'
IMGD = os.path.join(OUT, 'crops')
MANIFEST = os.path.join(OUT, 'manifest.jsonl')
STATS = os.path.join(OUT, 'stats.json')
os.makedirs(IMGD, exist_ok=True)
CHUNK = int(sys.argv[1]) if len(sys.argv) > 1 else 50
HOLDOUT_PCT = 5
# **صفرُ حشوٍ — الصندوق بالضبط.** مقيسٌ على عيّنتين مستقلّتين من القصاصات المحصودة
# (نفس الصناديق، قصٌّ مُشتَقّ، بلا إعادة كشفٍ ولا GPU):
#     الحشو        عيّنة 1 (n=120)   عيّنة 2 (n=200)
#     0.30/0.40         45.0%            51.5%      ⟵ الموروث من مسار الإصدار المُغلَق
#     0.00/0.10         65.8%            62.5%
#     **0.00/0.00**       —              **66.5%**
#     -0.08/0.00          —               27.5%     ⟵ القصّ داخل الصندوق ينهار
# أي **+15 إلى +21 نقطة مطابقةٍ تامّة بالتضييق وحده**. والسبب بنيويّ: الكاشف مُدرَّبٌ
# ليُنتج صندوقاً ضيّقاً حول الرقم، والحشو يُدخل رمزَ السجلّ («ش4/»، «حرب/») والحبرَ
# المجاور فيحاول قارئُ الأرقام تفسيرها. وانهيارُ القصّ السالب يُثبت أنّ الصندوق مضبوط.
# **قاعدة**: هذه القيمة وقيمةُ مسار القراءة الإنتاجيّ تتحرّكان معاً في إيداعٍ واحد —
# انفصالُ توزيعِ التدريب عن الإنتاج هو صنفُ كارثة الرماديّ/RGB.
PAD_X, PAD_Y = 0.0, 0.0
_ARD = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')


def norm(v):
    return ''.join(c for c in str(v or '').translate(_ARD) if c.isdigit())


def _sealed_books():
    """المجموعات المختومة — تُقرأ من مانيفستاتها لا من الذاكرة."""
    base = r'D:\migration\lettersys_models'
    ids = set()
    try:
        e = json.load(open(os.path.join(base, 'e2e_manifest.json'), encoding='utf-8'))
        for k in ('A', 'B', 'C'):
            ids |= set(e['sets'][k])
    except Exception:
        raise SystemExit('مانيفست e2e مفقود — لا حصاد بلا استثناءات')
    try:
        ids |= set(json.load(open(os.path.join(base, 'subject_corpus', 'subject200_manifest.json'),
                                  encoding='utf-8'))['books'])
        ids |= set(json.load(open(os.path.join(base, 'clean_pool.json'), encoding='utf-8')))
        ids |= {r['book'] for r in json.load(open(os.path.join(base, 'subject_corpus', 'corpus.json'),
                                                  encoding='utf-8'))}
    except Exception as exc:
        raise SystemExit('مانيفست مختومٌ مفقود (%s) — لا حصاد' % type(exc).__name__)
    return ids


def split_of(book_id):
    """حجزٌ بالكتاب لا بالقصاصة، حتميٌّ بالهاش."""
    h = int(hashlib.md5(str(book_id).encode()).hexdigest()[:8], 16)
    return 'holdout' if (h % 100) < HOLDOUT_PCT else 'train'


sealed = _sealed_books()
# **مفتاح الاستئناف «حوولت» لا «نجحت»** — أوّل صياغةٍ سجّلت النجاحات وحدها، فبقيت
# الكتبُ المرفوضة (بلا صندوق) خارج `done` وأُعيدت محاولتها كلّ دفعة: حلقةٌ مقفلة
# طبعت «حُفظ 0» ستّ مرّاتٍ متتالية وتوقّف التقدّم عند 242. تُسجَّل المحاولةُ الآن
# ولو فشلت، بسببها، فيتقدّم الحصاد ويبقى سجلُّ الرفض قابلاً للتدقيق.
attempted = set()
if os.path.exists(MANIFEST):
    for line in open(MANIFEST, encoding='utf-8'):
        try:
            attempted.add(json.loads(line)['book'])
        except Exception:
            pass
done = attempted

inc = ('incoming_internal', 'incoming_external')
qs = (Book.objects.filter(kind__in=inc, is_deleted=False, attachments__isnull=False)
      .exclude(sender_number='').exclude(sender_number=None)
      .exclude(id__in=sealed).order_by('id').distinct())
todo = [b for b in qs.values_list('id', 'sender_number') if b[0] not in done][:CHUNK]
print('مؤهَّلون %d · منجَز %d · هذه الدفعة %d' % (qs.count(), len(done), len(todo)), flush=True)

svc = AIExtractionService()
kept = no_box = bad_val = no_file = 0
with open(MANIFEST, 'a', encoding='utf-8') as mf:
    for bid, raw_val in todo:
        def _skip(reason):
            mf.write(json.dumps({'book': bid, 'skip': reason}, ensure_ascii=False) + chr(10))
            mf.flush()

        val = norm(raw_val)
        if not (1 <= len(val) <= 6):
            bad_val += 1
            _skip('bad_value')
            continue
        b = Book.objects.filter(id=bid).first()
        att = b.attachments.first() if b else None
        p = att.file.path if (att and hasattr(att.file, 'path')) else None
        if not (p and os.path.exists(p)):
            no_file += 1
            _skip('no_file')
            continue
        try:
            box = svc._detector_box_from_file(p)      # مسار الإنتاج حرفيّاً
            if not box:
                no_box += 1
                _skip('no_box')
                continue
            import fitz
            if p.lower().endswith('.pdf'):
                d = fitz.open(p)
                pg = d[0]
                z = 175 / 72.0
                lo = max(pg.rect.width, pg.rect.height) * z
                if lo > 3500:
                    z *= 3500 / lo
                px = pg.get_pixmap(matrix=fitz.Matrix(z, z))
                im = Image.frombytes('RGB', (px.width, px.height), px.samples)
                d.close()
            else:
                im = Image.open(p).convert('RGB')
            W, H = im.size
            x0, y0, x1, y1 = box
            ex, ey = PAD_X * (x1 - x0), PAD_Y * (y1 - y0)
            crop = im.convert('L').crop((max(0, int((x0 - ex) * W)), max(0, int((y0 - ey) * H)),
                                         min(W, int((x1 + ex) * W)), min(H, int((y1 + ey) * H))))
            del im
            if crop.width < 20 or crop.height < 10:
                no_box += 1
                del crop
                _skip('tiny_crop')
                continue
            name = '%d.png' % bid
            crop.save(os.path.join(IMGD, name))
            del crop
            mf.write(json.dumps({'book': bid, 'file': name, 'label': val,
                                 'box': [round(v, 4) for v in box], 'dims': [W, H],
                                 'split': split_of(bid)}, ensure_ascii=False) + '\n')
            mf.flush()
            kept += 1
        except Exception as exc:
            no_file += 1
            _skip('error:%s' % type(exc).__name__)
            print('  %s: %s' % (bid, type(exc).__name__), flush=True)
        gc.collect()

total = sum(1 for _ in open(MANIFEST, encoding='utf-8')) if os.path.exists(MANIFEST) else 0
print('حُفظ %d · بلا صندوق %d · قيمةٌ مرفوضة %d · ملفٌّ/خطأ %d · المجموع %d'
      % (kept, no_box, bad_val, no_file, total), flush=True)
json.dump({'total': total, 'no_box': no_box, 'bad_value': bad_val, 'no_file': no_file},
          open(STATS, 'w', encoding='utf-8'))
