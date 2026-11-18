# -*- coding: utf-8 -*-
"""الدفعة 3أ (11-18): صفحةُ الأدوار على النموذج المعتمد، وطريقُها إلى قائمة الحسابات والمحرّر وبالعكس.

- المصفوفةُ في إطارٍ يتمرّر فيه رأسُها وعمودُها الأوّل ثابتَين؛ وكلُّ خانةٍ رمزٌ وكلمة.
- ما لم يُربط حارسُه ولم يُقفل في «قادمة» آخرَ الصفحة — ويبقى رجوعُه إلى المعتمد إن عُدِّل قديماً.
- عمودُ مدير النظام سطرٌ واحد.
- الدورُ رابطٌ إلى حامليه النشطين، والاستثناءُ رابطٌ إلى أصحابه (تصفيةٌ لمدير النظام وحده — فيبل 11-18).
"""
import re
from pathlib import Path

from django.test import SimpleTestCase
from django.urls import reverse

from core.models import RoleCapabilityOverride, UserCapabilityOverride
from core.scoping import CAPABILITIES, WIRED_CAPABILITIES
from core.tests_roles_page import URL, RolesPageCase

ROOT = Path(__file__).resolve().parent.parent
ACCOUNTS = reverse('system_accounts')
LATER = [key for key, capability in CAPABILITIES.items() if key not in WIRED_CAPABILITIES and not capability.locked]


def _between(body, start, end):
    return body[body.index(start):body.index(end)]


class LayoutTests(RolesPageCase):
    def page(self):
        self.client.force_login(self.admin)
        return self.client.get(URL).content.decode()

    def test_the_matrix_scrolls_in_its_own_frame_and_later_rows_wait_below_it(self):
        body = self.page()
        frame = _between(body, 'id="rmFrame"', 'id="rmLater"')
        later = _between(body, 'id="rmLater"', 'id="rmBar"')
        self.assertIn('role="region" aria-label="مصفوفة الأدوار"', body)
        self.assertTrue(LATER, 'لا صفّ «قادمة» في السجلّ — الاختبارُ لا يقيس شيئاً')
        for key in LATER:
            with self.subTest(key=key):
                self.assertIn(f'id="cap-{key}"', later)
                self.assertNotIn(f'id="cap-{key}"', frame)
        for key in CAPABILITIES:
            if key not in LATER:
                with self.subTest(key=key):
                    self.assertIn(f'id="cap-{key}"', frame)   # المقفلُ يبقى في المصفوفة ولو لم يُربط
        self.assertIn(f'قادمة: صلاحيّاتٌ لم يُربط حارسها بعد ({len(LATER)})', later)
        self.assertNotIn('<button type="submit" name="change"', later)   # تُعرض ولا تُعدَّل

    def test_every_group_with_live_rows_has_a_jump_link_and_an_anchor(self):
        body = self.page()
        jumps = re.findall(r'<a href="#grp-(\d+)">([^<]+)</a>', body)
        anchors = re.findall(r'<tr class="rm-group" id="grp-(\d+)"><th scope="rowgroup">([^<]+)</th>', body)
        self.assertEqual(jumps, anchors)
        self.assertEqual([name for _n, name in anchors],
                         ['الكتب', 'الإحالة والإنجاز', 'الطاولات', 'الرقابة', 'البريد', 'الإدارة'])

    def test_the_system_admin_column_is_one_line(self):
        body = self.page()
        self.assertNotIn('مدير النظام: يستطيع، مقفل', body)
        self.assertIn('مدير النظام يستطيع كلّ شيء، فلا عمود له هنا (حساب واحد).', body)
        self.assertEqual(body.count('<th scope="col" id="role-'), 7)

    def test_every_cell_says_its_value_in_a_word(self):
        body = self.page()
        self.assertIn('<i class="bi bi-check-lg" aria-hidden="true"></i><span class="rm-word">نعم</span>', body)
        self.assertIn('<i class="bi bi-dash" aria-hidden="true"></i><span class="rm-word">لا</span>', body)
        # المقفلُ قفلٌ وكلمة، لا لونٌ باهتٌ وحده
        self.assertIn('<i class="bi bi-lock-fill" aria-hidden="true"></i>نعم</span>', body)
        self.assertIn('<i class="bi bi-lock-fill" aria-hidden="true"></i>لا</span>', body)
        buttons = re.findall(r'<button type="submit" name="change".*?</button>', body)
        self.assertEqual(len(buttons), sum(1 for b in buttons if 'class="rm-word"' in b and 'class="rm-tag"' in b))
        self.assertTrue(buttons)

    def test_roles_link_to_their_active_holders(self):
        body = self.page()
        link = f'{ACCOUNTS}?role=entry&amp;status=active'
        self.assertEqual(body.count(f'href="{link}"'), 2)   # الرقاقةُ ورأسُ العمود
        self.assertIn('3 موظّفين<span class="visually-hidden"> بدور مدخل</span>', body)
        self.assertIn('<th scope="col" id="role-entry" data-role="entry" data-label="مدخل" data-n="3">', body)

    def test_personal_exceptions_are_counted_and_linked(self):
        self.assertNotIn('class="rm-ex"', self.page())
        for user in self.entries[:2]:
            UserCapabilityOverride.objects.create(user=user, capability='referral.send', allowed=True)
        UserCapabilityOverride.objects.create(user=self.mail, capability='referral.receive', allowed=False)
        body = self.page()
        self.assertIn(f'<a class="rm-ex" href="{ACCOUNTS}?exception=referral.send">استثناءاتٌ شخصيّة: 2', body)
        self.assertIn(f'<a class="rm-ex" href="{ACCOUNTS}?exception=referral.receive">استثناءاتٌ شخصيّة: 1', body)
        self.assertEqual(body.count('class="rm-ex"'), 2)

    def test_exceptions_that_do_not_apply_are_called_dormant(self):
        """على صفٍّ لم يُربط أو مقفلٍ لا يسري الاستثناء (``has_capability``) — يُعدّ ويُقال «خامدة» (فيبل 11-18)."""
        UserCapabilityOverride.objects.create(user=self.entries[0], capability=LATER[0], allowed=True)
        UserCapabilityOverride.objects.create(user=self.entries[1], capability='secret.own', allowed=True)   # مربوطٌ مقفل
        body = self.page()
        self.assertIn(f'?exception={LATER[0]}">استثناءاتٌ خامدة: 1', body)
        self.assertIn('?exception=secret.own">استثناءاتٌ خامدة: 1', body)
        self.assertNotIn('استثناءاتٌ شخصيّة', body)

    def test_an_old_change_on_a_later_row_keeps_its_way_back(self):
        """صفٌّ مزروعٌ قبل حصر التعديل في المربوط يُعدّ في «رجوع إلى المعتمد كلّه» — فله رجوعُه في «قادمة»."""
        key = LATER[0]
        RoleCapabilityOverride.objects.create(role='entry', capability=key, allowed=not ('entry' in CAPABILITIES[key].holders))
        body = self.page()
        later = _between(body, 'id="rmLater"', 'id="rmBar"')
        self.assertIn(f'name="reset" value="{key}"', later)
        self.assertIn('، معدَّلة عن المعتمد"', later)
        self.assertIn('data-rm-count="1"', body)
        self.post(reset=key)
        self.assertFalse(RoleCapabilityOverride.objects.exists())


