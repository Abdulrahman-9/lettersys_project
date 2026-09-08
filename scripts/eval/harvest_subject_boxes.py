# -*- coding: utf-8 -*-
"""حصادُ صناديق الموضوع — وسومٌ مجّانيّةٌ من هندسة Tesseract، بصفر GPU.

نفس حركة صناديق العدد الـ1,024 التي صنعت الكاشف: حيثما قرأ Tesseract سطراً يطابق
عنوانَ الكاتب (F1 >= 0.7 بمسطرة v2 المُصحَّحة الحالة)، فهندسةُ ذلك السطر صندوقُ
موضوعٍ مُتحقَّق. البوّابة تُبوّب **الصندوق عبر النصّ المطابق للحقيقة** — لا عبر
اتّفاق نموذجٍ مع نفسه (درسُ الوسوم المسمومة).

العقود الصلبة (نفس أنبوب كاشف العدد حرفيّاً):
- الرسم 175dpi خام RGB بسقف 3500 — **وصفة تدريب الكاشف** لا وصفةً جديدة.
- الصندوق مُطبَّعٌ على **الصفحة الكاملة** ومعه dims — عقد الهندسة.
- الاستئناف بمفتاح «حوولت» لا «نجحت» — درسُ الحلقة المقفلة (صفوف skip تُسجَّل).
- الاستثناءات بالكتاب من كلّ المانيفستات المختومة، مفروضةٌ هنا: الكاشف الثنائيّ
  القادم يُعيد تدريب صنف **العدد** أيضاً، فتُستبعد e2e-A/B/C وsubject-200
  وsubject-40 والـ276 جميعاً.

    python scripts/eval/harvest_subject_boxes.py [دفعة]
"""
import gc
import json
import os
import re
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJ)
os.chdir(PROJ)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lettersys.settings')
import django  # noqa: E402
django.setup()

from PIL import Image  # noqa: E402
from core.models import Book  # noqa: E402

OUT = r'D:\migration\lettersys_models\subj_boxes'
MANIFEST = os.path.join(OUT, 'manifest.jsonl')
os.makedirs(OUT, exist_ok=True)
CHUNK = int(sys.argv[1]) if len(sys.argv) > 1 else 40
F1_GATE = 0.70

_AR = re.compile(r'[^؀-ۿ0-9A-Za-z]+')
_ST = {'في', 'من', 'الى', 'إلى', 'على', 'عن', 'و', 'ال', 'the', 'of', 'for', 'and', 'to'}


def _n(s):
    s = s or ''
    for a, b in (('أ', 'ا'), ('إ', 'ا'), ('آ', 'ا'), ('ى', 'ي'), ('ة', 'ه'), ('ـ', '')):
        s = s.replace(a, b)
    return s


def toks(s):
    return {t.lower() for t in _AR.split(_n(s).strip()) if len(t) >= 2 and t.lower() not in _ST}


def f1(a, b):
    A, B = toks(a), toks(b)
    if not A or not B:
        return 0.0
    i = len(A & B)
    return 0.0 if not i else 2 * (i / len(A)) * (i / len(B)) / ((i / len(A)) + (i / len(B)))


def _sealed_books():
    base = r'D:\migration\lettersys_models'
    ids = set()
    e = json.load(open(os.path.join(base, 'e2e_manifest.json'), encoding='utf-8'))
    for k in ('A', 'B', 'C'):
        ids |= set(e['sets'][k])
    ids |= set(json.load(open(os.path.join(base, 'subject_corpus', 'subject200_manifest.json'),
                              encoding='utf-8'))['books'])
    ids |= set(json.load(open(os.path.join(base, 'clean_pool.json'), encoding='utf-8')))
    ids |= {r['book'] for r in json.load(open(os.path.join(base, 'subject_corpus', 'corpus.json'),
                                              encoding='utf-8'))}
    return ids


def _untrusted_titles():
    """كتبٌ عنوانُها **ليس شهادةَ كاتبٍ مستقلّة** — تُستبعَد من الحصاد.

    **حلقةُ التسميم الذاتيّ**: حقيقةُ تدريب الموضوع هي `Book.title` عينُه، والواجهةُ
    تملأ العنوانَ من مسار العلامة تلقائيّاً **منذ أيّار 2026** (لا منذ اليوم —
    ادّعاءُ «الحصادُ القديمُ نظيفٌ بالبناء» نُقض بالقياس: 48 من 6,462 صندوقاً من
    كتبٍ أنشأها التطبيق). فعنوانٌ مملوءٌ وحُفظ بلا لمس، أو أُكّد بنقرةٍ على اقتراحٍ
    صالحٍ 6.5%، يعود وسماً يدرّب المُنتقي على مخرجه هو.

    **القاعدةُ فاشلةٌ‑مغلقاً**: كلُّ كتابٍ أنشأه التطبيق (`source_ref` فارغ) يُستبعَد
    **إلّا** إن التقطت له شهادةُ `typed` (كتبه الكاتبُ بيده). لا التقاطَ = يُستبعَد،
    و`autofilled`/`confirmed` = يُستبعَد. الكتبُ المستوردةُ من الورق تبقى: عناوينُها
    كتبها موظّفون في النظام القديم بلا مُنتقٍ آليّ.
    """
    from core.models import Book, DataExtractionResult
    typed = set(
        DataExtractionResult.objects
        .filter(additional_data__title_provenance='typed')
        .values_list('book_id', flat=True))
    app_made = set(
        Book.objects.filter(is_deleted=False, source_ref='')
        .values_list('id', flat=True))
    return app_made - typed


