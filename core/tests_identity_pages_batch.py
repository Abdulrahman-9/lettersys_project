"""دفعةُ الصفحات على الهويّة (2026-11-19) — الإصلاحاتُ المشتركة تُحرَس مرّةً هنا لا في كلّ وحدة.

ستَّ عشرةَ وحدةً قاست العيوبَ نفسَها في الملفّات المشتركة والتفّت عليها محلّيّاً؛ التكاملُ أصلحها في مصدرها
وحذف النسخ. هذه الحرّاسُ تثبّت المصدرَ الواحد، وحرّاسُ الوحدات (tests_identity_<unit>) تثبّت أنّ النسخ لا تعود.
"""
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core.models import UserProfile

ROOT = Path(settings.BASE_DIR)
COMMENT = re.compile(r'/\*.*?\*/', re.S)
UNIT_SHEETS = sorted(
    p for p in list((ROOT / 'static' / 'css').glob('*.css')) + [ROOT / 'static' / 'extraction_smart.css']
    if p.name not in ('theme.css', 'components.css'))


def _css(rel):
    return COMMENT.sub(' ', (ROOT / rel).read_text(encoding='utf-8'))


def _rule(css, selector):
    """جسمُ القاعدة التي محدِّدُها ``selector`` تماماً (الأولى)."""
    m = re.search(r'(?:^|\})\s*' + re.escape(selector) + r'\s*\{([^}]*)\}', css)
    return m.group(1) if m else None


class SharedButtonTests(SimpleTestCase):

    def test_every_button_shows_keyboard_focus(self):
        """Bootstrap يصفّر outline وحلقتُه ظلٌّ يطمسه ظلُّ «الورق» ⟵ إطارٌ بلون الفعل لكلّ ‎.btn‎."""
        body = _rule(_css('static/css/theme.css'), 'html:not([data-lx-legacy]) .btn:focus-visible')
        self.assertIsNotNone(body, 'قاعدةُ تركيز الأزرار غابت عن theme.css')
        self.assertIn('outline: 2px solid var(--lx-pri);', body)
        self.assertIn('outline-offset: 2px;', body)

    def test_the_secondary_outline_reads_in_both_themes(self):
        """رماديُّ Bootstrap ‎#6c757d‎ يقيس 4.27:1 على أرضيّة الفاتح («إغلاق الدليل») و3.6:1 على الداكن."""
        css = _css('static/css/components.css')
        body = _rule(css, 'html:not([data-lx-legacy]) .btn-outline-secondary')
        self.assertIsNotNone(body, 'القاعدةُ عادت مقصورةً على وضعٍ واحد')
        for decl in ('--bs-btn-color: var(--lx-mute);', '--bs-btn-hover-color: var(--lx-ink);',
                     '--bs-btn-disabled-color: var(--lx-mute);'):
            with self.subTest(decl=decl):
                self.assertIn(decl, body)
        self.assertNotRegex(css, r'\[data-bs-theme="dark"\]\s*\.btn-outline-secondary')

    def test_a_disabled_outline_primary_is_not_bootstrap_blue(self):
        body = _rule(_css('static/css/theme.css'), 'html:not([data-lx-legacy]) .btn-outline-primary')
        self.assertIn('--bs-btn-disabled-color: var(--lx-pri);', body)
        self.assertIn('--bs-btn-disabled-border-color: var(--lx-pri);', body)

    def test_buttons_name_their_transitions(self):
        """‏transition: all‏ كان يحرّك حلقةَ التركيز نفسَها فتبدأ باهتة."""
        body = _rule(_css('static/app.css'), '.btn,\n.form-control')
        self.assertIsNotNone(body)
        self.assertNotIn('all', body)
        self.assertIn('transition-property: color, background-color, border-color, box-shadow, transform;', body)

    def test_no_unit_sheet_keeps_its_own_copy(self):
        for path in UNIT_SHEETS:
            with self.subTest(sheet=path.name):
                css = COMMENT.sub(' ', path.read_text(encoding='utf-8'))
                self.assertNotRegex(css, r'\.btn-outline-secondary\s*\{[^}]*--bs-btn-color', 'نسخةُ «ثانويّ» محلّيّة')
                self.assertNotRegex(css, r'--[\w]+-field-line\s*:', 'رمزُ حدّ حقلٍ محلّيّ — الرمزُ ‎--lx-field-line‎')


