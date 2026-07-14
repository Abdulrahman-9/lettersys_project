# -*- coding: utf-8 -*-
"""اختبارات صدق زرّ «اختبار الاتصال SMTP».

الخلل الذي تحرسه: كان ``SMTPEngine.test_connection()`` ينادي ``get_connection()``،
وهذا يسقط إلى backend الافتراضي حين ``is_active=False`` — وهو في وضع DEBUG الـ
console backend الذي ينجح ``open()`` عليه **دائماً**. فكان الزر يُبلّغ «تم الاتصال
بنجاح ✓» حتى بلا خادم ولا مستخدم ولا كلمة مرور، فيظنّ المستخدم أن البريد يعمل
بينما لا يخرج شيء إطلاقاً.

القاعدة: الاختبار يجب أن يختبر SMTP حقيقياً — ولا ينجح أبداً على إعدادات ناقصة.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from core.messaging.engines.smtp import SMTPEngine
from core.models import EmailSettings


class SMTPTestConnectionHonestyTests(TestCase):

    def test_missing_password_never_reports_success(self):
        """الحالة التي أوقعت المالك: مستخدم وخادم مضبوطان، وكلمة المرور فارغة."""
        cfg = EmailSettings.get()
        cfg.smtp_host = 'smtp.gmail.com'
        cfg.smtp_user = 'someone@gmail.com'
        cfg.smtp_password = ''
        cfg.is_active = False
        cfg.save()

        result = SMTPEngine(cfg).test_connection()

        self.assertFalse(result['success'], 'زرّ الاختبار يكذب: أبلغ بالنجاح بلا كلمة مرور')
        self.assertIn('كلمة المرور', result['message'])

    def test_missing_host_and_user_are_named(self):
        cfg = EmailSettings.get()
        cfg.smtp_host = ''
        cfg.smtp_user = ''
        cfg.smtp_password = ''
        cfg.save()

        result = SMTPEngine(cfg).test_connection()

        self.assertFalse(result['success'])
        for label in ('خادم SMTP', 'اسم المستخدم', 'كلمة المرور'):
            self.assertIn(label, result['message'])

    def test_no_config_is_a_failure(self):
        result = SMTPEngine(None).test_connection()
        self.assertFalse(result['success'])

    @patch('core.messaging.engines.smtp.get_connection')
    def test_complete_config_opens_a_real_smtp_connection(self, mock_get_conn):
        """مع إعدادات كاملة يجب أن يُبنى backend الـSMTP صراحةً — لا الافتراضي."""
        cfg = EmailSettings.get()
        cfg.smtp_host = 'smtp.gmail.com'
        cfg.smtp_port = 587
        cfg.smtp_use_tls = True
        cfg.smtp_use_ssl = False
        cfg.smtp_user = 'someone@gmail.com'
        cfg.smtp_password = 'app-password-16'
        cfg.save()

        result = SMTPEngine(cfg).test_connection()

        self.assertTrue(result['success'])
        kwargs = mock_get_conn.call_args.kwargs
        self.assertEqual(kwargs['backend'], 'django.core.mail.backends.smtp.EmailBackend')
        self.assertEqual(kwargs['host'], 'smtp.gmail.com')
        self.assertEqual(kwargs['password'], 'app-password-16')
        mock_get_conn.return_value.open.assert_called_once()

    @patch('core.messaging.engines.smtp.get_connection')
    def test_server_refusal_is_reported_as_failure(self, mock_get_conn):
        mock_get_conn.return_value.open.side_effect = OSError('Authentication failed')

        cfg = EmailSettings.get()
        cfg.smtp_host = 'smtp.gmail.com'
        cfg.smtp_user = 'someone@gmail.com'
        cfg.smtp_password = 'wrong'
        cfg.save()

        result = SMTPEngine(cfg).test_connection()

        self.assertFalse(result['success'])
        self.assertIn('فشل الاتصال', result['message'])


class SMTPTestRateLimitTests(TestCase):
    """محدِّد المعدّل يُحتسب مرّة واحدة لكل نقرة — لا مرّتين.

    الخلل: ``mail_endpoints.api_test_smtp`` (الذي تناديه الواجهة) كان يحمل
    ``@rate_limit('test_smtp', 5, 300)`` ثم يفوّض إلى ``email_endpoints.test_smtp``
    الذي يحمل المحدِّد نفسه بنفس المفتاح — فكل نقرة تستهلك **محاولتين**، وتنفد
    الحصّة بعد نقرتين ونصف بدل خمس.
    """

    def setUp(self):
        cache.clear()
        self.staff = get_user_model().objects.create_user(
            username='rl_staff', password='pw-rl-12345', is_staff=True, is_superuser=True,
        )
        self.client.force_login(self.staff)

    @patch('core.messaging.engines.smtp.get_connection')
    def test_one_click_consumes_one_attempt(self, mock_get_conn):
        cfg = EmailSettings.get()
        cfg.smtp_host = 'smtp.gmail.com'
        cfg.smtp_user = 'someone@gmail.com'
        cfg.smtp_password = 'app-password-16'
        cfg.save()

        url = reverse('mail-api-test-smtp')
        for click in range(1, 21):
            resp = self.client.post(url)
            self.assertEqual(
                resp.status_code, 200,
                f'نفدت الحصّة عند النقرة {click} — المحدِّد يُحتسب مرّتين لكل نقرة',
            )

        # النقرة 21 تتجاوز الحد (20 لكل 5 دقائق)
        self.assertEqual(self.client.post(url).status_code, 429)

    def test_non_staff_gets_json_403_not_an_html_redirect(self):
        """نقطة API — يجب أن تُرجع 403 بصيغة JSON لا إعادة توجيه HTML."""
        self.client.logout()
        plain = get_user_model().objects.create_user(username='rl_plain', password='pw-rl-12345')
        self.client.force_login(plain)

        resp = self.client.post(reverse('mail-api-test-smtp'))

        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp['Content-Type'], 'application/json')
