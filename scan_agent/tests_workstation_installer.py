"""Runnable fixture tests for the workstation package (Setup.cmd / Setup.vbs / builder).

Every test runs the REAL scripts against a constructed package inside a sandbox folder
under the project directory, with LOCALAPPDATA/APPDATA/TEMP redirected into the sandbox.
Nothing touches the real user's certificate store (LETTERSYS_SETUP_SKIP_CERT_STORE=1),
startup folder, browser (LETTERSYS_SETUP_NO_BROWSER=1) or the agent port 17865 (fake
agents listen on a free port via LETTERSYS_AGENT_PORT).

Run:  python -m unittest scan_agent.tests_workstation_installer -v
Optional full builder test:  set LETTERSYS_TEST_EMBED_ZIP to an official
python-3.x-embed-amd64.zip (it is extracted into the sandbox only).
"""
import hashlib
import http.server
import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import unittest
import uuid
import zipfile
from pathlib import Path

SCAN_AGENT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCAN_AGENT_DIR.parent
WIN = os.name == "nt"
# Fixture machine names: the package is built on SERVER_NAME and installed on a different
# (fake) employee computer, so the server mis-click guard does not block per-user tests.
SERVER_NAME = "LS-FIXTURE-SRV"
CLIENT_NAME = "LS-FIXTURE-PC"


def _ps_quiet(script, timeout=120):
    subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, timeout=timeout)


def _ps(script, timeout=120):
    r = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(r.stdout + r.stderr)
    return r.stdout


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest().upper()


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _agent_version():
    text = (SCAN_AGENT_DIR / "__init__.py").read_text(encoding="utf-8")
    return re.search(r"__version__\s*=\s*['\"]([^'\"]+)['\"]", text).group(1)


class _Certs:
    """Self-signed public certificate built in memory (.NET CertificateRequest) - no store."""
    cer = pfx = None

    @classmethod
    def make(cls, folder):
        if cls.cer is None:
            folder.mkdir(parents=True, exist_ok=True)
            cer, pfx = folder / "test_root.cer", folder / "test_root.pfx"
            _ps(
                "$rsa = [Security.Cryptography.RSA]::Create(2048); "
                "$req = New-Object Security.Cryptography.X509Certificates.CertificateRequest("
                "'CN=LetterSys Test Root', $rsa, [Security.Cryptography.HashAlgorithmName]::SHA256, "
                "[Security.Cryptography.RSASignaturePadding]::Pkcs1); "
                "$c = $req.CreateSelfSigned([DateTimeOffset]::Now.AddDays(-1), [DateTimeOffset]::Now.AddDays(30)); "
                f"[IO.File]::WriteAllBytes('{cer}', $c.Export('Cert')); "
                f"[IO.File]::WriteAllBytes('{pfx}', $c.Export('Pfx', 'x'))"
            )
            thumb = _ps(f"(New-Object Security.Cryptography.X509Certificates.X509Certificate2('{cer}')).Thumbprint").strip()
            cls.cer, cls.pfx, cls.thumb = cer.read_bytes(), pfx.read_bytes(), thumb.upper()
        return cls


