"""حرّاسُ مساحة عمل البريد على الهويّة الموحّدة (11-12، المرحلة 1 من الخطّة المتكاملة).

١. **الطاولةُ والدفترُ والكشف داخل إطار البرنامج** (أمرُ المالك 11-12: الدفترُ والكشف كانا «في فضاءٍ
   فارغ») — صفحاتٌ منقولة تأخذ رموزَ الهويّة من ‎base.html‎، وورقتا أنماطها (desk.css · queues.css)
   بلا لونٍ صريح.
٢. **لا اسمَ حسابٍ على الورقة**: خانةُ اسم المُسلِّم فارغةٌ تُكتب بخطّ اليد، وسطرُ «بمعرفة» حُذف.
٣. **الورقةُ جزيرةٌ فاتحة** تبقى حبراً على أبيض في الوضع الداكن، و**الطباعةُ تُخرجها وحدَها**: لا شريطَ
   ولا قائمةَ ولا بطاقةَ الحساب — وقاعدةُ الطباعة العامّة في app.css لا تعيد صياغةَ جدولها.
٤. **للسرّيّ رمزُه** في الوضعين، و**زرُّ الخطر يحمرّ تحت اليد** (قاعدتاه بعد قاعدة المرور العامّة).
٥. **شريطُ التصفية**: مُددٌ سريعة، والحقلُ المطبَّق موسوم.
"""
import re

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core.models import BookReferral
from core.tests_desk import DeskTestCase
from core.tests_list_identity import DECL, _read, _strip

DESK_CSS = ('static/css/desk.css', 'static/css/queues.css')


def sheet_of(response):
    """ما بين وسمَي الورقة — ما يخرج من الطابعة، لا الإطار."""
    return response.content.decode('utf-8').split('id="desk-document-main"', 1)[1].split('</article>', 1)[0]


class DeskStylesheetTests(SimpleTestCase):

    def test_the_desk_stylesheets_speak_tokens(self):
        for rel in DESK_CSS:
            with self.subTest(rel=rel):
                values = ' '.join(m.group(2) for m in DECL.finditer(_strip(_read(rel))))
                hexes = {h.lower() for h in re.findall(r'#[0-9a-fA-F]{3,8}\b', values)}
                self.assertLessEqual(hexes, {'#fff'})
                self.assertNotIn('rgba(15, 23, 42', values)

    def test_the_workspace_tokens_read_the_identity(self):
        css = _read('static/css/desk.css')
        block = css[css.index('.desk-workspace {'):]
        block = block[:block.index('}')]
        for name in ('--brand', '--brand-strong', '--desk-line', '--desk-muted'):
            with self.subTest(token=name):
                self.assertRegex(block, re.escape(name) + r':\s*var\(--lx-')

    def test_the_secret_colour_is_a_token_in_both_modes(self):
        css = _read('static/css/theme.css')
        self.assertEqual(len(re.findall(r'--lx-secret:\s', css)), 2)
        self.assertIn('.qb-secret { --qb-tone: var(--lx-secret); }', _read('static/css/queues.css'))

    def test_the_danger_action_wins_its_hover(self):
        css = _read('static/css/queues.css')
        self.assertLess(css.index('.qb-act:hover:not(:disabled) {'),
                        css.index('.qb-act--danger:hover:not(:disabled) {'))

    def test_the_documents_take_the_identity_from_the_frame(self):
        src = _read('templates/core/_desk_document_assets.html')
        self.assertIn('{% include "core/_desk_css.html" %}', src)
        self.assertIn("{% static 'css/desk.css' %}", _read('templates/core/_desk_css.html'))
        for doubled in ('css/theme.css', 'cairo.css', 'bootstrap-icons'):
            with self.subTest(asset=doubled):
                self.assertNotIn(doubled, src)

    def test_the_sheet_can_be_a_light_island(self):
        self.assertIn(':root, [data-bs-theme="light"] {', _read('static/css/theme.css'))
        for name in ('desk_ledger', 'desk_handover'):
            with self.subTest(page=name):
                self.assertIn('<article class="sheet" id="desk-document-main" tabindex="-1" data-bs-theme="light"',
                              _read(f'templates/core/{name}.html'))

    def test_printing_leaves_the_frame_out(self):
        style = _read('templates/core/_sheet_style.html')
        printed = style[style.index('@media print'):]
        self.assertRegex(printed, r'\.app-topbar, \.app-sidebar[^{]*\{ display:none !important; \}')
        self.assertIn('@page { size:A4 portrait; margin:10mm; }', printed)
        self.assertNotIn('desk-paper', _read('static/css/desk.css'))

    def test_the_generic_print_table_rule_spares_the_sheets(self):
        css = _read('static/app.css')
        for cell in ('thead', 'th', 'td'):
            with self.subTest(cell=cell):
                self.assertIn(f'  table:not(.rep) {cell} {{', css)
                self.assertNotRegex(css, r'\n  table %s \{' % cell)


