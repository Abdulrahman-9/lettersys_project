"""خادم HTTP محلي لوكيل المسح (127.0.0.1 فقط).

ثلاث نقاط فقط: /agent/health و/agent/devices و/agent/scan.
الأمن: ربط محلي + فحص Origin + token مشترك + قوائم بيضاء للمعاملات.
النجاح في /agent/scan يُعاد كـ PDF ثنائي؛ الفشل يُعاد كـ JSON.
"""
import json
import os
import secrets
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from . import config, naps2, __version__ as VERSION


def _load_token():
    """يقرأ token المشترك من القرص، أو يولّده ويحفظه عند أول تشغيل."""
    try:
        with open(config.TOKEN_FILE, "r", encoding="utf-8") as f:
            tok = f.read().strip()
        if tok:
            return tok
    except OSError:
        pass
    tok = secrets.token_urlsafe(24)
    try:
        os.makedirs(config.TOKEN_DIR, exist_ok=True)
        with open(config.TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(tok)
    except OSError:
        pass
    return tok


AGENT_TOKEN = _load_token()


class Handler(BaseHTTPRequestHandler):
    server_version = "LetterSysScanAgent/" + VERSION

    # ───────── أدوات مساعدة ─────────
    def _origin_ok(self):
        # المتصفح يرسل Origin دائماً؛ طلبات بلا Origin (curl/الكشف) مقبولة.
        origin = self.headers.get("Origin")
        return origin is None or origin in config.ALLOWED_ORIGINS

    def _token_ok(self):
        return secrets.compare_digest(self.headers.get("X-LetterSys-Token") or "", AGENT_TOKEN)

    def _send_cors(self):
        origin = self.headers.get("Origin")
        if origin in config.ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", "X-LetterSys-Token, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        # كي يقرأ المتصفح عدد الصفحات من استجابة المسح عبر الأصل المختلف
        self.send_header("Access-Control-Expose-Headers", "X-Scan-Pages")

    def _json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._send_cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # صامت — لا ضجيج console

    # ───────── التوجيه ─────────
    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors()
        self.end_headers()

    def do_GET(self):
        if not self._origin_ok():
            return self._json(403, {"ok": False, "error": "أصل غير مسموح"})
        if self.path == "/agent/health":
            return self._health()
        if self.path.split("?")[0] == "/agent/devices":
            if not self._token_ok():
                return self._json(401, {"ok": False, "error": "token غير صالح"})
            return self._devices()
        return self._json(404, {"ok": False, "error": "غير موجود"})

    def do_POST(self):
        if not self._origin_ok():
            return self._json(403, {"ok": False, "error": "أصل غير مسموح"})
        if self.path == "/agent/scan":
            if not self._token_ok():
                return self._json(401, {"ok": False, "error": "token غير صالح"})
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
    print("ملف الـtoken: %s" % config.TOKEN_FILE)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nإيقاف الوكيل...")
    finally:
        httpd.server_close()
