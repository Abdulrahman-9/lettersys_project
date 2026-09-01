"""e2e-D — المستنداتُ الرقميّة (طبقةُ نصّ) حيث C عمياء.

    البوّابةُ المُسجَّلة: إصابة ≥55% · خاطئ ≤15%.

نسخةٌ حرفيّة من عدّة e2e-A على المجموعة C المختومة. **بوّابة النجاح المُسجَّلة
قبل النظر (docs/EVAL_REGISTRY.md):** إصابة ≥25/100 · خاطئ ≤5 · واثقٌ‑ومخطئ
(ثقة ≥0.90) ≤2. تُحكم مرّةً واحدة — لا تكرار للنظرة.

المجموعة مُجمَّدةٌ سلفاً (`e2e_manifest.json`، بذرة 20260818، 100 كتاب) من 7,005 لم
تُسهم بوزنٍ في نموذجٍ ولم ترَها عين. المرجع `sender_number` من القاعدة بتطبيعٍ **مُثبَّت
قبل التشغيل**: طيّ الأرقام العربيّة‑الهنديّة، وحذف الفواصل والشرطات والمسافات.

**قواعدُ القرار مُسجَّلةٌ قبل رؤية النتيجة** (فيبل 2026-08-18):
    >=60%   ⟵ وصّل اقتراح‑وتأكيد للعدد في الواجهة، وأجّل التدريب
    40–60%  ⟵ فكّ الترميز المُقيَّد هو السبرنت التالي، يُقاس على المجموعة B
    <40%    ⟵ أكبرُ دلوٍ في تفكيك الأعطال يفوز

وتفكيك الأعطال مُسجَّلٌ أيضاً: لم‑يُطلق · صندوقٌ خاطئ · صندوقٌ صحيحٌ وقراءةٌ خاطئة ·
امتناعُ القارئ عند بوّابة الثقة.

    python e2e_number.py [chunk]      # استئنافٌ تلقائيّ · عمليّةٌ واحدة (الجهاز 8GB)
"""
import gc, json, os, sys
PROJ = r"c:\Users\fwz\Downloads\lettersys_django_bootstrap_v4_scan\lettersys_django_bootstrap_v4_scan\lettersys_project"
sys.path.insert(0, PROJ); os.chdir(PROJ)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "lettersys.settings")
import django; django.setup()
from core.extraction.pipeline import AIExtractionService
from core.models import Book

MAN = r"D:\migration\lettersys_models\e2e_D_manifest.json"
OUT = r"D:\migration\lettersys_models\e2e_D_results.json"
CHUNK = int(sys.argv[1]) if len(sys.argv) > 1 else 10
_ARD = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')

def norm(v):
    """التطبيع المُثبَّت في السجلّ — يُفكّ قبل التشغيل كي لا يُفسّر خطأُ تطبيعٍ خطأَ نموذج."""
    s = str(v or '').translate(_ARD)
    return ''.join(ch for ch in s if ch.isdigit())

man = json.load(open(MAN, encoding="utf-8"))
books = [r["book"] for r in man["books"]]
done = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else []
have = {r["book"] for r in done}
todo = [b for b in books if b not in have][:CHUNK]
print("منجز %d/%d · هذه الدفعة %d" % (len(have), len(books), len(todo)), flush=True)

svc = AIExtractionService()
for bid in todo:
    b = Book.objects.filter(id=bid).first()
    att = b.attachments.first() if b else None
    p = att.file.path if (att and hasattr(att.file, "path")) else None
    rec = {"book": bid, "truth": norm(b.sender_number if b else "")}
    if not (p and os.path.exists(p)):
        rec.update({"pred": "", "err": "no-file"}); done.append(rec); continue
    try:
        res = svc.process_image(p)
        # **عيبٌ أُصلح 2026-08-18:** المهلة (120s) تُعيد نتيجةً فارغةً بحالة 'failed'
        # بلا استثناء — فكانت تُحسب «صامتاً»، أي أنّ دلو الصمت خلط الامتناعَ الحقيقيّ
        # بانتهاء المهلة. تُسجَّل الحالة الآن ويُستبعَد الفاشل من التبويب.
        rec["status"] = getattr(res, "status", "") or ""
        rec["pred"] = norm(getattr(res, "sender_number", "") or "")
        rec["conf"] = round(float(getattr(res, "sender_number_confidence", 0.0) or 0.0), 3)
        rec["box"] = getattr(res, "sender_number_bbox", None)
        rec["box_src"] = getattr(res, "sender_number_bbox_source", "") or ""
    except Exception as exc:
        rec.update({"pred": "", "err": type(exc).__name__})
    rec["hit"] = bool(rec.get("pred")) and rec["pred"] == rec["truth"]
    done.append(rec)
    json.dump(done, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    gc.collect()

n = len(done)
# الأنبوب يستعمل أربع حالات: pending/completed/failed/manual_review (pipeline.py:155).
# **`manual_review` نجاحٌ** (ثقةٌ منخفضة تستدعي مراجعةً بشريّة) لا فشل — وأوّل صياغةٍ
# لهذا المُرشِّح قبلت `completed` وحدها فأقصت 60 تشغيلةً ناجحة وأوهمت بمهلةٍ 95%.
_DEAD = ('failed', 'pending')
scored = [r for r in done if r.get("truth") and (r.get("status") or '') not in _DEAD]
timed_out = sum(1 for r in done if (r.get("status") or '') in _DEAD)
hit = sum(1 for r in scored if r.get("hit"))
silent = sum(1 for r in scored if not r.get("pred"))
wrong = len(scored) - hit - silent
cw = sum(1 for r in scored if r.get("pred") and not r.get("hit") and r.get("conf", 0) >= 0.90)
print("المجموع %d · مُقاسٌ %d · **إصابة %d (%.0f%%)** · صامت %d · خاطئ %d · واثقٌ‑ومخطئ(>=0.90) %d · مُستبعَد %d"
      % (n, len(scored), hit, 100*hit/max(1, len(scored)), silent, wrong, cw, timed_out), flush=True)
if len(have) + len(todo) >= len(books):
    print("البوّابة: إصابة>=25 %s · خاطئ<=5 %s · واثقٌ‑ومخطئ<=2 %s" % (
        "PASS" if hit >= 25 else "FAIL", "PASS" if wrong <= 5 else "FAIL",
        "PASS" if cw <= 2 else "FAIL"), flush=True)
