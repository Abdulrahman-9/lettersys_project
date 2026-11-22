"""حرّاسُ الأضابير على الهويّة الموحّدة (11-19، دفعةُ الصفحات): القائمةُ والإضبارة.

١. **منقولةٌ وبالرموز وحدَها**: الصفحتان تعلنان v2 (الرموزُ والوضعان)، وورقتُهما بلا لونٍ صريحٍ إلّا الأبيضَ
   حبراً على اللوح التركوازيّ، ولا لونَ في سمة style، ولا confirm/alert أصليّة.
٢. **مكوّناتُ قائمة الكتب لا نسخٌ منها**: لوحُ التبويب المنزلق (data-lx-tabs + lx_tabs.js) في الصفحتين،
   ومتغيّراتُ ورقة التبويبات المشتركة معرَّفةٌ هنا — كانت غيرَ معرَّفة فسقط حدُّ اللوح وفواصلُه.
٣. **أعطابٌ أُصلحت**: جدولُ الإضبارة يُقصّ على الهاتف (الحالةُ والإجراءاتُ خارج البطاقة) ⟵ صفوفٌ مكدّسة ·
   أيقونةُ البحث فوق آخر النصّ (الحشوُ في الجهة الأخرى) · رابطُ رقمٍ فارغٌ للكتاب بلا رقم · أزرارُ أيقوناتٍ
   بلا اسمٍ مسموع · «10 / 1» المقلوبةُ في ترقيم الصفحات · عدّادُ التبويب النشط 4.2:1 على طرف اللوح ·
   قواعدُ ميّتة (‎.filter-bar ‎.type-group > summary ‎.dd-tab.kind…) لا تعود.
"""
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core.models import Book, Entity

ROOT = Path(settings.BASE_DIR)
CSS = 'static/css/dossiers.css'
LIST = 'templates/core/dossier_list.html'
DETAIL = 'templates/core/dossier_detail.html'
ROW = 'templates/core/partials/dossier_book_row.html'
TEMPLATES = (LIST, DETAIL, ROW)

COMMENT = re.compile(r'/\*.*?\*/', re.S)
STRING = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'')
DECL = re.compile(r'([\w-]+)\s*:\s*([^;{}]+)')


def _read(rel):
    return (ROOT / rel).read_text(encoding='utf-8')


def _css():
    """الورقةُ بلا تعليقات ولا نصوصٍ مقتبسة."""
    return STRING.sub('""', COMMENT.sub(' ', _read(CSS)))


def _rule(css, selector):
    """جسمُ أوّلِ قاعدةٍ محدِّدُها هذا النصُّ بعينه (بعد طيّ المسافات)."""
    for m in re.finditer(r'([^{}]+)\{([^{}]*)\}', css):
        if ' '.join(m.group(1).split()) == selector:
            return m.group(2)
    return None


def _media(css, query):
    """محتوى كتلة ‎@media‎ بهذا الشرط (القواعدُ داخلها)."""
    start = css.index('@media (%s)' % query)
    i = css.index('{', start) + 1
    depth = 1
    for j in range(i, len(css)):
        depth += {'{': 1, '}': -1}.get(css[j], 0)
        if depth == 0:
            return css[i:j]
    raise AssertionError('كتلةٌ غيرُ مغلقة')


