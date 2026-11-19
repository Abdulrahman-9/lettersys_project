# -*- coding: utf-8 -*-
"""«التنبيهات» على الهويّة الموحّدة v2 (2026‑11‑19) — حرّاسُ العرض.

الصفحةُ منقولة (الوضعان من رموز theme.css)، وورقتُها رموزٌ وحدَها، ولا حوارَ أصليّاً، والسلوكُ كما كان
(النماذجُ نفسُها وأهدافُها وحقلُ ``next``)، والعيوبُ التي أُصلحت في النقل لا تعود:
وقتٌ مطلقٌ ظاهرٌ لا في ``title`` وحدَه · «فتح» موصوفٌ بعنوان تنبيهه · لا خانةَ أفعالٍ فارغة ·
حلقةُ تركيزٍ بلون الفعل · أهدافُ 44px على الهاتف · فراغٌ بعنوانٍ وطريقٍ للخارج.
"""
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Notification

ROOT = Path(settings.BASE_DIR)
TEMPLATE = 'templates/core/notifications.html'
SHEET = 'static/css/notifications.css'


def _read(rel):
    return (ROOT / rel).read_text(encoding='utf-8')


def _sheet_without_comments():
    return re.sub(r'/\*.*?\*/', '', _read(SHEET), flags=re.S)


def _phone_block(css):
    start = css.index('@media (max-width: 575.98px)')
    depth, i = 0, css.index('{', start)
    for j in range(i, len(css)):
        depth += {'{': 1, '}': -1}.get(css[j], 0)
        if depth == 0:
            return css[i:j]
    raise AssertionError('phone block not closed')


class NotificationsSourceGuards(SimpleTestCase):

    def test_the_sheet_is_tokens_only(self):
        css = _sheet_without_comments()
        hexes = re.findall(r'#[0-9a-fA-F]{3,8}\b', css)
        # الاستثناءُ الوحيد (BRIEF §2.2): حبرٌ أبيض على التركواز العميق في بلاطة الرأس
        self.assertEqual(hexes, ['#fff'], 'لونٌ صريحٌ في ورقة التنبيهات: %s' % hexes)
        self.assertIn('background: linear-gradient(135deg, var(--lx-hero-a), var(--lx-hero-b));', css)
        self.assertNotRegex(css, r'\b(?:rgba?|hsla?)\(', 'rgb()/hsl() صريحٌ بدل الرموز')
        self.assertNotRegex(css, r':\s*(?:white|black|red|green|blue|gray|grey|orange|yellow)\b')
        self.assertNotIn('data-theme', css, 'data-theme صفةٌ ميتةٌ للوضع القديم')

    def test_the_template_links_the_sheet_with_this_batch_version(self):
        self.assertIn("{% static 'css/notifications.css' %}?v=20261119-pages", _read(TEMPLATE))

    def test_no_native_dialog_and_no_inline_colour_in_the_template(self):
        tpl = _read(TEMPLATE)
        self.assertNotRegex(tpl, r'\b(?:confirm|alert|prompt)\s*\(')
        self.assertNotIn('onclick=', tpl)
        self.assertNotRegex(tpl, r'style="[^"]*(?:color|background)')

    def test_the_focus_ring_is_the_action_colour(self):
        # حلقةُ Bootstrap ربعُ اللون (‎rgba(pri, .25)‎) لا تبلغ 3:1 على السطح
        self.assertRegex(_sheet_without_comments(),
                         r'\.nt-page :is\(a, button\):focus-visible \{\s*outline: 2px solid var\(--lx-pri\);')

    def test_the_legacy_ripple_does_not_wash_the_hover(self):
        # موجةُ app.css البيضاء فوق «فتح» عند المرور: أبيضُ على تركوازٍ مُبيَّض ~3.1:1
        self.assertIn('.nt-page .btn::before { content: none; }', _sheet_without_comments())

    def test_buttons_name_their_transitions_and_honour_reduced_motion(self):
        # ‏transition: all‏ في app.css كان يحرّك حلقةَ التركيز نفسَها فتبدأ باهتة
        css = _sheet_without_comments()
        self.assertNotIn('transition: all', css)
        self.assertRegex(css, r'\.nt-page \.btn \{[^}]*transition: color var\(--lx-dur-1\) ease, background-color')
        reduce = css[css.index('@media (prefers-reduced-motion: reduce)'):]
        self.assertRegex(reduce, r'^@media \(prefers-reduced-motion: reduce\) \{\s*\.nt-page \.btn \{ transition: none; \}')

    def test_phone_targets_are_44px(self):
        phone = _phone_block(_sheet_without_comments())
        self.assertRegex(phone, r'\.nt-acts \.btn,[^{]*\{\s*min-height: 44px;')
        self.assertIn('.nt-mark { width: 44px; }', phone)
        self.assertIn('grid-template-areas: "icon body" ". acts";', phone)


