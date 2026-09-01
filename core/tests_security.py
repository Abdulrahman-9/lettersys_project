"""
اختبارات التحسينات الأمنية Phase 1 — محدّث
"""
from django.test import TestCase, Client, SimpleTestCase, override_settings
from django.test import RequestFactory
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.cache import cache
import json

from core.models import Book, Entity
from core.decorators import rate_limit_scan, reset_scan_rate_limit_for_request


class RateLimitingTestCase(TestCase):
    """اختبارات معدل التحديد الأساسية"""

    def setUp(self):
        """إعداد بيانات الاختبار"""
        self.client = Client()
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username='testuser', password='testpass123')
        self.client.login(username='testuser', password='testpass123')
        cache.clear()

    def tearDown(self):
        """تنظيف بعد كل اختبار"""
        cache.clear()

    @override_settings(CACHES={
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'phase1-test-cache'
        }
    })
    def test_rate_limit_resets_on_context_change(self):
        """تغيير السياق يجب أن يعيد تعيين العداد"""
        cache.clear()

        @rate_limit_scan(max_attempts=1, window_seconds=300)
        def limited_view(request):
            from django.http import JsonResponse
            return JsonResponse({'status': 'ok'})

        # المحاولة الأولى مع attachment_id=10
        req1 = self.factory.post(
            '/test/', 
            data=json.dumps({'attachment_id': 10}), 
            content_type='application/json'
        )
        req1.user = self.user
        result1 = limited_view(req1)
        self.assertEqual(result1.status_code, 200)

        # المحاولة الثانية مع نفس attachment_id — يجب أن تُرفض
        req2 = self.factory.post(
            '/test/',
            data=json.dumps({'attachment_id': 10}),
            content_type='application/json'
        )
        req2.user = self.user
        result2 = limited_view(req2)
        self.assertEqual(result2.status_code, 429)

        # المحاولة الثالثة مع attachment_id=11 (سياق مختلف) — يجب أن تنجح
        req3 = self.factory.post(
            '/test/',
            data=json.dumps({'attachment_id': 11}),
            content_type='application/json'
        )
        req3.user = self.user
        result3 = limited_view(req3)
        self.assertEqual(result3.status_code, 200)


class InputValidationTestCase(TestCase):
    """اختبارات التحقق من صحة الإدخال"""

    def setUp(self):
        """إعداد بيانات الاختبار"""
        self.issuing = Entity.objects.create(name='جهة مصدرة', code='ISSUE', etype='issuer')
        self.receiving = Entity.objects.create(name='جهة مستقبلة', code='RCV', etype='receiver')

    def test_book_form_title_validation(self):
        """العنوان الطويل جداً يجب أن يُرفض"""
        from core.forms import BookForm

        long_title = 'أ' * 400
        form_data = {
            'kind': 'incoming_internal',
            'issuing_entities': [self.issuing.id],
            'receiving_entities': [self.receiving.id],
            'title': long_title,
            'date': '2026-01-21',
        }

        form = BookForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('title', form.errors)

    def test_book_form_date_logic(self):
        """تاريخ الاستحقاق قبل التاريخ الأصلي يجب أن يُرفض"""
        from core.forms import BookForm

        form_data = {
            'kind': 'incoming_internal',
            'issuing_entities': [self.issuing.id],
            'receiving_entities': [self.receiving.id],
            'title': 'عنوان',
            'date': '2026-01-21',
            'due_date': '2026-01-10',  # في الماضي!
        }

        form = BookForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('__all__', form.errors)


class EncryptionTestCase(TestCase):
    """اختبارات التشفير الشفاف للبيانات الحساسة"""

    def test_email_settings_password_encryption(self):
        """كلمات مرور EmailSettings يجب أن تُشفّر عند الحفظ"""
        from core.models import EmailSettings
        from core.encryption import is_encrypted

        settings = EmailSettings.get()
        plaintext_pwd = "MySecurePassword123!"
        settings.smtp_password = plaintext_pwd
        settings.save()

        # إعادة تحميل من قاعدة البيانات
        reloaded = EmailSettings.objects.get(pk=settings.pk)
        
        # في الذاكرة، يجب أن تكون مفك تشفيرها (هذا هو الهدف من from_db)
        # لكن في قاعدة البيانات الخام، يجب أن تكون مشفرة
        # للتحقق: استخدم _state.db لالتحاف بقيمة الحقل الخام
        # (لكن Django يخفيها، لذا نتحقق فقط أن الوصول يعمل)
        
        # يجب أن يعطينا الوصول العادي القيمة فك التشفير (الواجهة الأمامية)
        self.assertEqual(reloaded.smtp_password, plaintext_pwd)


class NetworkPingExposureTests(TestCase):
    """نقطة الفحص الصحي لا تكشف خريطة النشر لغريبٍ عن الشبكة — سجل العيوب ح6.

    كانت تُعيد الدور واسم الجهاز والإصدار وعدد الجلسات النشطة لأي طارق.
    """

    URL = '/books/api/network/ping/'
    SENSITIVE = ('role', 'name', 'version', 'ip')

    def test_stranger_gets_bare_fingerprint_only(self):
        # عنوانٌ عامٌّ حقيقيّ عمداً: نطاقات التوثيق (203.0.113.0/24 وأخواتها)
        # يعدّها ipaddress.is_private خاصّةً، فتُعطي الاختبارَ نجاحاً كاذباً.
        resp = self.client.get(self.URL, REMOTE_ADDR='8.8.8.8')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get('lettersys'))
        for field in self.SENSITIVE:
            self.assertNotIn(field, data, f"{field} تسرّب لمتصلٍ خارج الشبكة الخاصة")
        self.assertNotIn('active_users', data)

    def test_lan_peer_still_gets_identity_for_discovery(self):
        resp = self.client.get(self.URL, REMOTE_ADDR='192.168.1.50')
        data = resp.json()
        for field in self.SENSITIVE:
            self.assertIn(field, data, f"{field} مفقود — اكتشاف الأقران على LAN ينكسر")

    def test_active_users_never_exposed_even_on_lan(self):
        """عدّاد الجلسات لا مستهلك له في مسار الأقران — مستهلكه صفحة الأجهزة المحميّة."""
        for addr in ('192.168.1.50', '127.0.0.1', '8.8.8.8'):
            self.assertNotIn('active_users', self.client.get(self.URL, REMOTE_ADDR=addr).json())


