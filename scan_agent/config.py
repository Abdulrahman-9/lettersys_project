"""إعدادات وكيل المسح المحلي — قيم ثابتة وقوائم بيضاء (لا تُمرَّر مدخلات المستخدم خاماً)."""
import json
import os
import sys
import threading
import time
from urllib.parse import urlsplit

HOST = "127.0.0.1"                                      # محلي فقط — لا وصول من الشبكة
PORT = int(os.environ.get("LETTERSYS_AGENT_PORT", "17865"))

# مضيفات Host المقبولة — حارسُ DNS-rebinding. المتصفّح يحلّ `localhost` داخلياً
# (RFC 6761) فلا يمكن لمهاجمٍ أن يوجّهه إلى غير الحلقة المحلّيّة، و`127.0.0.1` حرفيٌّ
# بلا DNS أصلاً. أيُّ اسمٍ آخر في ترويسة Host يعني ارتباطاً مُعاداً ⟵ يُرفض.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost"})

# أصولُ الحلقة المحلّيّة — الافتراضُ حين لا يوجد agent.json (استنساخٌ جديد أو
# كونسول الخادم نفسه): حالةُ «الجهاز الواحد» تعمل بصفر إعداد كما كانت.
DEFAULT_ORIGINS = ("http://127.0.0.1:8000", "http://localhost:8000")

# حدود التشغيل (ثوانٍ)
SCAN_TIMEOUT = 300
LIST_TIMEOUT = 60

# قوائم بيضاء لمعاملات NAPS2 — أي قيمة خارجها تُرفض
DRIVERS = {"twain", "wia", "escl"}
SOURCES = {"glass", "feeder", "duplex"}            # duplex = مسح الوجهين تلقائياً عبر ADF
# ترتيب المحاولة في المسح الأوتوماتيكي: الأغنى أولاً (وجهان ADF) ثم وجه ADF ثم الزجاج.
# إزالة الصفحات الفارغة لاحقاً تُحوّل المسح المزدوج لأحادي عند الحاجة → اكتشاف تلقائي
# للوجه/الوجهين. كما يحلّ خطأ "0 pages scanned" حين يكون المُغذّي فارغاً/المستند على الزجاج.
AUTO_SOURCE_ORDER = ("duplex", "feeder", "glass")
COLORS = {"color": "color", "gray": "gray", "bw": "bw"}   # تعيين قيم --bitdepth الصحيحة
ROTATIONS = {0, 90, 180, 270}                      # تدوير ثابت بالدرجات (مع الورق المقلوب)
DPI_MIN, DPI_MAX = 100, 600


# ════════════ مجلّد بيانات الوكيل على محطّة العمل ════════════
# يُشتقّ من %LOCALAPPDATA% لا من __file__: في نمط PyInstaller onefile يشير __file__
# إلى مجلّد استخراجٍ مؤقّت (%TEMP%\_MEIxxxxxx) يُنشَأ ويُحذَف مع كلّ تشغيل، فأيُّ ملفّ
# إعدادٍ يُبحَث عنه هناك لا يُوجَد أبداً ولا يستطيع أحدٌ تحريره.
# الدوالُّ تقرأ البيئة عند النداء (لا عند الاستيراد) كي يمكن قياسُها بمجلّدٍ مؤقّت.

def data_dir():
    """مجلّد إعدادات الوكيل وسجلّه: ‎%LOCALAPPDATA%\\LetterSys‎ (أو المنزل خارج ويندوز)."""
    return os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "LetterSys")


def config_file():
    """ملفُّ إعداد محطّة العمل: ‎%LOCALAPPDATA%\\LetterSys\\agent.json‎ (يكتبه المُثبِّت)."""
    return os.path.join(data_dir(), "agent.json")


def log_file():
    """سجلُّ الوكيل — يبقى بعد إغلاق النافذة، وفيه سطرُ الأصل المرفوض للتشخيص."""
    return os.path.join(data_dir(), "agent.log")


# ════════════ أصولُ الاستدعاء المسموحة ════════════
_DEFAULT_PORTS = {"http": 80, "https": 443}


