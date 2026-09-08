# -*- coding: utf-8 -*-
"""e2e‑F — الصارمُ بمسار الإنتاج على 60 كتاباً لم تُرَ (بوّابةٌ مُسجَّلةٌ في السجلّ §تصحيحات المساء).
انتقاءٌ كانتقاء E (نفسُ ENTITY_NAMES من build_e2e_e.py)، يستبعد A/B/C/D/E ومجموعاتِ الليلة.
الحقيقةُ الأوّليّة آليّة: وسمُ القاعدة == مرجعٌ مطبوعٌ مستقلٌّ في نصّ الصفحة الأولى (تعبيرٌ فضفاضٌ
غيرُ الصارم)؛ ما لم يتّفق يُترك «للعين» ولا يُحاسَب حتّى يحكم المالك.
    python scripts/eval/e2e_number_f.py
"""
import json, os, random, re, sys, time
PROJ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJ); os.chdir(PROJ)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lettersys.settings')
import django; django.setup()  # noqa: E402
from core.extraction.matchers.strict_ref import APPROVED_PREFIXES  # noqa: E402
from core.extraction.pipeline import AIExtractionService, pdf_first_page_text  # noqa: E402
from core.models import Book, Entity  # noqa: E402
BASE = r'D:\migration\lettersys_models'; SEED = 20260904
MAN = os.path.join(BASE, 'e2e_F_manifest.json'); OUT = os.path.join(BASE, 'e2e_F_results.json')
_src = open(os.path.join(PROJ, 'scripts', 'eval', 'build_e2e_e.py'), encoding='utf-8').read()
ENTITY_NAMES = eval(re.search(r'ENTITY_NAMES\s*=\s*(\(.*?\)|\[.*?\])', _src, re.S).group(1))
_ARD = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')
norm = lambda v: ''.join(c for c in str(v or '').translate(_ARD) if c.isdigit())
LOOSE = re.compile(r'\b(%s)\s*[-/ ]?\s*([A-Za-z]{0,6}[-/ ]?)?(\d[\d\- ]{2,12}\d)' % '|'.join(APPROVED_PREFIXES), re.I)

def excluded():
    ids = set(); e = json.load(open(os.path.join(BASE, 'e2e_manifest.json'), encoding='utf-8'))
    for k in ('A', 'B', 'C'): ids |= {int(i) for i in e['sets'][k]}
    for f in ('e2e_D_manifest.json', 'e2e_E_manifest.json', 'entity_E100_manifest.json', 'entity_E100_20260902_manifest.json',
              'date_sealed100_manifest.json', 'clean_pool.json', 'noise100_books.json'):
        p = os.path.join(BASE, f)
        if not os.path.exists(p): continue
        d = json.load(open(p, encoding='utf-8')); rows = d.get('books', d) if isinstance(d, dict) else d
        for r in rows:
            try: ids.add(int(r.get('book') if isinstance(r, dict) else r))
            except Exception: pass
    return ids

if not os.path.exists(MAN):
    ex = excluded(); ent = set()
    for n in ENTITY_NAMES: ent |= set(Entity.objects.filter(name__icontains=n).values_list('id', flat=True))
    pool = []
    for b in (Book.objects.filter(is_deleted=False, attachments__isnull=False, issuing_entities__id__in=ent,
                                  kind__startswith='incoming').exclude(source_ref='').exclude(id__in=ex)
              .order_by('id').distinct().only('id')):
        att = b.attachments.first(); p = att.file.path if (att and hasattr(att.file, 'path')) else None
        if p and os.path.exists(p) and p.lower().endswith('.pdf'): pool.append(b.id)
    random.Random(SEED).shuffle(pool); chosen = sorted(pool[:60])
    json.dump({'name': 'e2e-F', 'seed': SEED, 'pool': len(pool), 'books': chosen}, open(MAN, 'w', encoding='utf-8'), indent=1)
    print('manifest', len(chosen), 'من مسبح', len(pool), flush=True)

man = json.load(open(MAN, encoding='utf-8'))
done = json.load(open(OUT, encoding='utf-8')) if os.path.exists(OUT) else []
have = {r['book'] for r in done}; svc = AIExtractionService()
for bid in man['books']:
    if bid in have: continue
    b = Book.objects.get(id=bid); p = b.attachments.first().file.path; t0 = time.time()
    label = norm(b.sender_number); text = pdf_first_page_text(p)
    printed = sorted({norm(m.group(3)) for m in LOOSE.finditer(text)} - {''})
    truth = label if (label and label in printed) else ''          # اتّفاقُ مصدرين مستقلّين
    try:
        res = svc.process_image(p, book_kind=b.kind or '')
        rec = {'book': bid, 'out': res.sender_number or '', 'src': getattr(res, 'sender_number_source', ''),
               'conf': round(float(res.sender_number_confidence or 0), 3)}
    except Exception as exc:
        rec = {'book': bid, 'err': type(exc).__name__}
    rec.update({'label': label, 'printed_loose': printed, 'truth': truth, 'snippet': text[:400], 't': round(time.time() - t0, 1)})
    done.append(rec); json.dump(done, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    print('%d/%d' % (len(done), len(man['books'])), flush=True)
adj = [r for r in done if r.get('truth')]; eye = [r for r in done if not r.get('truth')]
strict = [r for r in adj if r.get('src') == 'strict_ref']; hit = sum(1 for r in adj if r.get('out') == r['truth'])
s_hit = sum(1 for r in strict if r['out'] == r['truth']); emitted = sum(1 for r in adj if r.get('out'))
wrong = sum(1 for r in adj if r.get('out') and r['out'] != r['truth'])
print('RESULT محكَّمٌ آليّاً %d · للعين %d · أطلق %d · إصابة %d · خاطئ %d · دقّةُ المُطلَق %.0f%% · الصارمُ أطلق %d أصاب %d · أخطاء %d'
      % (len(adj), len(eye), emitted, hit, wrong, (100*hit/emitted if emitted else 0), len(strict), s_hit, sum(1 for r in done if 'err' in r)))
