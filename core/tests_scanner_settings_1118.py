# -*- coding: utf-8 -*-
"""2026-11-18 — قسمُ «الماسح الضوئي» ودليلُ تجهيزه (التصميمُ المعتمد + مراجعةُ فيبل).

١. **مصدرٌ واحدٌ لفحص الوكيل** (scan_agent_client.js): كان المسبارُ مكرَّراً في صفحة الإدخال
   وصفحة الإعدادات، والأخيرةُ تعرض مسارَ NAPS2 (فيه اسمُ مستخدم ويندوز) وتكتب أسماءَ الماسحات
   بـinnerHTML.
٢. **لمن يمسح**: القسمُ لمن يستعمل صفحة الإدخال ولجمهور الإدارة، ولا يغيّر إعداداً في الخادم.
٣. **قواعدُ فيبل**: لا «جاهز» قبل مسحٍ ناجح · تأكيدٌ قبل سحب الورقة والناتجُ لا يُرفع · إعادةُ
   البحث طلبٌ واحدٌ بتراجعٍ حتّى دقيقتين ويتوقّف عند الإخفاء · التقريرُ قائمةٌ بيضاء.
٤. **التوست في صفحة الإدخال** أعلى المعاينة لا فوق أزرار المسح (قاعدةُ الهويّة كانت تغلب).
"""
import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from core.netaddr import approved_https_origin
from core.testing import as_writer

ROOT = Path(__file__).resolve().parent.parent
User = get_user_model()


def _read(rel):
    return (ROOT / rel).read_text(encoding='utf-8')


def _function(src, signature):
    """جسمُ دالّةٍ في ملفّ JS (من توقيعها إلى أوّل سطرٍ يبدأ بـ«  }» بعده)."""
    start = src.index(signature)
    end = src.index('\n  }\n', start)
    return src[start:end]


