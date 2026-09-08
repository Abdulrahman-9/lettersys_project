# -*- coding: utf-8 -*-
"""بوّابةُ e2e‑التاريخ (مُسجَّلة 2026-08-26، EVAL_REGISTRY §D4): 100 صفحةٍ لم تُرَ، بمسار
الإنتاج كاملاً — دقّةُ المقترح الأخضر (≥0.98) ≥90% · أخضرُ‑ومخطئ ≤2 · التباساتُ الختم تُعدّ.
    python scripts/eval/date_sealed_100.py
"""
import json, os, random, sys, time
PROJ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJ); os.chdir(PROJ)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lettersys.settings')
import django; django.setup()  # noqa: E402
from core.extraction.pipeline import AIExtractionService  # noqa: E402
from core.models import Book  # noqa: E402
BASE = r'D:\migration\lettersys_models'; SEED = 20260903
MAN = os.path.join(BASE, 'date_sealed100_manifest.json'); OUT = os.path.join(BASE, 'date_sealed100_results.json')

def excluded():
    ids = set()
    for line in open(os.path.join(BASE, 'date_ds', 'manifest.jsonl'), encoding='utf-8'):
        try: ids.add(int(json.loads(line)['book']))
        except Exception: pass
    for f in ('date_ds/d1_eye_sample.json', 'gate_b_date.json', 'e2e_D_manifest.json', 'e2e_E_manifest.json',
              'entity_E100_manifest.json', 'entity_E100_20260902_manifest.json', 'clean_pool.json', 'noise100_books.json'):
        p = os.path.join(BASE, f)
        if not os.path.exists(p): continue
        d = json.load(open(p, encoding='utf-8'))
        rows = d.get('books', d) if isinstance(d, dict) else d
        for r in rows:
            b = r.get('book') if isinstance(r, dict) else r
            try: ids.add(int(b))
            except Exception: pass
    e = json.load(open(os.path.join(BASE, 'e2e_manifest.json'), encoding='utf-8'))
    for k in ('A', 'B', 'C'): ids |= {int(i) for i in e['sets'][k]}
    return ids

if not os.path.exists(MAN):
    ex = excluded(); pool = []
    qs = (Book.objects.filter(is_deleted=False, attachments__isnull=False, sender_date__isnull=False,
                              date__isnull=False, kind__startswith='incoming')
          .exclude(source_ref='').exclude(id__in=ex).order_by('id').distinct())
    for b in qs.only('id', 'date', 'sender_date'):
        gap = (b.date - b.sender_date).days
        if not (0 < gap <= 45): continue                     # وسمٌ سليمُ الاتّجاه (حارسُ الفارق المُسجَّل)
        att = b.attachments.first(); p = att.file.path if (att and hasattr(att.file, 'path')) else None
        if p and os.path.exists(p) and p.lower().endswith('.pdf'): pool.append(b.id)
    random.Random(SEED).shuffle(pool); chosen = sorted(pool[:100])
    json.dump({'name': 'date-sealed-100', 'seed': SEED, 'pool': len(pool), 'excluded': len(ex), 'books': chosen},
              open(MAN, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('manifest', len(chosen), 'من مسبح', len(pool), '· مستبعَد', len(ex), flush=True)

man = json.load(open(MAN, encoding='utf-8'))
done = json.load(open(OUT, encoding='utf-8')) if os.path.exists(OUT) else []
have = {r['book'] for r in done}; svc = AIExtractionService()
for bid in man['books']:
    if bid in have: continue
    b = Book.objects.get(id=bid); p = b.attachments.first().file.path; t0 = time.time()
    try:
        res = svc.process_image(p, book_kind=b.kind or ''); sug = res.sender_date_suggestion or {}
        rec = {'book': bid, 'raw': sug.get('raw'), 'iso': sug.get('iso'), 'parse': sug.get('parse'),
               'conf': sug.get('confidence'), 'green_thr': sug.get('green_threshold'), 'status': res.status}
    except Exception as exc:
        rec = {'book': bid, 'err': type(exc).__name__}
    rec['truth'] = b.sender_date.isoformat(); rec['entry'] = b.date.isoformat(); rec['t'] = round(time.time() - t0, 1)
    done.append(rec); json.dump(done, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
    print('%d/%d' % (len(done), len(man['books'])), flush=True)
n = len(done); green = [r for r in done if r.get('iso') and r.get('parse') == 'ok' and (r.get('conf') or 0) >= (r.get('green_thr') or 0.98)]
g_ok = sum(1 for r in green if r['iso'] == r['truth']); g_bad = len(green) - g_ok
stamp = sum(1 for r in green if r['iso'] == r['entry'] and r['iso'] != r['truth'])
any_sug = sum(1 for r in done if r.get('iso')); exact_all = sum(1 for r in done if r.get('iso') == r['truth'])
print('RESULT n=%d · اقتراحٌ %d · تامٌّ %d (%.1f%%) · أخضر %d (تغطية %.0f%%) · أخضرٌ صحيح %d (%.1f%%) · أخضرٌ‑ومخطئ %d · التباسُ ختم %d · أخطاء %d'
      % (n, any_sug, exact_all, 100*exact_all/n, len(green), 100*len(green)/n, g_ok, (100*g_ok/len(green) if green else 0), g_bad, stamp, sum(1 for r in done if 'err' in r)))
