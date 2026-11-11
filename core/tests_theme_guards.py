"""حرّاسُ الهويّة الموحّدة والوضع الداكن (قرارُ المالك 2026-11-11، مراجعةُ فيبل).

١. **كاتبٌ واحدٌ للوضع**: سكربتُ الرأس في base.html وحده يكتب `data-bs-theme`؛
   theme.css لا يقرأ إعدادَ الجهاز بنفسه، ولا يبقى `DarkMode` القديم الذي كان
   يكتب `data-theme` بعد الرسم فيمحو الاختيار.
٢. **لا صفحةَ نصفَ داكنة**: السكربتُ لا يعمل إلّا في صفحةٍ تعلن `data-lx-page="v2"`،
   وتطبيقُ ألوان Bootstrap على الرموز محصورٌ في هذا النطاق — فتبقى الصفحاتُ
   غيرُ المنقولة على حالها حتّى يأتي دورُها.
٣. **لا وميض**: السكربتُ يسبق أوّل ورقة أنماط.
"""
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

ROOT = Path(settings.BASE_DIR)


def _read(rel):
    return (ROOT / rel).read_text(encoding='utf-8')


def _head_script(base):
    head = base[:base.index('</head>')]
    m = re.search(r'<script>(.*?)</script>', head, re.S)
    return head, m


class ThemeSourceGuardsTests(SimpleTestCase):

    def test_one_writer_no_device_branch_in_the_stylesheet(self):
        self.assertNotIn('prefers-color-scheme', _read('static/css/theme.css'))

    def test_the_legacy_dark_mode_is_gone(self):
        self.assertNotIn('DarkMode', _read('static/app.js'))
        self.assertNotIn('[data-theme="dark"]', _read('static/app.css'))

    def test_the_head_script_runs_before_any_stylesheet(self):
        base = _read('templates/base.html')
        head, m = _head_script(base)
        self.assertIsNotNone(m, 'سكربتُ الوضع غائبٌ عن الرأس')
        first_link = re.search(r'<link\s', head)
        self.assertLess(m.start(), first_link.start(), 'السكربتُ بعد أوّل ورقة أنماط ⟵ وميض')

    def test_the_head_script_only_touches_migrated_pages(self):
        _, m = _head_script(_read('templates/base.html'))
        script = m.group(1)
        self.assertIn("getAttribute('data-lx-page') !== 'v2'", script)
        self.assertIn("setAttribute('data-bs-theme'", script)
        self.assertIn("localStorage.getItem('lx-theme')", script)
        self.assertIn('beforeprint', script)

    def test_bootstrap_takes_the_tokens_only_inside_the_v2_scope(self):
        css = _read('static/css/theme.css')
        root_block = css[css.index(':root {'):css.index('}', css.index(':root {'))]
        self.assertNotIn('--bs-', root_block)
        scoped = css[css.index('[data-lx-page="v2"] {'):]
        self.assertIn('--bs-primary: var(--lx-pri)', scoped)

    def test_the_html_tag_carries_the_page_block(self):
        self.assertIn('<html lang="ar" dir="rtl"{% block html_attrs %}{% endblock %}>', _read('templates/base.html'))


class ThemePagesTests(TestCase):

    def test_the_login_page_is_migrated_with_its_toggle(self):
        html = self.client.get(reverse('login')).content.decode('utf-8')
        self.assertIn('<html lang="ar" dir="rtl" data-lx-page="v2">', html)
        self.assertRegex(html, r'<button[^>]*data-theme-toggle[^>]*aria-pressed="false"')
        self.assertIn('id="loginEye"', html)

    def test_a_page_not_yet_migrated_stays_out_of_the_dark(self):
        user = get_user_model().objects.create_user('theme_clerk', password='pw-theme-1111')
        self.client.force_login(user)
        html = self.client.get(reverse('dashboard')).content.decode('utf-8')
        self.assertIn('<html lang="ar" dir="rtl">', html)
        self.assertNotIn('data-lx-page', html.split('<head>')[0])
        self.assertNotIn('data-theme-toggle', html)
