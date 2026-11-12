"""حرّاسُ قائمة الكتب على الهويّة الموحّدة (11-12، قرارُ المالك «تركواز واحد + علامة اتّجاه»).

١. **الصفحةُ منقولة ولونُها واحد**: تعلن v2 فتأخذ الرموزَ والوضعين؛ متغيّراتُ الصفحة تُعرَّف مرّةً على
   الرموز بلا كتلةٍ لكلّ تبويب، وأوراقُ القائمة بلا ألوانٍ صريحة؛ الاتّجاهُ علامةٌ في الصفّ (ظرفٌ داخل/خارج).
٢. **ما كان لا يُرسم صار يُرسم**: شريطُ حالة المتابعة على الخليّة الأولى لا على <tr> (الجدولُ بحدودٍ
   منفصلة يتجاهل حدودَ الصفوف، فلم يظهر قطّ)، وحالاتُ المتابعة الأربع على رموز الحالات في v2.
٣. **لا تصريحَ يتيم**: سطرٌ فقد محدِّدَه في book_unified_tabs.css جعل المتصفّحَ يبتلع القاعدةَ التالية
   كلَّها بصمت — فحصٌ عامّ لكلّ ورقة أنماطٍ في static.
٤. **لا عودةَ لقواعد ‎#bookTableBody** القديمة في app.css (nowrap يبتر العنوانَ وسط الكلمة، وإطارٌ برتقاليّ).
٥. **أشرطةُ التمرير والتحديد** على الهويّة ومحصورةٌ في v2 (كانت برتقاليّةً من الهويّة القديمة).
"""
import re
from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase

ROOT = Path(settings.BASE_DIR)
LIST_CSS = (
    'static/css/book_unified.css',
    'static/css/book_unified_tabs.css',
    'static/css/book_unified_table.css',
    'static/css/book_unified_mobile.css',
    'static/css/number_hint.css',
)
COMMENT = re.compile(r'/\*.*?\*/', re.S)
STRING = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'')
DECL = re.compile(r'([\w-]+)\s*:\s*([^;{}]+)')


def _read(rel):
    return (ROOT / rel).read_text(encoding='utf-8')


def _strip(css):
    """التعليقاتُ فراغاتٌ تحفظ الأسطر، والنصوصُ المقتبسة فارغة."""
    return STRING.sub('""', COMMENT.sub(lambda m: re.sub(r'[^\n]', ' ', m.group(0)), css))


def css_orphans(css):
    """تصريحاتٌ خارج أيّ قاعدة (`prop: value;` في المستوى الأعلى) وأقواسٌ غيرُ متوازنة."""
    src = _strip(css)
    found, depth, start = [], 0, 0
    for i, ch in enumerate(src):
        if ch == '{':
            depth += 1
            start = i + 1
        elif ch == '}':
            depth -= 1
            if depth < 0:
                found.append((src.count('\n', 0, i) + 1, 'unbalanced }'))
                depth = 0
            start = i + 1
        elif ch == ';' and depth == 0:
            stmt = src[start:i].strip()
            if stmt and not stmt.startswith('@'):
                found.append((src.count('\n', 0, i) + 1, stmt[:60]))
            start = i + 1
    if depth:
        found.append((src.count('\n') + 1, 'unclosed {'))
    return found


class StylesheetSyntaxTests(SimpleTestCase):

    def test_no_declaration_lives_outside_a_rule(self):
        files = [p for p in (ROOT / 'static').rglob('*.css')
                 if 'vendor' not in p.parts and not p.name.endswith('.min.css')]
        self.assertGreater(len(files), 10)
        problems = [f'{p.relative_to(ROOT)}:{line}: {what}'
                    for p in files for line, what in css_orphans(p.read_text(encoding='utf-8'))]
        self.assertEqual(problems, [])

    def test_the_scanner_catches_the_lost_selector(self):
        # الشكلُ الذي وُجد فعلاً: تعليقٌ ثمّ تصريحان وقوسٌ بلا محدِّد — فتُبتلع القاعدةُ التالية
        lost = '.a { color: red; }\n/* حالةٌ مقلوبة */\n  background: #fff; color: red; }\n.b { color: blue; }'
        self.assertTrue(css_orphans(lost))
        sound = '@import url("x.css");\n.a { b: c; }\n@media (min-width: 1px) { .a { b: c; } }\n.q::after { content: "a;b}"; }'
        self.assertEqual(css_orphans(sound), [])


