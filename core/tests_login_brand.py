# -*- coding: utf-8 -*-
"""صفحةُ الدخول بهويّة النظام لا بهويّة الشركة (البند 6، قرارُ المالك 2026‑10‑07).

المستودعُ عامّ، وصفحةُ الدخول أوّلُ ما يراه أيُّ زائر: الاسمُ من «إعدادات النظام»
(``SystemSettings.app_name``)، وعلامةٌ عامّة بدل الشعار، وتركوازُ التطبيق بدل أزرق
Bootstrap — والإحساسُ نفسُه (الارتفاعُ عند المرور · الموجة · حلقةُ التركيز).
الشعارُ داخل التطبيق (``base.html``) باقٍ: ذاك قرارٌ آخر لم يُمَسّ.

اسمُ الشركة لا يُكتب هنا حرفيّاً — يُقرأ من مصدره الوحيد ``core.branding``.
"""
import re
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import DatabaseError
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core.branding import DEFAULT_ORG_NAME
from core.models import SystemSettings

LOGO = 'md-o-c-logo'
LOGIN_TEMPLATE = Path(settings.BASE_DIR) / 'templates' / 'core' / 'login.html'

#: كلُّ أزرقٍ كان في القالب (بلا مسافات) — واحدٌ منسيٌّ يترك ظلّاً أزرقَ تحت زرٍّ تركوازيّ.
BLUES = ('#0d6efd', '#1d4ed8', '#3b82f6', '#e8f0ff', 'rgba(13,110,253', 'rgba(59,130,246')


def _flat(text):
    return re.sub(r'\s+', '', text.lower())


class LoginPageBrandTests(TestCase):

    def setUp(self):
        # كاشُ العرض LocMem يعبر الاختبارات ولا يتراجع مع القاعدة — لا يرث اختبارٌ اسمَ غيره.
        cache.delete(SystemSettings.CACHE_KEY)
        self.addCleanup(cache.delete, SystemSettings.CACHE_KEY)

    def _login_page(self):
        resp = self.client.get(reverse('login'))
        self.assertEqual(resp.status_code, 200)
        return resp

    def test_the_page_carries_the_configured_system_name(self):
        cfg = SystemSettings.get()
        cfg.app_name = 'منظومة التجربة'
        cfg.brand_subtitle = 'سطرُ وصفٍ للتجربة'
        cfg.save()

        resp = self._login_page()

        self.assertContains(resp, '<h5>منظومة التجربة</h5>', html=True)
        self.assertContains(resp, 'سطرُ وصفٍ للتجربة')

    def test_no_company_name_logo_or_bootstrap_blue_on_the_page(self):
        html = self._login_page().content.decode('utf-8')

        self.assertNotIn(LOGO, html)
        # الكلمةُ الأولى («شركة») عامّة؛ ما بعدها هو الاسم — فلا يبقى منه جزء.
        for part in (DEFAULT_ORG_NAME, *DEFAULT_ORG_NAME.split()[1:]):
            with self.subTest(part=part):
                self.assertNotIn(part, html)
        flat = _flat(html)
        for blue in ('#0d6efd', 'rgba(13,110,253'):
            with self.subTest(blue=blue):
                self.assertNotIn(blue, flat)

    def test_the_form_keeps_its_copy(self):
        resp = self._login_page()

        self.assertContains(resp, 'تذكّرني 7 أيّام')
        self.assertContains(resp, 'name="remember_me"')

    def test_defaults_render_when_the_settings_are_unreachable(self):
        """قبل الهجرة أو والقاعدةُ متعثّرة يعيد المعالجُ ``None`` — والصفحةُ لا تفرغ من الاسم."""
        with mock.patch.object(SystemSettings, 'get', side_effect=DatabaseError('not ready')):
            resp = self._login_page()

        self.assertIsNone(resp.context['system_settings'])
        self.assertContains(resp, '<h5>نظام الكتب</h5>', html=True)
        self.assertContains(resp, 'نظام تتبع الكتب والمراسلات')

    def test_the_logo_stays_inside_the_app(self):
        """البند 6 يخصّ صفحةَ الدخول وحدَها: شريطُ التطبيق (``base.html``) يحمل الشعارَ كما كان."""
        self.client.force_login(User.objects.create_user('bclerk', password='pw-bclerk-1111'))

        self.assertContains(self.client.get(reverse('dashboard')), LOGO)


class LoginTemplateColourTests(SimpleTestCase):
    """يُقرأ مصدرُ القالب لا الصفحة: نافذتا المعاينة في ``base.html`` تُرسَمان في كلّ صفحةٍ
    بألوانهما، وليستا من هذا البند."""

    def test_every_blue_left_the_template(self):
        src = _flat(LOGIN_TEMPLATE.read_text(encoding='utf-8'))

        for blue in BLUES:
            with self.subTest(blue=blue):
                self.assertNotIn(blue, src)

    def test_the_tokens_are_the_teal_scope(self):
        """الرموزُ نفسُها التي تُلوّن ورشةَ الاستخراج (brand-components.css) — لا لونَ ثالث."""
        src = _flat(LOGIN_TEMPLATE.read_text(encoding='utf-8'))

        self.assertIn('--brand-strong:#0f766e', src)
        self.assertIn('--brand-strong-2:#115e59', src)
