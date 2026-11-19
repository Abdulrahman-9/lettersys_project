"""حرّاسُ صفحات الجهة على الهويّة الموحّدة (11-19): ملفُّ الجهة · الإضافةُ والتعديل · دمجُ المكرّرات.

١. منقولةٌ إلى الهويّة: القوالبُ الثلاثة تعلن v2 وتحمّل entity_pages.css بنسخة الدفعة.
٢. ورقةٌ بالرموز وحدها (‎#fff‎ حبراً وحده)، ولا أنماطَ مضمَّنة ولا table-warning/table-light في القوالب.
٣. لا confirm()/alert() أصليّ — الدمجُ يؤكَّد بـdata-confirm.
٤. مفتاحُ «مُصدرة/مُستلمة» في المحتوى (كان في العمود الجانبيّ: تحت الثنية، وفي الدرج، ومخفيّاً حين يُطوى).
٥. الكتابُ بلا رقم رابطٌ مرئيّ («بلا رقم» لا رابطاً فارغاً).
٦. الترقيمُ نافذةٌ حول الحاليّة بروابطه نفسِها (كانت كلُّ الصفحات تُرسم).
٧. النموذج: خلاصةُ أخطاءٍ بروابط إلى الحقول، والخطأُ بمعرّفٍ يُربط بحقله؛ المفاتيحُ المرسومةُ يدويّاً بأسمائها وحالها؛
   ولا كتلةَ داخل label.
٨. الدمج: الاختيارُ باسمٍ مقروء، والأمُّ بصنفٍ على الرموز. ٩. «ثانويّ» مقروءٌ على الكريميّ. ١٠. جدولُ الكتب يتكدّس على الهاتف.
"""
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core.models import Book, Entity

ROOT = Path(settings.BASE_DIR)
PAGES = ('templates/core/entity_detail.html', 'templates/core/entity_form.html', 'templates/core/entity_merge.html')
PARTIALS = ('templates/core/partials/_merge_cluster.html', 'templates/core/partials/entity_pages_pager.html')
SHEET = 'static/css/entity_pages.css'
RAW_COLOUR = re.compile(r'#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?)\(\s*\d')


def _read(rel):
    return (ROOT / rel).read_text(encoding='utf-8')


def _sheet():
    return re.sub(r'/\*.*?\*/', '', _read(SHEET), flags=re.S)


class EntityPagesStaticTests(SimpleTestCase):

    def test_every_page_opts_into_v2_and_loads_its_sheet(self):
        for rel in PAGES:
            with self.subTest(template=rel):
                src = _read(rel)
                self.assertIn('{% block html_attrs %} data-lx-page="v2"{% endblock %}', src)
                self.assertIn("{% static 'css/entity_pages.css' %}?v=20261119-pages", src)

    def test_the_sheet_paints_with_tokens_only(self):
        css = _sheet()
        bad = [f'{p}: {v.strip()}' for p, v in re.findall(r'([\w-]+)\s*:\s*([^;{}]+)', css)
               if RAW_COLOUR.search(v) and not (p == 'color' and v.strip() == '#fff')]
        self.assertEqual(bad, [])
        self.assertNotIn('data-theme', css)
        self.assertNotRegex(css, r'var\(--(?:soft-brown|deep-brown|warm-|accent-2|card-border)')

    def test_templates_carry_no_inline_paint(self):
        for rel in PAGES + PARTIALS:
            with self.subTest(template=rel):
                src = _read(rel)
                self.assertNotIn('<style', src)
                self.assertNotRegex(src, r'\sstyle="')
                self.assertNotIn('table-warning', src)
                self.assertNotIn('table-light', src)

    def test_no_native_confirm_or_alert(self):
        for rel in PAGES + PARTIALS:
            with self.subTest(template=rel):
                self.assertNotRegex(_read(rel), r'(?<![\w.-])(?:window\.)?(?:confirm|alert)\s*\(')
        self.assertIn('data-confirm="دمج هذا العنقود؟', _read(PARTIALS[0]))

    def test_no_block_inside_a_label(self):
        for rel in PAGES + PARTIALS:
            for label in re.findall(r'<label\b.*?</label>', _read(rel), re.S):
                with self.subTest(template=rel, label=label[:60]):
                    self.assertNotRegex(label, r'<(?:div|p)\b')

    def test_secondary_button_reads_on_the_cream_floor(self):
        # المصدرُ الواحد في الملفّ المشترك (حارسُه tests_identity_pages_batch) — النسخةُ المحلّيّة لا تعود
        self.assertNotIn('.btn-outline-secondary', _sheet())
        self.assertNotIn('--ep-field-line', _sheet())

    def test_the_book_table_stacks_on_a_phone(self):
        css = _sheet()
        block = css[css.index('@media (max-width: 767.98px)'):]
        rule = block[block.index('.ep-book-table tr {'):]
        self.assertIn('display: flex;', rule[:rule.index('}')])