class ListIdentitySourceTests(SimpleTestCase):

    def test_one_colour_for_every_tab(self):
        css = _read('static/css/book_unified.css')
        self.assertEqual(len(re.findall(r'--theme-primary\s*:', css)), 1)
        self.assertNotRegex(css, r'\[data-theme="(?:incoming|outgoing|all)"\]\s*\{')
        self.assertRegex(css, r'--theme-primary:\s*var\(--lx-pri\)')

    def test_the_list_stylesheets_speak_tokens(self):
        """لا لونَ صريحاً في أوراق القائمة إلّا الأبيضَ حبراً فوق السطح التركوازيّ العميق."""
        for rel in LIST_CSS:
            with self.subTest(rel=rel):
                values = ' '.join(m.group(2) for m in DECL.finditer(_strip(_read(rel))))
                hexes = {h.lower() for h in re.findall(r'#[0-9a-fA-F]{3,8}\b', values)}
                self.assertLessEqual(hexes, {'#fff'})

    def test_the_status_edge_paints_on_the_first_cell(self):
        css = _read('static/css/book_unified_table.css')
        for state in ('pending', 'due_today', 'overdue'):
            with self.subTest(state=state):
                self.assertRegex(css, r'tr\.book-row-' + state + r'\s*>\s*td:first-child\s*\{\s*'
                                 r'border-inline-start-color:\s*var\(--followup-' + state.replace('_', '-') + r'\)')

    def test_the_followup_states_follow_the_status_tokens_in_v2(self):
        css = _read('static/css/theme.css')
        start = css.index('html[data-lx-page="v2"] {\n  --followup-pending:')
        block = css[start:css.index('}', start)]
        for state, token in (('pending', 'prog'), ('due-today', 'wait'), ('overdue', 'late')):
            for suffix, part in (('', ''), ('-bg', '-bg'), ('-text', ''), ('-line', '-line')):
                with self.subTest(var=f'--followup-{state}{suffix}'):
                    self.assertIn(f'--followup-{state}{suffix}: var(--lx-{token}{part});', block)
        self.assertIn('--followup-archived: var(--lx-mute);', block)

    def test_direction_marks_in_rows_cards_and_tabs(self):
        for rel in ('templates/core/partials/book_unified_row.html',
                    'templates/core/partials/book_unified_card_mobile.html'):
            with self.subTest(rel=rel):
                src = _read(rel)
                self.assertIn('bi-envelope-arrow-down kind-icon kind-icon-incoming', src)
                self.assertIn('bi-envelope-arrow-up kind-icon kind-icon-outgoing', src)
        self.assertIn('data-lx-tabs', _read('templates/core/partials/book_unified_tabs.html'))
        self.assertIn("{% static 'js/lx_tabs.js' %}", _read('templates/core/book_unified.html'))

    def test_the_legacy_book_table_rules_stay_gone(self):
        self.assertNotIn('#bookTableBody', _read('static/app.css'))

    def test_scrollbars_and_selection_take_the_identity_only_in_v2(self):
        # التعليقاتُ وحدها تُحذف: المحدِّدُ نفسُه فيه نصٌّ مقتبس ("v2") يُفرغه _strip.
        # كلُّ محدِّدٍ في كلّ قائمة يُفحص وحدَه (لا آخرُ القائمة)، وشرطُ ‎@supports ليس محدِّداً
        css = COMMENT.sub(' ', _read('static/css/theme.css'))
        selectors = [sel.strip()
                     for m in re.finditer(r'([^{}]+)\{', css) if not m.group(1).strip().startswith('@')
                     for sel in m.group(1).split(',') if re.search(r'::(?:-webkit-scrollbar|selection)', sel)]
        self.assertGreaterEqual(len(selectors), 12)
        for selector in selectors:
            self.assertTrue(selector.startswith('html[data-lx-page="v2"]'), selector)