def normalize_origin(raw):
    """‎(scheme, host, port)‎ لأصلٍ صالح، أو ``None`` إن لم يكن أصلاً صريحاً.

    المنفذُ الافتراضيّ يُملأ (80/443) كي يتساوى ``http://lettersys`` — وهو ما يرسله
    المتصفّح فعلاً على المنفذ 80 — مع ``http://lettersys:80`` في agent.json، والمضيفُ
    يُصغَّر فيتساوى ``http://LETTERSYS``. تُرفض: القيمُ بلا مخطّط، ومسارٌ أو استعلام،
    و``*``، والفراغُ وأيُّ محرف تحكّم (كي لا يُحقَن سطرُ ترويسةٍ عند إعادة الأصل في ACAO).
    المقارنةُ بعد ذلك مساواةُ tuple تامّة — لا بادئةً ولا احتواءً — فلا يمرّ
    ``http://192.0.2.10:8000.evil.com``.
    """
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s or "*" in s:
        return None
    if any(ord(c) < 0x21 or ord(c) == 0x7F for c in s):
        return None
    if s.endswith("/"):
        s = s[:-1]                                  # لا شيءَ بعد المضيف ⟵ الشرطةُ المفردة تُقنَّن
    try:
        parts = urlsplit(s)
    except ValueError:
        return None
    scheme = (parts.scheme or "").lower()
    if scheme not in _DEFAULT_PORTS:
        return None
    if parts.path or parts.query or parts.fragment or parts.username or parts.password:
        return None
    try:
        host = (parts.hostname or "").lower()
        port = parts.port or _DEFAULT_PORTS[scheme]
    except ValueError:                               # منفذٌ غير رقميّ
        return None
    if not host:
        return None
    return (scheme, host, port)


def describe_origin(norm):
    """صياغةُ ‎(scheme, host, port)‎ للعرض: يُخفى المنفذُ الافتراضيّ كما يفعل المتصفّح."""
    scheme, host, port = norm
    if _DEFAULT_PORTS.get(scheme) == port:
        return "%s://%s" % (scheme, host)
    return "%s://%s:%d" % (scheme, host, port)


def _default_origins():
    return frozenset(normalize_origin(o) for o in DEFAULT_ORIGINS)


_PAIRING_UNKNOWN = "unknown"     # الملفُّ لم يُحلَّل (فاسدٌ أو مقفل) — لا نعرف ما فيه
_PAIRING_INVALID = "invalid"     # حُلِّل لكنّ require_pairing ليست true/false


def _read_origins(path):
    """قراءةٌ واحدةٌ لـ``agent.json`` ⟵ ‎(kind, origins, warnings, pairing)‎ — بلا قرارٍ في البديل.

    ``kind``: ``ok`` (قائمةٌ صالحة؛ والقائمةُ الصريحةُ الفارغة ``[]`` = الحلقةُ المحلّيّة)
    · ``missing`` · ``unreadable`` · ``invalid_json`` · ``no_list`` · ``no_valid_entries``.
    وفي غير ``ok`` تكون ``origins`` ‏``None``: البديلُ يختلف بين الإقلاع وإعادة التحميل،
    فيقرّره المستدعي لا القارئ. و``pairing`` علامةُ الحاسبة المُدارة من القراءة نفسها
    (‏True/False، أو ``_PAIRING_INVALID``/``_PAIRING_UNKNOWN``) — يحسمها ``requires_pairing``.
    """
    warns = []
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except FileNotFoundError:
        warns.append("لا يوجد %s." % path)
        return "missing", None, warns, False
    except ValueError as exc:                     # JSON فاسد أو ترميزٌ ليس UTF-8
        warns.append("تعذّر تحليل %s (%s)." % (path, exc))
        return "invalid_json", None, warns, _PAIRING_UNKNOWN
    except OSError as exc:                        # صلاحيّةٌ أو قفلٌ عابر: خطأٌ لا حذف
        warns.append("تعذّرت قراءة %s (%s)." % (path, exc))
        return "unreadable", None, warns, _PAIRING_UNKNOWN
    pairing = _PAIRING_INVALID
    if isinstance(data, dict):
        flag = data.get("require_pairing", False)
        if type(flag) is bool:
            pairing = flag
    raw_list = data.get("allowed_origins") if isinstance(data, dict) else None
    if not isinstance(raw_list, (list, tuple)):
        warns.append("%s بلا قائمة allowed_origins." % path)
        return "no_list", None, warns, pairing
    origins = set()
    for entry in raw_list:
        norm = normalize_origin(entry)
        if norm is None:
            warns.append("أصلٌ غير صالح في agent.json: %r — يُتجاهَل." % (entry,))
            continue
        origins.add(norm)
    if origins:
        return "ok", frozenset(origins), warns, pairing
    if raw_list:
        warns.append("كلُّ مدخلات allowed_origins غير صالحة.")
        return "no_valid_entries", None, warns, pairing
    warns.append("قائمةُ allowed_origins فارغة — الحلقةُ المحلّيّة وحدَها.")
    return "ok", _default_origins(), warns, pairing