class DossierIdentitySourceTests(SimpleTestCase):

    def test_the_sheet_speaks_tokens(self):
        """لا لونَ صريحاً إلّا ‎#fff‎ (حبراً على اللوح التركوازيّ)، ولا سمةَ الوضع القديم."""
        values = ' '.join(m.group(2) for m in DECL.finditer(_css()))
        hexes = {h.lower() for h in re.findall(r'#[0-9a-fA-F]{3,8}\b', values)}
        self.assertLessEqual(hexes, {'#fff'})
        self.assertEqual(re.findall(r'rgba?\(\s*\d', values), [])
        self.assertEqual(re.findall(r'(?<![\w-])(?:white|black|red|blue|green|orange|gr[ae]y)(?![\w-])', values), [])
        self.assertNotIn('[data-theme', _read(CSS))

    def test_no_colour_in_style_attributes_and_no_native_dialogs(self):
        for rel in TEMPLATES:
            with self.subTest(rel=rel):
                src = _read(rel)
                for style in re.findall(r'style="([^"]*)"', src):
                    self.assertNotRegex(style, r'(?i)colou?r|background|#[0-9a-f]{3}')
                self.assertNotRegex(src, r'\b(?:alert|confirm|prompt)\s*\(')

    def test_both_pages_use_the_sliding_tab_board(self):
        for rel in (LIST, DETAIL):
            with self.subTest(rel=rel):
                src = _read(rel)
                self.assertRegex(src, r'class="[^"]*\btabs-split\b[^"]*"[^>]*\bdata-lx-tabs\b')
                self.assertIn("{% static 'js/lx_tabs.js' %}", src)
                self.assertIn("{% static 'css/dossiers.css' %}?v=20261119-pages", src)

    def test_the_shared_tab_sheet_finds_its_variables_here(self):
        """book_unified_tabs.css يقرأ ‎--border‎ و‎--theme-*‎ — صفحةُ الكتب تعرّفها على حاويتها، وهنا كانت غائبة."""
        body = _rule(_css(), '.dossiers-page, .dossier-detail')
        self.assertIsNotNone(body)
        # المصدرُ الواحد في الملفّ المشترك (حارسُه tests_identity_pages_batch) — النسخةُ المحلّيّة لا تعود: الورقةُ المشتركة تحمل بدائلَها
        for name in ('--border', '--theme-'):
            with self.subTest(name=name):
                self.assertNotIn(name, _css())

    def test_the_active_tab_count_is_full_white(self):
        """82% أبيضُ الورقة المشتركة 4.2:1 عند الطرف الأفتح من اللوح — هنا أبيضُ كامل."""
        # المصدرُ الواحد في الملفّ المشترك (حارسُه tests_identity_pages_batch) — النسخةُ المحلّيّة لا تعود
        self.assertNotIn('.tab-main.active .tab-count', _css())

    def test_the_search_icon_has_its_own_room(self):
        """الأيقونةُ في جهة inline-end؛ الحشوُ العريضُ هناك لا في الجهة الأخرى."""
        # المصدرُ الواحد في الملفّ المشترك (حارسُه tests_identity_pages_batch) — النسخةُ المحلّيّة لا تعود
        body = _rule(_css(), '.dossier-detail .fb-search input')
        self.assertIsNotNone(body)
        self.assertNotIn('padding', body)

    def test_the_book_table_stacks_on_a_phone(self):
        """كانت ستّةُ أعمدةٍ تُقصّ داخل البطاقة فتغيب الحالةُ والإجراءاتُ على الهاتف."""
        phone = _media(_css(), 'max-width: 700px')
        body = _rule(phone, '.dd-table tr.dd-row')
        self.assertIsNotNone(body)
        self.assertIn('display: grid', body)
        self.assertIn('grid-template-areas', body)
        row = _read(ROW)
        self.assertIn('<tr class="dd-row st-{{ b.followup_state }}">', row)
        self.assertIn('data-label="{% if side == \'out\' %}إلى{% else %}من{% endif %}"', row)

    def test_icon_only_row_actions_have_names(self):
        anchors = re.findall(r'<a class="(view|edit|print)"[^>]*>', _read(ROW))
        self.assertEqual(len(anchors), 3)
        for tag in re.findall(r'<a class="(?:view|edit|print)"[^>]*>', _read(ROW)):
            with self.subTest(tag=tag[:30]):
                self.assertRegex(tag, r'aria-label="[^"]+"')

    def test_the_pager_reads_in_words_not_a_reversed_fraction(self):
        """«1 / 10» في سياقٍ عربيّ تُرسم «10 / 1» — صارت «صفحة 1 من 10»."""
        src = _read(LIST)
        self.assertIn('صفحة <b>{{ page_obj.number }}</b> من <b>{{ page_obj.paginator.num_pages }}</b>', src)
        self.assertNotRegex(src, r'\{\{ page_obj\.number \}\}\s*/')

    def test_no_dead_rules_return(self):
        """كلُّ صنفٍ في الورقة يحمله قالبٌ من قوالب الوحدة (أو يضيفه سكربتٌ) — القواعدُ الميّتة لا تعود."""
        markup = ' '.join(_read(rel) for rel in TEMPLATES)
        tokens = set()
        for attr in re.findall(r'class="([^"]*)"', markup):
            tokens.update(re.sub(r'\{[{%].*?[%}]\}', ' ', attr).split())
        prefixes = tuple(t for t in tokens if t.endswith('-'))
        runtime = {'dd-js', 'lx-tabs-on'}   # يضيفهما سكربتُ الإضبارة وlx_tabs.js
        css = _css()
        dead = sorted({cls for sel in re.findall(r'([^{}]+)\{', css) if not sel.strip().startswith('@')
                       for cls in re.findall(r'\.([A-Za-z_][\w-]*)', sel)
                       if cls not in tokens and cls not in runtime and not cls.startswith(prefixes)})
        self.assertEqual(dead, [])


class DossierIdentityRenderTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.root = get_user_model().objects.create_superuser('dos_ident', 'dos@x.co', 'pw-dos-ident-1')
        cls.entity = Entity.objects.create(name='جهةُ الهويّة', code='HW')
        cls.numberless = Book.objects.create(kind='outgoing_external', our_number='', title='كتابٌ بلا رقم',
                                             created_by=cls.root)
        cls.numberless.issuing_entities.add(cls.entity)

    def setUp(self):
        self.client.force_login(self.root)

    def test_both_pages_are_migrated(self):
        for url in (reverse('dossier_list'), reverse('dossier_detail', args=[self.entity.pk])):
            with self.subTest(url=url):
                self.assertContains(self.client.get(url), '<html lang="ar" dir="rtl" data-lx-page="v2">')

    def test_a_numberless_book_still_has_a_readable_link(self):
        """رابطُ الرقم كان فارغاً للكتاب بلا رقم — لا يُرى ولا يُسمع."""
        resp = self.client.get(reverse('dossier_detail', args=[self.entity.pk]), {'document_type': 'متفرقة'})
        url = reverse('book_detail', args=[self.numberless.pk])
        self.assertContains(resp, f'<a class="num" href="{url}">بلا رقم</a>', html=False)
        self.assertNotContains(resp, f'<a class="num" href="{url}"></a>', html=False)
