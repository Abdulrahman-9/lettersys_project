# -*- coding: utf-8 -*-
"""تدقيقُ 2026-10-08، مجموعةُ «البريد».

١. **أفعالٌ تفشل صامتة (H1/H9)**: تحميلُ القالب ومزامنةُ الوارد وتغييرُ حالة الخيط بلا `catch`
   — يُختار القالبُ ولا يتغيّر شيءٌ ولا يُقال لماذا. الآن كلٌّ منها رسالةٌ تُقرأ، وردٌّ ليس JSON
   رسالةٌ برقم حالته.
٢. **حذفُ القالب بحارسٍ غير حارس جاراته**: كان `is_staff` وحدَه فيُردّ مديرُ النظام الذي ليس «موظّفاً»
   عن حذفٍ يرى زرّه؛ الآن `staff_required` كالقوالب والتحرير والإعدادات.
"""
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

ROOT = Path(__file__).resolve().parent.parent
User = get_user_model()


class MailHubScriptTests(SimpleTestCase):
    def src(self):
        return (ROOT / 'templates' / 'core' / 'mail' / 'hub.html').read_text(encoding='utf-8')

    def block(self, header):
        src = self.src()
        i = src.index(header)
        return src[i:src.index('\n}\n', i)]

    def test_every_action_reports_its_failure(self):
        for header in ('async function loadTemplate(', 'async function triggerSync(',
                       'async function changeThreadStatus(', 'async function sendMail('):
            with self.subTest(fn=header):
                body = self.block(header)
                # كتلةُ catch حقيقيّة (لا `.json().catch` وحدَه) تُظهر رسالةَ فشل
                self.assertRegex(body, r"\}\s*catch\s*(\(\w*\))?\s*\{\s*showToast\(")
                self.assertNotIn('const data = await res.json();', body)


class TemplateDeleteGuardTests(TestCase):
    def test_superuser_without_staff_flag_can_delete(self):
        from core.models import EmailTemplate

        boss = User.objects.create_user('mail_boss', password='pw-mail-boss-1', is_superuser=True)
        self.assertFalse(boss.is_staff)
        tpl = EmailTemplate.objects.create(name='قالبٌ يُحذف', slug='to-delete-1008',
                                           subject_template='s', body_html='b')
        self.client.force_login(boss)
        resp = self.client.post(reverse('mail_template_delete', args=[tpl.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(EmailTemplate.objects.filter(pk=tpl.pk).exists())

    def test_a_clerk_still_cannot(self):
        from core.models import EmailTemplate

        clerk = User.objects.create_user('mail_clerk', password='pw-mail-clerk-1')
        tpl = EmailTemplate.objects.create(name='قالبٌ باقٍ', slug='stays-1008',
                                           subject_template='s', body_html='b')
        self.client.force_login(clerk)
        self.assertEqual(self.client.post(reverse('mail_template_delete', args=[tpl.pk])).status_code, 403)
        self.assertTrue(EmailTemplate.objects.filter(pk=tpl.pk).exists())
