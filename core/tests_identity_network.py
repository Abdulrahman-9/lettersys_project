"""«الشبكة والأجهزة» على الهويّة v2 (2026-11-19) — حارسٌ لكلّ ما نُقل أو أُصلح في العرض.

العرضُ وحده: القواعدُ في core/devices/service.py ولها حرّاسُها في core/devices/tests.py. هنا ما يخصّ الصفحة:
الاشتراكُ في الهويّة، ورقةُ أنماطٍ على الرموز وحدها، ولا نافذةَ أصليّة، والأعطابُ التي أُصلحت حتّى لا تعود
(تمدّدُ الصفحة 587px على الهاتف، وتبهيتُ الأوضاع للقراءة، والقائمةُ الحيّة التي تُقرأ كلَّ 10 ث …).
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase
from django.urls import reverse

from core.devices.tests import DevicesTestBase

ROOT = Path(settings.BASE_DIR)
PAGE = ROOT / 'templates' / 'core' / 'devices' / 'page.html'
THIS_DEVICE = ROOT / 'templates' / 'core' / 'devices' / '_this_device.html'
CSS = ROOT / 'static' / 'css' / 'devices.css'
PAGE_JS = ROOT / 'static' / 'js' / 'devices_page.js'
COMMON_JS = ROOT / 'static' / 'js' / 'devices_common.js'


def _read(path):
    return path.read_text(encoding='utf-8')


def _css_rules(css):
    """‎[(المحدِّد, الجسم)]‎ لكلّ قاعدةٍ ورقيّة (داخل ‎@container/@media‎ أيضاً)، بلا تعليقات."""
    css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    return [(sel.strip(), body) for sel, body in re.findall(r'([^{}]+)\{([^{}]*)\}', css)]


class NetworkPageSourceGuards(SimpleTestCase):
    def test_page_opts_into_the_v2_identity(self):
        self.assertIn('{% block html_attrs %} data-lx-page="v2"{% endblock %}', _read(PAGE))

    def test_sheet_is_tokens_only(self):
        css = re.sub(r'/\*.*?\*/', '', _read(CSS), flags=re.S)
        self.assertNotIn('[data-theme', css, 'سمةُ الوضع القديم ميّتة: الداكنُ ‎[data-bs-theme]‎ من الرموز')
        self.assertEqual(re.findall(r'\b(?:rgba?|hsla?)\(', css), [], 'لونٌ خامّ: الألوانُ من ‎--lx-*‎ وحدها')
        self.assertEqual(re.findall(r':\s*(?:white|black)\b', css), [])
        hexes = re.findall(r'#[0-9a-fA-F]{3,8}\b', css)
        self.assertEqual(hexes, ['#fff'], 'الأبيضُ وحده مسموح، حبراً على التركواز العميق')
        mark = [body for sel, body in _css_rules(css) if '#fff' in body]
        self.assertEqual(len(mark), 1)
        self.assertIn('var(--lx-hero-a)', mark[0], 'الأبيضُ حبرٌ على سطح «القيادة» وحده (علامةُ الصفحة)')

    def test_templates_carry_no_inline_style(self):
        for path in (PAGE, THIS_DEVICE):
            with self.subTest(template=path.name):
                self.assertNotIn('style="', _read(path), 'الشكلُ في devices.css — ولا لونَ في سمة style')

    def test_no_native_dialogs(self):
        for path in (PAGE_JS, COMMON_JS):
            with self.subTest(script=path.name):
                self.assertEqual(re.findall(r'(?<![\w.])(?:alert|confirm|prompt)\(', _read(path)), [])
        self.assertIn('window.confirmDelete({', _read(PAGE_JS))

    def test_the_table_scroller_contains_its_positioned_children(self):
        """العطب: عنوانُ عمود الإجراءات ‎.visually-hidden‎ (مطلقُ الموضع) يفلت من إطار التمرير غيرِ الموضعيّ
        إلى طرف الصفحة الأيسر — فتتّسع 587px على الهاتف وتظهر لقطتُه بيضاء."""
        bodies = [body for sel, body in _css_rules(_read(CSS)) if sel == '.dvs-table-wrap']
        self.assertTrue(bodies)
        self.assertRegex(' '.join(bodies), r'position:\s*relative')
        self.assertRegex(' '.join(bodies), r'overflow-x:\s*auto')

    def test_no_grid_track_is_wider_than_a_phone(self):
        """‎minmax(380px, 1fr)‎ كان يمدّ «هذا الجهاز» 9px على 390، و‎minmax(320px…)‎ يضغط بطاقاتِ المدير."""
        css = _read(CSS)
        self.assertEqual(re.findall(r'minmax\(\s*\d+(?:\.\d+)?(?:px|rem|em)', css), [],
                         'مسارٌ بحدٍّ أدنى ثابت: ‎minmax(min(Xpx, 100%), 1fr)‎ أو استعلامُ الحاوية')

    def test_read_only_modes_keep_their_contrast(self):
        """للقراءة (ليس جهازَ الخادم) كان ‎opacity:.6‎ يُنزل وصفَ الوضع إلى 2.6:1 — والفاحصُ لا يراه."""
        for sel, body in _css_rules(_read(CSS)):
            if '.dvs-mode' in sel:
                with self.subTest(selector=sel):
                    self.assertNotIn('opacity', body)

    def test_the_step_description_rule_spares_the_number(self):
        """‎.dvs-steps span‎ كان يصبغ رقمَ الخطوة ومسارَ الملفّ بالخافت ويصغّرهما."""
        selectors = [sel for sel, _ in _css_rules(_read(CSS))]
        self.assertNotIn('.dvs-steps span', selectors)
        self.assertIn('.dvs-steps li > div > span', selectors)

    def test_the_requests_list_is_not_a_live_region(self):
        """القائمةُ تُعاد رسمُها مع التحديث الحيّ: منطقةً حيّة كانت تُقرأ كلُّها لقارئ الشاشة كلَّ 10 ث."""
        page = _read(PAGE)
        tag = re.search(r'<ul\b[^>]*\bid="dvsRequests"[^>]*>', page).group(0)
        self.assertNotIn('aria-live', tag)
        self.assertRegex(page, r'<p class="visually-hidden" role="status" id="dvsReqStatus"></p>')

    def test_the_poll_redraws_only_what_changed(self):
        """إعادةُ البناء كلَّ 10 ث بلا تغيّر تُسقط التركيزَ عن زرّ «إجراءات» تحت يد المستخدم."""
        js = _read(PAGE_JS)
        body = js[js.index('async function refresh('):js.index('function announceRequest(')]
        self.assertIn('if (changed) keepFocus(render);', body)
        self.assertNotRegex(body, r'(?m)^\s*render\(\);', 'رسمٌ غيرُ مشروط في التحديث الحيّ')
        self.assertIn("if ($('dvsLiveText').textContent !== text)", js, 'role=status يُقرأ مع كلّ تحديث')

    def test_the_code_digits_fit_a_phone(self):
        """خمسُ خاناتٍ بعرض 68px ثابت = 385px لا تدخل حواريّةَ هاتفٍ عرضُه 390."""
        bodies = [body for sel, body in _css_rules(_read(CSS)) if sel == '.dvs-digit']
        self.assertRegex(' '.join(bodies), r'width:\s*clamp\(')

    def test_the_crumb_returns_to_its_tab_and_hides_inside_the_hub(self):
        page = _read(PAGE)
        nav = re.search(r'<nav class="dvs-crumbs[^"]*"[^>]*>.*?</nav>', page, re.S).group(0)
        self.assertIn('settings-embed-hide', nav, 'داخل لوحة المركز يحمّل الرابطُ المركزَ في نفسه')
        self.assertIn("{% url 'settings_hub' %}?tab=network", nav)
        self.assertIn('aria-label="مسار التصفّح"', nav)

    def test_changed_assets_are_cache_busted(self):
        page = _read(PAGE)
        self.assertIn("{% static 'css/devices.css' %}?v=20261119-pages", page)
        self.assertIn("{% static 'js/devices_page.js' %}?v=20261119-pages", page)


class NetworkPageRenderGuards(DevicesTestBase):
    """الصفحةُ كما تُرسم: المديرُ قبل الإعلان وبعده، والموظّفُ يرى جهازَه — كلُّها على الهويّة."""

    def _count_tag(self, page):
        return re.search(r'<span[^>]*\bid="dvsReqCount"[^>]*>', page).group(0)

    def test_zero_counts_are_neutral_and_a_request_turns_amber(self):
        page = self.server.get(reverse('network_settings')).content.decode()
        self.assertIn('data-lx-page="v2"', page)
        self.assertNotIn('data-tone', self._count_tag(page), 'صفرُ طلبات بلون «ينتظر» يقول ما ليس')
        self.assertNotIn('class="dvs-stat" data-tone', page)
        self.declare()
        _, clerk = self.user_client()
        clerk.get(reverse('dashboard'))
        clerk.post(reverse('device_join_request'))
        page = self.server.get(reverse('network_settings')).content.decode()
        self.assertIn('data-tone="wait"', self._count_tag(page))

    def test_a_read_only_gate_says_why(self):
        lock = 'يُغيَّر من جهاز الخادم'
        page = self.server.get(reverse('network_settings')).content.decode()
        self.assertIn(lock, page)                          # لا خادمَ بعد: الأوضاعُ للقراءة
        self.assertRegex(page, r'<fieldset class="dvs-modes" id="dvsModes"\s+disabled')
        self.declare()
        page = self.server.get(reverse('network_settings')).content.decode()
        self.assertNotIn(lock, page)                       # جهازُ الخادم يغيّرها

    def test_this_device_is_v2_too(self):
        _, clerk = self.user_client()
        page = clerk.get(reverse('network_settings')).content.decode()
        self.assertIn('data-lx-page="v2"', page)
        self.assertIn('id="dvsMe"', page)
        self.assertIn('class="dvs-state" data-tone="done"', _read(THIS_DEVICE))