class SharedFieldLineTests(SimpleTestCase):

    def test_the_field_line_token_lives_in_both_themes(self):
        """‎--lx-line-strong‎ يقيس 1.36:1 على السطح؛ حدُّ عنصر التحكّم يلزمه 3:1 (WCAG 1.4.11)."""
        css = _css('static/css/theme.css')
        self.assertEqual(
            css.count('--lx-field-line: color-mix(in srgb, var(--lx-mute) 75%, var(--lx-surface));'), 2)

    def test_fields_and_checkboxes_wear_it(self):
        css = _css('static/css/theme.css')
        self.assertIn('--bs-border-color: var(--lx-field-line);',
                      _rule(css, 'html:not([data-lx-legacy]) :is(.form-control, .form-select)') or '')
        self.assertIn('border-color: var(--lx-field-line);',
                      _rule(css, 'html:not([data-lx-legacy]) .form-check-input') or '')

    def test_the_mix_measures_three_to_one_in_both_themes(self):
        """يُحسب من قيم الرموز نفسِها: لو تغيّر الحبرُ الخافت أو السطح فسقط الحدّ عن 3:1 احمرّ هذا."""
        css = _css('static/css/theme.css')
        light, dark = css.split('[data-bs-theme="dark"] {', 1)

        def token(block, name):
            return re.search(r'--lx-' + name + r':\s*(#[0-9a-fA-F]{6})', block).group(1)

        def rgb(h):
            return [int(h[i:i + 2], 16) for i in (1, 3, 5)]

        def lum(c):
            lin = [(v / 255 / 12.92) if v / 255 <= .03928 else ((v / 255 + .055) / 1.055) ** 2.4 for v in c]
            return .2126 * lin[0] + .7152 * lin[1] + .0722 * lin[2]

        for name, block in (('light', light), ('dark', dark)):
            with self.subTest(theme=name):
                mute, surface = rgb(token(block, 'mute')), rgb(token(block, 'surface'))
                line = [.75 * m + .25 * s for m, s in zip(mute, surface)]
                hi, lo = sorted((lum(line), lum(surface)), reverse=True)
                self.assertGreaterEqual((hi + .05) / (lo + .05), 3.0)


class SharedTabSheetTests(SimpleTestCase):
    SHEET = 'static/css/book_unified_tabs.css'

    def test_the_active_count_is_full_white(self):
        """‎.82‎ من الأبيض كان 4.24:1 عند طرف ‎--lx-hero-a‎ من اللوح."""
        css = _css(self.SHEET)
        self.assertIn('color: #fff;', _rule(css, '.tab-main.active,\n.tab-main.active .tab-count') or '')
        self.assertNotRegex(css, r'\.tab-count\s*\{\s*color:\s*rgba')

    def test_the_focus_ring_reads_on_the_surface_and_on_the_board(self):
        css = _css(self.SHEET)
        self.assertIn('outline: 2px solid var(--lx-pri);', _rule(css, '.tab-main:focus-visible') or '')
        self.assertIn('outline-color: #fff;', _rule(css, '.tab-main.active:focus-visible') or '')

    def test_the_search_field_pads_logically(self):
        body = _rule(_css(self.SHEET), '.fb-search input')
        self.assertIn('padding-inline: 0.7rem 2rem;', body)
        self.assertNotRegex(body, r'padding:\s')

    def test_link_tabs_and_link_pills_are_not_underlined(self):
        css = _css(self.SHEET)
        for selector in ('.tab-main', '.fb-pill'):
            with self.subTest(selector=selector):
                self.assertIn('text-decoration: none;', _rule(css, selector) or '')

    def test_every_page_variable_has_a_fallback(self):
        """‎--border‎ و‎--theme-*‎ تعرّفها صفحةُ الكتب وحدها؛ الصفحاتُ الأخرى كانت تفقد حدَّ اللوح."""
        self.assertEqual(re.findall(r'var\(--(?:border|theme-[a-z]+)\)', _css(self.SHEET)), [])


class SharedShellTests(TestCase):

    def test_the_sticky_last_cell_follows_the_surface(self):
        body = _rule(_css('static/app.css'), '.table td:last-child')
        self.assertIn('background: var(--lx-surface, #fff);', body)

    def test_the_restore_page_lights_its_nav_item(self):
        nav = (ROOT / 'templates/core/partials/system_admin_nav.html').read_text(encoding='utf-8')
        self.assertIn("{% if u == 'backup_database' or u == 'data_restore' %}on{% endif %}", nav)

    def test_a_must_change_user_still_gets_the_offline_page(self):
        """عاملُ الخدمة يجلب ‎/offline.html‎ عند التثبيت: لو حُوِّل لخُزِّنت صفحةُ كلمة المرور (باسم صاحبها) مكانَها."""
        user = get_user_model().objects.create_user('must-change', password='x-12345678')
        UserProfile.objects.update_or_create(user=user, defaults={'must_change_password': True})
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('dashboard')).status_code, 302)
        self.assertEqual(self.client.get(reverse('offline')).status_code, 200)