class ScannerSectionAccessTests(TestCase):
    def test_a_clerk_who_scans_reaches_the_guide(self):
        clerk = as_writer(User.objects.create_user('scs_clerk', password='pw-scs-11'))
        self.client.force_login(clerk)
        r = self.client.get(reverse('scan_settings'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'id="scsWizard"')
        self.assertContains(r, 'دليل التجهيز السريع')

    def test_a_reader_without_a_role_is_refused(self):
        self.client.force_login(User.objects.create_user('scs_reader', password='pw-scs-12'))
        self.assertIn(self.client.get(reverse('scan_settings')).status_code, (302, 403))

    def test_scripts_load_the_shared_client_first(self):
        clerk = as_writer(User.objects.create_user('scs_clerk2', password='pw-scs-13'))
        self.client.force_login(clerk)
        html = self.client.get(reverse('scan_settings')).content.decode('utf-8')
        self.assertLess(html.index('js/scan_agent_client.js'), html.index('js/scanner_settings.js'))

    def test_the_package_link_is_offered_over_https_only(self):
        """التنزيلُ يُرفض بـHTTP (device_setup_download) — فلا يُعرض زرٌّ يقود إلى رفض."""
        clerk = as_writer(User.objects.create_user('scs_clerk3', password='pw-scs-14'))
        self.client.force_login(clerk)
        html = self.client.get(reverse('scan_settings')).content.decode('utf-8')
        self.assertIn('data-package-url=""', html)


class ApprovedOriginTests(SimpleTestCase):
    def setUp(self):
        self.rf = RequestFactory()

    def test_a_secure_page_is_its_own_approved_origin(self):
        req = self.rf.get('/books/settings/scan/', secure=True, HTTP_HOST='lettersys.test')
        self.assertEqual(approved_https_origin(req), 'https://lettersys.test')

    @override_settings(CSRF_TRUSTED_ORIGINS=['http://lettersys.test:1312', 'https://lettersys.test'],
                       ALLOWED_HOSTS=['lettersys.test'])
    def test_an_insecure_page_points_to_the_single_https_origin(self):
        req = self.rf.get('/books/settings/scan/', HTTP_HOST='lettersys.test:1312')
        self.assertEqual(approved_https_origin(req), 'https://lettersys.test')

    @override_settings(CSRF_TRUSTED_ORIGINS=['https://lettersys.test', 'https://lettersys.test:8443'],
                       ALLOWED_HOSTS=['lettersys.test'])
    def test_two_https_candidates_name_none(self):
        req = self.rf.get('/books/settings/scan/', HTTP_HOST='lettersys.test:1312')
        self.assertEqual(approved_https_origin(req), '')

    @override_settings(CSRF_TRUSTED_ORIGINS=['https://other.test'], ALLOWED_HOSTS=['lettersys.test'])
    def test_another_host_is_never_offered(self):
        req = self.rf.get('/books/settings/scan/', HTTP_HOST='lettersys.test:1312')
        self.assertEqual(approved_https_origin(req), '')


class ScannerSettingsScriptTests(SimpleTestCase):
    def setUp(self):
        self.js = _read('static/js/scanner_settings.js')

    def test_agent_text_is_never_html(self):
        code = '\n'.join(l for l in self.js.splitlines() if not l.strip().startswith(('*', '/**', '//')))
        self.assertNotIn('innerHTML', code)
        self.assertNotIn('insertAdjacentHTML', code)

    def test_report_is_a_whitelist(self):
        body = _function(self.js, 'function reportText() {')
        for leak in ('naps2_path', '.pid', 'pair_nonce', 'client_uuid', 'started_at'):
            with self.subTest(leak=leak):
                self.assertNotIn(leak, body)
        self.assertNotIn('naps2_path', self.js)

    def test_ready_is_not_claimed_before_a_scan_worked(self):
        self.assertNotIn('جاهز للمسح', self.js)
        self.assertIn("'الماسح متّصل'", self.js)
        self.assertIn('LAST_SCAN_KEY', _function(self.js, 'function renderSummary(c) {'))

    def test_test_scan_asks_before_pulling_paper_and_uploads_nothing(self):
        body = _function(self.js, 'async function testScan() {')
        self.assertLess(body.index('await confirmApp('), body.index('Agent.scan('))
        self.assertNotIn('process-upload', self.js)
        self.assertIn('URL.revokeObjectURL', self.js)

    def test_rediscovery_is_one_request_with_backoff_that_pauses(self):
        self.assertIn('const RETRY_FIRST_MS = 5000;', self.js)
        self.assertIn('const RETRY_MAX_MS = 120000;', self.js)
        self.assertIn('if (st.discovering) return st.discovering;', self.js)
        sched = _function(self.js, 'function maybeScheduleRetry() {')
        for guard in ('wiz.timer', 'document.hidden', 'st.scanning', 'st.discovering'):
            with self.subTest(guard=guard):
                self.assertIn(guard, sched)
        self.assertIn('Math.min(wiz.delay * 2, RETRY_MAX_MS)', sched)

    def test_no_listing_while_scanning_and_no_scan_while_listing(self):
        """الوكيلُ بلا قفلٍ بين السرد والمسح (مراجعةُ فيبل 11-18) — الصفحةُ تحرس الاتّجاهين."""
        self.assertIn('if (st.scanning) return null;', _function(self.js, 'async function probe() {'))
        self.assertIn('if (!st.base || st.scanning) return null;', _function(self.js, 'async function discover() {'))
        self.assertIn('if (st.discovering || st.checking) {', _function(self.js, 'async function testScan() {'))

    def test_retry_is_scheduled_after_the_first_probe_ends(self):
        """السردُ داخل الفحص الأوّل لا يجدول (الفحصُ جارٍ)؛ الفحصُ يجدول عند انتهائه."""
        probe = _function(self.js, 'async function probe() {')
        self.assertLess(probe.index('st.checking = false;'), probe.index('maybeScheduleRetry();'))

    def test_only_a_real_pdf_is_ever_opened(self):
        """الناتجُ يُفتح في أصل التطبيق: نوعٌ يعلنه برنامجٌ على المنفذ (text/html) لا يُوثَق به."""
        body = _function(self.js, 'async function testScan() {')
        self.assertIn("if (head !== '%PDF-') {", body)
        self.assertIn("new Blob([buf], { type: 'application/pdf' })", body)
        self.assertNotIn('r.blob()', body)
        self.assertLess(body.index("if (head !== '%PDF-') {"), body.index('store.set(LAST_SCAN_KEY'))

    def test_unmanaged_devices_skip_the_pairing_step(self):
        body = _function(self.js, 'function stepState(key, c) {')
        self.assertIn("if (!c.pairing.required) return 'skip';", body)


class EntryPageTests(SimpleTestCase):
    def setUp(self):
        self.js = _read('static/extraction_smart.js')

    def test_the_entry_page_probes_through_the_shared_client(self):
        for call in ('window.ScanAgentClient.health(', 'window.ScanAgentClient.respondsButRejects(',
                     'window.ScanAgentClient.devices(', 'window.ScanAgentClient.info('):
            with self.subTest(call=call):
                self.assertIn(call, self.js)
        self.assertNotIn("+ '/agent/health'", self.js)
        html = _read('templates/core/extraction_smart_desktop.html')
        self.assertLess(html.index('js/scan_agent_client.js'), html.index("'extraction_smart.js'"))

    def test_agent_help_points_to_the_guide(self):
        self.assertIn("const SCANNER_GUIDE_URL = '/books/settings/scan/?wizard=1';", self.js)
        self.assertIn("else if (act === 'guide') window.location.assign(SCANNER_GUIDE_URL);", self.js)

    def test_a_successful_scan_is_remembered_for_the_section(self):
        scan = self.js[self.js.index('async startScan(opts = {}) {'):]
        scan = scan[:scan.index('\n    }\n')]
        self.assertLess(scan.index("if (!ud.ok) return fail("), scan.index("'lettersys_last_scan_ok'"))

    def test_toasts_sit_above_the_preview_not_over_its_buttons(self):
        css = _read('static/extraction_smart.css')
        m = re.search(r'html:not\(\[data-lx-legacy\]\) \.toast-container\.toast-center \{([^}]*)\}', css)
        self.assertIsNotNone(m, 'قاعدةُ الهويّة تغلب قاعدةَ صفحة الإدخال فينزل التوستُ فوق الأزرار')
        self.assertIn('bottom: auto', m.group(1))
