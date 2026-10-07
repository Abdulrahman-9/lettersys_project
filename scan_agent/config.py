"""إعدادات وكيل المسح المحلي — قيم ثابتة وقوائم بيضاء (لا تُمرَّر مدخلات المستخدم خاماً)."""
import json
import os
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


def load_allowed_origins(path=None, warnings=None):
    """أصولُ محطّة العمل المسموح لها بتشغيل الماسح، من ``agent.json``.

    ``{"allowed_origins": ["http://192.0.2.10:8000"]}`` — يكتبه
    المُثبِّت مرّةً لكلّ حاسبة، فالكاتبةُ لا تكتب شيئاً. ملفٌّ مفقودٌ أو غيرُ مقروءٍ أو
    فاسدٌ ⟵ أصولُ الحلقة المحلّيّة وحدَها (حالةُ الجهاز الواحد كما هي اليوم) مع تحذيرٍ
    عند البدء. عنوانُ الخادم لا يُكتَب في هذا المستودع العامّ بحالٍ.
    """
    path = path or config_file()
    warn = warnings if warnings is not None else []
    raw_list = None
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except FileNotFoundError:
        warn.append("لا يوجد %s — الأصولُ المسموحة هي الحلقةُ المحلّيّة وحدَها." % path)
    except (OSError, ValueError) as exc:
        warn.append("تعذّر قراءة %s (%s) — الأصولُ المسموحة هي الحلقةُ المحلّيّة وحدَها." % (path, exc))
    else:
        raw_list = data.get("allowed_origins") if isinstance(data, dict) else None
        if not isinstance(raw_list, (list, tuple)):
            warn.append("%s بلا قائمة allowed_origins — الحلقةُ المحلّيّة وحدَها." % path)
            raw_list = None

    origins = set()
    for entry in (DEFAULT_ORIGINS if raw_list is None else raw_list):
        norm = normalize_origin(entry)
        if norm is None:
            warn.append("أصلٌ غير صالح في agent.json: %r — يُتجاهَل." % (entry,))
            continue
        origins.add(norm)
    if not origins:
        warn.append("قائمةُ الأصول خلت بعد التقنين — الحلقةُ المحلّيّة وحدَها.")
        origins = {normalize_origin(o) for o in DEFAULT_ORIGINS}
    return origins


ORIGIN_WARNINGS = []
# الأصولُ المسموحة (مجموعةُ tuples مُقنَّنة) — تُقرأ مرّةً عند الاستيراد؛ تغييرُ
# agent.json يحتاج إعادةَ تشغيل الوكيل (وهذا مذكورٌ في تعليمات الكاتبة).
ALLOWED_ORIGINS = load_allowed_origins(warnings=ORIGIN_WARNINGS)


def naps2_candidates():
    """مسارات NAPS2.Console.exe المحتملة بالأولوية (NAPS2_CONSOLE ثم المثبّت ثم المحمول)."""
    here = os.path.dirname(os.path.abspath(__file__))
    env = os.environ.get("NAPS2_CONSOLE")
    cands = [env] if env else []
    cands += [
        r"C:\Program Files\NAPS2\NAPS2.Console.exe",
        r"C:\Program Files (x86)\NAPS2\NAPS2.Console.exe",
        # تثبيتُ «لي وحدي» (بلا صلاحيّات مسؤول) — الشائعُ على حاسبة كاتبةٍ بحسابٍ عاديّ.
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "NAPS2", "NAPS2.Console.exe"),
        os.path.join(here, "naps2_portable", "NAPS2.Console.exe"),
    ]
    return [c for c in cands if c]
