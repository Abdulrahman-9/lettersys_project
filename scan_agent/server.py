"""خادم HTTP محلي لوكيل المسح (127.0.0.1 فقط).

نقاط المسح ونقطة ربط جهاز الموظف ومتابعته.

الأمن — بوّابتان مستقلّتان تمرّان قبل أيّ توجيه، ولا توكِن بعد اليوم:
  1. **Host**: يجب أن يكون الحلقةَ المحلّيّة حرفيّاً بمنفذنا — حارسُ DNS-rebinding
     (صفحةُ المهاجم على evil.example:PORT تحوّل اسمَها إلى 127.0.0.1 فتصير طلباتُها
     «نفسَ الأصل»: لا CORS ولا Origin، والاستجابةُ تُقرأ. الشيءُ الوحيدُ الباقي أنّ
     ترويسةَ Host تحمل اسمَ المهاجم، فهي الحارس).
  2. **Origin**: أصلُ الصفحة الطالبة يجب أن يكون في قائمة محطّة العمل
     (‎%LOCALAPPDATA%\\LetterSys\\agent.json‎) — المتصفّح يُلحق Origin بكلّ طلبٍ عابرِ
     أصلٍ ولا تستطيع شيفرةُ الصفحة تزويرَه. ومطلوبٌ **وجودُه** على /devices و/scan كي
     تُسدَّ مساراتُ «بلا أصل» (‎<img src>‎ · تنقّلٌ علويّ · no-cors GET) التي كان
     التوكِنُ يسدّها.

التوكِنُ المشترك أُزيل: كان يُسلَّم تلقائيّاً لأيّ صفحةٍ على أصلٍ مسموح، فهو مكافئٌ
منطقيّاً لفحص الأصل الذي يحرسه، ويضيف أصلاً قابلاً للتسريب — وكان خادمُ Django يقرأه
من قرصه ويسلّمه لمتصفّحٍ بعيد، وذاك الجهازُ الخطأ لكلّ كاتبة (وكيلُها يولّد توكِنَه هو).
النجاح في /agent/scan يُعاد كـ PDF ثنائي؛ الفشل يُعاد كـ JSON.
"""
import http.client
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from . import config, naps2, __version__ as VERSION

# أصولٌ رُفضت وسُجّلت — مرّةً واحدةً لكلّ أصلٍ ما بقيت القائمةُ كما هي (لا يُملأ السجلُّ
# بالتكرار)، وتُصفَّر مع كلّ تغيّرٍ في القائمة: أصلٌ يُرفض بعد التعديل يُسجَّل من جديد.
_LOGGED_ORIGINS = set()
_LOGGED_GENERATION = [None]

# متى بدأت هذه النسخة — يُكشَف في /agent/health مع رقم العمليّة، فتعرف صفحةُ الإعدادات
# أيَّ نسخةٍ تردّ (كانت ثلاثُ نسخٍ تعمل معاً ولا يدري أحدٌ أيّها يجيب).
_STARTED_AT = time.strftime("%Y-%m-%dT%H:%M:%S")


def _split_host_port(value):
    """‎(host, port)‎ من ترويسة Host: المنفذُ ``None`` إن غاب و``False`` إن لم يكن رقميّاً."""
    s = (value or "").strip().lower()
    if ":" not in s:
        return s, None
    host, _, port = s.rpartition(":")
    if not port.isdigit():
        return s, False
    return host, int(port)


