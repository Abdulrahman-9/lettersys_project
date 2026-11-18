"""حرّاسُ الصفحات المستقلّة على الهويّة (11-15، الخطوة ① بعد جولة الألوان).

١. **التقريران المطبوعان داخل إطار البرنامج** (كانا صفحتين قائمتين بذاتهما بخطٍّ وألوانٍ غير الهويّة):
   صفحتان منقولتان، والورقةُ جزيرةٌ فاتحة بلغة ورقة الدفتر، والطباعةُ تُخرجها وحدَها،
   والرابطُ الأمّ في الشريط نشطٌ عليهما.
٢. **لا نصَّ دون التباين على الورقة**: الرماديّ #9aa5b1 (2.5:1) غاب، ولا تعبئةَ تُجبر الطابعةَ على الحبر.
٣. **الطباعةُ التلقائيّة تنتظر الخطّ**: كانت بعد 350ms فتخرج الورقةُ بخطٍّ احتياطيّ.
٤. **صفحةُ التحقّق العامّة** تبقى بلا إطار، لكنّها على الرموز والوضعُ من كاتبه الوحيد.
٥. **لوحةُ الإدارة المستقلّة** بلا لوحها الدافئ القديم — نقلُها ببنيتها ووضعُها الداكن في مرحلة عائلة الإدارة.
"""
import re
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core.models import Book, Entity

ROOT = settings.BASE_DIR


def _read(rel):
    return (ROOT / rel).read_text(encoding='utf-8')


def _style_of(rel):
    src = _read(rel)
    return src[src.index('<style>'):src.index('</style>')]


class ReportPagesTests(TestCase):

    def setUp(self):
        self.admin = User.objects.create_superuser('stand_admin', 's@x.co', 'pw-stand-1111')
        self.client.force_login(self.admin)
        self.entity = Entity.objects.create(name='جهةُ التقرير')
        self.book = Book.objects.create(kind='outgoing_external', title='كتابُ الورقة', our_number='7701',
                                        created_by=self.admin)
        self.book.receiving_entities.add(self.entity)

    def _pages(self):
        return (('book_report', self.client.get(reverse('book_report', args=[self.book.pk]))),
                ('dossier_report', self.client.get(reverse('dossier_report', args=[self.entity.pk]))))

    def test_the_reports_live_in_the_frame_with_a_light_sheet(self):
        for name, resp in self._pages():
            with self.subTest(page=name):
                html = resp.content.decode('utf-8')
                self.assertEqual(resp.status_code, 200)
                self.assertIn('<html lang="ar" dir="rtl" data-lx-page="v2">', html)
                self.assertIn('class="app-shell"', html)
                self.assertRegex(html, r'<article class="sheet[^"]*" id="report-sheet" tabindex="-1" data-bs-theme="light"')
                # الطباعةُ تُخفي الإطار — من _sheet_style المشترك مع الدفتر
                self.assertIn('.app-topbar, .app-sidebar, .skip-link, .toast-container { display:none !important; }', html)
                self.assertIn('css/desk.css?v=', html)

    def test_the_parent_link_is_active_on_each_report(self):
        for name, resp in self._pages():
            label = 'كلّ الكتب' if name == 'book_report' else 'الأضابير'
            with self.subTest(page=name):
                html = resp.content.decode('utf-8')
                self.assertRegex(html, r'(?s)<a class="[^"]*\b(on|active)\b[^"]*"[^>]*>(?:(?!</a>).)*' + label)

    def test_the_book_report_keeps_its_numbered_sections_as_text(self):
        html = self._pages()[0][1].content.decode('utf-8')
        self.assertIn('① هوية الكتاب', html)
        self.assertIn('③ مسار الكتاب', html)
        self.assertIn('⑧ سجلّ', html)

    def test_the_dossier_sheet_names_the_configured_section_and_unit(self):
        from core.models import EmailSettings
        cfg = EmailSettings.get()
        cfg.org_section, cfg.org_unit = 'قسمُ الورقة', 'وحدةُ الورقة'
        cfg.save()
        html = self._pages()[1][1].content.decode('utf-8')
        self.assertIn('قسمُ الورقة — وحدةُ الورقة', html)

    def test_the_dossier_report_filters_itself(self):
        """طلبُ المالك 11-15: «تقرير الإضبارة ليس فيه تصفية» — شريطٌ فوق الورقة بخيارات الإضبارة، يحفظ المختار."""
        resp = self.client.get(reverse('dossier_report', args=[self.entity.pk]),
                               {'followup': 'archived', 'q': 'الورقة'})
        html = resp.content.decode('utf-8')
        self.assertIn('aria-label="تصفية التقرير"', html)
        for name in ('q', 'document_type', 'date_from', 'date_to', 'period', 'followup', 'secret_level', 'sort'):
            with self.subTest(field=name):
                self.assertRegex(html, r'<(input|select)[^>]*name="%s"' % name)
        self.assertRegex(html, r'<option value="archived" selected>')
        self.assertIn('value="الورقة"', html)
        self.assertIn('مسح التصفية', html)
        # بطاقةُ الكتاب المفرد بلا شريط
        single = self.client.get(reverse('dossier_report', args=[self.entity.pk]), {'book_id': self.book.pk})
        self.assertNotIn('aria-label="تصفية التقرير"', single.content.decode('utf-8'))

    def test_a_dossier_without_section_says_what_the_paper_is(self):
        html = self._pages()[1][1].content.decode('utf-8')
        self.assertIn('تقرير أرشيفي للمراسلات', html)