def render(p, dpi=175, cap=3500):
    if p.lower().endswith('.pdf'):
        import fitz
        d = fitz.open(p)
        pg = d[0]
        z = dpi / 72.0
        lo = max(pg.rect.width, pg.rect.height) * z
        if lo > cap:
            z *= cap / lo
        px = pg.get_pixmap(matrix=fitz.Matrix(z, z))
        im = Image.frombytes('RGB', (px.width, px.height), px.samples)
        d.close()
        return im
    return Image.open(p).convert('RGB')


sealed = _sealed_books()
attempted = set()
if os.path.exists(MANIFEST):
    for line in open(MANIFEST, encoding='utf-8'):
        try:
            attempted.add(json.loads(line)['book'])
        except Exception:
            pass

poisoned = _untrusted_titles()
qs = (Book.objects.filter(is_deleted=False, attachments__isnull=False)
      .exclude(title='').exclude(title=None)
      .exclude(id__in=sealed).exclude(id__in=poisoned)
      .order_by('id').distinct())
todo = [b for b in qs.values_list('id', 'title') if b[0] not in attempted][:CHUNK]
print('مؤهَّلون %d · حوولوا %d · مستبعَدٌ بلا شهادةِ كاتب %d · هذه الدفعة %d'
      % (qs.count(), len(attempted), len(poisoned), len(todo)), flush=True)

from core.extraction.ocr.providers import TesseractOCRProvider  # noqa: E402
prov = TesseractOCRProvider()
pt = prov._pytesseract
pt.pytesseract.tesseract_cmd = prov.cmd
if prov.tessdata_dir:
    os.environ['TESSDATA_PREFIX'] = prov.tessdata_dir

kept = no_line = no_file = 0
with open(MANIFEST, 'a', encoding='utf-8') as mf:
    for bid, title in todo:
        def _skip(reason):
            mf.write(json.dumps({'book': bid, 'skip': reason}, ensure_ascii=False) + chr(10))
            mf.flush()

        b = Book.objects.filter(id=bid).first()
        att = b.attachments.first() if b else None
        p = att.file.path if (att and hasattr(att.file, 'path')) else None
        if not (p and os.path.exists(p)):
            no_file += 1
            _skip('no_file')
            continue
        try:
            im = render(p)
            W, H = im.size
            tsv = pt.image_to_data(im, lang=prov.lang, config='--psm %s' % prov.psm,
                                   output_type=pt.Output.DICT)
            del im
            lines = {}
            n = len(tsv['text'])
            for i in range(n):
                w = (tsv['text'][i] or '').strip()
                if not w:
                    continue
                key = (tsv['block_num'][i], tsv['par_num'][i], tsv['line_num'][i])
                L = lines.setdefault(key, {'words': [], 'x0': 10**9, 'y0': 10**9,
                                           'x1': 0, 'y1': 0})
                L['words'].append(w)
                L['x0'] = min(L['x0'], tsv['left'][i])
                L['y0'] = min(L['y0'], tsv['top'][i])
                L['x1'] = max(L['x1'], tsv['left'][i] + tsv['width'][i])
                L['y1'] = max(L['y1'], tsv['top'][i] + tsv['height'][i])
            best, bl = 0.0, None
            for L in lines.values():
                s = f1(' '.join(L['words']), title)
                if s > best:
                    best, bl = s, L
            if best < F1_GATE or bl is None:
                no_line += 1
                _skip('no_line@%.2f' % best)
                continue
            mf.write(json.dumps({
                'book': bid, 'cls': 'subject', 'f1': round(best, 3),
                'line_text': ' '.join(bl['words'])[:90],
                'box': [round(bl['x0'] / W, 4), round(bl['y0'] / H, 4),
                        round(bl['x1'] / W, 4), round(bl['y1'] / H, 4)],
                'dims': [W, H]}, ensure_ascii=False) + chr(10))
            mf.flush()
            kept += 1
        except Exception as exc:
            no_file += 1
            _skip('error:%s' % type(exc).__name__)
        gc.collect()

total = sum(1 for _ in open(MANIFEST, encoding='utf-8')) if os.path.exists(MANIFEST) else 0
print('حُفظ %d · بلا سطرٍ مطابق %d · ملفّ/خطأ %d · المجموع %d'
      % (kept, no_line, no_file, total), flush=True)
