"""حرّاسُ سجلّ الحركات على الهويّة الموحّدة (11-19، دفعة الصفحات).

١. **الصفحةُ منقولة**: تعلن v2 فتأخذ الرموزَ والوضعين؛ ورقتُها بالرموز وحدها (#fff حبراً على التركواز
   العميق هو الاستثناء)، ولا لونَ في سمة style ولا حواريّةَ أصليّة.
٢. **ما كان معطوباً في العرض**: الكتابُ بلا رقم كان يفقد رابطَه وعنوانَه (القالب يتفرّع على الرقم)؛
   والوقتُ والتاريخُ بلا عزلٍ فينقلبان في سطرٍ عربيّ («12:32 2026/11/12»).
٣. **الدفتر**: الصفوفُ مجمّعةٌ يوماً يوماً تحت رأسٍ يعلن ترتيبَه (الأحدث أوّلاً)، والمحجوبُ بنفسجيُّ
   «السرّيّ» بلا رابط، و«مسح التصفية» لا يظهر إلّا حين توجد تصفية، والحالةُ الفارغة تعطي مخرجاً.
٤. **ما يحفظ الشكلَ حيّاً**: الرأسُ اللاصق لا تحبسه ‎overflow: hidden‎، وإصلاحا التباين على لوح التبويب.
"""
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Book, BookHistory, Department, UserProfile
from core.scoping import STUB_TITLE

ROOT = Path(settings.BASE_DIR)
TEMPLATE = 'templates/core/audit_log.html'
SHEET = 'static/css/audit.css'
NAMED = r'\b(?:white|black|red|green|blue|orange|gr[ae]y|yellow|purple|teal|navy|silver|gold|brown|pink)\b'


def _read(rel):
    return (ROOT / rel).read_text(encoding='utf-8')


def _css_rule(css, selector):
    """جسمُ القاعدة الأولى التي يبدأ رأسُها بـselector."""
    body = css[css.index(selector + ' {'):]
    return body[:body.index('}')]


class AuditSourceTests(SimpleTestCase):

    def test_the_page_opts_into_the_identity(self):
        self.assertIn('{% block html_attrs %} data-lx-page="v2"{% endblock %}', _read(TEMPLATE))

    def test_the_sheet_paints_with_tokens_only(self):
        css = re.sub(r'/\*.*?\*/', '', _read(SHEET), flags=re.S)
        raw = [c for c in re.findall(r'#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?)\(', css) if c.lower() != '#fff']
        self.assertEqual(raw, [])
        self.assertNotRegex(css, r':\s*' + NAMED)
        self.assertNotIn('data-theme', css)

    def test_no_inline_style_and_no_native_dialogs(self):
        src = _read(TEMPLATE)
        self.assertNotIn('style=', src)
        self.assertNotRegex(src, r'\b(?:confirm|alert)\s*\(')

    def test_the_sheet_is_linked_with_the_batch_version(self):
        self.assertIn("{% static 'css/audit.css' %}?v=20261119-pages", _read(TEMPLATE))

    def test_the_tabs_ride_the_shared_board(self):
        src = _read(TEMPLATE)
        self.assertIn('class="tabs-split audit-tabs" role="tablist" aria-label="نوع الحركات" data-lx-tabs', src)
        self.assertEqual(src.count('role="tab"'), 2)
        self.assertIn("{% static 'js/lx_tabs.js' %}", src)

    def test_the_sticky_header_is_not_trapped(self):
        """‎overflow: hidden‎ يصنع حاويةَ تمريرٍ فيلتصق الرأسُ بها لا بالنافذة — أي لا يلتصق أبداً."""
        css = _read(SHEET)
        sheet = _css_rule(css, '.audit-sheet')
        self.assertIn('overflow: clip;', sheet)
        self.assertNotRegex(sheet, r'overflow:\s*(?:hidden|auto|scroll)')
        self.assertIn('position: sticky;', _css_rule(css, '.audit-table thead th'))

    def test_the_tab_board_contrast_fixes_hold(self):
        """سطرُ التلميح الأبيضُ الشفّاف 4.3:1 على اللوح، وحلقةُ التركيز الذهبيّة 2.4:1 على الأبيض."""
        css = _read(SHEET)
        # المصدرُ الواحد في الملفّ المشترك (حارسُه tests_identity_pages_batch) — النسخةُ المحلّيّة لا تعود
        for copy in ('.tab-main.active .tab-count', '.tab-main:focus-visible', '--bs-btn-color', '.btn:focus-visible'):
            with self.subTest(copy=copy):
                self.assertNotIn(copy, css)


