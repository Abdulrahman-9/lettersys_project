"""حرّاسُ مركز الإعدادات على الهويّة الموحّدة (v2، 11-19).

١. **الصفحةُ منقولة**: تعلن v2؛ ورقتُها على الرموز وحدها (الأبيضُ وحده صريحاً، حبراً فوق التركواز العميق)،
   بلا كتلة الوضع القديم ‎[data-theme]‎ ولا لونٍ في سمة style.
٢. **المكوّنُ المشترك لا نسخةٌ منه**: الشريطُ لوحُ data-lx-tabs (js/lx_tabs.js)؛ لا مؤشّرَ يُقاس ويُحرَّك هنا.
٣. **لا حوارَ أصليّاً** (confirm/alert/prompt).
٤. **أعطابٌ وُجدت وأُصلحت**: h4/h5 بلا h1 · بطاقتا «عام» متلاصقتان · حافّتا الفيض معكوستان في RTL · اللوحاتُ
   مخفيّةٌ حتّى يعمل السكربت (والحفظُ يعود دائماً إلى ?tab=) · التبويبُ لا يدلّ على لوحته · التلميحاتُ غيرُ
   موصولةٍ بحقولها · التاريخُ بلا عزل اتّجاه · حدُّ الثقة يظهر فارغاً («0,4» بالفاصلة العربيّة).
"""
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core.tests_list_identity import DECL, _strip

ROOT = Path(settings.BASE_DIR)
TEMPLATE = 'templates/core/settings/hub.html'
SHEET = 'static/css/settings_hub.css'
SCRIPT = 'static/js/settings_hub.js'


def _read(rel):
    return (ROOT / rel).read_text(encoding='utf-8')


def _rule(css, selector):
    """القاعدةُ التي محدِّدُها هذا وحده (لا عنصراً في قائمة محدِّدات)."""
    return re.search(r'(?:^|\})\s*' + re.escape(selector) + r'\s*\{([^}]*)\}', css).group(1)


class SettingsHubSourceGuards(SimpleTestCase):

    def test_the_sheet_speaks_tokens_only(self):
        values = ' '.join(m.group(2) for m in DECL.finditer(_strip(_read(SHEET))))
        self.assertLessEqual({h.lower() for h in re.findall(r'#[0-9a-fA-F]{3,8}\b', values)}, {'#fff'})
        self.assertNotRegex(values, r'\b(?:rgba?|hsla?)\(\s*\d')

    def test_no_dead_dark_mode_attribute(self):
        for rel in (SHEET, SCRIPT, TEMPLATE):
            with self.subTest(rel=rel):
                self.assertNotRegex(_read(rel), r'\[data-theme|data-theme\s*=')
        self.assertNotIn('prefers-color-scheme', _read(SHEET))

    def test_no_colour_in_style_attributes(self):
        for style in re.findall(r'style="([^"]*)"', _read(TEMPLATE)):
            self.assertNotRegex(style, r'colou?r|#[0-9a-fA-F]{3}|--accent|rgb|hsl|background', style)

    def test_no_native_dialogs(self):
        js = re.sub(r'/\*.*?\*/|//[^\n]*', '', _read(SCRIPT), flags=re.S)
        for src in (js, _read(TEMPLATE)):
            self.assertNotRegex(src, r'(?<![\w.])(?:window\.)?(?:confirm|alert|prompt)\s*\(')

    def test_the_strip_is_the_shared_sliding_board(self):
        src = _read(TEMPLATE)
        self.assertRegex(src, r'id="settingsTabstrip" role="tablist"[^>]*\sdata-lx-tabs>')
        self.assertLess(src.index("{% static 'js/lx_tabs.js' %}"), src.index("{% static 'js/settings_hub.js' %}"))
        for gone in ('moveIndicator', 'indicator.style', 'settingsTabIndicator'):
            self.assertNotIn(gone, _read(SCRIPT))

    def test_headings_start_at_h1(self):
        src = _read(TEMPLATE)
        self.assertEqual(len(re.findall(r'<h1\b', src)), 1)
        self.assertNotRegex(src, r'<h[3-6]\b')

    def test_overflow_fades_are_solid_at_the_edge_in_rtl(self):
        css = _strip(_read(SHEET))
        self.assertIn('linear-gradient(to left, var(--lx-surface)', _rule(css, '.settings-tabstrip-shell::before'))
        self.assertIn('linear-gradient(to right, var(--lx-surface)', _rule(css, '.settings-tabstrip-shell::after'))

    def test_cards_in_one_pane_keep_their_distance(self):
        rule = _rule(_strip(_read(SHEET)), '.settings-pane.is-active')
        self.assertIn('display: grid;', rule)
        self.assertRegex(rule, r'\bgap:\s*[1-9]')

    def test_changed_assets_are_cache_busted(self):
        src = _read(TEMPLATE)
        for asset in ('css/settings_hub.css', 'js/settings_hub.js'):
            m = re.search(r"\{% static '" + re.escape(asset) + r"' %\}\?v=(\d{8})", src)
            self.assertIsNotNone(m, asset)
            self.assertGreaterEqual(int(m.group(1)), 20261119, asset)

    def test_the_brand_preview_writes_text_not_markup(self):
        js = _read(SCRIPT)
        self.assertNotRegex(js, r'innerHTML|insertAdjacentHTML|outerHTML')
        self.assertIn('out.textContent = input.value.trim() || fallback', js)
        src = _read(TEMPLATE)
        for target in re.findall(r'data-brand-preview="([^"]+)"', src):
            self.assertIn(f'id="{target}"', src)

    def test_an_empty_search_is_announced(self):
        self.assertIn('id="settingsSearchEmpty" role="status"', _read(TEMPLATE))
        self.assertIn("searchNote.textContent = shown ? ''", _read(SCRIPT))