class DialogAndToastTests(SimpleTestCase):
    """إضافةُ المالك (11-19): الحواريّاتُ والتوستُ والصياغةُ واحدةٌ في كلّ الصفحات."""

    TEMPLATES = sorted((ROOT / 'templates').rglob('*.html'))
    # خارج الدفعة: اللوحةُ القديمة تتقاعد مع الدفعة 3-2، وصفحاتُ البريد مؤجَّلةٌ بقرار المالك (11-18)
    NOT_IN_BATCH = ('core/admin_panel.html', 'core/mail/')

    def _in_batch(self, path):
        rel = path.relative_to(ROOT / 'templates').as_posix()
        return not rel.startswith(self.NOT_IN_BATCH)

    def test_every_declarative_confirm_names_itself_and_its_button(self):
        """العنوانُ يقول ما الفعل، والنصُّ عاقبتُه، والزرُّ فعلُه — لا «تأكيد العملية / تأكيد» الافتراضيّان."""
        seen = 0
        for path in filter(self._in_batch, self.TEMPLATES):
            src = path.read_text(encoding='utf-8')
            for m in re.finditer(r'<(?:form|button|a)\b[^>]*?data-confirm="[^"]*"[^>]*>', src, re.S):
                seen += 1
                with self.subTest(template=path.name, line=src.count('\n', 0, m.start()) + 1):
                    self.assertIn('data-confirm-title="', m.group(0))
                    self.assertIn('data-confirm-ok="', m.group(0))
                    self.assertNotRegex(m.group(0), r'data-confirm-ok="(?:تأكيد|نعم|موافق|إلغاء)[ "]')
        self.assertGreaterEqual(seen, 15)

    def test_the_apps_dialog_starts_on_cancel_when_it_destroys(self):
        app = (ROOT / 'static/app.js').read_text(encoding='utf-8')
        self.assertIn("(opts.danger === false ? ok : modal.querySelector('.btn-cancel')).focus();", app)
        self.assertIn("modal.querySelector('.modal-body').textContent = opts.message || '';", app)

    def test_cancel_comes_first_in_every_dialog_footer(self):
        """ترتيبٌ واحد: «إلغاء» ثمّ الفعل — كحواريّة التطبيق (نموذجا الأجهزة كانا معكوسَين)."""
        seen = 0
        for path in filter(self._in_batch, self.TEMPLATES):
            src = path.read_text(encoding='utf-8')
            for m in re.finditer(r'<div class="modal-footer[^"]*">(.*?)</div>', src, re.S):
                footer = m.group(1)
                cancel = re.search(r'<button[^>]*>\s*إلغاء\s*</button>', footer)
                action = re.search(r'<button[^>]*type="submit"', footer)
                if not (cancel and action):
                    continue
                seen += 1
                with self.subTest(template=path.name):
                    self.assertLess(cancel.start(), action.start())
        self.assertGreaterEqual(seen, 3)

    def test_a_server_message_interrupts_only_when_it_is_an_error(self):
        base = (ROOT / 'templates/base.html').read_text(encoding='utf-8')
        self.assertIn('''role="{% if 'error' in tag %}alert{% else %}status{% endif %}" '''
                      '''aria-live="{% if 'error' in tag %}assertive{% else %}polite{% endif %}"''', base)
        self.assertNotIn('role="alert" aria-live="assertive"', base)
        app = (ROOT / 'static/app.js').read_text(encoding='utf-8')
        self.assertIn("toastEl.setAttribute('aria-live', type === 'error' ? 'assertive' : 'polite');", app)

    def test_one_word_for_clearing_a_filter(self):
        for path in filter(self._in_batch, self.TEMPLATES):
            with self.subTest(template=path.name):
                self.assertNotRegex(path.read_text(encoding='utf-8'), r'مسح الفلاتر|تطابق الفلاتر')

    def test_a_danger_toast_is_an_error_toast(self):
        """صفحةُ الأجهزة تطلب ‎toast('danger', …)‎: كان الخطأ يظهر «معلومة» زرقاء بنبرةٍ مهذّبة وأربع ثوانٍ."""
        app = (ROOT / 'static/app.js').read_text(encoding='utf-8')
        self.assertIn("if (type === 'danger') type = 'error';", app)
        self.assertLess(app.index("if (type === 'danger') type = 'error';"), app.index('var meta = getToastMeta(type);'))