def load_allowed_origins(path=None, warnings=None):
    """أصولُ محطّة العمل المسموح لها بتشغيل الماسح، من ``agent.json`` — بدلالة الإقلاع.

    ``{"allowed_origins": ["http://192.0.2.10:8000"]}`` — يكتبه المُثبِّت مرّةً لكلّ
    حاسبة، فالكاتبةُ لا تكتب شيئاً. ملفٌّ مفقودٌ أو غيرُ مقروءٍ أو فاسدٌ ⟵ أصولُ الحلقة
    المحلّيّة وحدَها (حالةُ الجهاز الواحد) مع تحذير. عنوانُ الخادم لا يُكتَب في هذا
    المستودع العامّ بحالٍ. (أثناء العمل تسري ``allowed_origins()`` لا هذه.)
    """
    kind, origins, warns, _pairing = _read_origins(path or config_file())
    if warnings is not None:
        warnings.extend(warns)
    return set(origins if kind == "ok" else _default_origins())


# ════════════ القائمةُ الحيّة — تعديلُ agent.json يسري بلا إعادة تشغيل ════════════
# كانت القائمةُ تُقرأ مرّةً عند الاستيراد، فكلُّ تعديلٍ يحتاج إعادةَ تشغيل الوكيل — وعلى
# ويندوز كانت «إعادةُ التشغيل» تُبقي النسخةَ القديمة حيّةً تردّ بقائمتها القديمة (مقيسٌ
# 2026-11-16: ثلاثُ نسخٍ على المنفذ نفسه). الآن قبل كلّ طلبٍ تُقارَن بصمةُ الملفّ
# ‎(ino, mtime_ns, size)‎ بما قُرئ آخرَ مرّة، فإن تغيّرت أُعيدت القراءة:
#   - ملفٌّ صالح ⟵ قائمتُه، ويُمحى أيُّ خطأٍ سابق.
#   - ملفٌّ حُذف ⟵ الحلقةُ المحلّيّة وحدَها: **الحذفُ هو طريقُ الإلغاء المتعمَّد**.
#   - فاسدٌ / بلا قائمة / كلُّ مدخلاته مرفوضة / تعذّرت قراءتُه ⟵ تبقى آخرُ قائمةٍ صالحة،
#     ويُكشَف رمزُ الخطأ في /agent/health فتعرضه الصفحةُ توستاً (أصلُها ما زال مسموحاً
#     فتقرؤه). الحفظُ في Notepad وSet-Content يمرّ بلحظةٍ يكون فيها الملفُّ فارغاً أو نصفَ
#     مكتوب، فلو سقطت الثقةُ معها لانقطع المسحُ مع كلّ حفظ. الثمنُ مقبولٌ ومكشوف: إلغاءُ
#     أصلٍ بتعديلٍ فيه خطأ لا يسري حتّى يُصلَح الملفّ أو يُحذف.
#   - عند الإقلاع لا «أخيرَ صالح»: الفاسدُ ⟵ الحلقةُ المحلّيّة كما كان دائماً.
# البصمةُ تُؤخذ **قبل** القراءة وتُحفظ حتّى عند الفشل: ملفٌّ تغيّر بين الفحص والقراءة
# تختلف بصمتُه في الطلب التالي فيُقرأ من جديد، وملفٌّ فاسدٌ ثابت لا يُعاد تحليلُه مع كلّ طلب.

class _Snapshot:
    __slots__ = ("path", "signature", "origins", "error", "generation", "warnings", "pairing")

    def __init__(self, path, signature, origins, error, generation, warnings, pairing):
        self.pairing = pairing                    # كما قُرئ — يحسمه requires_pairing()
        self.path = path
        self.signature = signature
        self.origins = origins                    # frozenset — يُستبدَل كلُّه ولا يُعدَّل
        self.error = error                        # رمزٌ ثابتٌ أو None
        self.generation = generation              # يزيد مع كلّ تغيّرٍ في القائمة
        self.warnings = warnings


_LIVE_LOCK = threading.Lock()
_live = None


def _file_signature(path):
    """بصمةُ الملفّ قبل قراءته — ``None`` إن غاب."""
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return None
    except OSError as exc:
        return ("stat_error", exc.errno)
    return (st.st_ino, st.st_mtime_ns, st.st_size)


def _current():
    path = config_file()
    sig = _file_signature(path)
    snap = _live
    if snap is not None and snap.path == path and snap.signature == sig:
        return snap
    with _LIVE_LOCK:
        snap = _live
        if snap is not None and snap.path == path and snap.signature == sig:
            return snap
        return _reload(path, sig, snap)


def _reload(path, sig, prev):
    global _live
    kind, origins, warns, pairing = _read_origins(path)
    same_file = prev is not None and prev.path == path
    if kind == "ok":
        error = None
    elif kind == "missing":
        origins, error = _default_origins(), None
    elif same_file:
        origins, error = prev.origins, kind       # آخرُ قائمةٍ صالحة
    else:
        origins, error = _default_origins(), kind  # الإقلاع: لا أخيرَ صالح
    generation = prev.generation if prev is not None else 0
    if prev is None or origins != prev.origins:
        generation += 1
    snap = _Snapshot(path, sig, origins, error, generation, tuple(warns), pairing)
    if same_file:
        _note_reload(prev, snap, kind)
    _live = snap
    return snap