class PagerWindowTests(SimpleTestCase):

    def render(self, number, keep=''):
        page = Paginator(range(1000), 25).page(number)   # 40 صفحة
        return render_to_string('core/partials/entity_pages_pager.html',
                                {'page': page, 'key': 'pi', 'keep_key': 'pr', 'keep': keep, 'label': 'صفحات'})

    def test_a_window_around_the_current_page(self):
        html = self.render(20, keep='3')
        self.assertEqual(re.findall(r'<bdi dir="ltr">(\d+)</bdi>', html), ['1', '18', '19', '20', '21', '22', '40'])
        self.assertEqual(html.count('…'), 2)
        self.assertIn('href="?pi=21&amp;pr=3"', html)
        self.assertIn('aria-current="page"><bdi dir="ltr">20</bdi>', html)

    def test_the_first_page(self):
        html = self.render(1)
        self.assertEqual(re.findall(r'<bdi dir="ltr">(\d+)</bdi>', html), ['1', '2', '3', '40'])
        self.assertNotIn('pr=', html)
        self.assertNotIn('الصفحة السابقة', html)


class EntityDetailRenderTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser('ep_admin', 'ep@x.co', 'pw-ep-admin-1119')
        cls.entity = Entity.objects.create(name='جهةٌ للهويّة')
        cls.numberless = Book.objects.create(kind='incoming_external', our_number='', title='كتابٌ بلا رقم',
                                             created_by=cls.admin)
        cls.numberless.issuing_entities.add(cls.entity)

    def html(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('entity_detail', args=[self.entity.pk]))
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode('utf-8')

    def test_the_tab_switch_lives_in_the_content(self):
        html = self.html()
        main = html.index('id="main"')
        self.assertGreater(html.index('id="issued-tab"'), main)
        self.assertGreater(html.index('id="received-tab"'), main)
        self.assertRegex(html, r'role="tablist"[^>]*data-lx-tabs')
        self.assertIn('js/lx_tabs.js', html)
        self.assertNotIn('app-sidebar-context-panel', html)

    def test_a_numberless_book_is_a_visible_link(self):
        url = reverse('book_detail', args=[self.numberless.pk])
        self.assertIn('href="%s"><bdi dir="ltr">بلا رقم</bdi></a>' % url, self.html())


class EntityFormTests(TestCase):

    def setUp(self):
        self.client.force_login(User.objects.create_superuser('ep_form', password='pw-ep-form-1119'))
        self.entity = Entity.objects.create(name='جهةٌ للتعديل', notify_on_send=True)

    def test_a_failed_save_summarises_and_links_each_error(self):
        html = self.client.post(reverse('entity_create'), {'name': ''}).content.decode('utf-8')
        self.assertIn('id="ep-error-summary" role="alert" tabindex="-1"', html)
        self.assertIn('href="#id_name"', html)
        self.assertIn('id="id_name-error"', html)

    def test_the_hand_drawn_switches_keep_their_names_and_state(self):
        html = self.client.get(reverse('entity_edit', args=[self.entity.pk])).content.decode('utf-8')
        self.assertIn('name="notify_on_send" id="id_notify_on_send" checked>', html)
        self.assertIn('name="notify_on_receive" id="id_notify_on_receive">', html)
        self.assertIn('name="is_active" id="id_is_active" checked>', html)
        # بعد إرسالٍ فاشل يبقى ما اختاره المستخدم (القيمةُ المربوطة لا قيمةُ القاعدة)
        html = self.client.post(reverse('entity_edit', args=[self.entity.pk]),
                                {'name': '', 'kind': self.entity.kind, 'notify_on_receive': 'on'}).content.decode('utf-8')
        self.assertIn('name="notify_on_receive" id="id_notify_on_receive" checked>', html)
        self.assertIn('name="notify_on_send" id="id_notify_on_send">', html)


class EntityMergeRenderTests(TestCase):

    def test_each_pick_is_named_and_the_mother_row_wears_tokens(self):
        self.client.force_login(User.objects.create_superuser('ep_merge', password='pw-ep-merge-1119'))
        a = Entity.objects.create(name='مديريةُ الهويّة')
        b = Entity.objects.create(name='مديريه الهويه')
        html = self.client.get(reverse('entity_merge'), {'ids': f'{a.pk},{b.pk}'}).content.decode('utf-8')
        self.assertRegex(html, r'<label class="ep-pick">\s*<input class="form-check-input canon-radio"[^>]*>\s*'
                               r'<span class="visually-hidden">اجعل «')
        self.assertRegex(html, r'<label class="ep-pick">\s*<input class="form-check-input victim-check"[^>]*>\s*'
                               r'<span class="visually-hidden">ادمج «')
        self.assertIn("tr.classList.toggle('is-canonical'", html)
        self.assertNotIn('table-warning', html)