class AuditPageTests(TestCase):
    """رئيسُ القسم يرى شجرتَه — ومنها كتابٌ سرّيٌّ في شُعبته لا يملك محتواه."""

    @classmethod
    def setUpTestData(cls):
        cls.dept = Department.objects.create(name='المتابعة', code='س-ش13')
        cls.unit = Department.objects.create(name='شعبة الموازنة', code='س-ش13/1', parent=cls.dept)
        cls.head = User.objects.create_user('au-head', password='pw-au-head-1119')
        UserProfile.objects.create(user=cls.head, department=cls.dept, is_department_head=True)
        cls.clerk = User.objects.create_user('au-clerk', password='pw-au-clerk-1119',
                                             first_name='سارة', last_name='الكاتبة')
        UserProfile.objects.create(user=cls.clerk, department=cls.unit)
        cls.numbered = Book.objects.create(kind='incoming_internal', title='تخصيصاتُ الحفر',
                                           our_number='2433', department=cls.dept, created_by=cls.clerk)
        cls.numberless = Book.objects.create(kind='outgoing_external', title='كتابٌ بلا رقمٍ بعد',
                                             our_number='', department=cls.dept, created_by=cls.clerk)
        cls.secret = Book.objects.create(kind='incoming_internal', title='مناقصةٌ سرّيّة',
                                         our_number='2437', department=cls.unit, created_by=cls.clerk,
                                         secret_level='secret')
        for book in (cls.numbered, cls.numberless, cls.secret):
            BookHistory.objects.create(book=book, action='edit', by=cls.clerk)

    def page(self, **params):
        self.client.force_login(self.head)
        response = self.client.get(reverse('audit_log'), params)
        self.assertEqual(response.status_code, 200)
        return response.content.decode('utf-8')

    def test_the_rendered_page_is_v2(self):
        self.assertIn('<html lang="ar" dir="rtl" data-lx-page="v2">', self.page())

    def test_a_numberless_book_keeps_its_link(self):
        """كان القالبُ يتفرّع على الرقم: الكتابُ بلا رقم يظهر «—» بلا رابطٍ ولا عنوان."""
        body = self.page()
        link = 'href="%s"' % reverse('book_detail', args=[self.numberless.pk])
        self.assertIn(link, body)
        row = body[body.index(link):]
        row = row[:row.index('</a>')]
        self.assertIn('<span class="audit-stamp">بلا رقم</span>', row)
        self.assertIn('كتابٌ بلا رقمٍ بعد', row)

    def test_times_and_dates_are_isolated_ltr(self):
        body = self.page()
        local = timezone.localtime(BookHistory.objects.filter(book=self.numbered).first().created_at)
        # داخل الجدول وحده: حاشيةُ «السجل يبدأ من» تحمل الوقتَ نفسَه (أقدمُ صفّ) فتُخفي سقوطَ العزل
        table = body[body.index('<table class="audit-table'):body.index('</table>')]
        self.assertIn('<th scope="row" class="audit-c-when"><time dir="ltr" datetime="%s">'
                      % local.isoformat(), table)
        self.assertEqual(table.count('<th scope="row" class="audit-c-when"><time dir="ltr" datetime="'), 3)
        self.assertIn('<time class="audit-day-date" dir="ltr" datetime="%s">%s</time>'
                      % (local.strftime('%Y-%m-%d'), local.strftime('%d/%m/%Y')), body)
        self.assertIn('<span class="audit-stamp"><bdi dir="ltr">2433</bdi></span>', body)
        self.assertIn('السجل يبدأ من <time dir="ltr"', body)

    def test_a_restricted_row_is_stubbed_without_a_link(self):
        body = self.page()
        self.assertNotIn('مناقصةٌ سرّيّة', body)
        self.assertNotIn('href="%s"' % reverse('book_detail', args=[self.secret.pk]), body)
        cell = re.search(r'<span class="audit-book is-restricted">.*?</td>', body, re.S)
        self.assertIsNotNone(cell)
        self.assertIn(STUB_TITLE, cell.group(0))
        self.assertIn('<bdi dir="ltr">2437</bdi>', cell.group(0))
        self.assertIn('.audit-book.is-restricted .audit-book-title {\n  color: var(--lx-secret);', _read(SHEET))

    def test_rows_are_grouped_by_day_under_a_sorted_header(self):
        body = self.page()
        table = body[body.index('<table class="audit-table'):body.index('</table>')]
        self.assertIn('<th scope="col" class="audit-c-when" aria-sort="descending">الوقت</th>', table)
        self.assertIn('<th scope="rowgroup" colspan="6">', table)
        self.assertIn('<span class="audit-today">اليوم</span>', table)
        self.assertEqual(table.count('<tbody>'), 1)        # الصفوفُ الثلاثة كُتبت اليوم: يومٌ واحد
        self.assertEqual(table.count('<tr class="audit-row">'), 3)

    def test_the_reset_appears_only_with_a_filter_and_the_empty_state_offers_a_way_out(self):
        self.assertNotIn('مسح التصفية', self.page())
        body = self.page(tab='books', actor='لا أحد')
        self.assertIn('<p class="audit-empty-title">لا حركات مطابقة</p>', body)
        empty = body[body.index('class="audit-empty"'):]
        self.assertIn('href="?tab=books"', empty)
        self.assertIn('مسح التصفية', empty)

    def test_the_users_tab_selects_its_tab(self):
        body = self.page(tab='users')
        users = body[body.index('href="?tab=users"') - 160:body.index('href="?tab=users"')]
        self.assertIn('aria-selected="true"', users)
        self.assertIn('<th scope="col" class="audit-c-ip">عنوان IP</th>', body)
