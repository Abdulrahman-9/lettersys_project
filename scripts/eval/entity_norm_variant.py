# -*- coding: utf-8 -*-
"""تجربةٌ تطويريّة (مُسجَّلة): توحيدُ شكل نصّ الذاكرة بين التخزين (Tesseract خامّ) والاستعلام
(`clean_text`) — بترقيعٍ زمنيٍّ للمُطبِّع لا بتعديل الشيفرة؛ تُقارَن بنتائج E‑100 بالنوع (44.0/60.6).
    python scripts/eval/entity_norm_variant.py
"""
import json, os, re, sys, time
PROJ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJ); os.chdir(PROJ)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lettersys.settings')
import django; django.setup()  # noqa: E402
from core.extraction.matchers import entity as E  # noqa: E402
from core.extraction.pipeline import AIExtractionService  # noqa: E402
from core.models import Book  # noqa: E402
_orig = E._normalize_ar
_ALLOWED = set('0123456789 ') | {chr(i) for i in range(0x0600, 0x06FF)} | set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ') | set('.,;:!?-/()[]{}')
def _norm_v2(s):
    s = ''.join(c if c in _ALLOWED else ' ' for c in str(s or ''))
    return _orig(s)
E._normalize_ar = _norm_v2                       # يُطبَّق على الفهرس والاستعلام معاً (بحثٌ عامّ وقت النداء)
BASE = r'D:\migration\lettersys_models'
man = json.load(open(os.path.join(BASE, 'entity_E100_manifest.json'), encoding='utf-8'))
OUT = os.path.join(BASE, 'entity_E100_results_normv2.json')
done = json.load(open(OUT, encoding='utf-8')) if os.path.exists(OUT) else []
have = {r['book'] for r in done}; svc = AIExtractionService()
for bid in man['books']:
    if bid in have: continue
    b = Book.objects.get(id=bid); p = b.attachments.first().file.path; svc._eval_exclude_book_id = bid
    try:
        res = svc.process_image(p, book_kind=b.kind or '')
        rec = {'book': bid, 'issuer': [m.get('entity_id') for m in (res.issuing_entity_matches or [])],
               'receiver': [m.get('entity_id') for m in (res.receiving_entity_matches or [])]}
    except Exception as exc:
        rec = {'book': bid, 'err': type(exc).__name__}
    ie = b.issuing_entities.first(); re_ = b.receiving_entities.first()
    rec['issuer_truth'] = ie.id if ie else None; rec['receiver_truth'] = re_.id if re_ else None
    done.append(rec); json.dump(done, open(OUT, 'w', encoding='utf-8'))
    print('%d/%d' % (len(done), len(man['books'])), flush=True)
for key in ('issuer', 'receiver'):
    n = h1 = h3 = 0
    for r in done:
        t = r.get(key + '_truth'); ids = r.get(key) or []
        if t is None or 'err' in r: continue
        n += 1; h1 += bool(ids and ids[0] == t); h3 += (t in ids)
    print('RESULT normv2 %-8s n=%d top1 %.1f%% top3 %.1f%%' % (key, n, 100*h1/n, 100*h3/n))
