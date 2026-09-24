"""خادم HTTP محلي لوكيل المسح (127.0.0.1 فقط).

ثلاث نقاط فقط: /agent/health و/agent/devices و/agent/scan.

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
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from . import config, naps2, __version__ as VERSION

# أصولٌ رُفضت وسُجّلت — مرّةً واحدةً لكلّ أصلٍ في العمليّة (لا يُملأ السجلُّ بالتكرار)
_LOGGED_ORIGINS = set()


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
    key = origin or "(بلا أصل)"
    if key in _LOGGED_ORIGINS:
        return
    _LOGGED_ORIGINS.add(key)
    line = "رُفض الأصل %s — أضفه إلى %s ثمّ أعد تشغيل الوكيل" % (key, config.config_file())
    sys.stderr.write(line + "\n")
    try:
        os.makedirs(config.data_dir(), exist_ok=True)
        with open(config.log_file(), "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), line))
    except OSError:
        pass                      # السجلُّ رفاهيّةُ تشخيص؛ السطرُ ذهب إلى stderr أصلاً


class Handler(BaseHTTPRequestHandler):
    server_version = "LetterSysScanAgent/" + VERSION

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

    def _origin_allowed(self):
        """أهذا الأصلُ في قائمة محطّة العمل؟ مساواةُ tuple مُقنَّنة — لا بادئةَ ولا احتواء."""
        norm = config.normalize_origin(self.headers.get("Origin"))
        return norm is not None and norm in config.ALLOWED_ORIGINS

    # ───────── الاستجابات ─────────
    def _send_cors(self):
        """ترويساتُ CORS — تُبعَث للأصل المسموح وحدَه، وعلى كلّ استجابةٍ حتّى الخطأ
        (كي تقرأ الصفحةُ نصَّ خطأ الوكيل العربيّ بدل «فشلٌ مجهول»)."""
        if not self._origin_allowed():
            return
        self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin"))
        self.send_header("Vary", "Origin")
        # كي يقرأ المتصفح عدد الصفحات من استجابة المسح عبر الأصل المختلف
        self.send_header("Access-Control-Expose-Headers", "X-Scan-Pages")

    def _json(self, status, payload, cors=True):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        if cors:
            self._send_cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
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
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
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
        return self._json(404, {"ok": False, "error": "غير موجود"})

    def do_POST(self):
        if not self._host_ok():
            return self._bad_host()
        if self.path == "/agent/scan":
            if not self._origin_allowed():
                return self._reject_origin()
            return self._scan()
        return self._json(404, {"ok": False, "error": "غير موجود"})

    # ───────── المعالجات ─────────
    def _health(self):
        exe = naps2.locate_exe()
        self._json(200, {
            "ok": True,
            "version": VERSION,
            "backend": "naps2" if exe else "none",
            "naps2_available": bool(exe),
            "naps2_path": exe or "",
            "platform": sys.platform,
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
            return self._json(200, {"ok": True, "driver": driver, "devices": [], "warning": str(exc)})
        devices = [{"id": n, "name": n, "driver": driver} for n in names]
        self._json(200, {"ok": True, "driver": driver, "devices": devices})

    def _scan(self):
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
        except ValueError as exc:
            self._json(400, {"ok": False, "code": "bad_request", "error": str(exc)})
        except RuntimeError as exc:
            self._json(502, {"ok": False, "code": "scan_failed", "error": str(exc)})
        except Exception as exc:
            self._json(500, {"ok": False, "code": "error", "error": str(exc)})
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


def _describe_origin(norm):
    """صياغةُ ‎(scheme, host, port)‎ للعرض: يُخفى المنفذُ الافتراضيّ كما يفعل المتصفّح."""
    scheme, host, port = norm
    if (scheme, port) in (("http", 80), ("https", 443)):
        return "%s://%s" % (scheme, host)
    return "%s://%s:%d" % (scheme, host, port)


def serve():
    try:
        httpd = ThreadingHTTPServer((config.HOST, config.PORT), Handler)
    except OSError as exc:
        # WinError 10048 / EADDRINUSE: المنفذ مستخدَم (نسخة وكيل أخرى؟)
        sys.stderr.write(
            "\n[خطأ] تعذّر بدء وكيل المسح على %s:%d — %s\n"
            "المنفذ مستخدَم غالباً (قد تعمل نسخة أخرى من الوكيل). أغلقها، "
            "أو اضبط متغيّر البيئة LETTERSYS_AGENT_PORT لمنفذ آخر.\n"
            % (config.HOST, config.PORT, exc)
        )
        sys.exit(1)
    print("LetterSys Scan Agent يعمل على http://%s:%d" % (config.HOST, config.PORT))
    print("ملف الإعداد: %s" % config.config_file())
    print("الأصول المسموح لها بالمسح: %s"
          % "، ".join(sorted(_describe_origin(o) for o in config.ALLOWED_ORIGINS)))
    for w in config.ORIGIN_WARNINGS:
        sys.stderr.write("[تنبيه] %s\n" % w)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nإيقاف الوكيل...")
    finally:
        httpd.server_close()