class ReportSourceTests(SimpleTestCase):

    def test_no_low_contrast_grey_and_no_forced_ink(self):
        for rel in ('templates/core/book_report.html', 'templates/core/dossier_report.html'):
            with self.subTest(page=rel):
                css = _style_of(rel)
                for grey in ('#9aa5b1', '#94a3b8', '#64748b'):
                    self.assertNotIn(grey, css)
                self.assertNotRegex(css, r'\*\s*\{[^}]*print-color-adjust')
                self.assertNotIn('Segoe UI', css)

    def test_the_report_classes_do_not_collide_with_the_frame(self):
        # داخل الإطار: Bootstrap و_sheet_style يملكان .badge .empty .toolbar .grid — للتقرير بادئتُه
        css = _style_of('templates/core/book_report.html')
        for generic in ('.badge', '.toolbar', '.grid', '.empty', '.section'):
            self.assertNotRegex(css, re.escape(generic) + r'\b(?![-\w])')

    def test_auto_print_waits_for_the_font(self):
        for rel in ('templates/core/book_report.html', 'templates/core/dossier_report.html'):
            with self.subTest(page=rel):
                src = _read(rel)
                self.assertIn('document.fonts.ready', src)
                self.assertNotIn('setTimeout(function(){ window.print(); }, 350)', src)


class VerifyPageTests(TestCase):

    def test_the_public_page_is_on_the_tokens_with_one_mode_writer(self):
        html = self.client.get(reverse('verify_signature', args=['nosuchtoken'])).content.decode('utf-8')
        self.assertIn('<html lang="ar" dir="rtl" data-lx-page="v2">', html)
        self.assertNotIn('class="app-shell"', html)
        writer = html.index("setAttribute('data-bs-theme'")
        self.assertLess(writer, html.index('<link'))
        self.assertIn('css/theme.css?v=', html)
        self.assertEqual(html.count("setAttribute('data-bs-theme', theme)"), 1)

    def test_the_old_warm_palette_is_gone(self):
        css = _style_of('templates/core/signature_verify.html')
        for warm in ('#fff8ee', '#fde5cc', '#9c7a63', '#6f4631', '#362014'):
            self.assertNotIn(warm, css)

    def test_the_page_names_the_company(self):
        with patch('core.branding.org_name', return_value='مؤسّسةُ التحقّق'):
            html = self.client.get(reverse('verify_signature', args=['nosuchtoken'])).content.decode('utf-8')
        self.assertIn('مؤسّسةُ التحقّق', html)


class AdminPanelPaletteTests(SimpleTestCase):

    def test_the_warm_palette_left_the_standalone_panel(self):
        src = _read('templates/core/admin_panel.html')
        for warm in ('#2b170d', '#b45309', '#f3f0eb', '#7c6656', '#fffaf3', '#fffdfa', '#fcf9f4', '#fcd34d',
                     '#dc2626', 'rgba(30,15,5', 'rgba(20,10,0'):
            with self.subTest(colour=warm):
                self.assertNotIn(warm, src)
        root = src[src.index(':root{'):]
        root = root[:root.index('}')]
        for name in ('--mute', '--amber', '--bg', '--line', '--danger'):
            with self.subTest(token=name):
                self.assertRegex(root, re.escape(name) + r':var\(--lx-')
