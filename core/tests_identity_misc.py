"""حرّاسُ وحدة «misc» على الهويّة v2 (11-19): تغييرُ كلمة المرور · صفحةُ الانقطاع · 403 · 404 · 500.

١. الانضمامُ (data-lx-page="v2") في الصفحات الخمس، والألوانُ من الرموز وحدَها، ولا حواراتٍ أصليّة.
٢. صفحةُ الانقطاع قائمةٌ بذاتها: لا تطلب إلّا ما في قشرة عامل الخدمة بعنوانه حرفيّاً، ولا تحمل شيئاً
   من المستخدم، ولا تعيد تحميلَ نفسِها في حلقةٍ حين تُفتح بعنوانها والخادمُ حيّ (مقيسٌ قبلها 11-19).
٣. 500 تُرسم بلا سياقٍ ولا طلب (كما يرسمها server_error).
٤. 403 تقول لماذا؛ و404 تذكر العنوان، و«سلّة المهملات» لمن تُفتح له وحدَه.
٥. كلمةُ المرور: تسمياتٌ ظاهرة وautocomplete وزرُّ إظهارٍ لكلّ حقل، والخطأُ تحت حقله ويأخذ التركيز،
   والتغييرُ الإجباريّ يعرض الخروجَ لا «إلغاءً» يعيد إلى الصفحة نفسِها.
"""
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.template import loader
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from core.testing import as_writer

ROOT = Path(settings.BASE_DIR)
V2 = '<html lang="ar" dir="rtl" data-lx-page="v2">'
COMMENT = re.compile(r'/\*.*?\*/', re.S)
OWN_CSS = ('static/css/misc_pages.css', 'templates/_misc_status_style.html', 'templates/offline.html')
OWN_SOURCES = OWN_CSS + ('static/js/misc_pages.js', 'templates/500.html', 'templates/403.html',
                         'templates/404.html', 'templates/core/_error_page.html',
                         'templates/core/password_change.html')


def _read(rel):
    return (ROOT / rel).read_text(encoding='utf-8')


def _styles(rel):
    src = _read(rel)
    if not rel.endswith('.css'):
        src = ' '.join(re.findall(r'<style>(.*?)</style>', src, re.S))
    return COMMENT.sub(' ', src)


class MiscSourceGuards(SimpleTestCase):

    def test_own_styles_speak_tokens_only(self):
        for rel in OWN_CSS:
            with self.subTest(rel=rel):
                css = _styles(rel)
                self.assertGreater(len(css), 200)
                self.assertLessEqual({h.lower() for h in re.findall(r'#[0-9a-fA-F]{3,8}\b', css)}, {'#fff'})
                self.assertNotRegex(css, r'\b(?:rgba?|hsla?)\(\s*\d')   # rgba(var(--lx-pri-rgb), …) وحدَها
                self.assertNotIn('[data-theme="dark"]', css)

    def test_no_native_dialogs_or_inline_colours(self):
        for rel in OWN_SOURCES:
            with self.subTest(rel=rel):
                src = _read(rel)
                self.assertNotRegex(src, r'(?<![\w.-])(?:window\.)?(?:confirm|alert)\s*\(')
                self.assertNotRegex(src, r'style="[^"]*color')

    def test_the_offline_page_stands_alone_on_the_workers_shell(self):
        src = _read('templates/offline.html')
        sw = _read('static/service-worker.js')
        start = sw.index('SHELL_URLS')
        shell = set(re.findall(r"'(/[^']+)'", sw[start:sw.index('];', start)]))
        self.assertIn('/offline.html', shell)
        self.assertNotIn('{% extends', src)
        self.assertIn(V2, src)
        # الأيقونةُ data:, (لا طلبَ أصلاً — كان المتصفّحُ يطلب ‎/favicon.ico‎ فيُسجّل 404)
        assets = re.findall(r'<link rel="stylesheet" href="([^"]+)"|<script\b[^>]*\bsrc="([^"]+)"', src)
        assets = [a or b for a, b in assets]
        self.assertIn('<link rel="icon" href="data:,">', src)
        self.assertTrue(assets)
        for url in assets:
            self.assertIn(url, shell, 'لا يصل من مخبأ عامل الخدمة بلا شبكة')
        self.assertNotIn('class="bi ', src)   # خطُّ الأيقونات يُطلب بـ?hash فلا يطابق المخبأ: SVG مضمَّن
        head = src[:src.index('</head>')]
        self.assertLess(head.index('{% include "_theme_head.html" %}'), head.index('<link rel="stylesheet"'))