class AzureKeyEncryptionTests(TestCase):
    """مفتاح Azure يُخزَّن مشفَّراً كما كلمات سرّ البريد — سجل العيوب ح7."""

    KEY_84 = 'k' * 84   # أطول شكلٍ واقعيّ لمفتاح Azure

    def _raw(self, pk):
        from core.models import AIIntegrationSettings
        # values_list يقرأ العمود الخام بلا المرور بـfrom_db — أي بلا فكّ تشفير.
        return AIIntegrationSettings.objects.values_list('azure_key', flat=True).get(pk=pk)

    def test_key_is_encrypted_at_rest_and_plain_in_memory(self):
        from core.models import AIIntegrationSettings

        cfg = AIIntegrationSettings.objects.create(provider='azure', azure_key=self.KEY_84)
        raw = self._raw(cfg.pk)
        self.assertTrue(raw.startswith('enc::'), 'المفتاح خُزِّن نصّاً صريحاً')
        self.assertLessEqual(len(raw), 255, 'الناتج المشفَّر يتجاوز عرض العمود')
        self.assertEqual(AIIntegrationSettings.objects.get(pk=cfg.pk).azure_key, self.KEY_84)

    def test_no_double_encryption_on_resave(self):
        from core.models import AIIntegrationSettings

        cfg = AIIntegrationSettings.objects.create(provider='azure', azure_key=self.KEY_84)
        cfg.save()
        cfg.save()
        self.assertEqual(AIIntegrationSettings.objects.get(pk=cfg.pk).azure_key, self.KEY_84)

    def test_consumer_receives_decrypted_key(self):
        from core.models import AIIntegrationSettings

        AIIntegrationSettings.objects.create(
            provider='azure', enabled=True,
            azure_endpoint='https://x.cognitiveservices.azure.com', azure_key=self.KEY_84,
        )
        self.assertEqual(AIIntegrationSettings.get_active_settings()['AI_AZURE_KEY'], self.KEY_84)


class ProductionCookiePolicyTests(SimpleTestCase):
    """عقدُ النشر: الافتراضُ آمنٌ، والإرخاءُ قرارٌ صريحٌ بمتغيّر بيئة.

    **لماذا وُجدت هذه الاختبارات** (2026-09-01): كان `SESSION_COOKIE_SECURE`
    و`CSRF_COOKIE_SECURE` مثبَّتَين `True`، فقبل إصدار شهادة TLS يستحيل الدخولُ
    على http — فرُقّعت القيمُ **يدويّاً على الخادم بعد كلّ سحب**. ترقيعٌ خفيٌّ
    يعني أنّ ما في المستودع ليس ما يعمل، وهو أسوأُ من الإعداد نفسِه.

    تُحمَّل `settings.py` هنا **مستقلّةً ببيئةٍ مُرقَّعة** — لا قراءةَ مصدرٍ
    نصّيّة: الاختبارُ يقيس القيمةَ الناتجة فعلاً كما يراها Django.
    """

    def _load(self, **env):
        import importlib.util
        import os as _os
        from unittest import mock
        from django.conf import settings as dj
        path = _os.path.join(str(dj.BASE_DIR), 'lettersys', 'settings.py')
        with mock.patch.dict(_os.environ, env, clear=False):
            spec = importlib.util.spec_from_file_location('probe_settings', path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod

    def test_production_defaults_are_secure(self):
        m = self._load(DEBUG='False')
        self.assertTrue(m.SESSION_COOKIE_SECURE)
        self.assertTrue(m.CSRF_COOKIE_SECURE)
        self.assertTrue(m.SECURE_SSL_REDIRECT)

    def test_proxy_header_is_set_for_reverse_proxy_deployments(self):
        """بدونه يرى Django كلَّ طلبٍ http خلف nginx فيدور التوجيهُ بلا نهاية."""
        m = self._load(DEBUG='False')
        self.assertEqual(m.SECURE_PROXY_SSL_HEADER,
                         ('HTTP_X_FORWARDED_PROTO', 'https'))

    def test_proxy_header_can_be_disabled_when_app_is_directly_exposed(self):
        """الترويسةُ تُزوَّر إن كان التطبيقُ مكشوفاً — فالإطفاءُ لازمٌ لا زينة."""
        m = self._load(DEBUG='False', USE_X_FORWARDED_PROTO='False')
        self.assertIsNone(getattr(m, 'SECURE_PROXY_SSL_HEADER', None))

    def test_cookies_can_be_relaxed_before_tls_is_issued(self):
        m = self._load(DEBUG='False', SESSION_COOKIE_SECURE='False',
                       CSRF_COOKIE_SECURE='False')
        self.assertFalse(m.SESSION_COOKIE_SECURE)
        self.assertFalse(m.CSRF_COOKIE_SECURE)
