"""إعدادات وكيل المسح المحلي — قيم ثابتة وقوائم بيضاء (لا تُمرَّر مدخلات المستخدم خاماً)."""
import os


def _split_csv(value):
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def get_host():
    """إرجاع عنوان الربط الخاص بالخادم: افتراضياً localhost، أو 0.0.0.0 عند الشبكة المحلية."""
    return os.environ.get("LETTERSYS_AGENT_HOST", "127.0.0.1")


def get_allowed_origins():
    """يُعيد قائمة الأصول المسموح بها، مع دعم URL التطبيق على الشبكة المحلية."""
    origins = {
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    }
    for env_name in (
        "LETTERSYS_AGENT_ALLOWED_ORIGINS",
        "LETTERSYS_ALLOWED_ORIGINS",
        "CSRF_TRUSTED_ORIGINS",
    ):
        origins.update(_split_csv(os.environ.get(env_name)))
    # دعم التطبيق الذي يفتح عبر IP الشبكة (مثلاً http://172.16.2.16:8000)
    for env_name in ("LETTERSYS_APP_URL", "LETTERSYS_DASHBOARD_URL", "DJANGO_BASE_URL"):
        value = os.environ.get(env_name)
        if value:
            origins.add(value.rstrip("/"))
    return sorted(origins)


HOST = get_host()
PORT = int(os.environ.get("LETTERSYS_AGENT_PORT", "17865"))

# الأصول المسموح لها باستدعاء الوكيل (مكافحة استغلال المتصفح / DNS-rebinding)
ALLOWED_ORIGINS = set(get_allowed_origins())

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

# token مشترك بين الوكيل وصفحة Django (Django يقرأ نفس الملف ويمرّره للصفحة)
TOKEN_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "LetterSys")
TOKEN_FILE = os.path.join(TOKEN_DIR, "agent_token.txt")


def naps2_candidates():
    """مسارات NAPS2.Console.exe المحتملة بالأولوية (NAPS2_CONSOLE ثم المثبّت ثم المحمول)."""
    here = os.path.dirname(os.path.abspath(__file__))
    env = os.environ.get("NAPS2_CONSOLE")
    cands = [env] if env else []
    cands += [
        r"C:\Program Files\NAPS2\NAPS2.Console.exe",
        r"C:\Program Files (x86)\NAPS2\NAPS2.Console.exe",
        os.path.join(here, "naps2_portable", "NAPS2.Console.exe"),
    ]
    return [c for c in cands if c]