class SettingsHubPageGuards(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.boss = get_user_model().objects.create_superuser('idh_boss', 'idh@x.co', 'pw-idh-boss-11')

    def page(self, query=''):
        self.client.force_login(self.boss)
        response = self.client.get(reverse('settings_hub') + query)
        self.assertEqual(response.status_code, 200)
        return response.content.decode('utf-8')

    def test_the_hub_is_a_migrated_page(self):
        self.assertIn('<html lang="ar" dir="rtl" data-lx-page="v2">', self.page())

    def test_every_tab_names_its_panel_and_back(self):
        html = self.page()
        tabs = re.findall(r'<button class="settings-tab"[^>]*>', html)
        self.assertEqual(len(tabs), 6)
        ids = set(re.findall(r'\sid="([^"]+)"', html))
        panels = {re.search(r'\sid="([^"]+)"', tag).group(1): tag
                  for tag in re.findall(r'<div [^>]*role="tabpanel"[^>]*>', html)}
        for tab in tabs:
            controls = re.search(r'aria-controls="([^"]+)"', tab)
            self.assertIsNotNone(controls, tab)
            self.assertIn(controls.group(1), panels, tab)
        for pid, tag in panels.items():
            labelled = re.search(r'aria-labelledby="([^"]+)"', tag)
            self.assertIsNotNone(labelled, pid)
            self.assertIn(labelled.group(1), ids, pid)

    def test_the_server_opens_the_asked_pane(self):
        html = self.page('?tab=notifications')
        self.assertRegex(html, r'id="settingsTab-notifications"[^>]*aria-selected="true" tabindex="0"')
        self.assertIn('class="settings-pane is-active" data-pane="notifications"', html)
        self.assertNotIn('class="settings-pane is-active" data-pane="general"', html)
        self.assertIn('class="settings-pane is-active" data-pane="general"', self.page())
        unknown = self.page('?tab=scan')   # مجهولٌ: السكربتُ يختار «عام» كما كان
        strip = unknown[unknown.index('id="settingsTabstrip"'):unknown.index('id="settingsSearchEmpty"')]
        self.assertNotIn('aria-selected="true"', strip)
        self.assertNotIn('settings-pane is-active', unknown)

    def test_helper_texts_are_tied_to_their_fields(self):
        html = self.page()
        for field in ('ov_enabled', 'ov_email', 'sec_min_len', 'ai_key'):
            tag = re.search(r'<input\b[^>]*\bid="%s"[^>]*>' % field, html)
            described = re.search(r'aria-describedby="([^"]+)"', tag.group(0))
            self.assertIsNotNone(described, field)
            for ref in described.group(1).split():
                self.assertIn(f'id="{ref}"', html, f'{field} → {ref}')

    def test_the_last_notice_date_is_direction_isolated(self):
        from core.models import Book, BookHistory
        book = Book.objects.create(kind='incoming_external', our_number='7802', title='متأخّر', created_by=self.boss)
        BookHistory.objects.create(book=book, action='overdue', by=None, notes='x')
        self.assertRegex(self.page('?tab=notifications'),
                         r'آخرُ إشعار تأخّرٍ أُرسل: <bdi dir="ltr" class="num">\d{2}/\d{2}/\d{4} \d{2}:\d{2}</bdi>')

    def test_the_threshold_shows_its_saved_value(self):
        from core.models import AIIntegrationSettings
        AIIntegrationSettings.objects.create(low_confidence_threshold=0.4)
        tag = re.search(r'<input\b[^>]*\bid="ai_threshold"[^>]*>', self.page('?tab=ai')).group(0)
        self.assertIn('value="0.4"', tag)