def _log_rejected_origin(origin):
    """يكتب الأصلَ المرفوض إلى الشاشة وإلى agent.log — فيُشخَّص العطبُ بلا devtools."""
    generation = config.origins_generation()
    if _LOGGED_GENERATION[0] != generation:
        _LOGGED_ORIGINS.clear()
        _LOGGED_GENERATION[0] = generation
    key = origin or "(بلا أصل)"
    if key in _LOGGED_ORIGINS:
        return
    _LOGGED_ORIGINS.add(key)
    line = ("رُفض الأصل %s — أضفه إلى %s (يُقرأ تلقائيّاً، بلا إعادة تشغيل)"
            % (key, config.config_file()))
    sys.stderr.write(line + "\n")
    try:
        os.makedirs(config.data_dir(), exist_ok=True)
        with open(config.log_file(), "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), line))
    except OSError:
        pass                      # السجلُّ رفاهيّةُ تشخيص؛ السطرُ ذهب إلى stderr أصلاً


class Handler(BaseHTTPRequestHandler):
    # ترويسةُ ``Server`` تُبعَث على كلّ استجابةٍ **قبل** أيّ حارس (حتّى 403 الارتباط
    # المُعاد)، فتبقى ثابتةً بلا إصدارِ وكيلٍ وبلا «Python/3.x»: الإصدارُ يُقرأ من
    # ‎/agent/health‎ وحدَه، وهو خلف البوّابتين. (``sys_version=""`` يمنع لصقَ إصدار
    # المفسّر الذي تضيفه المكتبةُ القياسيّة تلقائيّاً.)
    server_version = "LetterSysScanAgent"
    sys_version = ""

    def version_string(self):
        """نصُّ ``Server`` حرفيّاً: المكتبةُ تلصق ``sys_version`` وفراغاً بينهما."""
        return self.server_version

    # كلُّ فعلٍ يمرّ ببوّابة Host — حتّى فعلٌ لا مسارَ له. المكتبةُ القياسيّة تبحث عن
    # ``do_<METHOD>``، فإن غاب ردّت ``501`` من عندها **قبل** حرّاسنا (بصفحة HTML
    # وبترويسة Server). فنُعلن وجودَ كلّ ``do_*`` ونوجّهها إلى حارسنا.
    def __getattr__(self, name):
        if name.startswith('do_'):
            return self._unrouted
        raise AttributeError(name)

    def _unrouted(self):
        """‎PUT · DELETE · PATCH · HEAD · TRACE‎ وأيُّ اسمٍ آخر: بوّابةُ Host ثمّ 405."""
        if not self._host_ok():
            return self._bad_host()
        return self._json(405, {"ok": False, "code": "method_not_allowed",
                                "error": "فعل غير مسموح (الوكيل يقبل GET وPOST وOPTIONS)"},
                          headers=(("Allow", "GET, POST, OPTIONS"),))

    # ───────── الحرّاس ─────────
    def _expected_port(self):
        """المنفذُ الذي رُبِط فعلاً (= config.PORT في الإنتاج؛ منفذٌ عابر في الاختبار)."""
        return getattr(self.server, "server_port", None) or config.PORT

    def _host_ok(self):
        """ترويسةُ Host: مضيفٌ من الحلقة المحلّيّة حرفيّاً + منفذُنا. حارسُ الارتباط المُعاد.

        ``127.0.0.1.evil.example`` يفشل لأنّ المقارنة مساواةٌ تامّة، والمنفذُ المخالف
        يفشل، وغيابُ Host يفشل. يُطبَّق على OPTIONS و/agent/health أيضاً — فلا يُقرأ
        إصدارُ الوكيل ولا مسارُ NAPS2 (وفيه اسمُ مستخدم ويندوز عند النسخة المحمولة)
        عبر ارتباطٍ مُعاد.
        """
        raw = self.headers.get("Host")
        if not raw:
            return False
        host, port = _split_host_port(raw)
        if host not in config.LOOPBACK_HOSTS:
            return False
        if port is False:
            return False
        if port is None:
            return self._expected_port() == 80     # منفذٌ ضمنيٌّ = 80 وحدَه
        return port == self._expected_port()

    def parse_request(self):
        self._origin_resolved = False             # كلُّ طلبٍ يحسم أصلَه من جديد
        return super().parse_request()

    def _allowed_origin(self):
        """‎(scheme, host, port)‎ للأصل المسموح، أو ``None``. مساواةُ tuple مُقنَّنة —
        لا بادئةَ ولا احتواء.

        يُحسم **مرّةً لكلّ طلب**: القائمةُ حيّةٌ تتغيّر مع agent.json، فلو سُئلت مرّتين
        (البوّابةُ ثمّ ترويساتُ CORS) لأمكن أن يمرّ الطلبُ بقائمةٍ ويُجاب بأخرى.
        """
        if not getattr(self, "_origin_resolved", False):
            norm = config.normalize_origin(self.headers.get("Origin"))
            allowed = norm is not None and norm in config.allowed_origins()
            self._origin_norm = norm if allowed else None
            self._origin_resolved = True
        return self._origin_norm

    def _origin_allowed(self):
        return self._allowed_origin() is not None

    # ───────── الاستجابات ─────────
    def _send_cors(self):
        """ترويساتُ CORS — تُبعَث للأصل المسموح وحدَه، وعلى كلّ استجابةٍ حتّى الخطأ
        (كي تقرأ الصفحةُ نصَّ خطأ الوكيل العربيّ بدل «فشلٌ مجهول»)."""
        norm = self._allowed_origin()
        if norm is None:
            return
        # يُعاد **مدخلُ القائمة المُقنَّن** لا نصُّ الترويسة الخامّ: القيمةُ المُعادة هي
        # ما وثقنا به حرفيّاً، فلا يمرّ إلى ترويسةِ استجابةٍ شيءٌ جاء من العميل ولو
        # تساوى معه بعد التقنين (اختلافُ حالةِ الأحرف أو منفذٌ ضمنيّ).
        self.send_header("Access-Control-Allow-Origin", config.describe_origin(norm))
        self.send_header("Vary", "Origin")
        # كي يقرأ المتصفح عدد الصفحات من استجابة المسح عبر الأصل المختلف
        self.send_header("Access-Control-Expose-Headers", "X-Scan-Pages")

    def _json(self, status, payload, cors=True, headers=()):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        for name, value in headers:
            self.send_header(name, value)
        if cors:
            self._send_cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":          # استجابةُ HEAD بلا جسم (الترويساتُ كما هي)
            self.wfile.write(body)

    def _bad_host(self):
        """403 بلا أيّ ترويسةِ CORS — حتّى لأصلٍ مسموح: الارتباطُ المُعاد يموت قبل التوجيه،
        فلا تقرأ صفحةُ المهاجم شيئاً ولو زوّرت أصلاً (وهي لا تستطيع)."""
        return self._json(403, {"ok": False, "code": "bad_host",
                                "error": "مضيف غير مسموح (الوكيل محليٌّ فقط)"}, cors=False)

    def _reject_origin(self):
        """403 بلا ACAO: يقرأه curl للتشخيص، ويبقى معتماً على المتصفّح."""
        origin = self.headers.get("Origin")
        _log_rejected_origin(origin)
        return self._json(403, {"ok": False, "code": "origin_not_allowed",
                                "origin": origin or "",
                                "error": "أصل غير مسموح — أضفه إلى agent.json"})

    def log_message(self, *args):
        pass  # صامت — لا ضجيج console

    # ───────── التوجيه ─────────
    def do_OPTIONS(self):
        if not self._host_ok():
            return self._bad_host()
        if not self._origin_allowed():
            return self._reject_origin()
        self.send_response(204)
        self._send_cors()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        headers = "Content-Type, X-LetterSys-Pairing" if self.path == "/agent/workstation/pair" else "Content-Type"
        self.send_header("Access-Control-Allow-Headers", headers)
        # الشبكةُ الخاصّة/المحلّيّة: مقيسٌ أنّ كروم اليوم لا يحجب صفحةَ http ⟶ الحلقةَ
        # المحلّيّة، والرأسُ يُبقيها عاملةً لو أنفذ إصدارٌ قادمٌ الفحصَ فعلاً.
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def do_GET(self):
        if not self._host_ok():
            return self._bad_host()
        path = self.path.split("?")[0]
        if path == "/agent/health":
            # بلا Origin (curl/تشخيص/مسبارُ no-cors) مقبولٌ، ومع أصلٍ غير مسموح يُرفض.
            if self.headers.get("Origin") is not None and not self._origin_allowed():
                return self._reject_origin()
            return self._health()
        if path == "/agent/devices":
            # الأصلُ **مطلوب**: يسدّ مساراتِ «بلا أصل»، ويرفض قبل أيّ نداءِ NAPS2 فلا
            # يحجز مهاجمٌ خيطاً ستّين ثانيةً في سردِ الأجهزة (LIST_TIMEOUT).
            if not self._origin_allowed():
                return self._reject_origin()
            return self._devices()
        if path == "/agent/workstation":
            if not self._origin_allowed():
                return self._reject_origin()
            monitor = getattr(self.server, 'device_monitor', None)
            if monitor is None:
                return self._json(503, {"ok": False, "error": "Device monitor is not running"})
            return self._json(200, monitor.public_status())
        return self._json(404, {"ok": False, "error": "غير موجود"})

    def do_POST(self):
        if not self._host_ok():
            return self._bad_host()
        if self.path == "/agent/scan":
            if not self._origin_allowed():
                return self._reject_origin()
            return self._scan()
        if self.path == "/agent/workstation/pair":
            if not self._origin_allowed():
                return self._reject_origin()
            return self._pair_workstation()
        return self._json(404, {"ok": False, "error": "غير موجود"})

    # ───────── المعالجات ─────────
    def _pair_workstation(self):
        if (self.headers.get('X-LetterSys-Pairing') != '1' or
                self.headers.get('Content-Type') != 'application/json'):
            return self._json(400, {"ok": False, "error": "Explicit JSON pairing approval required"})
        monitor = getattr(self.server, 'device_monitor', None)
        if monitor is None:
            return self._json(503, {"ok": False, "error": "Device monitor is not running"})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 4096:
                raise ValueError('Invalid pairing request length')
            payload = json.loads(self.rfile.read(length))
            status = monitor.pair(payload, self.headers.get('Origin'))
        except (ValueError, TypeError) as exc:
            return self._json(400, {"ok": False, "error": str(exc)})
        except OSError as exc:
            sys.stderr.write('Workstation pairing failed: %s\n' % exc)
            return self._json(500, {"ok": False, "error": "Cannot save protected device settings"})
        if status.get('error'):
            return self._json(503, {"ok": False, "error": status['error']})
        return self._json(200, status)

    def _health(self):
        # الصحّةُ لا تسقط أبداً بسبب الإعداد: كان agent.json الفاسدُ يقطع الاتّصالَ هنا فتقرأ
        # الصفحةُ «الوكيلُ متوقّف». وضعٌ غيرُ محدَّد ⟵ لا نخمّن أيَّ NAPS2 نشغّل، ويُكشَف الرمز.
        try:
            exe = naps2.locate_exe()
        except config.AgentConfigError:
            exe = None
        self._json(200, {
            "ok": True,
            "version": VERSION,
            "backend": "naps2" if exe else "none",
            "naps2_available": bool(exe),
            "naps2_path": exe or "",
            "platform": sys.platform,
            "pid": os.getpid(),
            "started_at": _STARTED_AT,
            # رمزٌ ثابت (invalid_json · no_list · no_valid_entries · unreadable ·
            # invalid_pairing) أو null —
            # الصفحةُ تختار نصَّها العربيّ بالرمز ولا تعرض نصّاً جاء من هنا.
            "config_error": config.origin_status()["config_error"],
        })

    def _devices(self):
        q = parse_qs(urlparse(self.path).query)
        driver = (q.get("driver", ["twain"])[0] or "twain").lower()
        if driver not in config.DRIVERS:
            driver = "twain"
        try:
            names = naps2.list_devices(driver)
            if not names and driver == "twain":          # احتياط: جرّب WIA إن خلت قائمة TWAIN
                names = naps2.list_devices("wia")
                driver = "wia"
        except Exception as exc:                          # غياب NAPS2/مهلة → قائمة فارغة مع تحذير
            monitor = getattr(self.server, 'device_monitor', None)
            if monitor:
                monitor.observe_scanner('error')
            return self._json(200, {"ok": True, "driver": driver, "devices": [], "warning": str(exc)})
        monitor = getattr(self.server, 'device_monitor', None)
        if monitor:
            monitor.observe_scanner('ready' if names else 'no_device', names)
        devices = [{"id": n, "name": n, "driver": driver} for n in names]
        self._json(200, {"ok": True, "driver": driver, "devices": devices})

    def _scan(self):
        monitor = getattr(self.server, 'device_monitor', None)
        if monitor and not monitor.check_server():
            return self._json(503, {"ok": False, "code": "server_unavailable",
                                    "error": "اربط الجهاز من صفحة «تجهيز هذا الجهاز» أولاً. إذا كان مرتبطاً، فقد انقطع اتصال الخادم أو أوقف المسؤول ربطه. أعد الفحص قبل سحب الورق."})
        length = int(self.headers.get("Content-Length") or 0)
        try:
            req = json.loads(self.rfile.read(length) or b"{}") if length else {}
        except json.JSONDecodeError:
            return self._json(400, {"ok": False, "error": "JSON غير صالح"})

        device = (req.get("device_id") or "").strip()
        if not device:
            return self._json(400, {"ok": False, "code": "no_device", "error": "لم يُحدَّد جهاز"})

        out_path = None
        try:
            driver = req.get("driver", "twain")
            dpi = req.get("dpi", 300)
            color = req.get("color", "color")
            source = req.get("source")
            # الوضع الأوتوماتيكي (الافتراضي): يكتشف المصدر تلقائياً ويحلّ «0 pages».
            # يُمرَّر مصدر صريح فقط للتوافق الرجعي إن طُلب نصّاً.
            if (req.get("mode") == "auto") or not source:
                out_path = naps2.scan_to_pdf_auto(
                    device=device, driver=driver, dpi=dpi, color=color,
                )
            else:
                out_path = naps2.scan_to_pdf(
                    device=device, source=source, dpi=dpi, color=color, driver=driver,
                    deskew=req.get("deskew", True), rotate=req.get("rotate", 0),
                )
            with open(out_path, "rb") as f:
                pdf = f.read()
            pages = _count_pages(out_path)
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            if pages is not None:
                self.send_header("X-Scan-Pages", str(pages))
            self._send_cors()
            self.send_header("Content-Length", str(len(pdf)))
            self.end_headers()
            self.wfile.write(pdf)
        except naps2.ScanNoPagesError as exc:
            self._json(409, {"ok": False, "code": "no_pages", "error": str(exc)})
        except naps2.ScanTimeoutError as exc:
            self._json(504, {"ok": False, "code": "scan_timeout", "error": str(exc)})
        except naps2.ScanDeviceError as exc:
            self._json(409, {"ok": False, "code": "device_not_ready", "error": str(exc)})
        except config.AgentConfigError as exc:     # قبل ValueError: ليس طلباً خاطئاً بل إعداداً
            self._json(503, {"ok": False, "code": "config_error", "error": str(exc)})
        except ValueError as exc:
            self._json(400, {"ok": False, "code": "bad_request", "error": str(exc)})
        except RuntimeError:
            self._json(502, {
                "ok": False,
                "code": "scan_failed",
                "error": "تعذّر تنفيذ المسح. تحقّق من اتصال الماسح وتعريفه ثم أعد المحاولة.",
            })
        except Exception:
            self._json(500, {
                "ok": False,
                "code": "error",
                "error": "حدث خطأ غير متوقع أثناء المسح. أعد تشغيل وكيل المسح ثم حاول مجدداً.",
            })
        finally:
            naps2.safe_remove(out_path)


def _count_pages(pdf_path):
    """عدد صفحات الـPDF (best-effort عبر PyMuPDF؛ None إن تعذّر)."""
    try:
        import fitz
        with fitz.open(pdf_path) as doc:
            return doc.page_count
    except Exception:
        return None


class AgentHTTPServer(ThreadingHTTPServer):
    """لا تعمل نسختان من الوكيل معاً على المنفذ نفسه.

    ``ThreadingHTTPServer`` يضبط ``SO_REUSEADDR`` (‏allow_reuse_address = 1)، وعلى ويندوز
    يعني ذلك أنّ نسخةً ثانيةً **بالخيار نفسه** تربط المنفذَ بلا خطأ — مقيسٌ 2026-11-16: ثلاثُ
    نسخٍ معاً، وقديمةٌ بقائمةٍ قديمة تردّ بعد «إعادة التشغيل»، وفرعُ «المنفذ مستخدَم» في
    ``serve()`` لا يقع أبداً. بلا الخيار تُرفض الثانيةُ (10048) والقديمةُ (10013).

    جدولُ الربط المقيس على 127.0.0.1 (2026-11-16، ويندوز 11): الأولى بلا خيار ⟵ الثانيةُ
    تُرفض بخيارٍ وبلا خيار؛ الأولى بـREUSEADDR ⟵ الثانيةُ بـREUSEADDR **تربط**. و
    ``SO_EXCLUSIVEADDRUSE`` لم يغيّر خانةً واحدة من الجدول فلم يُضَف: حارسٌ لا يُقاس لا يبقى.
    وربطٌ على ‎0.0.0.0‎ ينجح في كلّ الحالات لكنّه لا يأخذ اتّصالاتِ 127.0.0.1 (الأخصُّ يغلب).
    ومقيسٌ أنّ إعادةَ الربط فورَ الإغلاق تنجح رغم اتّصالات TIME_WAIT.
    """
    allow_reuse_address = False


def running_agent_health(port, timeout=2.0):
    """صحّةُ وكيلنا القائم على المنفذ (dict)، أو ``None`` إن لم يردّ وكيلُنا.

    ‏``http.client`` لا ``urllib``: الأخيرُ يمرّ بوكيل الشبكة المضبوط في ويندوز. والطلبُ
    بلا Origin وبمضيف 127.0.0.1:المنفذ، فيمرّ ببوّابتَي الوكيل كما يمرّ ``curl``.
    """
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request("GET", "/agent/health")
        resp = conn.getresponse()
        data = json.loads(resp.read().decode("utf-8"))
    except (OSError, ValueError, http.client.HTTPException):
        return None
    finally:
        conn.close()
    if isinstance(data, dict) and data.get("ok") is True and isinstance(data.get("version"), str):
        return data
    return None


def _bind_or_explain():
    """يربط المنفذ، أو يكتب سببَ التعذّر بالعربيّة ويخرج.

    نسخةٌ منّا تعمل أصلاً ⟵ خروجٌ هادئ (0): اختصارُ بدء التشغيل نُقر مرّتين، لا عطل.
    غيرُ ذلك ⟵ خطأ (1). ورمزُ 10013 لا يعني «نسخةً قديمة» حتماً: ويندوز يحجز نطاقاتِ
    منافذ لـHyper-V/WSL، فيُسأل المنفذُ أوّلاً ولا يُخمَّن.
    """
    try:
        return AgentHTTPServer((config.HOST, config.PORT), Handler)
    except OSError as exc:
        running = running_agent_health(config.PORT)
        if running is not None:
            sys.stderr.write(
                "[تنبيه] وكيلُ المسح يعمل أصلاً على %s:%d (الإصدار %s، العمليّة %s، منذ %s) — "
                "هذه النسخةُ تخرج ولا حاجةَ لشيء. تعديلُ agent.json يسري فيه تلقائيّاً.\n"
                % (config.HOST, config.PORT, running.get("version"), running.get("pid", "؟"),
                   running.get("started_at", "؟")))
            sys.exit(0)
        sys.stderr.write(
            "[خطأ] تعذّر بدء وكيل المسح على %s:%d — %s\n"
            "المنفذُ يشغله برنامجٌ آخر أو يقع في نطاقٍ يحجزه ويندوز (Hyper-V/WSL — راجعه بـ"
            "`netsh interface ipv4 show excludedportrange protocol=tcp`). أغلق ذلك البرنامج "
            "ثمّ شغّل الوكيل من جديد.\n" % (config.HOST, config.PORT, exc))
        sys.exit(1)


def serve():
    httpd = _bind_or_explain()
    print("LetterSys Scan Agent يعمل على http://%s:%d (العمليّة %d)"
          % (config.HOST, config.PORT, os.getpid()))
    print("ملف الإعداد: %s — تعديلُه يسري تلقائيّاً بلا إعادة تشغيل" % config.config_file())
    print("الأصول المسموح لها بالمسح: %s"
          % "، ".join(sorted(config.describe_origin(o) for o in config.allowed_origins())))
    for w in config.origin_warnings():
        sys.stderr.write("[تنبيه] %s\n" % w)
    from .workstation import DeviceMonitor
    httpd.device_monitor = DeviceMonitor()
    httpd.device_monitor.start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nإيقاف الوكيل...")
    finally:
        httpd.device_monitor.stop()
        httpd.server_close()
