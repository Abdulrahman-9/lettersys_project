"""حرّاسُ صفحة الجهات على الهويّة الموحّدة (2026-11-19، دفعةُ الصفحات).

١. الصفحةُ منقولة (v2) وأوراقُها رموزٌ فقط، وقوالبُها بلا ألوانٍ مضمَّنة ولا أدواتِ ألوانٍ قديمة،
   ولا حوارَ أصليّاً (confirm/alert) في سكربتيها.
٢. العيوبُ التي أُصلحت لا تعود: الهاتفُ كان يعرض الاسمَ حرفاً في سطر (الجدولُ بطاقاتٌ تحت 680px
   بعرض الحاوية) · شريطُ التحديد كان يلتصق «بالأسفل» من موضعٍ فوق الجدول فلا يتبع التمرير ·
   العنقودُ المعطّل كان يُبهَت إلى 58% دون 4.5:1 · إجراءاتُ الصفّ كانت تُبهَت إلى 55% حتّى المرور ·
   حقلُ بحث المنتقي كان بلا تركيزٍ مرئيّ · وجها الصفحة ملاحةٌ (aria-current) لا tablist ·
   والبحثُ بلا نتيجة يقدّم مخرجَه بنقرة.
"""
import re

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core.models import Entity
from core.tests_list_identity import DECL, _read, _strip

SHEETS = ('static/css/entities_design.css', 'static/css/entity_list.css')
TEMPLATES = ('templates/core/entity_list.html', 'templates/core/_entity_groups.html',
             'templates/core/partials/entity_list_empty.html')
SCRIPTS = ('static/js/entity_list.js', 'static/js/member_picker.js')


def _rule(css, selector):
    """جسمُ أوّل قاعدةٍ محدِّدُها هو `selector` حرفيّاً."""
    body = css[css.index(selector + ' {') + len(selector) + 2:]
    return body[:body.index('}')]


class EntityListIdentitySourceTests(SimpleTestCase):

    def test_the_page_opts_into_the_identity(self):
        self.assertIn('{% block html_attrs %} data-lx-page="v2"{% endblock %}', _read('templates/core/entity_list.html'))

    def test_the_sheets_speak_tokens_only(self):
        for rel in SHEETS:
            css = _strip(_read(rel))
            values = ' '.join(m.group(2) for m in DECL.finditer(css))
            with self.subTest(rel=rel):
                self.assertLessEqual({h.lower() for h in re.findall(r'#[0-9a-fA-F]{3,8}\b', values)}, {'#fff'})
                self.assertNotRegex(values, r'(?:rgba?|hsla?)\(\s*[\d.]')
                self.assertNotRegex(values, r'(?<![\w-])(?:white|black)(?![\w-])')
                self.assertNotIn('data-theme', css)

    def test_templates_carry_no_colour_of_their_own(self):
        for rel in TEMPLATES:
            html = _read(rel)
            with self.subTest(rel=rel):
                self.assertNotRegex(html, r'style="[^"]*(?:color|background)')
                self.assertNotRegex(html, r'\b(?:btn-orange|text-dark|text-warning|text-info|text-primary|bg-\w+-subtle|'
                                          r'btn-outline-(?:info|primary|success|danger)|btn-success|hover-lift)\b')

    def test_no_native_dialogs(self):
        for rel in SCRIPTS + TEMPLATES:
            with self.subTest(rel=rel):
                self.assertNotRegex(_read(rel), r'(?<![\w.$])(?:window\.)?(?:confirm|alert)\s*\(')

    def test_the_narrow_table_becomes_cards_by_its_container(self):
        css = _read('static/css/entity_list.css')
        self.assertIn('container: en-table / inline-size;', _rule(css, '.entities-table-wrapper'))
        narrow = css[css.index('@container en-table (width < 680px)'):]
        self.assertIn('"check name name"', narrow)
        self.assertIn('.en-selall { display: inline;', narrow)

    def test_the_selection_bar_sticks_under_the_topbar(self):
        bar = _rule(_read('static/css/entities_design.css'), '.en-bulkbar')
        self.assertIn('position: sticky;', bar)
        self.assertIn('top: calc(var(--lx-topbar-h) + .5rem);', bar)
        self.assertNotIn('bottom:', bar)

    def test_quiet_states_keep_their_contrast(self):
        css = _read('static/css/entities_design.css') + _read('static/css/entity_list.css')
        self.assertNotIn('opacity', _rule(css, '.en-group.is-off'))
        self.assertNotRegex(_strip(css), r'\.row-actions[^{]*\{[^}]*opacity')
        self.assertIn('معطّل', _read('templates/core/_entity_groups.html'))

    def test_the_picker_search_shows_its_focus(self):
        focus = _rule(_read('static/css/entities_design.css'), '.en-picker-search:focus')
        self.assertIn('box-shadow: inset 0 0 0 2px var(--lx-pri);', focus)

    def test_the_two_faces_are_navigation_not_tabs(self):
        html = _read('templates/core/entity_list.html')
        nav = html[html.index('<nav class="tabs-split'):]
        nav = nav[:nav.index('</nav>')]
        self.assertNotIn('role="tab', nav)
        self.assertEqual(nav.count('aria-current="page"'), 2)


class EntityListRenderTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser('idl-admin', 'idl@example.com', 'pw-idl-admin-1')
        Entity.objects.create(name='وزارة النفط', kind=Entity.KIND_EXTERNAL)

    def test_a_search_without_result_offers_its_way_out(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse('entity_list'), {'q': 'لا-شيء-بهذا', 'sort': 'books'}).content.decode('utf-8')
        out = re.search(r'<a href="([^"]*)">امسح البحث</a>', html)
        self.assertIsNotNone(out)
        self.assertIn('sort=books', out.group(1))
        self.assertNotIn('q=', out.group(1))
