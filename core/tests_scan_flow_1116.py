# -*- coding: utf-8 -*-
"""2026-11-16 — المسحُ والنوافذُ الأصليّة: أمرُ المالك «أريد التوست احترافيّاً».

١. **نوافذُ المتصفّح الأصليّة** (يعنونها «172.16.2.16 says» وتكسر اتّجاهَ الصفحة): تحريرُ الرقم
   المحجوز، واختلافُ رقم الصادر، وإيقافُ ربط جهاز، ورسائلُ مسح الشبكة، وتأكيدٌ مكرَّر في لوحة
   الإدارة كان يسأل **بعد** موافقة حواريّة التطبيق. صارت حواريّةَ التطبيق وتوستاتِه؛ وتبقى
   ``window.confirm`` احتياطاً وحيداً حين تغيب الحواريّة.
٢. **المسحُ يبدو متجمّداً**: كان المسحُ العاديّ يكتفي بسطرٍ صغيرٍ بجوار الزرّ طوال انتظار الماسح
   والرفع؛ الآن أوفرلاي الرفع نفسُه في لوحة المعاينة من أوّل لحظةٍ حتى تُرسَم الورقة، بمرحلةٍ
   حقيقيّة لكلّ خطوة. والشريطُ الثابتُ أعلى الصفحة بألوانٍ مكتوبةٍ يدويّاً صار توستَ التطبيق.
٣. **«لا يثق بعنوان هذا الخادم»**: خطوةٌ يفعلها الموظّف (المُثبِّت) لا تحريرُ JSON مخفيّ، ولا
   «أعد تشغيل الوكيل» — الوكيلُ ≥ 1.2.0 يقرأ agent.json حيّاً، وخطأُ الإعداد يصل توستاً.
"""
import re
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parent.parent


def _read(rel):
    return (ROOT / rel).read_text(encoding='utf-8')


def _method(src, signature):
    """جسمُ دالّةٍ في صنف ES (من توقيعها إلى أوّل سطرٍ يبدأ بـ«    }» بعده)."""
    start = src.index(signature)
    end = src.index('\n    }\n', start)
    return src[start:end]


class NativeDialogsTests(SimpleTestCase):
    def setUp(self):
        self.js = _read('static/extraction_smart.js')

    def test_releasing_a_reserved_number_asks_through_the_app(self):
        body = _method(self.js, 'async _releaseCurrentReservation() {')
        self.assertIn('window.confirmDelete({', body)
        self.assertEqual(body.count('window.confirm('), 1, 'confirm() أصليّة خارج الاحتياط')
        self.assertIn("title: 'تحرير الرقم المحجوز'", body)

    def test_number_mismatch_is_an_action_toast_not_a_blocking_dialog(self):
        body = _method(self.js, '_reconcileManualNumber(input, extracted, confidence) {')
        self.assertNotIn('window.confirm(', body)
        self.assertIn('window.ToastCenter.action(', body)
        self.assertIn("'اعتمد المقروء'", body)
        self.assertIn("'أبقِ رقمي'", body)
        # رقمُ الموظّف لا يُكتب فوقه إن غيّره بعد السؤال
        self.assertIn('if (input.value !== shown) return;', body)

    def test_device_board_revoke_asks_through_the_app(self):
        src = _read('static/js/workstation_board.js')
        self.assertIn('window.confirmDelete({', src)
        self.assertEqual(src.count('window.confirm('), 1)

    def test_device_pages_have_no_native_dialogs(self):
        for rel in ('static/js/devices_page.js', 'static/js/device_join.js'):
            src = _read(rel)
            self.assertEqual(re.findall(r'(?<![\w.])(?:alert|confirm|prompt)\(', src), [], rel)

    def test_admin_panel_no_longer_asks_twice(self):
        src = _read('templates/core/admin_panel.html')
        self.assertNotRegex(src, r'(?<![\w.])confirm\(')


class ScanProgressTests(SimpleTestCase):
    def setUp(self):
        self.js = _read('static/extraction_smart.js')
        self.scan = _method(self.js, 'async startScan(opts = {}) {')

    def test_overlay_covers_every_scan_not_only_append_mode(self):
        self.assertIn("this._showExtractionOverlay('جارٍ تجهيز الماسح…'", self.scan)
        self.assertNotIn("if (this._scanAppendMode) {\n            this._showExtractionOverlay", self.scan)

    def test_each_stage_is_announced(self):
        for stage in ("'جارٍ تجهيز الماسح…'", "'البحث عن الماسح…'", "'جارٍ المسح من '",
                      "'جارٍ رفع المستند…'", "'جارٍ عرض المستند…'"):
            with self.subTest(stage=stage):
                self.assertIn(stage, self.scan)

    def test_stage_text_never_goes_through_innerHTML(self):
        """اسمُ الجهاز يأتي من NAPS2 — setMsg تكتب textContent وحدَها."""
        set_msg = self.scan[self.scan.index('const setMsg = (m, sub) => {'):]
        set_msg = set_msg[:set_msg.index('\n        };')]
        self.assertNotIn('innerHTML', set_msg)
        self.assertIn('textContent', set_msg)

    def test_overlay_never_stays_stuck_when_the_token_load_fails(self):
        body = _method(self.js, "_loadScanToken(token, { notice = null } = {}) {")
        self.assertGreaterEqual(body.count('this._hideExtractionOverlay();'), 3)

    def test_fixed_top_banner_with_hardcoded_colours_is_gone(self):
        body = _method(self.js, "_showProgressBanner(message, type = 'info') {")
        self.assertNotIn('#1d4ed8', body)
        self.assertNotIn('position:fixed', body)
        self.assertIn('this.showToast(', body)


class UntrustedAgentGuidanceTests(SimpleTestCase):
    def setUp(self):
        self.js = _read('static/extraction_smart.js')

    def test_no_restart_instruction_survives(self):
        self.assertNotIn('أعد تشغيل الوكيل', self.js)
        self.assertNotIn('أعد تشغيله', _read('templates/core/scan_settings.html'))

    def test_one_hint_for_the_toast_and_the_scan_failure(self):
        self.assertEqual(self.js.count('UNTRUSTED_AGENT_HINT(window.location.origin)'), 2)
        self.assertIn('INSTALL.bat', self.js[self.js.index('const UNTRUSTED_AGENT_HINT'):][:400])

    def test_config_error_toast_reads_every_health_answer(self):
        body = _method(self.js, 'async _agentHealthNow() {')
        self.assertIn('this._noteAgentConfigError(this._agentHealth);', body)
        note = _method(self.js, '_noteAgentConfigError(hd) {')
        for code in ('invalid_json', 'no_list', 'no_valid_entries', 'unreadable', 'invalid_pairing'):
            with self.subTest(code=code):
                self.assertIn(code + ':', note)
