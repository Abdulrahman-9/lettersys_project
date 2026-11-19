"""حرّاسُ «تجهيز هذا الجهاز» على الهويّة الموحّدة (2026-11-19).

١. الصفحةُ منقولة (data-lx-page="v2") وأصولُها الثلاثة بختم الدفعة ‎?v=20261119-pages‎.
٢. مسارٌ واحدٌ من أربع خطوات: لكلّ خطوةٍ عقدةٌ مرقّمة و«الخطوة n» في عنوانها؛ ومسارُ رجوعٍ أعلى الصفحة.
٣. سطورُ الحالة حيّةٌ لقارئ الشاشة (role=status + aria-live) وتحمل data-tone؛ والسكربتان يكتبان الحالةَ في
   data-tone لا في أصناف اللون، ولكلّ حالةٍ في الورقة أيقونةٌ بشكلٍ مختلف — لا لونٌ وحده.
٤. كلُّ دليلٍ يكشفه السكربت يبدأ بعنوانٍ قابلٍ للتركيز من مستوى يجده محدِّدُ السكربت، والعناوينُ لا تقفز مستوى.
٥. الورقةُ رموزٌ فقط (لا hex ولا rgb/hsl ولا أسماءَ ألوان ولا سمةَ الوضع القديم)، والحركةُ كلُّها لمن لم يطلب تقليلها.
٦. لا بطاقةَ Bootstrap (‎.card‎ يرفعها app.css عند المرور فتقفز الصفحةُ كلّها)، ولا style مضمَّن، ولا حوارات المتصفّح.
٧. «ثانويّ» Bootstrap على حبر الهويّة الخافت — كان رماديُّه 4.27:1 على الأرضيّة (مقيسٌ قبل النقل).
٨. السكربتان يطلبان ما كانا يطلبانه — نقلُ الشكل لم يمسّ الفحوصَ الحيّة.
"""
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

ROOT = Path(settings.BASE_DIR)
TEMPLATE = 'templates/core/device_setup.html'
CSS = 'static/css/device_setup.css'
SCRIPTS = ('static/js/device_setup.js', 'static/js/workstation_setup.js')
STAMP = '?v=20261119-pages'
TONES = ('secondary', 'info', 'success', 'warning', 'danger')
STATUSES = ('setupConnection', 'deviceCheckResult', 'workstationPairResult')
PANELS = ('trustSetupHelp', 'scannerSetupHelp', 'deviceSetupHelp', 'deviceEnrollment')


def _read(rel):
    return (ROOT / rel).read_text(encoding='utf-8')


def _css():
    return re.sub(r'/\*.*?\*/', '', _read(CSS), flags=re.S)


def _tag(html, element_id):
    """الوسمُ الافتتاحيّ للعنصر صاحب المعرّف."""
    match = re.search(r'<[a-z0-9]+\b[^>]*\bid="%s"[^>]*>' % element_id, html)
    assert match, element_id
    return match.group(0)


def _media_blocks(css, query):
    """كتلُ ‎@media‎ المطلوبة كاملةً بأقواسها المتوازنة."""
    blocks = []
    for start in [m.start() for m in re.finditer(re.escape(query), css)]:
        depth = 0
        for end in range(css.index('{', start), len(css)):
            depth += {'{': 1, '}': -1}.get(css[end], 0)
            if depth == 0:
                blocks.append(css[start:end + 1])
                break
    return blocks


class DeviceSetupPageTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username='ds-identity')

    def _html(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('device_setup'))
        self.assertEqual(response.status_code, 200)
        return response.content.decode('utf-8')

    def test_the_page_is_migrated(self):
        self.assertIn('<html lang="ar" dir="rtl" data-lx-page="v2">', self._html())

    def test_own_assets_carry_the_batch_stamp(self):
        html = self._html()
        for asset in ('css/device_setup.css', 'js/device_setup.js', 'js/workstation_setup.js'):
            self.assertIn(asset + STAMP, html, asset)

    def test_one_path_of_four_numbered_steps(self):
        steps = self._html().split('<li class="ds-step"')[1:]
        self.assertEqual(len(steps), 4)
        for number, step in enumerate(steps, 1):
            self.assertIn('<span class="ds-node" aria-hidden="true"><b>%d</b></span>' % number, step)
            self.assertIn('<h3 class="ds-step-title"><span class="ds-eyebrow">الخطوة %d</span>' % number, step)

    def test_the_way_back_is_at_the_top(self):
        html = self._html()
        head = html[html.index('class="ds-head"'):html.index('class="ds-layout"')]
        self.assertIn('href="%s"' % reverse('network_settings'), head)
        self.assertIn('aria-current="page"', head)
        self.assertIn('href="%s"' % reverse('dashboard'), html)

    def test_status_lines_are_live_and_carry_a_tone(self):
        html = self._html()
        for status_id in STATUSES:
            tag = _tag(html, status_id)
            for attribute in ('class="ds-status"', 'role="status"', 'aria-live="polite"'):
                self.assertIn(attribute, tag, status_id)
            self.assertRegex(tag, r'data-tone="(%s)"' % '|'.join(TONES))
        self.assertIn('role="status"', _tag(html, 'setupInstallResult'))

    def test_every_revealed_panel_opens_on_a_heading_the_script_focuses(self):
        html = self._html()
        selector = re.search(r"panel\.querySelector\('([^']+)'\)\?\.focus\(\)", _read(SCRIPTS[0])).group(1)
        levels = {part.strip() for part in selector.split(',')}
        for panel in PANELS:
            tag = _tag(html, panel)
            heading = re.match(r'\s*<(h[1-6])\b[^>]*\btabindex="-1"', html[html.index(tag) + len(tag):])
            self.assertTrue(heading, panel)
            self.assertIn(heading.group(1), levels, panel)

    def test_headings_descend_one_level_at_a_time(self):
        html = self._html()
        start = html.index('id="deviceSetup"')
        levels = [int(level) for level in re.findall(r'<h([1-6])\b', html[start:html.index('</aside>', start)])]
        self.assertEqual(levels[0], 1)
        for previous, current in zip(levels, levels[1:]):
            self.assertLessEqual(current, previous + 1, levels)

    def test_addresses_and_file_names_are_isolated(self):
        html = self._html()
        server = html[html.index('class="ds-dl"'):html.index('</dl>')]
        self.assertEqual(server.count('<bdi dir="ltr" class="ds-mono">'), 2)
        self.assertIn('<bdi dir="ltr" class="ds-mono">Setup.vbs</bdi>', html)


