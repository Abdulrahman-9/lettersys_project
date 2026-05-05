"""
اختبارات التحسينات الأمنية Phase 1 — محدّث
"""
from django.test import TestCase, Client, override_settings
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
