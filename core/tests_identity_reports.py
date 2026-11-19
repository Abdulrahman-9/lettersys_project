"""حرّاسُ صفحة التقارير على الهويّة الموحّدة (2026‑11‑19، دفعةُ الصفحات الباقية).

١. **الصفحةُ منقولة**: تعلن v2 فتأخذ الرموزَ والوضعين، وورقتُها مرفوعةُ النسخة.
٢. **الشاشةُ رموزٌ وحدها**: لا لونَ صريحاً في reports.css خارج كتلة الطباعة؛ أسماءُ الصفحة (‎--rx-*‎) تُربط
   بـ‎--lx-*‎ مرّةً واحدة، ولا كتلةَ داكنٍ على سمة الوضع القديم المحذوف؛ والتعبئةُ بحبرها.
٣. **الورقُ حبرٌ على أبيض**: كتلةُ الطباعة تعيد ربطَ الأسماء نفسِها بحبرٍ صريح (فلا يُطبع نصٌّ فاتحٌ من الوضع
   الداكن)، والاستجاباتُ مقصورةٌ على الشاشة فلا تقلب ورقةُ A4 الجدولَ بطاقات.
٤. **لا لونَ وحده**: رقاقةُ المتابعة وبلاطةُ الحالة بأيقونةٍ ونصّ، وقِطَعُ شرائط القسم بنقوشٍ يحملها المفتاحُ
   نفسُه (كان المفتاحُ نقاطاً بلونٍ مضمَّنٍ في القالب)؛ والأرقامُ معزولةُ الاتّجاه.
٥. **أعطابٌ أُصلحت**: شريطُ تمرير قائمة الجهات يعود إلى الهويّة (scrollbar-width كان يُسقطه)، والخيارُ النشط
   يُعلَن لقارئ الشاشة، والصفرُ هادئ، والتصفيةُ المطبَّقة موسومة، والقائمةُ الفارغة تعرض مخرجاً حقيقيّاً.
"""
import re

from django.test import SimpleTestCase

import core.tests_reports_design as design
from core.tests_list_identity import DECL, _read, _strip

CSS = 'static/css/reports.css'
TEMPLATE = 'templates/core/reports.html'
COLOUR = re.compile(r'#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?)\(|\b(?:white|black)\b')


def _block(text, opener):
    """جسمُ الكتلة التي تبدأ بـ ``opener`` (حتّى قوسها المقابل)."""
    start = text.index(opener) + len(opener)
    depth = 1
    for i in range(start, len(text)):
        depth += {'{': 1, '}': -1}.get(text[i], 0)
        if depth == 0:
            return text[start:i]
    raise AssertionError('unclosed block: ' + opener)


def _screen(css):
    """الورقةُ بلا كتلة الطباعة — ما يُرسم على الشاشة."""
    css = _strip(css)
    printed = '@media print {' + _block(css, '@media print {') + '}'
    return css.replace(printed, '')


def _rule(css, selector):
    """تصريحاتُ أوّلِ قاعدةٍ محدِّدُها ``selector`` بالضبط."""
    css = _strip(css)
    m = re.search(r'(?:^|[}\s])' + re.escape(selector) + r'\s*\{([^}]*)\}', css)
    assert m, selector
    return m.group(1)


class ReportsStylesheetTests(SimpleTestCase):

    def test_the_screen_speaks_tokens_only(self):
        values = [m.group(2) for m in DECL.finditer(_screen(_read(CSS)))]
        self.assertGreater(len(values), 300)
        self.assertEqual([v.strip() for v in values if COLOUR.search(v)], [])

    def test_the_page_names_read_the_identity_once(self):
        aliases = dict(re.findall(r'(--rx-[\w-]+):\s*([^;]+);', _rule(_read(CSS), '.rx')))
        self.assertGreaterEqual(len(aliases), 25)
        for name, value in aliases.items():
            if name == '--rx-r-ctl':        # نصفُ قطرٍ لا لون
                continue
            with self.subTest(alias=name):
                self.assertIn('var(--lx-', value)
        # والأسماءُ تُعرَّف في كتلةٍ واحدةٍ للشاشة (لا كتلةَ لكلّ وضع)
        self.assertEqual(len(re.findall(r'--rx-ink:', _screen(_read(CSS)))), 1)

    def test_no_dead_dark_mode_block(self):
        for rel in (CSS, TEMPLATE):
            with self.subTest(rel=rel):
                self.assertNotIn('[data-theme', _read(rel))

    def test_the_fill_wears_its_ink(self):
        aliases = _rule(_read(CSS), '.rx')
        self.assertIn('--rx-fill: var(--lx-pri-fill);', aliases)
        self.assertIn('--rx-fill-ink: var(--lx-pri-fill-ink);', aliases)
        primary = _rule(_read(CSS), '.rx-btn--primary, .rx-btn--primary:hover')
        self.assertIn('background: var(--rx-fill);', primary)
        self.assertIn('color: var(--rx-fill-ink);', primary)

    def test_paper_rebinds_the_names_to_ink_on_white(self):
        printed = _block(_strip(_read(CSS)), '@media print {')
        rebinding = _block(printed, '.rx {')
        for decl in ('--rx-surface: #fff;', '--rx-ink: #000;', '--rx-mute: #444;', '--rx-pri: #000;', '--rx-fill-ink: #fff;'):
            with self.subTest(decl=decl):
                self.assertIn(decl, rebinding)
        self.assertIn('border-bottom: 3px double var(--rx-ink);', printed)
        # ولا يخرج من الطابعة إلّا الوثيقة
        self.assertRegex(printed, r'\.app-topbar, \.app-sidebar, \.skip-link, \.toast-container, \.dvs-banner')

    def test_responsive_rules_stay_off_paper(self):
        queries = re.findall(r'@media ([^{]+)\{', _strip(_read(CSS)))
        sized = [q.strip() for q in queries if 'width' in q]
        self.assertEqual(len(sized), 3)
        for query in sized:
            with self.subTest(query=query):
                self.assertTrue(query.startswith('screen and '), query)

    def test_bar_segments_are_patterned_not_coloured_alone(self):
        css = _read(CSS)
        overdue = _rule(css, '.rx .s-overdue')
        today = _rule(css, '.rx .s-due_today')
        pending = _rule(css, '.rx .s-pending')
        self.assertNotIn('gradient', overdue)
        for name, body, angle in (('due_today', today, '-45deg'), ('pending', pending, '90deg')):
            with self.subTest(segment=name):
                self.assertIn('repeating-linear-gradient(' + angle, body)
        # المفتاحُ يلبس نقوشَ القِطَع نفسَها — أصنافٌ لا ألوانٌ مضمَّنة
        legend = re.search(r'<div class="rx-legend">(.*?)</div>', _read(TEMPLATE), re.S).group(1)
        for key in ('overdue', 'due_today', 'pending'):
            with self.subTest(key=key):
                self.assertIn(f'<i class="rx-key s-{key}" aria-hidden="true"></i>', legend)

    def test_the_combo_list_keeps_the_identity_scrollbar(self):
        self.assertNotIn('scrollbar-width', _strip(_read(CSS)))


