"""حرّاسُ جولة الألوان الشاملة (قرارُ المالك 11-15، بطريقة فيبل): ألوانُ الهويّة الفاتحة لكلّ الصفحات بلا تغيير بنية.

مقيسٌ بجولةٍ آليّة على 35 صفحة قبل/بعد: طلاءُ اللوح الدافئ القديم 965 ⟵ 17 (والـ17 ورقةُ الطباعة عمداً)،
والنصوصُ دون التباين 283 ⟵ 73 (أكثرُها في صفحاتٍ لها خطوتُها: التقريرُ المطبوع واللوحةُ المستقلّة والإدخال).
١. متغيّراتُ اللوح القديم في app.css تشير إلى رموز الهويّة — الخلفيّاتُ والأحبارُ معاً.
٢. شريطُ تمريرٍ واحدٌ لكلّ الصفحات (theme.css)، ولا شريطَ قديماً في app.css.
٣. عائلاتُ الحالة في Bootstrap وأدواتُ نصّها على ألوان حالات الهويّة.
٤. تخصيصُ «المنقولة وحدها» لم يبقَ إلّا لزرّ الوضع (الداكنُ لها وحدها).
٥. لا برتقاليَّ يتسلّل عائداً إلى الملفّات التي شملتها الجولة (فحصٌ ساكنٌ بمنطق الجولة نفسِه).
"""
import colorsys
import re

from django.test import SimpleTestCase

from core.tests_list_identity import _read

SWEPT = ['static/app.css', 'static/css/system_admin.css', 'static/css/entity_list.css', 'static/css/entities_design.css',
         'static/css/dossiers.css', 'static/css/reports.css', 'static/css/document_manager.css', 'static/css/doc_canvas.css',
         'static/css/settings_hub.css', 'templates/core/mail/hub.html', 'templates/core/admin_panel.html',
         'templates/core/entity_merge.html']
OWN = {'b45309', 'd99a1e', 'c4320a', 'fef3c7', 'fffbeb', 'fcd34d', 'fde68a', 'ffc107', 'f2c14e', 'b54708', 'fedf89', 'fffaeb',
       'd97706', 'f59e0b', '92400e', '78350f'}
SEMANTIC = re.compile(r'warn|alert|(?<![a-z])late|overdue|danger|(?<![a-z])due|error|stale|expired|urgent', re.I)
COLOR = re.compile(r'#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b|rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})')


def legacy_orange(text):
    """الألوانُ الدافئةُ المشبعةُ الباقية خارج قواعد المعنى وخارج ألوان الهويّة نفسِها."""
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    text = re.sub(r':root\s*\{[^}]*\}', '', text)
    found = []
    for m in re.finditer(r'([^{}]+)\{([^{}]*)\}', text):
        if SEMANTIC.search(m.group(1)):
            continue
        for c in COLOR.finditer(m.group(2)):
            if c.group(1):
                h = c.group(1).lower()
                h = ''.join(x * 2 for x in h) if len(h) == 3 else h
            else:
                h = '%02x%02x%02x' % tuple(int(c.group(i)) for i in (2, 3, 4))
            if h in OWN:
                continue
            hue, light, sat = colorsys.rgb_to_hls(*(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)))
            if 12 / 360 <= hue <= 48 / 360 and sat > .30 and .12 < light < .97:
                found.append(f'{" ".join(m.group(1).split())[-40:]} → #{h}')
    return found


class HarmonizeTests(SimpleTestCase):

    def test_the_legacy_palette_points_at_the_identity(self):
        css = _read('static/app.css')
        root = css[css.index(':root {'):]
        root = root[:root.index('}')]
        for name, token in (('--accent', '--lx-pri'), ('--deep-brown', '--lx-ink'), ('--soft-brown', '--lx-mute'),
                            ('--warm-bg-top', '--lx-bg'), ('--warm-clay', '--lx-pri'), ('--card-border', '--lx-line')):
            with self.subTest(var=name):
                self.assertIn(f'{name}: var({token});', root)
        self.assertNotRegex(root, r'#[0-9a-fA-F]{3,6}\b')

    def test_one_scrollbar_for_every_page(self):
        self.assertNotIn('::-webkit-scrollbar', _read('static/app.css'))
        self.assertIn('html:not([data-lx-legacy])::-webkit-scrollbar', _read('static/css/theme.css'))

    def test_bootstrap_status_families_follow_the_tokens(self):
        css = _read('static/css/theme.css')
        for decl in ('--bs-warning-bg-subtle: var(--lx-wait-bg);', '--bs-danger-text-emphasis: var(--lx-late);',
                     '--bs-info-border-subtle: var(--lx-prog-line);', '--bs-code-color: var(--lx-pri-strong);',
                     'html:not([data-lx-legacy]) .text-warning { color: var(--lx-wait) !important; }',
                     'html:not([data-lx-legacy]) .btn-warning,'):
            with self.subTest(decl=decl):
                self.assertIn(decl, css)

    def test_only_the_mode_toggle_stays_on_migrated_pages(self):
        css = re.sub(r'/\*.*?\*/', '', _read('static/css/theme.css'), flags=re.S)
        scoped = [line.strip() for line in css.split('\n') if 'data-lx-page="v2"]' in line]
        self.assertEqual(scoped, ['html[data-lx-page="v2"] .lx-shell-toggle { display: inline-grid; }'])
        self.assertNotIn('data-lx-page="v2"]', re.sub(r'/\*.*?\*/', '', _read('static/css/components.css'), flags=re.S))

    def test_dark_mode_stays_on_migrated_pages(self):
        # الألوانُ الفاتحةُ صارت لكلّ الصفحات بلا بوّابة CSS؛ ما يمنع الداكنَ عن الصفحات القديمة هو هذا السطرُ وحدَه
        # في سكربت الرأس — فلا يُكتب data-bs-theme إلّا في المنقولة (مراجعةُ فيبل 11-15)
        base = _read('templates/base.html')
        guard = "if (root.getAttribute('data-lx-page') !== 'v2') return;"
        self.assertIn(guard, base)
        self.assertLess(base.index(guard), base.index("root.setAttribute('data-bs-theme', theme);"))

    def test_the_lifecycle_scope_joined_the_pass(self):
        css = re.sub(r'/\*.*?\*/', '', _read('static/css/lifecycle_design.css'), flags=re.S)
        self.assertNotIn('data-lx-page="v2"]', css)
        self.assertIn('html:not([data-lx-legacy]) .lc-scope {', css)

    def test_back_to_top_wears_the_identity_on_the_content_side(self):
        css = _read('static/app.css')
        rule = css[css.index('.back-to-top {'):]
        rule = rule[:rule.index('}')]
        self.assertIn('inset-inline-end: 24px;', rule)
        self.assertNotRegex(rule, r'(?<![-\w])right:')
        self.assertIn('var(--lx-hero-a)', rule)
        self.assertNotIn('transition: all', rule)

    def test_home_is_not_hijacked_inside_fields(self):
        js = _read('static/app.js')
        block = js[js.index('class BackToTopButton'):js.index('  scrollToTop() {')]
        self.assertIn("e.target.closest('input, textarea, select, [contenteditable], [role=\"textbox\"], [role=\"combobox\"]')", block)
        self.assertIn("setAttribute('aria-label', 'العودة إلى أعلى الصفحة')", block)

    def test_no_legacy_orange_creeps_back(self):
        for rel in SWEPT:
            with self.subTest(file=rel):
                self.assertEqual(legacy_orange(_read(rel)), [])
