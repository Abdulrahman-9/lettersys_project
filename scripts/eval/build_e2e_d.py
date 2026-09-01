# -*- coding: utf-8 -*-
"""بناءُ مجموعة **e2e-D** — المستنداتُ الرقميّة (طبقةُ نصّ) حيث C عمياء.

**لماذا مجموعةٌ منفصلة** (استشارة فيبل 2026-08-27): كاتبُ المطبوع (S4) والنقضُ
البنيويّ كلاهما يعيش حيث لا تراهما C — تعرُّضُهما فيها **خمسُ حالاتٍ فقط**، وهو
عجزٌ إحصائيٌّ يجعل «صفرَ أثرٍ» غيرَ دالٍّ لا أماناً. وe2e-D تسدّ دَينَ القياس هذا.

**الاختيارُ حتميٌّ ومُجمَّد**: ترتيبٌ بهاش ثابت، واستبعادُ المجموعات المختومة
كلِّها **ومنها الاثنا عشر إيميلاً التي قِيست تطويراً** (رُئيت وصُمّم عليها،
فاقتباسُها نتيجةً تسريبٌ). الوسمُ حقيقةُ القاعدة (`sender_number`) بتطبيعٍ مُثبَّت.

    python scripts/eval/build_e2e_d.py [عدد]
"""
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

import fitz  # noqa: E402
from django.db.models import Q  # noqa: E402
from core.models import Book  # noqa: E402

BASE = r'D:\migration\lettersys_models'
OUT = os.path.join(BASE, 'e2e_D_manifest.json')
N = int(sys.argv[1]) if len(sys.argv) > 1 else 50
DEV_SEEN = [11343, 11342, 11301, 11295, 11294, 11291, 11239, 11237, 11233, 11232,
            11231, 11226]        # الاثنا عشر التي قِيست تطويراً — لا تُقاس تقييماً


def sealed():
    ids = set(DEV_SEEN)
    try:
        e = json.load(open(os.path.join(BASE, 'e2e_manifest.json'), encoding='utf-8'))
        for k in ('A', 'B', 'C'):
            ids |= set(e['sets'][k])
        ids |= set(json.load(open(os.path.join(BASE, 'subject_corpus',
                                              'subject200_manifest.json'),
                                  encoding='utf-8'))['books'])
        ids |= set(json.load(open(os.path.join(BASE, 'clean_pool.json'), encoding='utf-8')))
        ids |= set(json.load(open(os.path.join(BASE, 'noise100_books.json'), encoding='utf-8')))
    except Exception as exc:
        raise SystemExit('مانيفستٌ مختومٌ مفقود (%s) — لا بناءَ بلا استثناءات'
                         % type(exc).__name__)
    return ids


def text_len(path):
    if not path.lower().endswith('.pdf'):
        return 0
    d = fitz.open(path)
    try:
        return len(d[0].get_text().strip())
    finally:
        d.close()


seal = sealed()
qs = (Book.objects.filter(is_deleted=False, attachments__isnull=False)
      .exclude(sender_number='').exclude(sender_number__isnull=True)
      .exclude(id__in=seal)
      .distinct().values_list('id', flat=True))
# **كلُّ مستندٍ رقميّ** لا الألفبائيَّ وحده: كاتبُ المطبوع يعمل على أيّ رقمٍ
# مطبوعٍ في الترويسة، وتضييقُ المرشِّح إلى `[A-Za-z]` أعطى 9 مرشّحين فقط —
# عيّنةٌ أضيقُ من أن تحكم.
cand = sorted(qs, key=lambda b: hashlib.md5(('e2ed-%s' % b).encode()).hexdigest())
print('مرشَّحون بعد استبعاد المختوم: %d' % len(cand), flush=True)

picked = []
for bid in cand:
    if len(picked) >= N:
        break
    try:
        b = Book.objects.get(id=bid)
        p = b.attachments.first().file.path
        if not os.path.exists(p) or text_len(p) < 200:
            continue        # مستندٌ رقميٌّ حصراً — طبقةُ نصٍّ معتبرة
        picked.append({'book': bid, 'truth': b.sender_number,
                       'entity': (b.issuing_entity_names or '')[:40]
                       if hasattr(b, 'issuing_entity_names') else ''})
    except Exception:
        continue

json.dump({'name': 'e2e-D', 'built': '2026-08-27', 'n': len(picked),
           'rule': 'digital PDFs (text layer >=200 chars) with any sender_number, '
                   'deterministic md5 order, sealed sets + 12 dev emails excluded',
           'gate': {'hit_rate_min': 0.55, 'wrong_rate_max': 0.15},
           'books': picked},
          open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('e2e-D: %d مستنداً ⟵ %s' % (len(picked), OUT))
