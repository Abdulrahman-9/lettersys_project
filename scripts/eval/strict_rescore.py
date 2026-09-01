# -*- coding: utf-8 -*-
"""إعادةُ تسجيلِ المسار النصّيّ الصارم وحدَه — بلا مسٍّ للمسار البصريّ.

**لماذا سكريبتٌ ثانٍ**: `score_e2e_e.py` يحسب من عمود `strict` المخزَّن في نتائج
التشغيلة (كودُ 2026‑08‑30)، فلا يرى تعديلاً لاحقاً على `strict_ref.py`. وهذا
يُعيد استخراجَ الخانات **من طبقة نصّ الملفّ نفسِه بالكود الحاضر** (0.03 ث/مستند)،
فلا يُستدعى البصريُّ ولا تُستهلك نظرةٌ جديدة على مجموعةٍ مختومة.

**والمحاسَبةُ صريحةٌ في مرتبتها**:
- **e2e-E ⟵ مجموعةُ تطوير.** أُنفقت نظرتُها يوم 2026‑08‑30، ثمّ عُدّل الكود
  بعدها (الحكمُ على السطر). فأرقامُها هنا **قياسُ تطويرٍ لا بوّابة**، والبوّابةُ
  القادمة تنتظر e2e-F مسحوبةً جديدةً بحقيقةٍ محكَّمةٍ بالعين.
- **e2e-D ⟵ مختومةٌ لهذا المسار** (بُنيت للبصريّ ولم يُضبَط عليها حرفٌ من
  `strict_ref`): فهي حارسُ عدم التراجع الصادق — **خاطئ = 0 وإطلاقٌ ≤ 2/60**.

    python scripts/eval/strict_rescore.py
"""
import json
import os
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJ)
os.chdir(PROJ)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lettersys.settings')
import django  # noqa: E402
django.setup()

import fitz  # noqa: E402
from core.extraction.matchers.strict_ref import (  # noqa: E402
    canonical_sender_number, strict_ref_match)
from core.models import Book  # noqa: E402

ROOT = r'D:\migration\lettersys_models'
_ARD = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')


def norm(v):
    return ''.join(c for c in str(v or '').translate(_ARD) if c.isdigit())


def page1_text(book_id):
    b = Book.objects.filter(id=book_id).first()
    att = b.attachments.first() if b else None
    p = att.file.path if (att and hasattr(att.file, 'path')) else None
    if not (p and os.path.exists(p) and p.lower().endswith('.pdf')):
        return ''
    try:
        d = fitz.open(p)
        t = d[0].get_text()
        d.close()
        return t
    except Exception:
        return ''


def strict_of(book_id):
    raw = strict_ref_match(page1_text(book_id))
    return (canonical_sender_number(raw) if raw else ''), (raw or '')


# ══ e2e-E — قياسُ تطويرٍ على الحقيقة المحكَّمة بالعين ══════════════════════
rows = json.load(open(os.path.join(ROOT, 'e2e_E_results.json'), encoding='utf-8'))
scored = [r for r in rows if r.get('truth')]
fire = hit = wrong = 0
moved, bad = [], []
for r in scored:
    new, raw = strict_of(r['book'])
    old = r.get('strict') or ''
    if new != old:
        moved.append((r['book'], old or '—', new or '—', r['truth']))
    if not new:
        continue
    fire += 1
    if new == r['truth']:
        hit += 1
    else:
        wrong += 1
        bad.append((r['book'], new, r['truth'], raw))
print('e2e-E (تطوير) — محاسَبٌ %d/%d' % (len(scored), len(rows)))
print('  أطلق %d · إصابة %d · خاطئ %d · دقّةُ المُطلَق %.0f%% · صمت %d'
      % (fire, hit, wrong, (100.0 * hit / fire) if fire else 0.0, len(scored) - fire))
if bad:
    print('  الخاطئ:', bad)
print('  المتحرّكُ عن تشغيلة 08-30 (%d صفّاً):' % len(moved))
for m in moved:
    mark = '✅' if m[2] == m[3] else ('❌' if m[2] != '—' else '·')
    print('    %s %-6s %s ⟵ %s (حقيقة %s)' % (mark, m[0], m[1], m[2], m[3]))
regress = [m for m in moved if m[1] == m[3] and m[2] != m[3]]
print('  تراجعٌ صفّاً بصفّ (كان صحيحاً فصار غيرَه): %d %s'
      % (len(regress), regress if regress else '✅'))

# ══ e2e-D — الحارسُ المختوم ═══════════════════════════════════════════════
d = json.load(open(os.path.join(ROOT, 'e2e_D_results.json'), encoding='utf-8'))
d_fire, d_wrong, d_rows = 0, 0, []
for r in d:
    new, raw = strict_of(r['book'])
    if not new:
        continue
    d_fire += 1
    ok = new == norm(r.get('truth'))
    d_wrong += 0 if ok else 1
    d_rows.append(('✅' if ok else '❌', r['book'], new, norm(r.get('truth')), raw))
print('\ne2e-D (مختومة · حارسُ عدم التراجع) — أطلق %d/%d · خاطئ %d'
      % (d_fire, len(d), d_wrong))
for x in d_rows:
    print('    %s %-6s نصّيّ %-10s وسم %-10s (%s)' % x)
print('  البوّابة: إطلاق ≤ 2 %s · خاطئ = 0 %s'
      % ('✅' if d_fire <= 2 else '❌', '✅' if d_wrong == 0 else '❌'))
