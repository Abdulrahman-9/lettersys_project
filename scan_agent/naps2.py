"""غلاف NAPS2.Console — تحديد الموقع، سرد الأجهزة، المسح إلى PDF.

كل دالة صغيرة ومستقلة وقابلة للاختبار. الفشل يُرفَع كاستثناء واضح
(RuntimeError لأخطاء التشغيل، ValueError لمدخلات غير صالحة) لا كصمت.
"""
import os
import re
import subprocess
import tempfile

from . import config


def locate_exe():
    """يُعيد مسار NAPS2.Console.exe أول ما يُوجَد، أو None."""
    for path in config.naps2_candidates():
        if os.path.isfile(path):
            return path
    return None


def list_devices(driver="twain"):
    """أسماء الأجهزة المتصلة لسائق معيّن (قائمة قد تكون فارغة = لا أجهزة)."""
    exe = _require_exe()
    if driver not in config.DRIVERS:
        raise ValueError("سائق غير مدعوم")
    try:
        proc = subprocess.run(
            [exe, "--listdevices", "--driver", driver],
            capture_output=True, text=True, timeout=config.LIST_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("انتهت مهلة سرد الأجهزة")
    return [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()]


class ScanNoPagesError(RuntimeError):
    """لم تُلتقط أي صفحة (مُغذّي فارغ / مستند على الزجاج / مصدر غير مدعوم).

    إشارة للمسح الأوتوماتيكي كي يجرّب المصدر التالي بدل الفشل النهائي.
    """


class ScanTimeoutError(Exception):
    """انتهت مهلة المسح — الجهاز معلّق/لا يستجيب. **ليست** RuntimeError عمداً كي لا
    يبتلعها cascade المصدر فيكرّر 300ث على كل مصدر؛ يجب أن تفشل فوراً (fail-fast).
    """


class ScanDeviceError(Exception):
    """خطأ تعريف/عتاد صلب (الماسح غير جاهز/مستخدَم من برنامج آخر: -4400/-4539…).
    **ليست** RuntimeError عمداً: يجب أن تفشل فوراً بلا تجريب بقية المصادر، وإلا
    تُظهر حواريّة تعريف أصليّة لكل مصدر (تكرار مزعج). حواريّة واحدة تكفي.
    """


# علامات خطأ تعريف/عتاد صلب (لا يُجدي معها تبديل المصدر) — تُفشِل المسح الأوتوماتيكي فوراً.
_DEVICE_ERROR_MARKERS = (
    "-4400", "-4539", "not ready", "in use", "another program",
    "power may have been cycled", "device is busy", "is busy",
)


def _is_device_error(text):
    t = (text or "").lower()
    return any(m in t for m in _DEVICE_ERROR_MARKERS)


# علامات مخرجات NAPS2 الدالة على «صفر صفحات» (أساس خطأ المستخدم
# "0 page(s) scanned. No scanned pages to export.")
_NO_PAGE_MARKERS = ("no scanned pages", "no pages", "nothing to export")


def _is_no_pages(text):
    t = (text or "").lower()
    if any(m in t for m in _NO_PAGE_MARKERS):
        return True
    # «0 صفحة» بحدود كلمات كي لا يطابق «10 pages» / «100 pages» (تطابق جزئي خاطئ)
    return re.search(r"\b0 pages?\b", t) is not None


def _run_scan(exe, device, source, dpi, color, driver, deskew=True, rotate=0):
    """ينفّذ محاولة مسح واحدة بمصدر محدّد. يُعيد مسار PDF عند النجاح.

    يرفع ScanNoPagesError إن لم تُلتقط صفحات (لينتقل الأوتوماتيكي للمصدر التالي)،
    وRuntimeError لأخطاء التشغيل الأخرى. على المُستدعي حذف الملف بعد الاستخدام.
    """
    fd, out_path = tempfile.mkstemp(suffix=".pdf", prefix="lettersys_scan_")
    os.close(fd)
    cmd = [
        exe, "--noprofile",            # إلزامي عند تمرير أعلام الجهاز مباشرةً
        "--driver", driver, "--device", device,
        "--source", source, "--dpi", str(dpi),
        "--bitdepth", config.COLORS[color], "--pagesize", "a4",
    ]
    if deskew:
        cmd.append("--deskew")         # تقويم الميل تلقائياً (جودة أفضل، آمن دائماً)
    if rotate:
        cmd += ["--rotate", str(rotate)]
    cmd += ["-o", out_path, "--force", "--verbose"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=config.SCAN_TIMEOUT)
    except subprocess.TimeoutExpired:
        safe_remove(out_path)
        # ليست RuntimeError: تُفشِل المسح الأوتوماتيكي فوراً بدل تكرار المهلة على كل مصدر
        raise ScanTimeoutError("انتهت مهلة المسح — الماسح لا يستجيب")

    # نجاح حقيقي = رمز خروج صفر + ملف غير فارغ (NAPS2 قد يكتب على stderr مع رمز 0)
    if proc.returncode == 0 and os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
        return out_path

    safe_remove(out_path)
    output = ((proc.stderr or "") + "\n" + (proc.stdout or "")).strip()
    if _is_no_pages(output) or (proc.returncode == 0 and not output):
        # rc=0 بلا ملف ولا مخرجات = فخّ NAPS2 الصامت = لا صفحات فعلياً
        raise ScanNoPagesError(output or "لم تُلتقط صفحات من هذا المصدر")
    if _is_device_error(output):
        # خطأ عتاد/تعريف صلب — لا يُجدي معه تبديل المصدر، فيفشل فوراً (حواريّة واحدة لا ثلاث)
        raise ScanDeviceError(
            "الماسح غير جاهز أو مستخدَم من برنامج آخر. أغلق برامج المسح الأخرى "
            "(مثل CaptureOnTouch)، وأطفئ الماسح ثم شغّله (إعادة تدوير الطاقة)، ثم أعد المحاولة."
        )
    raise RuntimeError(output or "فشل المسح (لا مخرجات — تحقّق من الورق والجهاز)")


def scan_to_pdf(device, source="feeder", dpi=300, color="color", driver="twain",
                deskew=True, rotate=0):
    """مسح بمصدر محدّد (واجهة متوافقة رجعياً). يُعيد مسار PDF مؤقت.

    للمسح الأوتوماتيكي الذي يكتشف المصدر تلقائياً استخدم scan_to_pdf_auto.
    """
    exe = _require_exe()
    if not device:
        raise ValueError("لم يُحدَّد جهاز")
    if driver not in config.DRIVERS:
        raise ValueError("سائق غير مدعوم")
    if source not in config.SOURCES:
        raise ValueError("مصدر غير مدعوم")
    if color not in config.COLORS:
        raise ValueError("عمق لون غير مدعوم")
    rotate = _clamp_rotate(rotate)
    dpi = _clamp_dpi(dpi)
    return _run_scan(exe, device, source, dpi, color, driver, deskew, rotate)


def scan_to_pdf_auto(device, driver="twain", dpi=300, color="color"):
    """مسح أوتوماتيكي بالكامل — يكتشف المصدر المناسب حسب المستند والماسح.

    يجرّب المصادر بالترتيب (وجهان ADF → وجه ADF → زجاج) ويتوقّف عند أول نجاح.
    هذا يحلّ من الجذر خطأ «0 pages scanned / No scanned pages to export» الذي يقع
    حين يُطلب مصدرٌ خاطئ (مُغذّي فارغ أو مستند على الزجاج)، ويحقّق الاكتشاف التلقائي
    للوجه/الوجهين (مع إزالة الصفحات الفارغة لاحقاً). deskew مُفعّل دائماً، بلا تدوير
    يدوي (التقويم تلقائي).
    """
    exe = _require_exe()
    if not device:
        raise ValueError("لم يُحدَّد جهاز")
    if driver not in config.DRIVERS:
        raise ValueError("سائق غير مدعوم")
    if color not in config.COLORS:
        raise ValueError("عمق لون غير مدعوم")
    dpi = _clamp_dpi(dpi)

    last_detail = ""
    for source in config.AUTO_SOURCE_ORDER:
        try:
            return _run_scan(exe, device, source, dpi, color, driver, deskew=True)
        except ScanNoPagesError as exc:
            last_detail = str(exc)
            continue
        except RuntimeError as exc:
            # مصدر غير مدعوم/خطأ جهاز لهذا المصدر — جرّب التالي مع تذكّر السبب
            last_detail = str(exc)
            continue
    raise RuntimeError(
        "لم يُلتقط أي مستند من الماسح. ضع الورق في وحدة التغذية (ADF) أو على الزجاج "
        "ثم أعد المحاولة." + (f" (تفاصيل: {last_detail[:160]})" if last_detail else "")
    )


def safe_remove(path):
    """حذف ملف بهدوء (لا يرمي)."""
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def _require_exe():
    exe = locate_exe()
    if not exe:
        raise RuntimeError("NAPS2 غير مثبّت — ثبّته من naps2.com أو ضع نسخة محمولة في scan_agent/naps2_portable/")
    return exe


def _clamp_dpi(dpi):
    try:
        dpi = int(dpi)
    except (TypeError, ValueError):
        raise ValueError("dpi غير صالح")
    return max(config.DPI_MIN, min(config.DPI_MAX, dpi))


def _clamp_rotate(rotate):
    try:
        rotate = int(rotate)
    except (TypeError, ValueError):
        raise ValueError("زاوية تدوير غير صالحة")
    if rotate not in config.ROTATIONS:
        raise ValueError("زاوية تدوير غير مدعومة (0/90/180/270)")
    return rotate