class AccountsFilterTests(RolesPageCase):
    def list(self, user, **params):
        self.client.force_login(user)
        return self.client.get(ACCOUNTS, params)

    def names(self, response):
        return sorted(row['username'] for row in response.context['page_obj'].object_list)

    def test_the_exception_filter_shows_its_holders_and_what_they_hold(self):
        UserCapabilityOverride.objects.create(user=self.entries[0], capability='referral.send', allowed=True)
        UserCapabilityOverride.objects.create(user=self.mail, capability='referral.send', allowed=False)
        UserCapabilityOverride.objects.create(user=self.head, capability='referral.receive', allowed=True)
        response = self.list(self.admin, exception='referral.send')
        self.assertEqual(self.names(response), ['m_entry0', 'm_mail'])
        self.assertContains(response, 'أصحاب استثناءٍ شخصيّ على «الإحالة»')
        self.assertContains(response, f'href="{URL}#cap-referral.send"')
        self.assertContains(response, '<span class="sa-chip ok"><span class="visually-hidden">استثناء </span>مضاف</span>')
        self.assertContains(response, '<span class="sa-chip bad"><span class="visually-hidden">استثناء </span>محجوب</span>')
        self.assertNotContains(response, 'خامد')
        self.assertNotContains(response, 'sa-acc-note')
        self.assertContains(response, '<input type="hidden" name="exception" value="referral.send">')
        # الفرزُ والحالةُ يحفظانها
        self.assertTrue(all('exception=referral.send' in c['url'] for c in response.context['columns']))
        self.assertTrue(all('exception=referral.send' in s['url'] for s in response.context['statuses']))
        self.assertNotIn('exception=', response.context['exception_clear_url'])

    def test_an_exception_that_does_not_apply_is_dormant_not_green(self):
        """«مضاف» أخضرُ لقدرةٍ لا يملكها أحد كان يضلّل: غيرُ المربوط والمقفلُ ومديرُ النظام «خامد» (فيبل 11-18)."""
        UserCapabilityOverride.objects.create(user=self.entries[0], capability=LATER[0], allowed=True)
        response = self.list(self.admin, exception=LATER[0])
        self.assertEqual(self.names(response), ['m_entry0'])
        self.assertContains(response, '<span class="sa-chip"><span class="visually-hidden">استثناء </span>خامد</span>')
        self.assertContains(response, 'فالاستثناءات عليها خامدة لا تسري.')
        self.assertNotContains(response, 'مضاف')
        UserCapabilityOverride.objects.create(user=self.entries[1], capability='secret.own', allowed=True)   # مربوطٌ مقفل
        response = self.list(self.admin, exception='secret.own')
        self.assertContains(response, 'الصلاحيّة مقفلة، فلا يسري عليها استثناء.')
        self.assertContains(response, '<span class="visually-hidden">استثناء </span>خامد</span>')
        # ومديرُ النظام يستطيع كلّ شيء — حجبُه على مربوطٍ لا يحجب شيئاً
        UserCapabilityOverride.objects.create(user=self.admin, capability='referral.send', allowed=False)
        UserCapabilityOverride.objects.create(user=self.mail, capability='referral.send', allowed=False)
        response = self.list(self.admin, exception='referral.send')
        effects = {row['username']: row['exception'] for row in response.context['page_obj'].object_list}
        self.assertEqual(effects, {'m_root': 'dormant', 'm_mail': 'blocked'})
        self.assertNotContains(response, 'sa-acc-note')

    def test_the_exception_filter_is_the_system_admins_alone(self):
        """رئيسُ القسم يرى صفوفاً لا يفتحها — التصفيةُ لا تكشف استثناءاتِها (فيبل 11-18)."""
        UserCapabilityOverride.objects.create(user=self.mail, capability='referral.send', allowed=False)
        everyone = self.names(self.list(self.head))
        response = self.list(self.head, exception='referral.send')
        self.assertEqual(response.context['exception'], '')
        self.assertEqual(self.names(response), everyone)
        self.assertNotContains(response, 'name="exception"')
        self.assertNotContains(response, 'sa-acc-context')

    def test_an_unknown_capability_is_ignored(self):
        response = self.list(self.admin, exception='ghost.key')
        self.assertEqual(response.context['exception'], '')
        self.assertEqual(len(self.names(response)), len(self.names(self.list(self.admin))))

    def test_a_role_nobody_holds_stays_a_filter(self):
        """رابطُ «لا أحد» من المصفوفة يفتح قائمةً فارغةً تقول ذلك — لا كلَّ الحسابات (فيبل 11-18)."""
        response = self.list(self.admin, role='archivist', status='active')
        self.assertEqual(response.context['role'], 'archivist')
        self.assertEqual(self.names(response), [])
        self.assertContains(response, '<option value="archivist" selected>مسؤول الأرشفة</option>')
        self.assertContains(response, 'لا حساب يطابق الدور «مسؤول الأرشفة»')

    def test_the_role_count_and_its_link_agree(self):
        """رأسُ العمود يعدّ النشطين، والرابطُ يفتح النشطين — فالعددان واحد (المعطَّلُ لا يُعدّ)."""
        response = self.list(self.admin, role='entry', status='active')
        self.assertEqual(self.names(response), ['m_entry0', 'm_entry1', 'm_entry2'])

    def test_the_role_filter_leads_back_to_its_column(self):
        response = self.list(self.admin, role='mail')
        self.assertContains(response, f'href="{URL}#role-mail"')
        self.assertContains(response, 'ما يستطيعه دور «مختصّ البريد» في المصفوفة')
        self.assertNotContains(self.list(self.admin, role='admin'), '#role-admin')
        self.assertNotContains(self.list(self.head, role='entry'), URL)