class _FakeAgent:
    """Minimal stand-in for scan_agent.server on a free loopback port."""

    def __init__(self, health, devices_body, status=200):
        self.health, self.devices_body, self.status = health, devices_body, status
        self.origins = []
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if self.path == "/agent/health":
                    body = json.dumps(outer.health, ensure_ascii=False).encode("utf-8")
                elif self.path == "/agent/devices":
                    outer.origins.append(self.headers.get("Origin"))
                    body = outer.devices_body if isinstance(outer.devices_body, bytes) else \
                        json.dumps(outer.devices_body, ensure_ascii=False).encode("utf-8")
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(outer.status if self.path == "/agent/devices" else 200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.port = _free_port()
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", self.port), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@unittest.skipUnless(WIN, "Windows installer")
class WorkstationSetupTests(unittest.TestCase):
    ORIGIN = "https://127.0.0.1:1"

    def setUp(self):
        self.sandbox = PROJECT_DIR / f"test_sandbox_ws_{uuid.uuid4().hex[:8]}"
        self.sandbox.mkdir()
        self.addCleanup(self._cleanup)
        self.certs = _Certs.make(PROJECT_DIR / "test_sandbox_ws_certs")
        self.pkg = self.sandbox / "pkg dir"
        self.local = self.sandbox / "local app"
        self.roaming = self.sandbox / "roaming"
        self.tmp = self.sandbox / "tmp"
        for d in (self.local, self.roaming, self.tmp):
            d.mkdir()
        # A real Windows profile always has the Startup folder; install_agent.bat expects it.
        (self.roaming / "Microsoft/Windows/Start Menu/Programs/Startup").mkdir(parents=True)
        self._build_package()

    def _cleanup(self):
        _ps_quiet("Get-Process | Where-Object { $_.Path -like "
            f"'{self.sandbox}\\*' }} | ForEach-Object {{ Stop-Process -Id $_.Id -Force }}")
        for _ in range(5):
            try:
                shutil.rmtree(self.sandbox)
                return
            except OSError:
                time.sleep(1)

    # ---------------------------------------------------------------- fixture
    def _build_package(self, origin=None):
        pkg = self.pkg
        (pkg / "scan_agent").mkdir(parents=True)
        for f in SCAN_AGENT_DIR.glob("*.py"):
            if not f.name.startswith("tests_"):
                shutil.copy2(f, pkg / "scan_agent" / f.name)
        shutil.copy2(SCAN_AGENT_DIR / "install_agent.bat", pkg / "scan_agent")
        (pkg / "python").mkdir()
        (pkg / "python" / "pythonw.exe").write_bytes(b"fake pythonw")
        (pkg / "python" / "python312._pth").write_text("python312.zip\n.\n..\n")
        n = pkg / "naps2_portable"
        (n / "lib").mkdir(parents=True)
        (n / "NAPS2.exe").write_bytes(b"gui")
        (n / "NAPS2.Console.exe").write_bytes(b"console")
        (n / "lib" / "NAPS2.Sdk.dll").write_bytes(b"sdk")
        (n / "appsettings.xml").write_text("<x/>")
        for name in ("Setup.cmd", "Setup.vbs", "setup_messages.txt", "THIRD_PARTY_LICENSES.txt"):
            shutil.copy2(SCAN_AGENT_DIR / name, pkg / name)
        (pkg / "root_ca.cer").write_bytes(self.certs.cer)
        self.write_config(origin or self.ORIGIN)

    def write_config(self, origin, **over):
        cfg = {
            "schema_version": "1.0",
            "package_role": "client",
            "server_machine_name": SERVER_NAME,
            "server_origin": origin,
            "device_setup_url": origin + "/books/device-setup/",
            "root_cert_file": "root_ca.cer",
            "root_cert_sha256": _sha(self.pkg / "root_ca.cer"),
            "root_cert_thumbprint": self.certs.thumb,
            "created_at": "2026-01-01T00:00:00Z",
        }
        cfg.update(over)
        cfg = {k: v for k, v in cfg.items() if v is not None}
        (self.pkg / "config.json").write_text(json.dumps(cfg, indent=2), encoding="ascii")
        self.write_sums()

    def write_sums(self, extra_lines=()):
        lines = []
        for f in sorted(self.pkg.rglob("*")):
            if f.is_file() and f.name != "SHA256SUMS.txt":
                lines.append(f"{_sha(f)}  {f.relative_to(self.pkg)}")
        lines.extend(extra_lines)
        (self.pkg / "SHA256SUMS.txt").write_bytes(("\r\n".join(lines) + "\r\n").encode("ascii"))

    @property
    def agent_dir(self):
        return self.local / "LetterSys" / "agent"

    @property
    def naps2_dest(self):
        return self.agent_dir / "scan_agent" / "naps2_portable"

    def env(self, **extra):
        env = dict(os.environ)
        env.update({
            "LOCALAPPDATA": str(self.local), "APPDATA": str(self.roaming),
            "TEMP": str(self.tmp), "TMP": str(self.tmp),
            "COMPUTERNAME": CLIENT_NAME,
            "LETTERSYS_INSTALL_ALLOW_ELEVATED": "1",
            "LETTERSYS_SETUP_SKIP_CERT_STORE": "1",
            "LETTERSYS_SETUP_NO_BROWSER": "1",
            "LETTERSYS_SETUP_AUTO_APPROVE": "1",
            "LETTERSYS_SETUP_SERVER_ATTEMPTS": "1",
            "LETTERSYS_SETUP_RUN_ID": "run-" + uuid.uuid4().hex,
        })
        for k in ("NAPS2_CONSOLE", "LETTERSYS_SETUP_NO_START", "LETTERSYS_SETUP_TEST_FAKE_AGENT",
                  "LETTERSYS_AGENT_PORT", "LETTERSYS_SETUP_GUI_TEST_DIALOG_FILE"):
            env.pop(k, None)
        for k, v in extra.items():
            if v is None:
                env.pop(k, None)
            else:
                env[k] = v
        return env

    def run_setup(self, pkg=None, stdin=None, timeout=300, **extra):
        env = self.env(**extra)
        r = subprocess.run(["cmd.exe", "/d", "/c", str((pkg or self.pkg) / "Setup.cmd")],
                           env=env, input=(stdin or "").encode(), capture_output=True, timeout=timeout)
        out = r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")
        res_file = self.local / "LetterSys" / "install_result.json"
        result = json.loads(res_file.read_text(encoding="utf-8")) if res_file.exists() else None
        if result is not None:
            self.assertEqual(result["run_id"], env["LETTERSYS_SETUP_RUN_ID"], out)
            self.assertEqual(result["exit_code"], r.returncode, out)
        return r.returncode, result, out

    def fake_agent(self, devices, health=None, status=200):
        h = {"ok": True, "version": _agent_version(), "backend": "naps2", "naps2_available": True,
             "naps2_path": str(self.naps2_dest / "NAPS2.Console.exe"), "platform": "win32"}
        if health:
            h.update(health)
        a = _FakeAgent(h, devices, status)
        self.addCleanup(a.close)
        return a

    def run_with_agent(self, agent, **extra):
        return self.run_setup(LETTERSYS_SETUP_TEST_FAKE_AGENT="1", LETTERSYS_AGENT_PORT=str(agent.port),
                              LETTERSYS_SETUP_HEALTH_SECONDS="4", **extra)

    # ---------------------------------------------------------------- integrity
    def test_no_start_install_succeeds_and_writes_structured_result(self):
        rc, res, out = self.run_setup(LETTERSYS_SETUP_NO_START="1")
        self.assertEqual(rc, 0, out)
        self.assertTrue(res["agent_installed"])
        self.assertEqual(res["device_status"], "not_checked")
        self.assertEqual(res["server_status"], "unreachable")
        self.assertFalse(res["browser_opened"])
        self.assertEqual(res["server_origin"], self.ORIGIN)
        for rel in ("python/pythonw.exe", "scan_agent/__main__.py", "scan_agent/workstation.py",
                    "scan_agent/naps2_portable/NAPS2.exe", "scan_agent/naps2_portable/NAPS2.Console.exe",
                    "scan_agent/naps2_portable/lib/NAPS2.Sdk.dll"):
            self.assertTrue((self.agent_dir / rel).is_file(), rel)
        cfg = json.loads((self.local / "LetterSys" / "agent.json").read_text(encoding="utf-8-sig"))
        self.assertIn(self.ORIGIN, cfg["allowed_origins"])
        self.assertIs(cfg["require_pairing"], True)
        self.assertEqual(cfg["allowed_origins"][0], self.ORIGIN)
        self.assertNotIn("require_pairing", (self.pkg / "scan_agent" / "install_agent.bat").read_text(encoding="utf-8"))
        link = self.roaming / "Microsoft/Windows/Start Menu/Programs/Startup/LetterSys Scan Agent.lnk"
        self.assertTrue(link.is_file())
        target = _ps(f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut('{link}'); "
                     "$s.TargetPath + '|' + $s.WorkingDirectory").strip()
        self.assertEqual(target.lower(), f"{self.agent_dir}\\python\\pythonw.exe|{self.agent_dir}".lower())

    def test_tampered_file_rejected_before_any_effect(self):
        (self.pkg / "naps2_portable" / "lib" / "NAPS2.Sdk.dll").write_bytes(b"evil")
        rc, res, out = self.run_setup(LETTERSYS_SETUP_NO_START="1")
        self.assertEqual(rc, 7, out)
        self.assertIn("HASH_MISMATCH", res["detail"])
        self.assertFalse(res["agent_installed"])
        self.assertFalse(self.agent_dir.exists())
        self.assertFalse((self.local / "LetterSys" / "agent.json").exists())

    def test_unlisted_file_rejected(self):
        (self.pkg / "scan_agent" / "injected.py").write_text("x = 1")
        rc, res, out = self.run_setup(LETTERSYS_SETUP_NO_START="1")
        self.assertEqual(rc, 7, out)
        self.assertIn("UNLISTED_FILE", res["detail"])
        self.assertFalse(self.agent_dir.exists())

    def test_tampered_setup_cmd_is_detected(self):
        with open(self.pkg / "setup_messages.txt", "ab") as f:
            f.write(b"\r\nextra=1\r\n")
        rc, res, out = self.run_setup(LETTERSYS_SETUP_NO_START="1")
        self.assertEqual(rc, 7, out)

    def test_unsafe_manifest_paths_rejected(self):
        h = "0" * 64
        for line in (f"{h}  ..\\outside.txt", f"{h}  C:\\Windows\\win.ini", f"{h}  scan_agent\\a.py:ads",
                     f"{h}  scan_agent\\.\\__init__.py", f"{h}  scan_agent/__init__.py",
                     f"{h}  \\\\server\\share\\x", "not a manifest line"):
            with self.subTest(line=line):
                self.write_sums(extra_lines=[line])
                rc, res, out = self.run_setup(LETTERSYS_SETUP_NO_START="1")
                self.assertEqual(rc, 7, out)
                self.assertFalse(self.agent_dir.exists())

    def test_duplicate_manifest_entry_rejected(self):
        first = (self.pkg / "SHA256SUMS.txt").read_text(encoding="ascii").splitlines()[0]
        self.write_sums(extra_lines=[first])
        rc, res, out = self.run_setup(LETTERSYS_SETUP_NO_START="1")
        self.assertEqual(rc, 7, out)

    def test_missing_full_naps2_component_rejected(self):
        (self.pkg / "naps2_portable" / "NAPS2.exe").unlink()
        self.write_sums()
        rc, res, out = self.run_setup(LETTERSYS_SETUP_NO_START="1")
        self.assertEqual(rc, 8, out)

    def test_invalid_config_and_cert_pins(self):
        cases = [
            ({"server_origin": "http://127.0.0.1:1", "device_setup_url": "http://127.0.0.1:1/books/device-setup/"}, 2),
            ({"device_setup_url": "https://evil.example/books/device-setup/"}, 2),
            ({"server_origin": "https://user@127.0.0.1:1", "device_setup_url": "https://user@127.0.0.1:1/books/device-setup/"}, 2),
            ({"root_cert_file": "..\\root_ca.cer"}, 2),
            ({"root_cert_sha256": "A" * 64}, 3),
            ({"root_cert_thumbprint": "B" * 40}, 3),
        ]
        for over, code in cases:
            with self.subTest(over=over):
                self.write_config(self.ORIGIN, **over)
                rc, res, out = self.run_setup(LETTERSYS_SETUP_NO_START="1")
                self.assertEqual(rc, code, out)
                self.assertFalse(self.agent_dir.exists())

    def test_private_key_bundle_rejected_as_cert(self):
        (self.pkg / "root_ca.cer").write_bytes(self.certs.pfx)
        self.write_config(self.ORIGIN)
        rc, res, out = self.run_setup(LETTERSYS_SETUP_NO_START="1")
        self.assertEqual(rc, 3, out)

    def test_stale_and_tampered_installed_naps2_is_replaced(self):
        self.naps2_dest.mkdir(parents=True)
        (self.naps2_dest / "NAPS2.exe").write_bytes(b"old gui")
        (self.naps2_dest / "NAPS2.Console.exe").write_bytes(b"console")
        (self.naps2_dest / "stale.dll").write_bytes(b"stale")
        rc, res, out = self.run_setup(LETTERSYS_SETUP_NO_START="1")
        self.assertEqual(rc, 0, out)
        self.assertFalse((self.naps2_dest / "stale.dll").exists())
        self.assertEqual((self.naps2_dest / "NAPS2.exe").read_bytes(), b"gui")

    def test_elevated_session_refused_without_writing(self):
        fake = self.sandbox / "fakebin"
        fake.mkdir()
        (fake / "whoami.bat").write_text("@echo Mandatory Label\\High Mandatory Level Label S-1-16-12288\r\n")
        rc, res, out = self.run_setup(LETTERSYS_INSTALL_ALLOW_ELEVATED=None, LETTERSYS_SETUP_NO_START="1",
                                      PATH=f"{fake};{os.environ['PATH']}", PATHEXT=".BAT;.COM;.EXE;.CMD")
        self.assertEqual(rc, 6, out)
        self.assertIsNone(res)
        self.assertFalse(self.agent_dir.exists())

    def test_interactive_decline_in_existing_installer_is_cancel(self):
        rc, res, out = self.run_setup(stdin="n\r\n", LETTERSYS_SETUP_AUTO_APPROVE=None, LETTERSYS_SETUP_NO_START="1")
        self.assertEqual(rc, 1, out)
        self.assertEqual(res["stage"], "install")
        self.assertFalse(self.agent_dir.exists())

    # ---------------------------------------------------------------- health / devices
    def test_devices_ready_reports_names_from_name_field(self):
        agent = self.fake_agent({"ok": True, "driver": "twain", "devices": [
            {"id": "1", "name": "Canon DR-C225", "driver": "twain"},
            {"id": "2", "name": "\u0645\u0627\u0633\u062d HP", "driver": "twain"}]})
        rc, res, out = self.run_with_agent(agent)
        self.assertEqual(rc, 0, out)
        self.assertEqual(res["device_status"], "ready")
        self.assertEqual(res["agent_status"], "healthy")
        self.assertEqual(res["device_names"], ["Canon DR-C225", "\u0645\u0627\u0633\u062d HP"])
        self.assertEqual(agent.origins, [self.ORIGIN])

    def test_empty_device_list_is_no_device(self):
        agent = self.fake_agent({"ok": True, "driver": "wia", "devices": []})
        rc, res, out = self.run_with_agent(agent)
        self.assertEqual(rc, 31, out)
        self.assertEqual(res["device_status"], "no_device")

    def test_warning_malformed_or_failed_device_answers_are_unknown_not_no_device(self):
        cases = [
            {"ok": True, "devices": [], "warning": "TWAIN enumeration failed"},
            {"ok": False, "error": "boom", "devices": []},
            {"ok": "true", "devices": []},
            {"ok": True},
            {"ok": True, "devices": "none"},
            {"ok": True, "devices": [{"id": "1"}]},
            {"ok": True, "devices": [{"id": "1", "name": ""}]},
            b"<html>not json</html>",
        ]
        for body in cases:
            with self.subTest(body=body):
                shutil.rmtree(self.local / "LetterSys", ignore_errors=True)
                agent = self.fake_agent(body)
                rc, res, out = self.run_with_agent(agent)
                self.assertEqual(rc, 32, out)
                self.assertEqual(res["device_status"], "unknown")

    def test_device_http_error_is_error(self):
        agent = self.fake_agent({"ok": False, "error": "x"}, status=500)
        rc, res, out = self.run_with_agent(agent)
        self.assertEqual(rc, 32, out)
        self.assertEqual(res["device_status"], "error")

    def test_unhealthy_agent_fails(self):
        cases = [{"version": "0.0.0"}, {"naps2_available": False},
                 {"naps2_path": "C:\\Program Files\\NAPS2\\NAPS2.Console.exe"}, {"ok": "yes"}]
        for health in cases:
            with self.subTest(health=health):
                shutil.rmtree(self.local / "LetterSys", ignore_errors=True)
                agent = self.fake_agent({"ok": True, "devices": []}, health=health)
                rc, res, out = self.run_with_agent(agent)
                self.assertEqual(rc, 30, out)
                self.assertEqual(res["agent_status"], "unhealthy")
                self.assertEqual(res["device_status"], "not_checked")

    # ---------------------------------------------------------------- GUI launcher
    def run_vbs(self, answer="yes", pkg=None, **extra):
        dialogs = self.sandbox / "dialogs.txt"
        env = self.env(LETTERSYS_SETUP_AUTO_APPROVE=None, LETTERSYS_SETUP_RUN_ID=None,
                       LETTERSYS_SETUP_GUI_TEST_DIALOG_FILE=str(dialogs),
                       LETTERSYS_SETUP_GUI_TEST_ANSWER=answer, **extra)
        r = subprocess.run(["cscript.exe", "//nologo", str((pkg or self.pkg) / "Setup.vbs")],
                           env=env, capture_output=True, timeout=400)
        text = dialogs.read_text(encoding="utf-8-sig") if dialogs.exists() else ""
        return r.returncode, text, r.stdout.decode("mbcs", "replace") + r.stderr.decode("mbcs", "replace")

    def msg(self, key):
        for line in (SCAN_AGENT_DIR / "setup_messages.txt").read_text(encoding="utf-8").splitlines():
            if line.startswith(key + "="):
                return line[len(key) + 1:].replace("\\n", "\n")
        raise KeyError(key)

    def test_refuses_client_setup_on_server_computer(self):
        for name in (SERVER_NAME, SERVER_NAME.lower()):
            with self.subTest(name=name):
                rc, res, out = self.run_setup(LETTERSYS_SETUP_NO_START="1", COMPUTERNAME=name)
                self.assertEqual(rc, 11, out)
                self.assertFalse(res["agent_installed"])
                self.assertIn("SERVER", res["message"])
                self.assertFalse(self.agent_dir.exists())

    def test_config_requires_client_role_and_server_name(self):
        cases = [{"package_role": "server"}, {"package_role": None}, {"server_machine_name": ""},
                 {"server_machine_name": "a b"}, {"server_machine_name": None}]
        for over in cases:
            with self.subTest(over=over):
                self.write_config(self.ORIGIN, **over)
                rc, res, out = self.run_setup(LETTERSYS_SETUP_NO_START="1")
                self.assertEqual(rc, 2, out)
                self.assertFalse(self.agent_dir.exists())

    def test_vbs_refuses_on_server_computer_with_visible_message_before_asking(self):
        rc, text, out = self.run_vbs(COMPUTERNAME=SERVER_NAME)
        self.assertEqual(rc, 11, out + text)
        self.assertIn(self.msg("server_machine").split("(")[0], text)
        self.assertIn(SERVER_NAME, text)
        self.assertNotIn(self.msg("approve")[:20], text)
        self.assertFalse(self.agent_dir.exists())

    def test_vbs_shows_arabic_approval_with_origin_and_unreachable_server_truthfully(self):
        rc, text, out = self.run_vbs(LETTERSYS_SETUP_NO_START="1")
        self.assertEqual(rc, 0, out + text)
        self.assertIn(self.msg("approve").replace("{origin}", self.ORIGIN), text)
        self.assertIn("هل توافق", text)
        self.assertNotIn("????", text)
        self.assertIn(self.msg("not_started"), text)
        self.assertIn(self.msg("server_down").split("(")[0], text)
        self.assertNotIn(self.msg("server_ok_no_browser"), text)
        self.assertNotIn(self.msg("ok_ready").split("\r")[0], text)
        self.assertTrue((self.local / "LetterSys" / "install_log.txt").is_file())

    def test_vbs_decline_changes_nothing(self):
        rc, text, out = self.run_vbs(answer="no")
        self.assertEqual(rc, 1, out + text)
        self.assertIn(self.msg("cancelled"), text)
        self.assertFalse(self.agent_dir.exists())

    def test_vbs_rejects_bad_config_before_asking(self):
        self.write_config("https://127.0.0.1:1/path", device_setup_url="https://127.0.0.1:1/path/books/device-setup/")
        rc, text, out = self.run_vbs()
        self.assertEqual(rc, 2, out + text)
        self.assertIn(self.msg("bad_config"), text)
        self.assertNotIn(self.msg("approve")[:20], text)

    def test_vbs_reports_failure_code_from_structured_result(self):
        (self.pkg / "naps2_portable" / "NAPS2.exe").write_bytes(b"evil")
        rc, text, out = self.run_vbs()
        self.assertEqual(rc, 7, out + text)
        self.assertIn(self.msg("failed").split("(")[0], text)
        self.assertIn("HASH_MISMATCH", text)

    def test_vbs_device_unknown_is_not_success_or_no_device(self):
        agent = self.fake_agent({"ok": True, "devices": [], "warning": "TWAIN failed"})
        rc, text, out = self.run_vbs(LETTERSYS_SETUP_TEST_FAKE_AGENT="1", LETTERSYS_AGENT_PORT=str(agent.port),
                                     LETTERSYS_SETUP_HEALTH_SECONDS="4")
        self.assertEqual(rc, 32, out + text)
        self.assertIn(self.msg("device_unknown").split("{")[0], text)
        self.assertIn("TWAIN failed", text)
        self.assertNotIn(self.msg("no_device")[:30], text)

    def test_vbs_ready_lists_device_names(self):
        agent = self.fake_agent({"ok": True, "devices": [{"id": "a", "name": "\u0645\u0627\u0633\u062d \"A\"", "driver": "wia"}]})
        rc, text, out = self.run_vbs(LETTERSYS_SETUP_TEST_FAKE_AGENT="1", LETTERSYS_AGENT_PORT=str(agent.port),
                                     LETTERSYS_SETUP_HEALTH_SECONDS="4")
        self.assertEqual(rc, 0, out + text)
        self.assertIn(self.msg("ok_ready").replace("{devices}", "\u0645\u0627\u0633\u062d \"A\""), text)

    # ---------------------------------------------------------------- source hygiene
    def test_sources_are_ascii_crlf_and_policy_neutral(self):
        for name in ("Setup.cmd", "Setup.vbs", "build_workstation_dist.ps1"):
            data = (SCAN_AGENT_DIR / name).read_bytes()
            self.assertTrue(all(b < 128 for b in data), name)
            self.assertNotIn(b"Bypass", data, name)
            self.assertNotIn(b"ExecutionPolicy", data, name)
        cmd = (SCAN_AGENT_DIR / "Setup.cmd").read_bytes()
        self.assertEqual(cmd.count(b"\n"), cmd.count(b"\r\n"))
        self.assertIsNone(re.search(rb"powershell[^\r\n|&]*?\s-File\s", cmd, re.I))
        "".join((SCAN_AGENT_DIR / "setup_messages.txt").read_text(encoding="utf-8"))


@unittest.skipUnless(WIN, "Windows builder")
class WorkstationBuilderTests(unittest.TestCase):
    def setUp(self):
        self.sandbox = PROJECT_DIR / f"test_sandbox_wb_{uuid.uuid4().hex[:8]}"
        self.sandbox.mkdir()
        self.addCleanup(lambda: shutil.rmtree(self.sandbox, ignore_errors=True))
        self.certs = _Certs.make(PROJECT_DIR / "test_sandbox_ws_certs")
        self.cer = self.sandbox / "root.cer"
        self.cer.write_bytes(self.certs.cer)
        self.pfx = self.sandbox / "root.pfx"
        self.pfx.write_bytes(self.certs.pfx)
        self.naps2 = self.sandbox / "naps2.zip"
        with zipfile.ZipFile(self.naps2, "w") as z:
            z.writestr("NAPS2.Portable.exe", b"launcher")
            z.writestr("App/NAPS2.exe", b"gui")
            z.writestr("App/NAPS2.Console.exe", b"console")
            z.writestr("App/license.txt", b"GPL")
            z.writestr("App/lib/NAPS2.Sdk.dll", b"sdk")
            z.writestr("Data/.keep", b"")
        self.fake_embed = self.sandbox / "embed.zip"
        with zipfile.ZipFile(self.fake_embed, "w") as z:
            z.writestr("pythonw.exe", b"x")

    def build(self, embed=None, naps2=None, cert=None, origin="https://LetterSys.example:443/", out=None):
        out = out or self.sandbox / "out"
        r = subprocess.run(["powershell", "-NoProfile", "-File", str(SCAN_AGENT_DIR / "build_workstation_dist.ps1"),
                            "-EmbedZip", str(embed or self.fake_embed), "-Naps2Zip", str(naps2 or self.naps2),
                            "-RootCertificate", str(cert or self.cer), "-ServerOrigin", origin, "-Out", str(out)],
                           capture_output=True, text=True, timeout=600)
        return r.returncode, r.stdout + r.stderr, out

    def test_rejects_private_key_and_bad_origins_before_writing(self):
        rc, out, dest = self.build(cert=self.pfx)
        self.assertNotEqual(rc, 0)
        self.assertIn("private key", out)
        self.assertFalse(dest.exists())
        for origin in ("http://h", "https://u:p@h", "https://h/path", "https://h?q=1", "https://h#f", "h"):
            with self.subTest(origin=origin):
                rc, out, dest = self.build(origin=origin)
                self.assertNotEqual(rc, 0, out)
                self.assertFalse(dest.exists())

    def test_exe_validates_without_installing_and_reports_invalid_archives(self):
        cases = [
            ("valid", {"Setup.vbs": "WScript.Quit 0"}, True),
            ("missing", {"readme.txt": "test"}, False),
            ("unsafe", {"Setup.vbs": "WScript.Quit 0", "..\\escape.txt": "test"}, False),
            ("corrupt", None, False),
        ]
        for name, entries, valid in cases:
            with self.subTest(name=name):
                archive = self.sandbox / (name + ".zip")
                executable = self.sandbox / (name + ".exe")
                if entries is None:
                    archive.write_bytes(b"not a ZIP archive")
                else:
                    with zipfile.ZipFile(archive, "w") as output:
                        for path, contents in entries.items():
                            output.writestr(path, contents)
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-File", str(SCAN_AGENT_DIR / "build_workstation_exe.ps1"),
                     "-PackageZip", str(archive), "-Out", str(executable)],
                    capture_output=True, text=True, timeout=120,
                )
                details = result.stdout + result.stderr
                if valid:
                    self.assertEqual(result.returncode, 0, details)
                    self.assertTrue(executable.is_file())
                else:
                    self.assertNotEqual(result.returncode, 0, details)
                    self.assertIn("Extractor validation failed: 2", details)

    @unittest.skipUnless(os.environ.get("LETTERSYS_TEST_EMBED_ZIP"), "set LETTERSYS_TEST_EMBED_ZIP to an official embeddable zip")
    def test_full_build_then_install_from_built_package(self):
        rc, out, dest = self.build(embed=os.environ["LETTERSYS_TEST_EMBED_ZIP"], origin="https://127.0.0.1:1")
        self.assertEqual(rc, 0, out)
        cfg = json.loads((dest / "config.json").read_text(encoding="ascii"))
        self.assertEqual(cfg["server_origin"], "https://127.0.0.1:1")
        self.assertEqual(cfg["root_cert_sha256"], _sha(self.cer))
        self.assertEqual(cfg["root_cert_thumbprint"], self.certs.thumb)
        for rel in ("Setup.vbs", "Setup.cmd", "setup_messages.txt", "THIRD_PARTY_LICENSES.txt", "root_ca.cer",
                    "naps2_portable/NAPS2.exe", "naps2_portable/NAPS2.Console.exe", "naps2_portable/lib/NAPS2.Sdk.dll",
                    "python/pythonw.exe", "scan_agent/install_agent.bat"):
            self.assertTrue((dest / rel).is_file(), rel)
        self.assertFalse((dest / "naps2_portable" / "NAPS2.Portable.exe").exists())
        for f in SCAN_AGENT_DIR.glob("*.py"):
            self.assertEqual((dest / "scan_agent" / f.name).is_file(), not f.name.startswith("tests_"), f.name)
        names = {p.name for p in (dest / "scan_agent").iterdir()}
        self.assertFalse({n for n in names if n.startswith(("Setup", "setup_", "test", "build_")) or n == "__pycache__"})
        self.assertFalse([p for p in dest.rglob("*") if p.suffix in (".pfx", ".key", ".pem", ".sqlite3") or p.name.startswith(".env")])
        listed = {}
        for line in (dest / "SHA256SUMS.txt").read_text(encoding="ascii").splitlines():
            h, rel = line.split("  ", 1)
            listed[rel] = h
        actual = {str(p.relative_to(dest)): _sha(p) for p in dest.rglob("*") if p.is_file() and p.name != "SHA256SUMS.txt"}
        self.assertEqual(listed, actual)

        # End to end: the built package installs (fixture LOCALAPPDATA) and its REAL agent
        # starts from the installed runtime folder, answers health, and the package copy can
        # be deleted afterwards without affecting the installed agent.
        t = WorkstationSetupTests("test_no_start_install_succeeds_and_writes_structured_result")
        t.sandbox = self.sandbox
        t.local, t.roaming, t.tmp = self.sandbox / "local app", self.sandbox / "roaming", self.sandbox / "tmp"
        for d in (t.local, t.roaming, t.tmp):
            d.mkdir()
        t.pkg = dest
        t.certs = self.certs
        port = _free_port()
        self.addCleanup(_ps, "$ErrorActionPreference = 'Stop'; Get-Process | Where-Object { $_.Path -like "
                             f"'{self.sandbox}\\*' }} | ForEach-Object {{ Stop-Process -Id $_.Id -Force }}")
        rc, res, out = t.run_setup(LETTERSYS_AGENT_PORT=str(port))
        self.assertEqual(res["agent_status"], "healthy", out)
        self.assertIn(rc, (0, 31, 32), out)
        procs = _ps("Get-Process pythonw -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "
                    f"'{self.sandbox}\\*' }} | ForEach-Object {{ $_.Path }}").strip().splitlines()
        self.assertEqual([p.lower() for p in procs], [str(t.agent_dir / "python" / "pythonw.exe").lower()])
        shutil.rmtree(dest)
        import urllib.request
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/agent/health", timeout=10) as r:
            health = json.loads(r.read().decode("utf-8"))
        self.assertTrue(health["ok"])
        self.assertTrue(health["naps2_path"].lower().startswith(str(t.naps2_dest).lower()))


def tearDownModule():
    shutil.rmtree(PROJECT_DIR / "test_sandbox_ws_certs", ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
