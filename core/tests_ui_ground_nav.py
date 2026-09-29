# -*- coding: utf-8 -*-
"""حرّاسُ الدفعة 3 — الأرضيّةُ الهادئة لكلّ الصفحات، ودرجُ التنقّل على الهاتف.

قرارُ المالك (2026-09-29): الأرضيّةُ الحجريّة الهادئة التي كانت للّوحة وحدها
(`body.is-db`) صارت أرضيّةَ كلّ صفحة، والشريطُ الجانبيّ على الهاتف صار درجاً
(Bootstrap `offcanvas-xl` المحلّيّ) يُفتح بزرّ «القائمة» فيأتي المحتوى أوّلاً.

الحرّاسُ نصّيّةٌ على CSS عمداً (لا محرّكَ متصفّحٍ في الحزمة)، لكنّها تقرأ الملفَّ
**قواعدَ داخل وسائطها** لا أرقامَ أسطر: الحارسُ القديم كان يثبّت `app.css` بفهرس
السطر 63 فيكسره أيُّ سطرٍ يُضاف فوقه.
"""

import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core.dashboard_sections import sections_for
from core.models import Department, UserProfile
from core.roles import CONTROLLER_GROUP_NAME

ROOT = Path(settings.BASE_DIR)
XL_UP = '@media (min-width: 1200px)'
BELOW_XL = '@media (max-width: 1199.98px)'


def read(rel):
    return (ROOT / rel).read_text(encoding='utf-8')


def css_rules(text):
    """قواعدُ ملفّ CSS: ``[(وسائطُ مكدّسة, المحدِّد, الجسم)]`` بمطابقة الأقواس.

    الوسائطُ صفٌّ من مقدّمات ``@media`` المحيطة (فارغٌ = خارج كلّ وسائط)،
    والمسافاتُ فيها وفي المحدِّد مطويّة إلى مسافةٍ واحدة.
    """
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    out = []

    def walk(start, end, stack):
        i = start
        while i < end:
            open_ = text.find('{', i, end)
            if open_ == -1:
                return
            head = ' '.join(text[i:open_].split())
            depth, j = 1, open_ + 1
            while depth and j < end:
                depth += {'{': 1, '}': -1}.get(text[j], 0)
                j += 1
            if head.startswith('@media'):
                walk(open_ + 1, j - 1, stack + (head,))
            elif not head.startswith('@'):
                out.append((stack, head, text[open_ + 1:j - 1]))
            i = j

    walk(0, len(text), ())
    return out


def selectors(head):
    return [' '.join(s.split()) for s in head.split(',')]


class CalmGroundTests(SimpleTestCase):
    """الأرضيّةُ تصريحٌ واحد في `app.css` — لا متغيّرٌ يتسرّب ولا صنفٌ يقصرها على صفحة."""

    def test_ground_is_one_calm_declaration(self):
        app_css = read('static/app.css')
        rules = css_rules(app_css)
        light = [b for m, h, b in rules if not m and h == 'body']
        dark = [b for m, h, b in rules if not m and h == '[data-theme="dark"] body']
        self.assertEqual(len(light), 1)
        self.assertEqual(len(dark), 1)
        self.assertIn('background: #f4f2ee', light[0])
        self.assertIn('background: #1d1d1d', dark[0])
        for m, h, b in rules:
            if h in ('body', '[data-theme="dark"] body'):
                self.assertNotIn('linear-gradient', b, (m, h))
        # اللونُ في موضعين لا ثالثَ لهما: الأرضيّة، والدرجُ الذي يُفتح فوقها بلونها.
        homes = sorted((h, b.split('#f4f2ee')[0].rsplit(';', 1)[-1].split(':')[0].strip())
                       for m, h, b in rules if '#f4f2ee' in b)
        self.assertEqual(homes, [('.app-sidebar', '--bs-offcanvas-bg'), ('body', 'background')])
        self.assertEqual(app_css.count('#f4f2ee'), 2)
        self.assertEqual(app_css.count('background: #f4f2ee'), 1)

        self.assertNotIn('bg-body', read('templates/base.html'))
        self.assertNotIn('is-db', read('templates/core/dashboard.html'))
        self.assertNotIn('body.is-db', read('static/css/dashboard_roles.css'))
        self.assertNotIn('#f5f7fa', read('static/extraction_smart.css'))


