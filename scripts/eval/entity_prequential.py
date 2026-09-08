# -*- coding: utf-8 -*-
"""قياسٌ زمنيّ (prequential): لكلّ ربع سنة، الذاكرةُ = صفوفُ الكتب المؤرَّخة قبله فقط.
يفصل «الجهةُ لم تُرَ بعد» (لا تُتعلَّم) عن «رُئيت وأُخطئت» (كفاءةُ التعلّم). قراءةٌ فقط."""
import os, sys, json, time, datetime as dt
from collections import defaultdict
sys.path.insert(0, os.getcwd()); os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lettersys.settings')
import django; django.setup()
from sklearn.feature_extraction.text import TfidfVectorizer
from core.models import LetterheadMemory, Book
from core.extraction.matchers import entity as E
from core.extraction.pipeline import AIExtractionService

rows_all = [r for r in LetterheadMemory.objects.values_list(
    'letterhead', 'issuing_entity_id', 'issuing_entity__name', 'issuing_entity__code',
    'receiving_entity_id', 'receiving_entity__name', 'receiving_entity__code',
    'book__date', 'created_at', 'book_id') if r[7]]
sample = json.load(open('docs/manifests/tierA_sample.json', encoding='utf-8'))
mem = {m.id: m.letterhead for m in LetterheadMemory.objects.filter(id__in=[r['mem'] for r in sample])}
books = {b.id: b for b in Book.objects.filter(id__in=[r['book'] for r in sample]).prefetch_related('receiving_entities')}
q = []
for r in sample:
    b = books.get(r['book']); t = mem.get(r['mem'])
    if not (b and t and b.date): continue
    rv = b.receiving_entities.first()
    q.append((b.date, b.id, t, r['truth'], rv.id if rv else None))
q.sort()
print('queries', len(q), 'rows dated', len(rows_all), 'span', q[0][0], '→', q[-1][0], flush=True)
em = AIExtractionService().entity_matcher
em._ensure_memory_index = lambda: em._memory_index

def qstart(d): return dt.date(d.year, 3 * ((d.month - 1) // 3) + 1, 1)
buckets = defaultdict(list)
for item in q: buckets[qstart(item[0])].append(item)
agg = {'issuer': [0, 0, 0, 0], 'receiver': [0, 0, 0, 0]}   # n, seen, top1|seen, top1
print('%-8s %6s %4s | %-26s | %-26s' % ('الربع', 'صفوف', 'n', 'المُصدِرة: رُئيت% · صحّ|رُئيت% · صحّ%', 'المستلمة: رُئيت% · صحّ|رُئيت% · صحّ%'))
for start in sorted(buckets):
    rows = [r for r in rows_all if r[7] < start]
    if rows:
        vec = TfidfVectorizer(analyzer='char_wb', ngram_range=(3, 5))
        em._memory_index = (vec, vec.fit_transform([E._normalize_ar(r[0]) for r in rows]), rows, -1)
    else:
        em._memory_index = (None, None, [], -1)
    em._memory_built_at = time.monotonic()
    seen_i = {r[1] for r in rows}; seen_r = {r[4] for r in rows}
    st = {'issuer': [0, 0, 0, 0], 'receiver': [0, 0, 0, 0]}
    for d, bid, text, ti, tr in buckets[start]:
        for et, truth, seen in (('issuer', ti, seen_i), ('receiver', tr, seen_r)):
            if truth is None: continue
            s = st[et]; s[0] += 1
            was_seen = truth in seen
            if was_seen: s[1] += 1
            ranked = em.match_from_memory(text, entity_type=et, top_k=3, exclude_book_id=bid)
            ok = bool(ranked) and ranked[0]['entity_id'] == truth
            if ok: s[3] += 1
            if ok and was_seen: s[2] += 1
    for et in st:
        for i in range(4): agg[et][i] += st[et][i]
    def fmt(s): return '%5.0f%% · %5.0f%% · %5.0f%%' % (100*s[1]/max(s[0],1), 100*s[2]/max(s[1],1), 100*s[3]/max(s[0],1))
    print('%-8s %6d %4d | %-26s | %-26s' % ('%d-Q%d' % (start.year, (start.month-1)//3+1), len(rows), st['issuer'][0], fmt(st['issuer']), fmt(st['receiver'])), flush=True)
print('المجموع %20s | %-26s | %-26s' % ('', fmt(agg['issuer']), fmt(agg['receiver'])))
print('n issuer', agg['issuer'][0], 'n receiver', agg['receiver'][0])
