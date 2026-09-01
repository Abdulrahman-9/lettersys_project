# -*- coding: utf-8 -*-
"""بناءُ مجموعة **e2e-E** — صفُّ الجهات ذاتِ المرجع المطبوع (NK · EBS · ADO).

**لماذا مجموعةٌ ثالثة**: المسارُ الصارم (`strict_ref_match`) يستهدف هذا الصفَّ
وحدَه، والاثنا عشر إيميلاً التي ضُبط عليها **مرئيّةٌ ومصمَّمٌ عليها** — فاقتباسُها
نتيجةً تسريبٌ. وe2e-D تقيس عدمَ التسرّب خارج الصفّ، وهذه تقيس القيمةَ داخله.

**الاختيارُ حتميٌّ ومُجمَّد**: ترتيبٌ بهاش ثابت، واستبعادُ كلِّ المجموعات المختومة
(A/B/C/D · subject200 · clean_pool · noise100) والاثني عشر.

**بلا اشتراطِ طبقةِ نصّ عمداً**: مستندُ NK ممسوحٌ بلا نصٍّ يُصمِت المسارَ الصارم
ويرثه البصريّ — وذاك هو الإنتاجُ حرفيّاً. تصفيةُ العيّنة إلى ما يملك نصّاً تقيس
المسارَ على تربته المفضّلة لا على عمله.

    python scripts/eval/build_e2e_e.py [عدد]
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

from core.models import Book, Entity  # noqa: E402

BASE = r'D:\migration\lettersys_models'
OUT = os.path.join(BASE, 'e2e_E_manifest.json')
N = int(sys.argv[1]) if len(sys.argv) > 1 else 60
DEV_SEEN = [11343, 11342, 11301, 11295, 11294, 11291, 11239, 11237, 11233, 11232,
            11231, 11226]
ENTITY_NAMES = ('NK Petroleum', 'EBS PETROLEUM', 'EBS Petroleum', 'ado digital energy')


def sealed():
    ids = set(DEV_SEEN)
    e = json.load(open(os.path.join(BASE, 'e2e_manifest.json'), encoding='utf-8'))
    for k in ('A', 'B', 'C'):
        ids |= set(e['sets'][k])
    ids |= set(r['book'] for r in json.load(
        open(os.path.join(BASE, 'e2e_D_manifest.json'), encoding='utf-8'))['books'])
    ids |= set(json.load(open(os.path.join(BASE, 'subject_corpus',
                                          'subject200_manifest.json'),
                              encoding='utf-8'))['books'])
    ids |= set(json.load(open(os.path.join(BASE, 'clean_pool.json'), encoding='utf-8')))
    ids |= set(json.load(open(os.path.join(BASE, 'noise100_books.json'), encoding='utf-8')))
    return ids


ent_ids = set()
for n in ENTITY_NAMES:
    ent_ids |= set(Entity.objects.filter(name__icontains=n).values_list('id', flat=True))

seal = sealed()
qs = (Book.objects.filter(is_deleted=False, issuing_entities__id__in=ent_ids,
                          attachments__isnull=False)
      .exclude(sender_number='').exclude(sender_number__isnull=True)
      .exclude(id__in=seal).distinct().values_list('id', flat=True))
cand = sorted(qs, key=lambda b: hashlib.md5(('e2ee-%s' % b).encode()).hexdigest())
print('مرشَّحون بعد استبعاد %d مختوماً: %d' % (len(seal), len(cand)), flush=True)

picked = []
for bid in cand:
    if len(picked) >= N:
        break
    b = Book.objects.get(id=bid)
    att = b.attachments.first()
    if not att or not os.path.exists(att.file.path):
        continue
    picked.append({'book': bid, 'truth': b.sender_number,
                   'entity': ' / '.join(e.name for e in b.issuing_entities.all()[:1])})

json.dump({'name': 'e2e-E', 'built': '2026-08-30', 'n': len(picked),
           'rule': 'books of approved-prefix entities (NK / EBS / ADO) with any '
                   'sender_number and an existing attachment; deterministic md5 '
                   'order; sealed sets A/B/C/D + subject200 + clean_pool + '
                   'noise100 + the 12 dev emails excluded; NO text-layer filter',
           'books': picked},
          open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('e2e-E: %d مستنداً ⟵ %s' % (len(picked), OUT))
