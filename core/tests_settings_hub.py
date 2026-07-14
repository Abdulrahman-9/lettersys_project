# -*- coding: utf-8 -*-
"""اختبارات مركز الإعدادات — الشريط العلوي ووضع التضمين (?embed=1).

العقد الذي تحرسه هذه الاختبارات:
1. المركز يعرض شريط تبويبات واحداً يحوي كل الأقسام (لا شريط جانبي، لا بطاقات إطلاق).
2. الأدوات الثقيلة تُشير إلى نفسها بـ ?embed=1 كي تُحمَّل داخل لوحة المركز.
3. وضع التضمين يُسقِط قشرة التطبيق (الشريط العلوي/الجانبي) فتظهر الأداة وحدها.
4. وضع التضمين «لاصق»: يبقى فعّالاً بعد إعادة التوجيه داخل الإطار عبر ترويسة
   Sec-Fetch-Dest — وإلا عادت القشرة للظهور داخل الإطار بعد أوّل حفظ.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class SettingsHubTabstripTests(TestCase):
    """الشريط العلوي يحوي كل الأقسام ويربط الأدوات الثقيلة بوضع التضمين."""

    @classmethod
    def setUpTestData(cls):
        cls.staff = get_user_model().objects.create_user(
            username='hub_staff', password='pw-hub-12345', is_staff=True, is_superuser=True,
        )

    def setUp(self):
        self.client.force_login(self.staff)

    def test_hub_renders_single_horizontal_tabstrip(self):
        html = self.client.get(reverse('settings_hub')).content.decode()
        self.assertIn('id="settingsTabstrip"', html)
        self.assertIn('settings-tab-indicator', html)
        # الأصول الجديدة موصولة (مع cache-busting)
        self.assertIn('css/settings_hub.css', html)
        self.assertIn('js/settings_hub.js', html)

    def test_every_section_is_present_as_a_tab(self):
        html = self.client.get(reverse('settings_hub')).content.decode()
        for key in ('general', 'email', 'notifications', 'security', 'backup',
                    'sequences', 'network', 'scan', 'users', 'trash', 'ai'):
            self.assertIn(f'data-tab="{key}"', html, f'التبويب {key} مفقود من الشريط')

    def test_heavy_tools_load_embedded_not_by_leaving(self):
        """الأدوات الثقيلة تُحمَّل داخل الإطار — لا كروابط تُخرِج المستخدم."""
        html = self.client.get(reverse('settings_hub')).content.decode()
        for name, tab in (('sequence_settings', 'sequences'),
                          ('network_settings', 'network'),
                          ('scan_settings', 'scan')):
            self.assertIn(f'data-embed-url="{reverse(name)}?embed=1"', html,
                          f'التبويب {tab} لا يُحمَّل داخل المركز')
        self.assertIn('id="settingsEmbedFrame"', html)

    def test_deep_link_tab_is_accepted(self):
        """?tab=scan لا يُسقِط الصفحة (الاختيار يتم في العميل من نفس الرابط)."""
        self.assertEqual(self.client.get(reverse('settings_hub') + '?tab=scan').status_code, 200)

    def test_hub_requires_staff(self):
        self.client.logout()
        plain = get_user_model().objects.create_user(username='hub_plain', password='pw-hub-12345')
        self.client.force_login(plain)
        self.assertNotEqual(self.client.get(reverse('settings_hub')).status_code, 200)


class EmbedModeTests(TestCase):
    """وضع التضمين يُسقِط قشرة التطبيق ويبقى لاصقاً بعد إعادة التوجيه."""

    @classmethod
    def setUpTestData(cls):
        cls.staff = get_user_model().objects.create_user(
            username='embed_staff', password='pw-embed-12345', is_staff=True, is_superuser=True,
        )

    def setUp(self):
        self.client.force_login(self.staff)

    def test_normal_page_keeps_app_chrome(self):
        html = self.client.get(reverse('sequence_settings')).content.decode()
        self.assertIn('app-topbar', html)
        self.assertIn('app-sidebar', html)

    def test_embed_query_param_drops_app_chrome(self):
        html = self.client.get(reverse('sequence_settings') + '?embed=1').content.decode()
        self.assertNotIn('app-topbar', html)
        self.assertNotIn('app-sidebar-nav', html)
        self.assertIn('settings-embed-body', html)
        self.assertIn('app-embed-main', html)

    def test_embed_is_sticky_via_sec_fetch_dest(self):
        """بعد حفظ نموذج داخل الإطار يعيد الـview التوجيه لرابط بلا ?embed=1.

        المتصفح يُتبِع التوجيه داخل الإطار فيرسل Sec-Fetch-Dest: iframe — وهذا وحده
        يجب أن يُبقي القشرة مُسقَطة، وإلا ظهر شريط التطبيق داخل إطار المركز.
        """
        html = self.client.get(
            reverse('sequence_settings'), headers={'sec-fetch-dest': 'iframe'},
        ).content.decode()
        self.assertNotIn('app-topbar', html)
        self.assertIn('settings-embed-body', html)

    def test_top_level_navigation_is_never_embedded(self):
        html = self.client.get(
            reverse('sequence_settings'), headers={'sec-fetch-dest': 'document'},
        ).content.decode()
        self.assertIn('app-topbar', html)

    def test_back_to_settings_button_returns_to_its_own_tab(self):
        """أزرار الرجوع كانت تشير لوجهات خاطئة (أو مفقودة) — الآن تعود لتبويبها."""
        hub = reverse('settings_hub')
        for name, tab in (('sequence_settings', 'sequences'),
                          ('network_settings', 'network'),
                          ('scan_settings', 'scan')):
            html = self.client.get(reverse(name)).content.decode()
            self.assertIn(f'{hub}?tab={tab}', html, f'{name}: زر الرجوع لا يعود لتبويبه')