def _note_reload(prev, snap, kind):
    """سطرٌ في السجلّ لكلّ تغيّرٍ فعليّ (تحت pythonw يذهب stderr إلى agent.log)."""
    listed = "، ".join(sorted(describe_origin(o) for o in snap.origins))
    if snap.error:
        if snap.error == prev.error:
            return
        line = "agent.json فيه خطأ (%s) — بقيت القائمةُ السابقة حتّى يُصلَح: %s" % (snap.error, listed)
    elif kind == "missing":
        if prev.origins == snap.origins:
            return
        line = "حُذف agent.json — الأصولُ المسموحة الآن الحلقةُ المحلّيّة وحدَها: %s" % listed
    elif snap.origins != prev.origins or prev.error:
        line = "أُعيدت قراءةُ agent.json بلا إعادة تشغيل — الأصولُ المسموحة الآن: %s" % listed
    else:
        return
    stream = sys.stderr
    if stream is None:
        return
    stream.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), line))
    for w in snap.warnings:
        stream.write("  - %s\n" % w)


def allowed_origins():
    """الأصولُ المسموحة **الآن** (frozenset مُقنَّنة) — المصدرُ الوحيدُ لكلّ مَن يحرس بها."""
    return _current().origins


def origin_status():
    """ما يُكشَف في /agent/health: رمزُ خطأ الإعداد إن وُجد (نصُّه في الصفحة لا هنا)."""
    snap = _current()
    error = snap.error
    if error is None and snap.pairing == _PAIRING_INVALID:
        error = "invalid_pairing"
    return {"config_error": error}


def origin_warnings():
    return list(_current().warnings)


def origins_generation():
    return _current().generation


class AgentConfigError(ValueError):
    """agent.json لا يحدّد وضعَ الجهاز: ``require_pairing`` ليست true/false (أو الملفُّ فاسدٌ
    عند الإقلاع). صنفٌ خاصّ كي لا يخرج من /agent/scan «طلباً خاطئاً» بنصٍّ إنكليزيّ."""


# الوضعُ المُدار لهذه العمليّة، لكلّ مسارِ إعداد — **مصدرٌ واحد** لـNAPS2 (naps2_candidates)
# ولمراقب الجهاز (workstation.py): كانا يقرآن العلامةَ كلٌّ بطريقته، وأحدُهما يجمّدها عند
# الإقلاع والآخرُ يقرؤها حيّةً. يتصاعد حيّاً (false ⟵ true: المُثبِّت يكتبها قبل التشغيل)
# ولا ينزل إلّا بإعادة تشغيل: نزولُه حيّاً كان يفتح ``NAPS2_CONSOLE`` القديمَ لحاسبةٍ مُدارة.
_PAIRING_MODE = {}


def requires_pairing():
    """هل هذه حاسبةٌ مُدارة (لا تسحب ورقاً قبل ربطها)؟ من القائمة الحيّة نفسها.

    ملفٌّ مفقود ⟵ لا. قيمةٌ ليست true/false ⟵ ``AgentConfigError`` (لا تُعامَل «قديمة»).
    ملفٌّ فاسدٌ أو مقفلٌ أثناء العمل (حفظٌ نصفُ مكتوب) ⟵ آخرُ وضعٍ صالح؛ وعند الإقلاع
    ⟵ ``AgentConfigError`` كما كان.
    """
    snap = _current()
    mode = _PAIRING_MODE.get(snap.path)
    if mode is True:
        return True
    if snap.pairing is True or snap.pairing is False:
        _PAIRING_MODE[snap.path] = snap.pairing
        return snap.pairing
    if snap.pairing == _PAIRING_UNKNOWN and mode is False:
        return False
    raise AgentConfigError(
        "ملفّ إعداد الوكيل لا يحدّد وضعَ الجهاز (require_pairing) — أعد تشغيل مُثبِّت LetterSys.")


def naps2_candidates():
    """الحزمة المُدارة تستخدم نسختها فقط؛ التثبيت القديم يحافظ على أولوياته."""
    here = os.path.dirname(os.path.abspath(__file__))
    portable = os.path.join(here, "naps2_portable", "NAPS2.Console.exe")
    if requires_pairing():
        return [portable]
    env = os.environ.get("NAPS2_CONSOLE")
    cands = [env] if env else []
    cands += [
        r"C:\Program Files\NAPS2\NAPS2.Console.exe",
        r"C:\Program Files (x86)\NAPS2\NAPS2.Console.exe",
        # تثبيتُ «لي وحدي» (بلا صلاحيّات مسؤول) — الشائعُ على حاسبة كاتبةٍ بحسابٍ عاديّ.
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "NAPS2", "NAPS2.Console.exe"),
        portable,
    ]
    return [c for c in cands if c]