class EditorLinkTests(RolesPageCase):
    def test_the_role_summary_leads_to_its_column_for_the_system_admin(self):
        page = reverse('system_account', args=[self.entries[0].pk])
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(page), f'href="{URL}#role-entry"')
        self.client.force_login(self.head)
        response = self.client.get(page)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, URL)


class ClientPinsTests(SimpleTestCase):
    """ما لا يراه الخادم: الإطارُ والثباتُ في الأنماط، والكلمةُ تنقلب في السكربت."""

    def css(self):
        return (ROOT / 'static' / 'css' / 'system_admin.css').read_text(encoding='utf-8')

    def rule(self, selector):
        match = re.search(r'(?m)^' + re.escape(selector) + r' \{([^}]*)\}', self.css())
        self.assertIsNotNone(match, selector)
        return match.group(1)

    def test_the_frame_scrolls_and_its_head_and_first_column_stick(self):
        frame = self.rule('.rm-frame')
        self.assertIn('overflow: auto', frame)
        self.assertIn('max-height:', frame)
        head = self.rule('.rm thead th')
        self.assertIn('position: sticky', head)
        self.assertIn('top: 0', head)
        first = self.rule('.rm tbody th')
        self.assertIn('position: sticky', first)
        self.assertIn('inset-inline-start: 0', first)
        self.assertIn('background:', first)   # بلا خلفيّةٍ تمرّ الخاناتُ تحته ظاهرة
        self.assertNotIn('.rm-card { overflow-x: auto; }', self.css())   # كان يأسر الثباتَ تحت 992px

    def test_focus_is_kept_clear_of_the_sticky_head_and_column(self):
        margins = self.rule('.rm-frame tbody tr, .rm-frame .rm-cell')
        self.assertIn('scroll-margin-top: var(--rm-head', margins)
        self.assertIn('scroll-margin-inline-start: var(--rm-first', margins)
        self.assertIn('scroll-padding-bottom', self.rule('html:has(#rmBar:not([hidden]))'))

    def test_keyboard_focus_is_scrolled_clear_by_the_script(self):
        """Chrome لا يعدّ المغطّى بعنصرٍ ثابتٍ مخفيّاً، فلا يمرّره (مقيسٌ 11-18: 60 من 91 تحت شريط الحفظ،
        والهاتفُ تحت العمود) — والسكربتُ يمرّره للوحة المفاتيح وحدها، ويحسب الشريطَ بنفسه."""
        js = (ROOT / 'static' / 'js' / 'role_matrix.js').read_text(encoding='utf-8')
        # النموذجُ كلُّه («قادمة» خارج الإطار)، لا أزرارُ الشريط نفسِه (كانت ستُزيح الصفحةَ عن نفسها)
        self.assertIn("form.addEventListener('focusin'", js)
        self.assertIn("if (el === frame || bar.contains(el) || !el.matches(':focus-visible')) return;", js)
        self.assertIn("if (frame && frame.contains(el)) el.scrollIntoView({ block: 'nearest', inline: 'nearest' });", js)
        self.assertIn("if (over > 0) window.scrollBy({ top: over, behavior: 'instant' });", js)
        self.assertIn('}).observe(bar);', js)   # يُقاس الشريطُ كلّما التفّ

    def test_the_floating_button_leaves_the_save_bar_alone(self):
        """زرُّ «العودة للأعلى» العائمُ كان فوق «احفظ» في الجهة نفسها، ورفعُه يُلقيه على الخانات — فيغيب مع الشريط."""
        self.assertIn('display: none', self.rule('html:has(#rmBar:not([hidden])) .back-to-top'))
        js = (ROOT / 'static' / 'js' / 'role_matrix.js').read_text(encoding='utf-8')
        self.assertIn("document.documentElement.style.setProperty('--rm-bar-h', bar.offsetHeight + 'px');", js)

    def test_the_pending_word_does_not_widen_its_column(self):
        self.assertIn('position: absolute', self.rule('.rm-cell.pending .rm-tag'))
        self.assertIn('display: none', self.rule('.rm-tag'))

    def test_the_cell_just_clicked_keeps_its_pending_frame(self):
        """المنقورةُ آخراً مركَّزة، وBootstrap يمحو إطارَ الزرّ المركَّز بالفأرة — فالقاعدةُ تعلوه تخصيصاً."""
        self.assertIn('outline: 2px dashed', self.rule('.rm-cell.pending, .rm-cell.pending:focus:not(:focus-visible)'))

    def test_the_script_flips_the_word_and_reads_the_hash_by_id(self):
        js = (ROOT / 'static' / 'js' / 'role_matrix.js').read_text(encoding='utf-8')
        self.assertIn("cell.querySelector('.rm-word').textContent = on ? 'نعم' : 'لا';", js)
        self.assertIn('document.getElementById(id)', js)
        self.assertNotIn('querySelector(decodeURIComponent', js)   # «#cap-referral.receive» محدِّداً صنفٌ
        self.assertIn("frame.style.setProperty('--rm-head'", js)
        self.assertIn("frame.style.setProperty('--rm-first'", js)

    def test_assets_were_bumped(self):
        roles = (ROOT / 'templates' / 'core' / 'system_admin' / 'roles.html').read_text(encoding='utf-8')
        self.assertIn("{% static 'js/role_matrix.js' %}?v=20261118-batch3a", roles)
        base = (ROOT / 'templates' / 'base.html').read_text(encoding='utf-8')
        self.assertIn("{% static 'css/system_admin.css' %}?v=20261118-batch3a", base)