class DeviceSetupStylesheetTests(SimpleTestCase):

    def test_tokens_only(self):
        css = _css()
        declarations = ' '.join(re.findall(r'\{([^{}]*)\}', css))
        self.assertEqual(re.findall(r'#[0-9a-fA-F]{3,8}\b', declarations), [])
        self.assertEqual(re.findall(r'\b(?:rgba?|hsla?)\(', declarations), [])
        self.assertEqual(re.findall(r':\s*(?:white|black|red|green|blue|orange|yellow|gr[ae]y)\b', declarations), [])
        self.assertNotIn('data-theme', css)

    def test_every_tone_draws_its_own_glyph(self):
        css = _css()
        glyphs = {}
        for tone in TONES:
            rule = re.search(r'\.ds-status\[data-tone="%s"\]::before[^{]*\{([^}]*)\}' % tone, css)
            self.assertTrue(rule, tone)
            glyph = re.search(r'content:\s*"(\\f[0-9a-f]{3})"', rule.group(1))
            self.assertTrue(glyph, tone)
            glyphs[tone] = glyph.group(1)
        self.assertEqual(len(set(glyphs.values())), len(TONES), glyphs)
        for tone in ('success', 'warning', 'danger'):
            self.assertRegex(css, r'\.ds-step:has\(\.ds-status\[data-tone="%s"\]\) \.ds-node::after \{ content: "\\f' % tone)

    def test_the_secondary_button_reads_on_the_cream(self):
        block = re.search(r'\.ds \.btn-outline-secondary\s*\{([^}]*)\}', _css()).group(1)
        self.assertIn('--bs-btn-color: var(--lx-mute)', block)

    def test_motion_only_for_who_did_not_ask_to_reduce_it(self):
        css = _css()
        motion = _media_blocks(css, '@media (prefers-reduced-motion: no-preference)')
        self.assertTrue(motion)
        rest = css
        for block in motion:
            rest = rest.replace(block, '')
        self.assertNotRegex(rest, r'\b(?:animation|transition)\s*:')


class DeviceSetupTemplateTests(SimpleTestCase):

    def test_no_bootstrap_card_under_the_flow(self):
        self.assertNotRegex(_read(TEMPLATE), r'class="[^"]*(?<![\w-])card(?![\w-])')

    def test_no_inline_style(self):
        self.assertNotIn('style=', _read(TEMPLATE))


class DeviceSetupScriptTests(SimpleTestCase):

    def test_no_native_dialogs(self):
        for rel in SCRIPTS:
            self.assertNotRegex(_read(rel), r'(?<![\w.$])(?:window\.)?(?:alert|confirm|prompt)\s*\(', rel)

    def test_status_is_a_tone_not_a_colour_class(self):
        for rel in SCRIPTS:
            body = re.search(r'function status\([^)]*\)\s*\{(.*?)\n  \}', _read(rel), re.S).group(1)
            self.assertIn('.dataset.tone = tone', body, rel)
            self.assertNotIn('className', body, rel)

    def test_the_checks_still_ask_what_they_asked(self):
        setup, pairing = (_read(rel) for rel in SCRIPTS)
        for needle in ('root.dataset.healthUrl', '/agent/health', '/agent/devices', "'lettersys:agent-detected'",
                       "['127.0.0.1', 'localhost']"):
            self.assertIn(needle, setup)
        for needle in ('/agent/workstation`', '/agent/workstation/pair', 'root.dataset.enrollUrl',
                       'root.dataset.mineUrl', "'X-CSRFToken'"):
            self.assertIn(needle, pairing)
