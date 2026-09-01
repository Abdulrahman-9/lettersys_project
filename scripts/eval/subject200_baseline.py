"""خطّ الأساس للموضوع على subject-200 — **جدولٌ لكلّ طبقة**، لا متوسّطٌ خام.

حكم فيبل: المجموعة طبقيّةٌ بحصصٍ مضمونة (وإلّا حضر الصادر الخارجيّ بكتابٍ واحد)، ولذلك
**متوسّطها الخام كذبة**. يُبلَّغ بجدولٍ لكلّ نوع + متوسّطٍ مُرجَّحٍ بنسب البِركة الحقيقيّة
(74/15/10/0.4). والصادر الخارجيّ (n=13) طبقةُ إنذارٍ: أعدادٌ خام لا نسب.

والمقياس رباعيّ لا رقم: متوسّط · صالح · صامت · **واثقٌ‑ومخطئ** (الأخير حارسُ ثقة الكاتب،
ولا يجوز أن يرتفع أبداً — الصمت أرخص من الكذب الواثق).
"""
import json, os, re, sys
PROJ = r"c:\Users\fwz\Downloads\lettersys_django_bootstrap_v4_scan\lettersys_django_bootstrap_v4_scan\lettersys_project"
sys.path.insert(0, PROJ); os.chdir(PROJ)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "lettersys.settings")
import django; django.setup()
from core.extraction.matchers.pattern import PatternMatcher
from core.models import Book

SRC = r"D:\migration\lettersys_models\subject_corpus\subject200.json"
OUT = r"D:\migration\lettersys_models\subject_probe\quad200.json"
CONF = {'marker': 0.75, 'bracket_ar': 0.0, 'bracket_en': 0.0, 'fallback': 0.35, '': 0.0}
POOL_W = {'incoming_internal': .74, 'outgoing_internal': .15,
          'incoming_external': .10, 'outgoing_external': .004}
_AR = re.compile(r"[^؀-ۿ0-9A-Za-z]+")
_ST = {"في","من","الى","إلى","على","عن","و","ال","the","of","for","and","to"}

def _n(s):
    s = s or ""
    for a, b in (("أ","ا"),("إ","ا"),("آ","ا"),("ى","ي"),("ة","ه"),("ـ","")):
        s = s.replace(a, b)
    return s

def T(s):
    return {t.lower() for t in _AR.split(_n(s).strip()) if len(t) >= 2 and t.lower() not in _ST}

def f1(a, b):
    A, B = T(a), T(b)
    if not A or not B: return 0.0
    i = len(A & B)
    return 0.0 if not i else 2*(i/len(A))*(i/len(B))/((i/len(A))+(i/len(B)))

pm = PatternMatcher()
rows = [r for r in json.load(open(SRC, encoding="utf-8")) if (r.get("text") or "").strip()]
kind = dict(Book.objects.filter(id__in=[r["book"] for r in rows]).values_list('id', 'kind'))
res = []
for r in rows:
    out = pm.extract_title_keywords(r["text"])
    src = getattr(pm, 'last_title_source', '') or ''
    lines = [l.strip() for l in r["text"].split("\n") if l.strip()]
    res.append({"book": r["book"], "kind": kind.get(r["book"], "?"),
                "f1": round(f1(out, r["db_title"]), 4), "src": src,
                "conf": CONF.get(src, 0.0),
                "orc": round(max((f1(l, r["db_title"]) for l in lines), default=0.0), 4),
                "out": out[:70], "db": r["db_title"][:70]})
os.makedirs(os.path.dirname(OUT), exist_ok=True)
json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

agg = {}
for x in res:
    a = agg.setdefault(x["kind"], {"n":0,"m":0.0,"u":0,"e":0,"c":0,"o":0.0})
    a["n"] += 1; a["m"] += x["f1"]; a["o"] += x["orc"]
    a["u"] += x["f1"] >= 0.5
    a["e"] += not x["out"].strip()
    a["c"] += (x["conf"] >= 0.75 and x["f1"] < 0.3)
print("خطّ الأساس · subject-200 · n=%d" % len(res))
print("%-20s %4s %7s %8s %8s %12s %7s" % ("النوع","n","mean","صالح","صامت","واثق-مخطئ","سقف"))
for k in sorted(agg):
    a = agg[k]; n = a["n"]
    warn = "  (إنذار)" if n < 20 else ""
    print("%-20s %4d %7.3f %6d/%-2d %6d/%-2d %8d/%-3d %7.3f%s" % (
        k, n, a["m"]/n, a["u"], n, a["e"], n, a["c"], n, a["o"]/n, warn))
wm = sum(POOL_W.get(k,0)*agg[k]["m"]/agg[k]["n"] for k in agg if agg[k]["n"])
wu = sum(POOL_W.get(k,0)*agg[k]["u"]/agg[k]["n"] for k in agg if agg[k]["n"])
wc = sum(POOL_W.get(k,0)*agg[k]["c"]/agg[k]["n"] for k in agg if agg[k]["n"])
wo = sum(POOL_W.get(k,0)*agg[k]["o"]/agg[k]["n"] for k in agg if agg[k]["n"])
tw = sum(POOL_W.get(k,0) for k in agg if agg[k]["n"])
print("\n**مُرجَّحٌ بالبِركة**  mean %.3f · صالح %.0f%% · واثق-مخطئ %.0f%% · سقف %.3f"
      % (wm/tw, 100*wu/tw, 100*wc/tw, wo/tw))
print("(المتوسّط الخام %.3f — **لا يُقتبَس**: الحصص مضمونة لا تناسبيّة)"
      % (sum(x["f1"] for x in res)/len(res)))
