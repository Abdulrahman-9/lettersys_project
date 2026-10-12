import tempfile
import unittest
from importlib import util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import scripts.windows_service as windows_service
from scripts.windows_service import _daphne_command, validate_runtime_settings


class WindowsServiceConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.static_root = tempfile.TemporaryDirectory()
        Path(self.static_root.name, "manifest.json").write_text("{}", encoding="utf-8")
        self.settings = SimpleNamespace(
            DEBUG=False,
            SECRET_KEY="configured-secret",
            ALLOWED_HOSTS=["192.168.1.50"],
            CSRF_TRUSTED_ORIGINS=["http://192.168.1.50:1312"],
            SECURE_PROXY_SSL_HEADER=None,
            SECURE_SSL_REDIRECT=False,
            SECURE_HSTS_SECONDS=0,
            SESSION_COOKIE_SECURE=False,
            CSRF_COOKIE_SECURE=False,
        )

    def tearDown(self):
        self.static_root.cleanup()

    def test_complete_private_lan_http_configuration_is_accepted(self):
        validate_runtime_settings(
            self.settings, "192.168.1.50", 1312, self.static_root.name
        )

    def test_development_or_incomplete_configuration_is_rejected(self):
        self.settings.DEBUG = True
        with self.assertRaisesRegex(RuntimeError, "DEBUG must be False"):
            validate_runtime_settings(
                self.settings, "192.168.1.50", 1312, self.static_root.name
            )

    def test_missing_static_manifest_is_rejected(self):
        Path(self.static_root.name, "manifest.json").unlink()
        with self.assertRaisesRegex(RuntimeError, "run collectstatic"):
            validate_runtime_settings(
                self.settings, "192.168.1.50", 1312, self.static_root.name
            )

    def test_public_address_must_be_a_private_ipv4(self):
        with self.assertRaisesRegex(RuntimeError, "private IPv4"):
            validate_runtime_settings(
                self.settings, "lettersys.company.local", 1312, self.static_root.name
            )

    def test_http_origin_must_match_address_and_port(self):
        self.settings.CSRF_TRUSTED_ORIGINS = ["https://192.168.1.50"]
        with self.assertRaisesRegex(RuntimeError, "CSRF_TRUSTED_ORIGINS"):
            validate_runtime_settings(
                self.settings, "192.168.1.50", 1312, self.static_root.name
            )

    def test_https_only_settings_are_rejected_for_http_deployment(self):
        self.settings.SECURE_SSL_REDIRECT = True
        self.settings.SECURE_HSTS_SECONDS = 31536000
        self.settings.SESSION_COOKIE_SECURE = True
        self.settings.CSRF_COOKIE_SECURE = True
        self.settings.SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
        with self.assertRaisesRegex(RuntimeError, "HTTP access"):
            validate_runtime_settings(
                self.settings, "192.168.1.50", 8080, self.static_root.name
            )

    def test_daphne_uses_project_python_not_scm_executable(self):
        with tempfile.TemporaryDirectory() as root:
            python = Path(root) / ".venv" / "Scripts" / "python.exe"
            python.parent.mkdir(parents=True)
            python.touch()
            with patch("scripts.windows_service.BASE_DIR", Path(root)), patch(
                "scripts.windows_service.sys.executable", "pythonservice.exe"
            ):
                command = _daphne_command(1313)
            self.assertEqual(command, [
                str(python), "-m", "daphne", "-b", "127.0.0.1",
                "-p", "1313", "lettersys.asgi:application",
            ])

    def test_missing_project_python_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            with patch("scripts.windows_service.BASE_DIR", Path(root)):
                with self.assertRaisesRegex(RuntimeError, "service requires"):
                    _daphne_command(1313)

    def test_windows_service_class_is_module_level_when_pywin32_is_available(self):
        if util.find_spec("win32serviceutil") is None:
            self.skipTest("pywin32 is not installed in this environment")
        self.assertTrue(hasattr(windows_service, "LetterSysDaphneService"))
        self.assertIsNotNone(windows_service.LetterSysDaphneService)
        self.assertEqual(
            windows_service.LetterSysDaphneService.__name__,
            "LetterSysDaphneService",
        )


if __name__ == "__main__":
    unittest.main()
