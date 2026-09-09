# -*- coding: utf-8 -*-
"""قياسُ الجهتين — المُصدِرة **والمستلمة** — بمسار الإنتاج على Tier A.

البروتوكولُ مُسجَّلٌ في `docs/EVAL_REGISTRY.md` (§الجهتان) **قبل** التشغيل:
Tier A (1000، «مفتوحةٌ للضبط» ⟵ النتيجةُ تطوير)، النصُّ = الترويسةُ المخزّنة،
`exclude_book_id` يُقصي صفَّ الكتاب من التصويت، حقيقةُ المستلمة = أوّلُ
`receiving_entities`. ذراعان للمُصدِرة: الذاكرةُ وحدَها (تُقارَن بـ49.0%) والمسارُ
كاملاً (`resolve_entity_candidates` — ما يبلغ الكاتبَ فعلاً).

    python scripts/eval/entity_eval.py
"""
import json
import os
import sys
from collections import defaultdict

PROJ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJ)
os.chdir(PROJ)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lettersys.settings')
import django  # noqa: E402
django.setup()

from core.extraction.pipeline import AIExtractionService  # noqa: E402
from core.models import Book, LetterheadMemory  # noqa: E402

MAN = os.path.join(PROJ, 'docs', 'manifests', 'tierA_sample.json')
OUT = r'D:\migration\lettersys_models\entity_eval_tierA.json'

rows = json.load(open(MAN, encoding='utf-8'))
svc = AIExtractionService()
pm = svc.pattern_matcher
mem = {m.id: m for m in LetterheadMemory.objects.filter(id__in=[r['mem'] for r in rows])}
books = {b.id: b for b in Book.objects.filter(id__in=[r['book'] for r in rows])
         .prefetch_related('receiving_entities')}

tally = defaultdict(lambda: {'n': 0, 'top1': 0, 'top3': 0, 'silent': 0})
records = []
for r in rows:
    m, b = mem.get(r['mem']), books.get(r['book'])
    if not (m and b):
        continue
    text = m.letterhead or ''
    kind = b.kind or ''
    recipient = pm.extract_recipient(text) or ''
    register = pm.extract_register_code(text) or ''
    cands = [t for (t, _c) in pm.extract_entities(text)]
    rec = {'book': b.id, 'kind': kind}
    arms = {
        'issuer_full': (svc.resolve_entity_candidates('issuer', text, kind, recipient, register, cands,
                                                      exclude_book_id=b.id, department_id=b.department_id), r['truth']),
        'issuer_memory_only': (svc.entity_matcher.match_from_memory(text, entity_type='issuer', top_k=3,
                                                                    exclude_book_id=b.id), r['truth']),
    }
    recv = b.receiving_entities.first()
    if recv:
        arms['receiver_full'] = (svc.resolve_entity_candidates('receiver', text, kind, recipient, register,
                                                               cands, exclude_book_id=b.id), recv.id)
    for arm, (ranked, truth) in arms.items():
        ids = [x['entity_id'] for x in ranked]
        for key in (arm, arm + '|' + kind):
            t = tally[key]; t['n'] += 1
            if not ids: t['silent'] += 1
            if ids and ids[0] == truth: t['top1'] += 1
            if truth in ids: t['top3'] += 1
        rec[arm] = {'ranked': ids, 'truth': truth,
                    'src': [x.get('match_type') for x in ranked]}
    records.append(rec)

json.dump({'protocol': 'EVAL_REGISTRY §الجهتان 2026-09-01', 'n': len(records),
           'tally': tally, 'records': records},
          open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('n =', len(records))
for key in sorted(tally):
    t = tally[key]
    print('%-40s n=%4d  top1 %5.1f%%  top3 %5.1f%%  صمت %5.1f%%'
          % (key, t['n'], 100 * t['top1'] / t['n'], 100 * t['top3'] / t['n'], 100 * t['silent'] / t['n']))
