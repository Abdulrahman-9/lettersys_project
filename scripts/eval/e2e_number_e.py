# -*- coding: utf-8 -*-
"""e2e-E — صفُّ المرجع المطبوع: المسارُ النصّيُّ الصارم مقابل البصريّ.

البوّابةُ مسجَّلةٌ في `docs/EVAL_REGISTRY.md` **قبل** هذا التشغيل، والحقيقةُ
(`printed_truth`) محكَّمةٌ بالعين في المانيفست **قبله أيضاً** — عينٌ رأت مخرجَ
المسار تنحاز في قراءة الحبر.

تشغيلةٌ واحدة تسجّل لكلّ كتاب: النصّيَّ وزمنَه · البصريَّ وزمنَه · الوسمَ ·
الحقيقةَ المحكَّمة. فيُحسب المتغيّران (الصارمُ وحده · التصادق) بلا نظرةٍ ثانية.

    python scripts/eval/e2e_number_e.py [حجم الدفعة]      # استئنافٌ تلقائيّ
"""
import json
import os
import sys
import time

PROJ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJ)
os.chdir(PROJ)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lettersys.settings')
import django  # noqa: E402
django.setup()

import fitz  # noqa: E402
from core.extraction.matchers.strict_ref import (  # noqa: E402
    canonical_sender_number, digits_of, strict_ref_match)
from core.extraction.pipeline import AIExtractionService  # noqa: E402
from core.models import Book  # noqa: E402

MAN = r'D:\migration\lettersys_models\e2e_E_manifest.json'
OUT = r'D:\migration\lettersys_models\e2e_E_results.json'
CHUNK = int(sys.argv[1]) if len(sys.argv) > 1 else 15
_ARD = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')


def norm(v):
    return ''.join(c for c in str(v or '').translate(_ARD) if c.isdigit())


man = json.load(open(MAN, encoding='utf-8'))
rows = {r['book']: r for r in man['books']}
done = json.load(open(OUT, encoding='utf-8')) if os.path.exists(OUT) else []
have = {r['book'] for r in done}
todo = [r['book'] for r in man['books'] if r['book'] not in have][:CHUNK]
print('منجز %d/%d · هذه الدفعة %d' % (len(have), len(rows), len(todo)), flush=True)

svc = AIExtractionService()
for bid in todo:
    src = rows[bid]
    b = Book.objects.filter(id=bid).first()
    att = b.attachments.first() if b else None
    p = att.file.path if (att and hasattr(att.file, 'path')) else None
    rec = {'book': bid, 'label': norm(src.get('truth')),
           'truth': norm(src.get('printed_truth')) if src.get('printed_truth') else '',
           'truth_src': src.get('truth_src', ''), 'entity': src.get('entity', '')}
    if not (p and os.path.exists(p)):
        rec['err'] = 'no-file'
        done.append(rec)
        continue

    # ── المسارُ النصّيّ ──
    t0 = time.time()
    text = ''
    if p.lower().endswith('.pdf'):
        try:
            d = fitz.open(p)
            text = d[0].get_text()
            d.close()
        except Exception:
            text = ''
    raw = strict_ref_match(text)
    rec['strict_raw'] = raw or ''
    rec['strict'] = canonical_sender_number(raw) if raw else ''
    rec['t_text'] = round(time.time() - t0, 4)

    # ── المسارُ البصريّ (السلوكُ القائم) ──
    t0 = time.time()
    try:
        res = svc.process_image(p)
        rec['status'] = getattr(res, 'status', '') or ''
        rec['visual'] = norm(getattr(res, 'sender_number', '') or '')
        rec['conf'] = round(float(getattr(res, 'sender_number_confidence', 0.0) or 0.0), 3)
        rec['box_src'] = getattr(res, 'sender_number_bbox_source', '') or ''
    except Exception as exc:
        rec['visual'] = ''
        rec['err'] = type(exc).__name__
    rec['t_visual'] = round(time.time() - t0, 3)

    done.append(rec)
    json.dump(done, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
    print('  %-6s حقيقة %-10s نصّيّ %-10s بصريّ %-10s  %.3f/%.2f ث'
          % (bid, rec['truth'] or '—', rec['strict'] or '—', rec.get('visual') or '—',
             rec['t_text'], rec.get('t_visual', 0)), flush=True)

print('اكتمل %d/%d' % (len(done), len(rows)))