class MiscPagesRenderTests(TestCase):

    def test_the_offline_page_carries_nothing_of_the_user_and_never_reloads_itself(self):
        user = User.objects.create_user('misc_off', password='pw-misc-off-11')
        self.client.force_login(user)
        html = self.client.get('/offline.html').content.decode('utf-8')
        self.assertIn(V2, html)
        self.assertNotIn('misc_off', html)
        self.assertNotIn('app-sidebar', html)
        self.assertIn("var ownAddress = window.location.pathname === '/offline.html';", html)
        self.assertIn('if (!ownAddress) {', html)

    def test_500_renders_without_any_context(self):
        html = loader.get_template('500.html').render()
        self.assertIn(V2, html)
        self.assertIn("setAttribute('data-bs-theme'", html)
        self.assertIn('misc-stamp is-late', html)
        src = _read('templates/500.html')
        for tag in ('{% extends', '{% url', '{% static', '{% load', '{{'):
            with self.subTest(tag=tag):
                self.assertNotIn(tag, src)


@override_settings(DEBUG=False)
class ErrorPagesTests(TestCase):

    def test_403_is_v2_and_says_why(self):
        self.client.force_login(as_writer(User.objects.create_user('misc403', password='pw-misc-403-1')))
        r = self.client.get(reverse('settings_hub'))
        self.assertEqual(r.status_code, 403)
        html = r.content.decode('utf-8')
        self.assertIn(V2, html)
        self.assertRegex(html, r'class="misc-status-reason".*هذه الصفحةُ لإدارة النظام\.')

    def test_404_names_the_address_and_offers_the_trash_only_to_who_opens_it(self):
        from core.scoping import can_open_trash

        plain = User.objects.create_user('misc404', password='pw-misc-404-1')
        boss = User.objects.create_superuser('misc404b', 'm@x.co', 'pw-misc-404-2')
        self.assertFalse(can_open_trash(plain))
        self.assertTrue(can_open_trash(boss))
        for user, shown in ((plain, False), (boss, True)):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                r = self.client.get('/books/misc-no-such-page/')
                self.assertEqual(r.status_code, 404)
                html = r.content.decode('utf-8')
                self.assertIn(V2, html)
                self.assertIn('<bdi dir="ltr">/books/misc-no-such-page/</bdi>', html)
                self.assertEqual(reverse('trash_list') + '"><i class="bi bi-trash3"' in html, shown)


class PasswordPageTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('misc_pw', password='old-pass-123456')
        self.client.force_login(self.user)

    def test_the_form_is_v2_with_labels_autocomplete_and_an_eye_per_field(self):
        html = self.client.get(reverse('password_change')).content.decode('utf-8')
        self.assertIn(V2, html)
        self.assertIn('css/misc_pages.css?v=20261119-pages', html)
        for name, auto in (('old_password', 'current-password'), ('new_password1', 'new-password'),
                           ('new_password2', 'new-password')):
            with self.subTest(name=name):
                self.assertIn('<label class="misc-label" for="id_%s">' % name, html)
                self.assertRegex(html, r'<input[^>]*name="%s"[^>]*autocomplete="%s"' % (name, auto))
                self.assertIn('class="misc-eye" aria-controls="id_%s" aria-pressed="false"' % name, html)
        self.assertNotRegex(html, r'onpaste|oncopy')   # اللصقُ ومديرو كلمات المرور مسموحون (WCAG 3.3.8)

    def test_an_error_sits_under_its_field_and_takes_the_focus(self):
        r = self.client.post(reverse('password_change'),
                             {'old_password': 'wrong-pass-1', 'new_password1': 'xx', 'new_password2': 'xx'})
        html = r.content.decode('utf-8')
        old = re.search(r'<input[^>]*name="old_password"[^>]*>', html).group(0)
        self.assertIn('aria-invalid="true"', old)
        self.assertIn('errOld', old)
        self.assertIn(' autofocus', old)
        self.assertIn('id="errOld"', html)
        self.assertEqual(html.count(' autofocus'), 1)

    def test_a_forced_change_offers_logout_not_a_cancel_that_loops(self):
        from core.models import UserProfile

        profile, _ = UserProfile.objects.get_or_create(user=self.user)
        profile.must_change_password = True
        profile.save(update_fields=['must_change_password'])
        html = self.client.get(reverse('password_change')).content.decode('utf-8')
        self.assertIn('class="misc-note"', html)
        self.assertNotIn(' data-back>', html)
        self.assertIn('action="%s" class="misc-later"' % reverse('logout'), html)
