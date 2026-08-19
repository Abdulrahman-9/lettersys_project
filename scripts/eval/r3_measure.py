"""يقيس R3 (نقضُ سطر الإحالة في مسار العدد المطبوع) على نصّ e2e-A المحصود.

المسار المطبوع نصّيٌّ بحت، فالقياس هنا **مطابقٌ** لما سيحدث في الأنبوب — ومسار CRNN
لا يمسّه R3 فيبقى ثابتاً بالبناء. البوّابة المُسجَّلة سلفاً: الإصابات تبقى كما هي،
الخاطئ ≤ 8، واثق‑مخطئ ≤ 3.
"""
import json, os, sys
PROJ = r"c:\Users\fwz\Downloads\lettersys_django_bootstrap_v4_scan\lettersys_django_bootstrap_v4_scan\lettersys_project"
sys.path.insert(0, PROJ); os.chdir(PROJ)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "lettersys.settings")
import django; django.setup()
from core.extraction.matchers.pattern import PatternMatcher

_ARD = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')
def norm(v):
    return ''.join(c for c in str(v or '').translate(_ARD) if c.isdigit())

rows = json.load(open(r"D:\migration\lettersys_models\e2eA_text.json", encoding="utf-8"))
pm = PatternMatcher()
hit = wrong = silent = 0
fired = []
for r in rows:
    t = norm(r.get("truth"))
    if not t:
        continue
    val, conf = pm.extract_sender_number(r.get("text") or "")
    p = norm(val)
    if not p:
        silent += 1
    elif p == t:
        hit += 1; fired.append((r["book"], p, t, conf, True))
    else:
        wrong += 1; fired.append((r["book"], p, t, conf, False))
print("مسار العدد المطبوع على e2e-A (n=%d):" % sum(1 for r in rows if norm(r.get('truth'))))
print("  إصابة %d · خاطئ %d · صامت %d" % (hit, wrong, silent))
if len(sys.argv) > 1 and sys.argv[1] == '-v':
    for b, p, t, c, ok in fired:
        if not ok:
            print("   خاطئ %-6s قرأ %-8r والصحيح %-8r" % (b, p, t))