class DrawerCascadeTests(SimpleTestCase):
    """تحت 1200 العمودُ درجٌ `offcanvas-xl`: قاعدةٌ عامّةٌ على `.app-sidebar` بالتخصيص
    نفسه تأتي بعد Bootstrap فتتغلّب عليه — `position: sticky` تُبقي الدرجَ في تدفّق
    الصفحة فوق المحتوى، و`transition` تمحو انزلاقه."""

    DESKTOP_ONLY = ('position: sticky', 'flex: 0 0 310px', 'max-height: calc(100vh - 104px)',
                    'transition:')

    def _sidebar_rules(self):
        return [(m, h, b) for m, h, b in css_rules(read('static/app.css'))
                if any(s == '.app-sidebar' or s.endswith(' .app-sidebar') for s in selectors(h))]

    def test_sidebar_desktop_rules_live_only_above_xl(self):
        rules = self._sidebar_rules()
        inside = [b for m, h, b in rules if m == (XL_UP,)]
        outside = [(m, h, b) for m, h, b in rules if XL_UP not in m]
        for decl in self.DESKTOP_ONLY:
            with self.subTest(decl=decl):
                self.assertTrue(any(decl in b for b in inside), decl)
                self.assertEqual([h for m, h, b in outside if decl in b], [])
        mini = [(m, h) for m, h, b in css_rules(read('static/app.css')) if '.sidebar-mini' in h]
        self.assertTrue(mini)
        self.assertEqual([h for m, h in mini if m != (XL_UP,)], [])
        self.assertNotIn('order: -1', read('static/app.css'))

    def test_extraction_hides_topbar_only_on_desktop(self):
        """سطحُ الإدخال يخفي الشريطَ العلويّ على المكتب وحده؛ تحته الشريطُ يحمل زرَّ القائمة."""
        rules = css_rules(read('static/extraction_smart.css'))
        hide = [m for m, h, b in rules
                if h == 'body.app-shell-body .app-topbar' and 'display: none !important' in b]
        self.assertEqual(hide, [(XL_UP,)])
        narrow = [m for m, h, b in rules
                  if h == 'body.app-shell-body .app-sidebar' and 'width: 200px !important' in b]
        self.assertEqual(narrow, [('@media (min-width: 1200px) and (max-width: 1366px)',)])
        sticky = [m for m, h, b in rules
                  if h == 'body.app-shell-body .app-sidebar' and 'position: sticky' in b]
        self.assertEqual(sticky, [(XL_UP,)])


class PhoneDrawerMarkupTests(TestCase):
    """الدرجُ وزرُّه في القشرة نفسها لكلّ صفحة — ولا قشرةَ في وضع التضمين."""

    def setUp(self):
        self.user = User.objects.create_user('drawer', 'd@x.co', 'pw')
        self.client.force_login(self.user)

    def test_phone_drawer_markup(self):
        html = self.client.get(reverse('dashboard')).content.decode('utf-8')

        aside = re.search(r'<aside\b[^>]*>', html).group(0)
        for attr in ('offcanvas-xl offcanvas-start', 'id="appNav"', 'tabindex="-1"',
                     'aria-labelledby="appNavTitle"'):
            self.assertIn(attr, aside)
        self.assertIn('id="appNavTitle"', html)

        header = html[html.index('<header class="app-topbar">'):html.index('</header>')]
        trigger = re.search(r'<button\b[^>]*\bapp-topbar-menu\b[^>]*>', header)
        self.assertIsNotNone(trigger, 'زرُّ «القائمة» ليس في الشريط العلويّ')
        for attr in ('data-bs-toggle="offcanvas"', 'data-bs-target="#appNav"',
                     'aria-controls="appNav"'):
            self.assertIn(attr, trigger.group(0))

        close = re.search(r'<button\b[^>]*data-bs-dismiss="offcanvas"[^>]*>', html)
        self.assertIsNotNone(close)
        self.assertRegex(close.group(0), r'aria-label="[^"]+"')
        self.assertIn('aria-label="التنقل الرئيسي"', html)
        toggle = re.search(r'<button\b[^>]*id="sidebarToggleBtn"[^>]*>', html).group(0)
        self.assertIn('d-none d-xl-inline-flex', toggle)

        embed = self.client.get(reverse('dashboard') + '?embed=1').content.decode('utf-8')
        self.assertNotIn('appNav', embed)


class QuietRowLinksTests(TestCase):
    """السطرُ الهادئ عنوانُه رابطٌ إلى `home` — فلا يتكرّر الرابطُ نفسُه أوّلَ روابطه."""

    def setUp(self):
        self.dept = Department.objects.create(name='قسم الهدوء', code='هـ.ق')
        self.clerk = User.objects.create_user('quiet_clerk', 'q@x.co', 'pw')
        UserProfile.objects.update_or_create(user=self.clerk, defaults={'department': self.dept})
        group, _ = Group.objects.get_or_create(name=CONTROLLER_GROUP_NAME)
        self.clerk.groups.add(group)

    def test_quiet_row_does_not_repeat_its_title_link(self):
        desk = {s['key']: s for s in sections_for(self.clerk)}['desk']
        self.assertIs(desk['quiet'], True)
        home = reverse('desk_board')
        self.assertEqual(desk['home'], home)
        self.assertTrue(desk['quiet_links'])
        self.assertTrue(all(l in desk['links'] for l in desk['quiet_links']))
        self.assertNotIn(home, [l['href'] for l in desk['quiet_links']])

        self.client.force_login(self.clerk)
        html = self.client.get(reverse('dashboard')).content.decode('utf-8')
        quiet = html[html.index('class="db-card db-quiet"'):]
        li = re.search(r'<li>(?:(?!</li>).)*id="db-h-desk"(?:(?!</li>).)*</li>', quiet, re.S)
        self.assertIsNotNone(li, 'قسمُ الطاولة ليس سطراً هادئاً')
        self.assertEqual(li.group(0).count('href="%s"' % home), 1)


class DashboardCarryOverTests(SimpleTestCase):
    """بقايا مراجعة المرحلة 2: منطقةُ نقرٍ ميّتة، ورابطُ «تحديث» بأزرق Bootstrap، والتحيّةُ في الليليّ."""

    def test_dashboard_carry_over_rules(self):
        css = read('static/css/dashboard_roles.css')
        self.assertIn('.db-sub{pointer-events:none', css)
        self.assertIn('.db-sub a{pointer-events:auto', css)
        self.assertRegex(css, r'\.db-asof a\{[^}]*color:var\(--amber\)')
        self.assertIn('[data-theme="dark"] .db-page{--ink:', css)
