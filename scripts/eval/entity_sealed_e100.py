# -*- coding: utf-8 -*-
"""E‑100 — الجهتان بمسار الإنتاج كاملاً على 100 كتابٍ لم تُرَ (بوّابةٌ في السجلّ).
    python scripts/eval/entity_sealed_e100.py          # يبني المانيفست إن غاب ويستأنف
"""
import json, os, random, sys, time
PROJ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJ); os.chdir(PROJ)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lettersys.settings')
import django; django.setup()  # noqa: E402
from core.extraction.pipeline import AIExtractionService  # noqa: E402
from core.models import Book  # noqa: E402
BASE = r'D:\migration\lettersys_models'
TAG = '' if (len(sys.argv) < 2 or sys.argv[1] == '20260901') else '_' + sys.argv[1]
MAN = os.path.join(BASE, 'entity_E100%s_manifest.json' % TAG); OUT = os.path.join(BASE, 'entity_E100%s_results.json' % TAG)
SEED = int(sys.argv[1]) if len(sys.argv) > 1 else 20260901
EXCLUDE_PREV = sys.argv[2:]          # مانيفستاتُ مجموعاتٍ مختومةٍ سابقة تُستبعَد

def excluded():
    ids = set(r['book'] for r in json.load(open('docs/manifests/tierA_sample.json', encoding='utf-8')))
    e = json.load(open(os.path.join(BASE, 'e2e_manifest.json'), encoding='utf-8'))
    for k in ('A', 'B', 'C'): ids |= set(e['sets'][k])
    for f in ('e2e_D_manifest.json', 'e2e_E_manifest.json'):
        ids |= {int(r['book']) for r in json.load(open(os.path.join(BASE, f), encoding='utf-8'))['books']}
    ids |= set(json.load(open(os.path.join(BASE, 'subject_corpus', 'subject200_manifest.json'), encoding='utf-8'))['books'])
    ids |= {r['book'] for r in json.load(open(os.path.join(BASE, 'subject_corpus', 'corpus.json'), encoding='utf-8'))}
    ids |= set(json.load(open(os.path.join(BASE, 'clean_pool.json'), encoding='utf-8')))
    for f in EXCLUDE_PREV:
        ids |= set(json.load(open(f, encoding='utf-8'))['books'])
    return {int(i) for i in ids}

if not os.path.exists(MAN):
    ex = excluded()
    pool = []
    qs = (Book.objects.filter(is_deleted=False, attachments__isnull=False, issuing_entities__isnull=False)
          .exclude(source_ref='').exclude(id__in=ex).order_by('id').distinct())
    for b in qs.only('id', 'kind'):
        att = b.attachments.first(); p = att.file.path if (att and hasattr(att.file, 'path')) else None
        if p and os.path.exists(p) and p.lower().endswith('.pdf'):
            pool.append(b.id)
    random.Random(SEED).shuffle(pool)
    chosen = sorted(pool[:100])
    comp = {}
    for b in Book.objects.filter(id__in=chosen).values_list('kind', flat=True): comp[b] = comp.get(b, 0) + 1
    json.dump({'name': 'entity-E100', 'seed': SEED, 'pool': len(pool), 'excluded': len(ex),
               'composition': comp, 'books': chosen}, open(MAN, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('manifest', len(chosen), 'من مسبح', len(pool), '·', comp, flush=True)

man = json.load(open(MAN, encoding='utf-8'))
done = json.load(open(OUT, encoding='utf-8')) if os.path.exists(OUT) else []
have = {r['book'] for r in done}
svc = AIExtractionService()
for bid in man['books']:
    if bid in have: continue
    b = Book.objects.get(id=bid); p = b.attachments.first().file.path
    t0 = time.time(); svc._eval_exclude_book_id = bid
    try:
        # النوعُ من القاعدة = ما يختاره الكاتبُ في التبويب قبل المسح (الواجهةُ ترسله الآن)
        res = svc.process_image(p, book_kind=b.kind or '')
        rec = {'book': bid, 'kind': b.kind, 'status': res.status,
               'issuer': [m.get('entity_id') for m in (res.issuing_entity_matches or [])],
               'issuer_src': [m.get('match_type') for m in (res.issuing_entity_matches or [])],
               'receiver': [m.get('entity_id') for m in (res.receiving_entity_matches or [])],
               'receiver_src': [m.get('match_type') for m in (res.receiving_entity_matches or [])]}
    except Exception as exc:
        rec = {'book': bid, 'kind': b.kind, 'err': type(exc).__name__}
    ie = b.issuing_entities.first(); re_ = b.receiving_entities.first()
    rec['issuer_truth'] = ie.id if ie else None; rec['receiver_truth'] = re_.id if re_ else None
    rec['t'] = round(time.time() - t0, 1)
    done.append(rec); json.dump(done, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
    print('%d/%d' % (len(done), len(man['books'])), flush=True)
svc._eval_exclude_book_id = None
def score(key):
    n = h1 = h3 = sil = 0
    for r in done:
        t = r.get(key + '_truth'); ids = r.get(key) or []
        if t is None or 'err' in r: continue
        n += 1; sil += (not ids); h1 += bool(ids and ids[0] == t); h3 += (t in ids)
    return n, h1, h3, sil
for key in ('issuer', 'receiver'):
    n, h1, h3, sil = score(key)
    print('RESULT %-8s n=%d top1 %.1f%% top3 %.1f%% صمت %.1f%%' % (key, n, 100*h1/n, 100*h3/n, 100*sil/n))
errs = sum(1 for r in done if 'err' in r); print('RESULT errors', errs, '· زمن/مستند %.1f ث' % (sum(r['t'] for r in done)/len(done)))