class ReportsTemplateTests(SimpleTestCase):

    def test_the_page_opts_into_v2_and_busts_its_cache(self):
        src = _read(TEMPLATE)
        self.assertIn('{% block html_attrs %} data-lx-page="v2"{% endblock %}', src)
        self.assertIn("{% static 'css/reports.css' %}?v=20261119-pages", src)

    def test_no_native_dialogs(self):
        self.assertNotRegex(_read(TEMPLATE), r'(?<![\w.])(?:window\.)?(?:confirm|alert|prompt)\s*\(')

    def test_no_inline_colour(self):
        """الأنماطُ المضمَّنة مقاساتٌ من البيانات وحدَها — اللونُ في الورقة."""
        styles = re.findall(r'style="([^"]*)"', _read(TEMPLATE))
        self.assertEqual(len(styles), 5)
        for style in styles:
            with self.subTest(style=style):
                self.assertRegex(style, r'^(?:width|flex-grow):\{\{ [\w.]+ \}\}%?$')

    def test_the_active_option_is_announced(self):
        src = _read(TEMPLATE)
        self.assertIn('id="entityOpt{{ e.id }}"', src)
        self.assertIn("search.setAttribute('aria-activedescendant', vis[activeIdx].id);", src)
        self.assertIn("search.removeAttribute('aria-activedescendant');", src)


class ReportsRenderTests(design.ReportsDesignTestCase):
    """البياناتُ من حرّاس التصميم: متأخّراتٌ بأعمار، وقيدُ متابعة، ومُنجَز، وسرّيٌّ في الشعبة."""

    def _html(self, user=None, **params):
        return self._get(user or self.admin, **params).content.decode('utf-8')

    def test_the_page_is_migrated(self):
        self.assertIn('data-lx-page="v2"', self._html())

    def test_every_followup_mark_carries_its_icon_and_words(self):
        tbody = design._tbody(self._html())
        for state, icon in (('overdue', 'bi-alarm'), ('pending', 'bi-hourglass-split'),
                            ('archived', 'bi-check2-circle')):
            with self.subTest(state=state):
                self.assertRegex(tbody, r'class="rx-chip rx-chip--%s" title="[^"]+"><i class="bi %s" aria-hidden="true"></i>[^<]+</span>'
                                 % (state, icon))

    def test_numbers_are_isolated(self):
        tbody = design._tbody(self._html())
        self.assertIn('<b><bdi dir="ltr">%s</bdi></b>' % self.o10.our_number_display, tbody)
        self.assertRegex(tbody, r'<td class="rx-date" data-label="تاريخ القيد"><bdi dir="ltr">\d\d/\d\d/\d{4}</bdi></td>')

    def test_a_zero_tile_is_quiet_and_a_live_one_is_not(self):
        html = self._html()
        self.assertRegex(html, r'rx-state--due_today"[^>]*data-zero>')
        self.assertNotRegex(html, r'rx-state--overdue"[^>]*data-zero>')

    def test_an_applied_filter_is_marked(self):
        form = lambda html: re.search(r'<form class="rx-filters"(.*?)</form>', html, re.S).group(1)  # noqa: E731
        self.assertNotIn('data-set', form(self._html()))
        self.assertIn('<label class="rx-field" data-set><small>النوع</small>', form(self._html(kind='incoming')))

    def test_an_empty_report_offers_a_real_way_out(self):
        """«مسح التصفية» يعود إلى «متابعة جارية» نفسِها — فالمخرجُ الأوّل «كل الحالات»."""
        tbody = design._tbody(self._html(bucket='due_today'))
        self.assertIn('rx-empty-row', tbody)
        self.assertRegex(tbody, r'<a class="rx-link" href="\?[^"]*bucket=all[^"]*">اعرض كل الحالات</a>')