def _ents(*names):
    return SimpleNamespace(all=[SimpleNamespace(name=n) for n in names])


class LedgerRowTests(SimpleTestCase):
    """ترتيبُ الدفتر (قرارُ المالك 11-12): ستّةُ أعمدة، والطرفُ الآخر يتصدّر خانةَ الجهة في الاتّجاهين."""

    def _row(self, **kw):
        book = dict(
            id=7, followup_state='archived', delay_days=0, kind='incoming_internal', is_incoming=True,
            our_number_display='3914', our_number_sequence='3914', our_number_year='', our_number_explained='',
            our_number_is_numberless=False, legacy_number='', date=None, due_date=None,
            sender_number='75', sender_date=None, shown_director_general_number='',
            title='تحديث بيانات', kind_label='وارد داخلي', source_ref='', attachment=None,
            issuing_entities=_ents('هيئة الفحص'),
            receiving_entities=_ents('قسم الأرشيف', 'الإدارة', 'شعبة الصيانة'),
        )
        book.update(kw)
        return render_to_string('core/partials/book_unified_row.html', {'book': SimpleNamespace(**book)})

    def test_cells_follow_the_ledger_order(self):
        cells = re.findall(r'<td class="(col-[a-z-]+)"', self._row())
        self.assertEqual(cells, ['col-select', 'col-our-number', 'col-sender-number', 'col-entity',
                                 'col-title', 'col-status', 'col-actions'])
        head = re.findall(r'<th class="(col-[a-z-]+)"', _read('templates/core/partials/book_unified_table.html'))
        self.assertEqual(head, cells)

    def test_the_counterparty_leads_in_both_directions(self):
        incoming = self._row()
        self.assertRegex(incoming, r'ent-main">\s*<span class="ent-lbl">من</span>\s*'
                                   r'<span class="entity-name" title="هيئة الفحص">هيئة الفحص</span>')
        outgoing = self._row(is_incoming=False, kind='outgoing_internal',
                             issuing_entities=_ents('شعبة النقل'),
                             receiving_entities=_ents('قسم العقود'))
        self.assertRegex(outgoing, r'ent-main">\s*<span class="ent-lbl">إلى</span>\s*'
                                   r'<span class="entity-name" title="قسم العقود">')
        self.assertRegex(outgoing, r'ent-ours">\s*<span class="ent-lbl">من</span>')

    def test_more_entities_become_a_count_not_fragments(self):
        html = self._row()
        self.assertIn('>+2</span>', html)
        self.assertIn('title="الإدارة، شعبة الصيانة"', html)
        self.assertNotIn(' · ', html)

    def test_a_done_book_is_a_quiet_mark_that_still_reopens(self):
        html = self._row()
        self.assertIn('status-badge-quiet', html)
        self.assertIn('<span class="visually-hidden">مُنجَز / بلا متابعة</span>', html)
        self.assertIn('data-status-url=', html)
        self.assertNotIn('status-badge-quiet', self._row(followup_state='overdue', delay_days=5))


class ListPageRenderTests(TestCase):

    def test_the_list_is_a_migrated_page_with_its_sliding_tabs(self):
        user = get_user_model().objects.create_superuser('lister', 'lister@example.com', 'x-Pass-42')
        self.client.force_login(user)
        resp = self.client.get('/books/unified/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'data-lx-page="v2"')
        self.assertContains(resp, 'data-lx-tabs')
        self.assertContains(resp, 'bi-envelope-arrow-down tab-icon')
