import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse


class DeviceSetupTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username='device-user')

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.package = Path(self.folder.name) / 'workstation.zip'
        self.setting = override_settings(WORKSTATION_SETUP_PACKAGE=self.package)
        self.setting.enable()
        self.addCleanup(self.setting.disable)

    def test_all_routes_require_login(self):
        for name in ('device_setup', 'device_setup_health', 'device_setup_download'):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 302)

    def test_normal_user_can_use_page_without_staff_role(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('device_setup'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'فحص هذا الجهاز')
        self.assertContains(response, 'حزمة التجهيز لم ينشرها')
        self.assertNotContains(response, 'id="downloadSetup"')
        self.assertIn('no-store', response.headers['Cache-Control'])

    def test_available_package_shows_download_and_installer_steps(self):
        self.package.write_bytes(b'package')
        self.client.force_login(self.user)
        response = self.client.get(reverse('device_setup'), secure=True)
        self.assertContains(response, 'id="downloadSetup"')
        self.assertContains(response, 'Setup.vbs')
        self.assertContains(response, 'ليس «تشغيل كمسؤول»')

    def test_missing_package_is_an_explicit_503(self):
        self.client.force_login(self.user)
        with self.assertLogs('lettersys', level='WARNING'):
            response = self.client.get(reverse('device_setup_download'), secure=True)
        self.assertEqual(response.status_code, 503)
        self.assertContains(response, 'غير متوفرة', status_code=503)

    def test_download_ignores_client_path_and_uses_configured_package(self):
        self.package.write_bytes(b'fixed-workstation-package')
        self.client.force_login(self.user)
        response = self.client.get(reverse('device_setup_download'), {'path': '../.env'}, secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b''.join(response.streaming_content), b'fixed-workstation-package')
        self.assertIn('LetterSys-Workstation.zip', response.headers['Content-Disposition'])
        self.assertIn('no-store', response.headers['Cache-Control'])

    def test_http_never_distributes_a_trust_installer(self):
        self.package.write_bytes(b'package')
        self.client.force_login(self.user)
        page = self.client.get(reverse('device_setup'))
        self.assertNotContains(page, 'id="downloadSetup"')
        self.assertContains(page, 'التنزيل من هذه الصفحة غير متاح')
        with self.assertLogs('lettersys', level='WARNING'):
            response = self.client.get(reverse('device_setup_download'))
        self.assertEqual(response.status_code, 400)

    def test_executable_download_keeps_the_correct_filename_and_type(self):
        executable = Path(self.folder.name) / 'setup.exe'
        executable.write_bytes(b'MZ-fixture-only')
        self.client.force_login(self.user)
        with override_settings(WORKSTATION_SETUP_PACKAGE=executable):
            response = self.client.get(reverse('device_setup_download'), secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('LetterSys-Workstation-Setup.exe', response.headers['Content-Disposition'])
        self.assertEqual(response.headers['Content-Type'], 'application/octet-stream')
        self.assertEqual(b''.join(response.streaming_content), b'MZ-fixture-only')

    def test_setup_explains_server_and_client_roles_without_installing_server_services(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('device_setup'), secure=True)
        self.assertContains(response, 'الأجهزة الأخرى كلاينت')
        self.assertContains(response, 'لا تحتاج حزمة الكلاينت')
        self.assertNotContains(response, 'إدارة أجهزة الكلاينت من السيرفر')

    def test_health_checks_authenticated_server_and_rejects_post(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('device_setup_health'))
        self.assertEqual(response.json(), {'ok': True})
        self.assertIn('no-store', response.headers['Cache-Control'])
        for name in ('device_setup', 'device_setup_health', 'device_setup_download'):
            with self.subTest(name=name):
                self.assertEqual(self.client.post(reverse(name)).status_code, 405)

    def test_every_step_has_a_real_action_and_manual_recovery(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('device_setup'), secure=True)
        for action in ('secureSetupLink', 'showTrustHelp', 'retryConnection', 'checkDevice',
                       'showSetupHelp', 'recheckAfterSetup', 'showScannerHelp', 'recheckScanner',
                       'goEnrollment', 'pairWorkstation', 'installSetupApp'):
            self.assertContains(response, 'id="' + action + '"')
        self.assertContains(response, reverse('book_create_incoming'))
        self.assertContains(response, 'لا تختَر تجاوز تحذير الشهادة')

    def test_http_https_action_uses_configured_https_port_not_http_port(self):
        self.client.force_login(self.user)
        with override_settings(CSRF_TRUSTED_ORIGINS=['https://testserver:8443']):
            response = self.client.get(reverse('device_setup'), HTTP_HOST='testserver:1312')
        self.assertContains(response, 'href="https://testserver:8443/books/device-setup/"')
        self.assertNotContains(response, 'href="https://testserver:1312')

    def test_missing_or_ambiguous_https_address_offers_help_not_a_guessed_link(self):
        self.client.force_login(self.user)
        for origins in ([], ['https://testserver', 'https://testserver:8443']):
            with self.subTest(origins=origins), override_settings(CSRF_TRUSTED_ORIGINS=origins):
                response = self.client.get(reverse('device_setup'), HTTP_HOST='testserver:1312')
                self.assertNotContains(response, 'id="secureSetupLink"')
                self.assertContains(response, 'اطلب الرابط الآمن')