class NotificationsPageGuards(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user('nt_guard', password='pw-nt-guard-1111')
        self.client.force_login(self.user)

    def _page(self, **query):
        return self.client.get(reverse('notifications'), query).content.decode('utf-8')

    def test_the_page_opts_into_the_identity(self):
        self.assertIn('<html lang="ar" dir="rtl" data-lx-page="v2">', self._page())

    def test_actions_keep_their_forms_and_open_is_described_by_its_title(self):
        unread = Notification.objects.create(user=self.user, title='أُحيل إليك كتاب', message='م', link_url='/books/7/')
        read = Notification.objects.create(user=self.user, title='قديم', message='م', link_url='/books/8/', is_read=True)
        html = self._page()
        mark = reverse('notification_mark_read', args=[unread.pk])
        # السلوكُ كما كان: «فتح» غيرِ المقروء نموذجٌ يعلّمه ويتبع next الداخليّ، و«تعليم الكلّ» نموذجٌ واحد
        self.assertEqual(html.count('action="%s"' % mark), 2)
        self.assertIn('<input type="hidden" name="next" value="/books/7/">', html)
        self.assertIn('action="%s"' % reverse('notification_mark_all_read'), html)
        self.assertRegex(html, r'<a class="btn btn-sm btn-outline-primary nt-open" href="/books/8/" '
                               r'aria-describedby="nt-t-%d">' % read.pk)
        # «فتح» يحمل عنوانَ تنبيهه وصفاً — لا «فتح» متشابهةٌ بلا سياقٍ لقارئ الشاشة
        self.assertIn('id="nt-t-%d"' % unread.pk, html)
        self.assertRegex(html, r'<button type="submit" class="btn btn-sm btn-outline-primary nt-open" '
                               r'aria-describedby="nt-t-%d">' % unread.pk)

    def test_the_absolute_time_is_visible_not_hover_only(self):
        n = Notification.objects.create(user=self.user, title='ت', message='م')
        stamp = timezone.localtime(n.created_at).strftime('%d/%m/%Y %H:%M')
        html = self._page()
        self.assertIn('<bdi class="nt-stamp" dir="ltr">%s</bdi>' % stamp, html)
        self.assertNotIn('title="%s"' % timezone.localtime(n.created_at).strftime('%Y/%m/%d %H:%M'), html)

    def test_a_read_notice_without_link_has_no_empty_action_cell(self):
        Notification.objects.create(user=self.user, title='ت', message='م', is_read=True)
        html = self._page()
        self.assertIn('class="nt-item p-info"', html)
        self.assertNotIn('class="nt-acts"', html)

    def test_the_pager_links_rel_and_isolates_its_numbers(self):
        Notification.objects.bulk_create([Notification(user=self.user, title='ت%d' % i, message='م') for i in range(51)])
        first = self._page()
        self.assertIn('<a class="btn btn-sm btn-outline-primary" rel="next" href="?page=2">', first)
        self.assertIn('صفحة <bdi dir="ltr">1</bdi> من <bdi dir="ltr">2</bdi>', first)
        self.assertIn('<a class="btn btn-sm btn-outline-primary" rel="prev" href="?page=1">', self._page(page=2))

    def test_the_empty_state_is_a_heading_with_a_way_out(self):
        html = self._page()
        self.assertIn('<h2 class="nt-empty-title">لا تنبيهات الآن</h2>', html)
        self.assertIn('<a class="btn btn-primary" href="%s">العودة إلى اللوحة</a>' % reverse('dashboard'), html)
        # والفراغُ يُقال مرّةً: لا «لا تنبيهات» في الرأس فوق بطاقته
        self.assertNotIn('class="nt-sub"', html)

    def test_the_status_line_counts_unread_then_all_read(self):
        n = Notification.objects.create(user=self.user, title='ت', message='م')
        self.assertRegex(self._page(), r'<strong><bdi dir="ltr">1</bdi></strong> غيرُ مقروء من <bdi dir="ltr">1</bdi>')
        Notification.objects.filter(pk=n.pk).update(is_read=True)
        self.assertIn('كلُّها مقروءة (<bdi dir="ltr">1</bdi>)', self._page())
