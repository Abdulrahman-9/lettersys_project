"""Run LetterSys' Daphne ASGI server under the Windows Service Control Manager."""

import ipaddress
import os
import subprocess
import sys
import time
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
LOG_PATH = BASE_DIR / "logs" / "windows_service.log"
LOG_BACKUP_PATH = BASE_DIR / "logs" / "windows_service.log.1"
MAX_LOG_BYTES = 10 * 1024 * 1024
DEFAULT_PORT = 1313
RESTART_DELAY_SECONDS = 5
MAX_RESTART_DELAY_SECONDS = 60


def _write_log(message):
    """Append service lifecycle details without sending them to a console window."""
    LOG_PATH.parent.mkdir(exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as log:
        log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")


def validate_runtime_settings(settings, public_host, public_port, static_root):
    """Reject development or incomplete private-LAN HTTP settings before listening."""
    problems = []
    if settings.DEBUG:
        problems.append("DEBUG must be False")
    if not settings.SECRET_KEY:
        problems.append("DJANGO_SECRET_KEY must be configured")
    if "*" in settings.ALLOWED_HOSTS:
        problems.append("ALLOWED_HOSTS must not contain '*'")
    if not public_host:
        problems.append("LETTERSYS_PUBLIC_HOST must be configured with the server's private IPv4 address")
    else:
        try:
            address = ipaddress.ip_address(public_host)
            if address.version != 4 or not address.is_private:
                problems.append("LETTERSYS_PUBLIC_HOST must be a private IPv4 address")
        except ValueError:
            problems.append("LETTERSYS_PUBLIC_HOST must be a private IPv4 address")
        if public_host not in settings.ALLOWED_HOSTS:
            problems.append("LETTERSYS_PUBLIC_HOST must be listed in ALLOWED_HOSTS")
        elif f"http://{public_host}:{public_port}" not in settings.CSRF_TRUSTED_ORIGINS:
            problems.append(
                "http://LETTERSYS_PUBLIC_HOST:LETTERSYS_PUBLIC_PORT must be in CSRF_TRUSTED_ORIGINS"
            )
    if getattr(settings, "SECURE_PROXY_SSL_HEADER", None) is not None:
        problems.append("USE_X_FORWARDED_PROTO must be False for direct HTTP access")
    if settings.SECURE_SSL_REDIRECT:
        problems.append("SECURE_SSL_REDIRECT must be False for HTTP access")
    if getattr(settings, "SECURE_HSTS_SECONDS", 0):
        problems.append("SECURE_HSTS_SECONDS must be 0 for HTTP access")
    if settings.SESSION_COOKIE_SECURE or settings.CSRF_COOKIE_SECURE:
        problems.append("secure session and CSRF cookies must be False for HTTP access")
    if not (Path(static_root) / "manifest.json").is_file():
        problems.append("run collectstatic; STATIC_ROOT/manifest.json is missing")
    if problems:
        raise RuntimeError("Unsafe or incomplete private-LAN HTTP configuration: " + "; ".join(problems))


def _validate_service_configuration():
    os.environ["DJANGO_SETTINGS_MODULE"] = "lettersys.settings"
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

    from django.conf import settings

    host = os.environ.get("LETTERSYS_PUBLIC_HOST", "").strip()
    try:
        public_port = int(os.environ.get("LETTERSYS_PUBLIC_PORT", "1312"))
    except ValueError as exc:
        raise RuntimeError("LETTERSYS_PUBLIC_PORT must be an integer") from exc
    if not 1 <= public_port <= 65535:
        raise RuntimeError("LETTERSYS_PUBLIC_PORT must be between 1 and 65535")
    validate_runtime_settings(settings, host, public_port, settings.STATIC_ROOT)
    try:
        service_port = int(os.environ.get("LETTERSYS_SERVICE_PORT", str(DEFAULT_PORT)))
    except ValueError as exc:
        raise RuntimeError("LETTERSYS_SERVICE_PORT must be an integer") from exc
    if not 1 <= service_port <= 65535:
        raise RuntimeError("LETTERSYS_SERVICE_PORT must be between 1 and 65535")
    return service_port


def _rotate_log_if_needed():
    if LOG_PATH.exists() and LOG_PATH.stat().st_size >= MAX_LOG_BYTES:
        if LOG_BACKUP_PATH.exists():
            LOG_BACKUP_PATH.unlink()
        LOG_PATH.replace(LOG_BACKUP_PATH)


def _daphne_command(port):
    # SCM runs pythonservice.exe, so sys.executable is not a Python CLI there.
    python = BASE_DIR / ".venv" / "Scripts" / "python.exe"
    if not python.is_file():
        raise RuntimeError("The service requires .venv/Scripts/python.exe in the project directory")
    return [
        str(python), "-m", "daphne",
        "-b", "127.0.0.1", "-p", str(port), "lettersys.asgi:application",
    ]


def _make_service_class(win32event, win32service, win32serviceutil, servicemanager):
    class LetterSysDaphneService(win32serviceutil.ServiceFramework):
        _svc_name_ = "LetterSysDaphne"
        _svc_display_name_ = "LetterSys Daphne Web Service"
        _svc_description_ = "Serves the LetterSys ASGI application on localhost for the LAN HTTP proxy."

        def __init__(self, args):
            super().__init__(args)
            self.stop_event = win32event.CreateEvent(None, 0, 0, None)
            self.process = None

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING, 30000)
            win32event.SetEvent(self.stop_event)
            if self.process and self.process.poll() is None:
                self.process.terminate()

        def SvcDoRun(self):
            self.ReportServiceStatus(win32service.SERVICE_RUNNING)
            servicemanager.LogInfoMsg("LetterSys Daphne service is starting.")
            self._serve_until_stopped()

        def _stopping(self):
            return win32event.WaitForSingleObject(self.stop_event, 0) == win32event.WAIT_OBJECT_0

        def _wait_or_stop(self, seconds):
            return win32event.WaitForSingleObject(self.stop_event, seconds * 1000) == win32event.WAIT_OBJECT_0

        def _stop_child(self):
            if not self.process or self.process.poll() is not None:
                return
            self.process.terminate()
            try:
                self.process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)

        def _serve_until_stopped(self):
            delay = RESTART_DELAY_SECONDS
            while not self._stopping():
                try:
                    port = _validate_service_configuration()
                    _rotate_log_if_needed()
                    command = _daphne_command(port)
                    with LOG_PATH.open("ab", buffering=0) as log:
                        self.process = subprocess.Popen(
                            command,
                            cwd=str(BASE_DIR),
                            stdin=subprocess.DEVNULL,
                            stdout=log,
                            stderr=subprocess.STDOUT,
                            close_fds=True,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                        )
                        _write_log(f"Daphne started on 127.0.0.1:{port} (PID {self.process.pid}).")
                        delay = RESTART_DELAY_SECONDS
                        while not self._stopping():
                            return_code = self.process.poll()
                            if return_code is not None:
                                _write_log(f"Daphne exited with code {return_code}.")
                                break
                            self._wait_or_stop(1)
                        self._stop_child()
                except Exception as exc:
                    message = f"Startup failed: {type(exc).__name__}: {exc}"
                    _write_log(message)
                    servicemanager.LogErrorMsg(message)
                finally:
                    self.process = None

                if self._stopping():
                    break
                _write_log(f"Retrying Daphne in {delay} seconds.")
                if self._wait_or_stop(delay):
                    break
                delay = min(delay * 2, MAX_RESTART_DELAY_SECONDS)

            _write_log("LetterSys Daphne service stopped.")
            servicemanager.LogInfoMsg("LetterSys Daphne service stopped.")

    return LetterSysDaphneService


def _load_service_runtime():
    if os.name != "nt":
        raise SystemExit("This command is supported on Windows only.")
    try:
        import servicemanager
        import win32event
        import win32service
        import win32serviceutil
    except ImportError as exc:
        raise SystemExit(
            "pywin32 is required. Install project dependencies before registering the service."
        ) from exc
    return servicemanager, win32event, win32service, win32serviceutil


# Expose a module-level class so pythonservice.exe can import it by name.
if os.name == "nt":
    try:
        (
            _servicemanager,
            _win32event,
            _win32service,
            _win32serviceutil,
        ) = _load_service_runtime()
        LetterSysDaphneService = _make_service_class(
            _win32event, _win32service, _win32serviceutil, _servicemanager
        )
    except SystemExit:
        LetterSysDaphneService = None
else:
    LetterSysDaphneService = None


def main():
    _, _, _, win32serviceutil = _load_service_runtime()
    service_class = LetterSysDaphneService
    if service_class is None:
        raise SystemExit("LetterSys service class is unavailable. Verify pywin32 installation.")
    win32serviceutil.HandleCommandLine(service_class)


if __name__ == "__main__":
    main()
