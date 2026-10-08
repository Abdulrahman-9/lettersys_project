"""خادم HTTP لوكيل المسح.

ثلاث نقاط فقط: /agent/health و/agent/devices و/agent/scan.
الأمن: ربط حلقي + فحص Host وOrigin + قوائم بيضاء للمعاملات.
النجاح في /agent/scan يُعاد كـ PDF ثنائي؛ الفشل يُعاد كـ JSON.
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse, urlsplit

from . import config, naps2, __version__ as VERSION


class Handler(BaseHTTPRequestHandler):
    server_version = "LetterSysScanAgent/" + VERSION

    # ───────── أدوات مساعدة ─────────
    def _host_ok(self):
        host = self.headers.get("Host", "")
        try:
            parsed = urlsplit("//" + host)
            return (
                parsed.hostname in {"127.0.0.1", "localhost"}
                and parsed.port == config.PORT
                and not parsed.username
                and not parsed.password
                and not parsed.path
                and not parsed.query
                and not parsed.fragment
            )
        except ValueError:
            return False

    def _origin_ok(self, required=False):
        origin = self.headers.get("Origin")
        if origin is None:
            return not required
        allowed = {item.rstrip("/") for item in config.ALLOWED_ORIGINS}
        return origin.rstrip("/") in allowed

    def _send_cors(self):
        origin = self.headers.get("Origin")
        allowed = {item.rstrip("/") for item in config.ALLOWED_ORIGINS}
        if origin and origin.rstrip("/") in allowed:
            self.send_header("Access-Control-Allow-Origin", origin.rstrip("/"))
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
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

    def log_message(self, *args):
        pass  # صامت — لا ضجيج console

    # ───────── التوجيه ─────────
    def do_OPTIONS(self):
        if not self._host_ok():
            return self._json(403, {"ok": False, "code": "bad_host"}, cors=False)
        if self.path != "/agent/scan" or not self._origin_ok(required=True):
            return self._json(403, {"ok": False, "error": "أصل غير مسموح"})
        self.send_response(204)
        self._send_cors()
        self.end_headers()

    def do_GET(self):
        if not self._host_ok():
            return self._json(403, {"ok": False, "code": "bad_host"}, cors=False)
        path = self.path.split("?", 1)[0]
        if path not in {"/agent/health", "/agent/devices"}:
            return self._json(404, {"ok": False, "error": "غير موجود"})
        if not self._origin_ok(required=path == "/agent/devices"):
            return self._json(403, {"ok": False, "error": "أصل غير مسموح"})
        if path == "/agent/health":
            return self._health()
        return self._devices()

    def do_POST(self):
        if not self._host_ok():
            return self._json(403, {"ok": False, "code": "bad_host"}, cors=False)
        if self.path != "/agent/scan":
            return self._json(404, {"ok": False, "error": "غير موجود"})
        if not self._origin_ok(required=True):
            return self._json(403, {"ok": False, "error": "أصل غير مسموح"})
        return self._scan()

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
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nإيقاف الوكيل...")
    finally:
        httpd.server_close()
