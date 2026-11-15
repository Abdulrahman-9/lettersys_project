"""حرّاسُ القشرة (11-15، بطلب المالك: الشريطان بتقنيات لوحة التحكّم، وطيٌّ احترافيّ).

مقيسٌ قبل الإصلاح في متصفّحٍ حقيقيّ:
١. **الطيُّ يومض مع كلّ صفحة** — كان يُطبَّق في آخر الصفحة فيُرسم العمودُ 310px ثمّ ينطوي إلى 52.
٢. **بقايا تسمياتٍ في شريط مدير النظام المطويّ** (14 بقيّة) — لا قواعدَ طيٍّ لـ‎.sa-nav‎ أصلاً.
٣. **عمودُ مدير النظام ينزلق تحت الشريط العلويّ** 75px عند التمرير (top: 0).
٤. **بطاقةُ الحساب مقصوصةٌ** أسفل العمود عند ارتفاع 900px.
والتسمياتُ في المطويّ تبهت ولا تُحذف: اسمُ الرابط يبقى لقارئ الشاشة.
"""
import re

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core.tests_list_identity import _read


def block(css, head):
    """نصُّ القاعدة التي تبدأ بـhead حتّى قوسها."""
    i = css.index(head)
    return css[i:css.index('}', i)]


class ShellSourceTests(SimpleTestCase):

    def test_the_folded_state_is_set_before_the_column_paints(self):
        base = _read('templates/base.html')
        shell = base.index('<div class="app-shell">')
        script = base.index("localStorage.getItem('app_sidebar_mini') === '1'")
        self.assertLess(shell, script)
        self.assertLess(script, base.index('<aside class="app-sidebar'))

    def test_the_fold_key_needs_a_modifier_and_stays_out_of_typing(self):
        base = _read('templates/base.html')
        self.assertIn("if (!(e.ctrlKey || e.metaKey) || e.altKey || e.shiftKey || e.code !== 'KeyB' || e.repeat) return;", base)
        self.assertIn("closest('input, textarea, select, [contenteditable], [role=\"textbox\"], [role=\"combobox\"]')", base)
        self.assertIn("document.querySelector('.modal.show, dialog[open]')", base)

    def test_tooltips_wait_once_and_peers_follow_at_once(self):
        js = _read('static/js/shell.js')
        self.assertIn("if (tip.classList.contains('is-on')) { place(el); return; }", js)
        self.assertIn('now ? 0 : 380', js)

    def test_reduced_motion_folds_without_motion(self):
        theme = _read('static/css/theme.css')
        block = theme[theme.index('@media (prefers-reduced-motion: reduce) {\n  .lx-tabs-ind.is-ready'):]
        self.assertIn('.app-sidebar, .app-sidebar * { transition-duration: 0s !important;', block[:block.index('}\n}')])

    def test_moving_titles_never_drops_a_name(self):
        self.assertIn("el.setAttribute('aria-label', el.title)", _read('static/js/shell.js'))

    def test_the_admin_column_is_the_shared_card_and_follows_the_mode(self):
        # أمرُ المالك 11-15: «الداكنُ ستايل والفاتحُ ستايل» — كان داكناً في الوضعين ويلصق top:0 تحت الشريط
        css = _read('static/css/system_admin.css')
        self.assertNotIn('.is-system-admin .app-sidebar {', css)
        self.assertNotIn('.is-system-admin .app-shell {', css)
        self.assertNotIn('--sa-dark', css)
        app = _read('static/app.css')
        xl = app[app.index('@media (min-width: 1200px) {\n  .app-sidebar {'):]
        self.assertIn('top: calc(var(--lx-topbar-h) + 1rem);', block(xl, '  .app-sidebar {'))

    def test_the_card_has_its_own_surface_over_bootstraps_transparency(self):
        app = _read('static/app.css')
        xl = app[app.index('@media (min-width: 1200px) {\n  .app-sidebar {'):]
        self.assertIn('background: var(--lx-surface) !important;', block(xl, '  .app-sidebar {'))

    def test_the_admin_links_speak_tokens(self):
        css = _read('static/css/system_admin.css')
        nav = css[css.index('.sa-nav a {'):css.index('/* لوحةُ الإدارة المستقلّة')]
        self.assertNotIn('--sa-on-dark', nav)
        self.assertIn('color: var(--lx-ink)', nav)

    def test_the_standalone_panel_loads_the_tokens_first(self):
        src = _read('templates/core/admin_panel.html')
        self.assertLess(src.index("static 'css/theme.css'"), src.index("static 'css/system_admin.css'"))

    def test_the_admin_labels_fade_when_folded(self):
        css = _read('static/css/system_admin.css')
        self.assertIn('.app-shell.sidebar-mini .sa-nav a > span { opacity: 0;', css)
        self.assertIn('.app-shell.sidebar-mini .sa-nav-group { color: transparent;', css)

    def test_folded_labels_fade_and_keep_their_names(self):
        css = _read('static/app.css')
        rule = block(css, '  .app-shell.sidebar-mini .app-sidebar-link > span,')
        self.assertIn('opacity: 0', rule)
        self.assertNotIn('display: none', rule)

    def test_the_account_card_is_pinned_to_the_bottom(self):
        css = _read('static/app.css')
        xl = css[css.index('@media (min-width: 1200px) {\n  .app-sidebar {'):]
        rule = block(xl, '  .app-sidebar-panel-footer {')
        self.assertIn('position: sticky', rule)
        self.assertIn('bottom: 0', rule)

    def test_the_top_bar_is_the_command_surface(self):
        css = _read('static/app.css')
        bar = block(css, '.app-topbar {\n')
        self.assertIn('var(--lx-hero-b)', bar)
        self.assertIn('background-color: var(--lx-hero-a)', bar)
        self.assertIn('var(--lx-accent)', block(css, '.app-topbar::after {'))
        self.assertRegex(_read('static/css/theme.css'), r'--lx-rail-w: 72px;')

    def test_the_shell_script_is_loaded_and_builds_its_parts(self):
        self.assertRegex(_read('templates/base.html'), r"static 'js/shell\.js' %\}\?v=\d{8}")
        js = _read('static/js/shell.js')
        for part in ("glide.className = 'lx-glide'", "tip.className = 'lx-tip'", "bar.classList.toggle('is-scrolled'"):
            with self.subTest(part=part):
                self.assertIn(part, js)


class ShellMarkupTests(TestCase):

    def setUp(self):
        self.client.force_login(User.objects.create_user('shell-user', password='pw-shell-1115'))

    def test_the_fold_button_lives_in_the_top_bar(self):
        html = self.client.get(reverse('dashboard')).content.decode('utf-8')
        header = html[html.index('<header class="app-topbar">'):html.index('</header>')]
        button = re.search(r'<button\b[^>]*id="sidebarToggleBtn"[^>]*>', header)
        self.assertIsNotNone(button)
        self.assertIn('aria-keyshortcuts="Control+B"', button.group(0))

    def test_the_account_menu_escapes_the_folded_column(self):
        html = self.client.get(reverse('dashboard')).content.decode('utf-8')
        self.assertIn('class="app-sidebar-account" data-bs-toggle="dropdown" data-bs-popper-config=\'{"strategy":"fixed"}\'', html)