class DeskPagesTests(TestCase):

    def setUp(self):
        self.client.force_login(User.objects.create_superuser('desk-identity', password='pw-desk-1112'))

    def test_the_three_pages_live_inside_the_frame(self):
        for page in ('desk_board', 'desk_ledger', 'desk_handover'):
            with self.subTest(page=page):
                r = self.client.get(reverse(page))
                self.assertContains(r, 'data-lx-page="v2"')
                self.assertContains(r, 'class="app-topbar"')
                self.assertContains(r, '<main', count=1)


class SheetNamesTests(DeskTestCase):
    """المُسلِّمون والمتعهّدون متبدّلون (قرارُ المالك 11-12): الورقةُ تُسحب بلا اسم، ويُكتب بخطّ اليد."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin = User.objects.create_superuser('desk-names-admin', password='pw-desk-1112')
        for user, first, last in ((cls.admin, 'سالم', 'الطابع'), (cls.officer, 'هدى', 'المختصّة')):
            user.first_name, user.last_name = first, last
            user.save()
        BookReferral.objects.create(book=cls.book, from_department=cls.dept, to_department=cls.unit, due_date=cls.due)

    def _sheets(self, user, extra):
        self.client.force_login(user)
        yield 'ledger', self.client.get(reverse('desk_ledger'), extra)
        yield 'handover', self.client.get(reverse('desk_handover'), {**extra, 'to': self.unit.pk})

    def test_no_account_name_is_printed_on_either_sheet(self):
        for user, extra in ((self.admin, {'department': self.dept.pk}), (self.officer, {})):
            for name, response in self._sheets(user, extra):
                with self.subTest(user=user.username, sheet=name):
                    paper = sheet_of(response)
                    self.assertIn('ho-sign', paper)
                    self.assertNotIn(user.get_full_name(), paper)
                    self.assertNotIn(user.username, paper)
                    self.assertNotIn('بمعرفة', paper)
                    self.assertEqual(paper.count('<span>الاسم</span><i></i>'), 2)


class FilterStripTests(DeskTestCase):

    def setUp(self):
        self.client.force_login(self.officer)

    def test_quick_ranges_are_offered_and_wired(self):
        for page in ('desk_ledger', 'desk_handover'):
            with self.subTest(page=page):
                self.assertContains(self.client.get(reverse(page)), 'data-desk-preset="', count=3)
        self.assertIn('[data-desk-presets]', _read('static/js/desk_actions.js'))

    def test_an_applied_filter_is_marked(self):
        idle = self.client.get(reverse('desk_ledger'))
        self.assertNotContains(idle, 'is-set')
        applied = self.client.get(reverse('desk_ledger'), {'kind': 'incoming', 'date_from': '2026-10-01'})
        self.assertContains(applied, 'desk-filter-kind is-set')
        self.assertContains(applied, 'class="desk-range is-set" aria-describedby="desk-date-hint"')
        self.assertNotContains(applied, 'class="desk-range is-set" aria-describedby="desk-number-hint"')
