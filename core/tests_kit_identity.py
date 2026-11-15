"""حرّاسُ طبقة المكوّنات — الجزء 1 (11-15): الحوارات على الهويّة، لوحُ النشط ينزلق بين الصفحات، لوحةُ المكوّنات.

١. **نوافذُ الصفحات المنقولة وحدها** تُلبَس الهويّة: كلُّ محدِّدٍ يمسّ ‎.modal‎ في components.css تحت
   ‎html[data-lx-page="v2"]‎ — الصفحاتُ غيرُ المنقولة لا تتغيّر. والحركةُ لمن لم يطلب تقليلها وحده.
٢. **حواريّةُ التأكيد الواحدة** تُعلن معناها قبل نصّها: بلاطةٌ حمراءُ بمثلّث للهدّام، وتركوازيّةٌ باستفهامٍ للآمن.
٣. **لوحُ الصفحة الحاليّة** يحمل اسمَ انتقالٍ واحداً فينزلق بين الصفحات — ويُرفع أثناء تبديل الوضع.
٤. **لوحةُ المكوّنات** لمدير النظام وحده.
٥. «طاولتي» تقول «الوحدة».
"""
import re

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core.tests_list_identity import _read


class KitSourceTests(SimpleTestCase):

    def test_the_layer_loads_after_app_css(self):
        base = _read('templates/base.html')
        self.assertLess(base.index("static 'app.css'"), base.index("static 'css/components.css'"))
        self.assertRegex(base, r"static 'css/components\.css' %\}\?v=\d{8}")

    def test_only_migrated_pages_wear_the_dialog_skin(self):
        # التعليقاتُ وحدها تُنزع: _strip يُفرغ النصوصَ المقتبسة فيصير "v2" فارغاً
        css = re.sub(r'/\*.*?\*/', '', _read('static/css/components.css'), flags=re.S)
        heads = [h.strip() for h in re.findall(r'([^{}]+)\{', css) if '.modal' in h]
        self.assertTrue(heads)
        for head in heads:
            for sel in head.split(','):
                with self.subTest(sel=sel.strip()):
                    self.assertTrue(sel.strip().startswith('html[data-lx-page="v2"]'))

    def test_the_backdrop_tint_is_declared_where_bootstrap_reads_it(self):
        css = _read('static/css/components.css')
        rule = css[css.index('html[data-lx-page="v2"] .modal-backdrop {'):]
        self.assertIn('--bs-backdrop-bg: #04211e;', rule[:rule.index('}')])
        self.assertNotRegex(css, r'html\[data-lx-page="v2"\] \{[^}]*--bs-backdrop')

    def test_the_dialog_does_not_clip_its_popups(self):
        css = _read('static/css/components.css')
        rule = css[css.index('html[data-lx-page="v2"] .modal-content {'):]
        self.assertNotIn('overflow', rule[:rule.index('}')])

    def test_static_dialogs_keep_their_bounce(self):
        css = _read('static/css/components.css')
        motion = css[css.index('@media (prefers-reduced-motion: no-preference) {'):]
        self.assertLess(motion.index('.modal.show .modal-dialog'), motion.index('.modal.modal-static .modal-dialog { transform: scale(1.02); }'))

    def test_the_slab_stays_home_when_scrolled_out_of_sight(self):
        js = _read('static/js/shell.js')
        self.assertIn("window.addEventListener('pageswap'", js)
        self.assertIn("now.style.viewTransitionName = 'none'", js)

    def test_dialog_motion_is_for_those_who_did_not_ask_to_reduce_it(self):
        css = _read('static/css/components.css')
        motion = css[css.index('@media (prefers-reduced-motion: no-preference) {'):]
        self.assertIn('.modal.show .modal-dialog', motion)
        self.assertEqual(css.count('transition:'), motion.count('transition:'))

    def test_the_confirm_dialog_says_its_meaning_first(self):
        src = _read('static/app.js')
        builder = src[src.index('function createConfirmModal'):]
        builder = builder[:builder.index('\n}\n')]
        self.assertIn('<span class="lx-dialog-ico" aria-hidden="true">', builder)
        self.assertIn("ico.classList.toggle('is-danger', danger);", builder)
        self.assertIn("danger ? 'bi-exclamation-triangle' : 'bi-question-circle'", builder)
        self.assertIn(".lx-dialog-title').textContent = opts.title", builder)

    def test_the_active_slab_moves_between_pages(self):
        css = _read('static/css/theme.css')
        self.assertIn('.app-sidebar-link.active,\n.sa-nav a.on { view-transition-name: lx-nav-active; }', css)
        self.assertIn('html.lx-flipping .sa-nav a.on { view-transition-name: none; }', css)

    def test_my_desk_speaks_of_the_unit(self):
        self.assertIn('{% if my_desk %}الوحدة{% else %}القسم{% endif %}', _read('templates/core/desk_board.html'))


class KitPageTests(TestCase):

    def test_the_components_page_is_for_the_system_admin_alone(self):
        self.client.force_login(User.objects.create_user('kit-plain', password='pw-kit-1115'))
        self.assertEqual(self.client.get(reverse('system_ui_kit')).status_code, 403)
        self.client.force_login(User.objects.create_superuser('kit-admin', password='pw-kit-1115'))
        r = self.client.get(reverse('system_ui_kit'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'data-lx-page="v2"')
        self.assertContains(r, 'data-kit-toast="', count=5)
        self.assertContains(r, 'data-kit-confirm="', count=2)
        self.assertContains(r, 'data-confirm=')
