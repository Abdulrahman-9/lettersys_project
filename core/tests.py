"""
=====================================
Comprehensive Test Suite
=====================================

مجموعة اختبارات شاملة لنظام الاستخراج
"""

from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from datetime import timedelta
import os
import json
import tempfile
from types import SimpleNamespace
from unittest import mock

from .models import (
    Book, Attachment, Entity, OCRResult, DataExtractionResult,
    ExtractionFeedback, ExtractionStatistics, ExtractionCache,
    BookNumberReservation,
)
from .extraction.pipeline import AIExtractionService
from .extraction.helpers import ExtractionWorkflow, ConfidenceAnalyzer, QuickFillAssistant
from .extraction.learning import ExtractionLearningSystem


class ModelTests(TestCase):
    """اختبارات نماذج قاعدة البيانات"""
    
    def setUp(self):
        """إعداد البيانات الأساسية"""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        
        self.entity = Entity.objects.create(
            name='وزارة الداخلية',
            code='MOI',
            etype='issuer',
            is_active=True
        )
    
    def test_create_book(self):
        """اختبار إنشاء كتاب"""
        book = Book.objects.create(
            our_number='2024-001',
            title='اختبار',
            date=timezone.now().date(),
            created_by=self.user
        )
        book.issuing_entities.add(self.entity)
        book.receiving_entities.add(self.entity)
        
        self.assertEqual(book.our_number, '2024-001')
        self.assertEqual(book.title, 'اختبار')
        self.assertFalse(book.is_deleted)
    
    def test_create_extraction_result(self):
        """اختبار إنشاء نتيجة استخراج"""
        # تجهيز كتاب ومرفق ونتيجة OCR لازمة للعلاقة
        book = Book.objects.create(
            our_number='2024-001',
            title='اختبار',
            date=timezone.now().date(),
            created_by=self.user
        )
        book.issuing_entities.add(self.entity)
        book.receiving_entities.add(self.entity)
        file = SimpleUploadedFile(name='t.jpg', content=b'x', content_type='image/jpeg')
        attachment = Attachment.objects.create(book=book, file=file)
        ocr = OCRResult.objects.create(attachment=attachment, status='completed')

        result = DataExtractionResult.objects.create(
            ocr_result=ocr,
            attachment=attachment,
            book_number='2024-001',
            book_number_confidence=0.95,
            title='اختبار',
            title_confidence=0.87,
            book_date=timezone.now().date(),
            book_date_confidence=0.92,
            overall_confidence=0.91,
            status='extracted'
        )
        
        self.assertEqual(result.overall_confidence, 0.91)
        self.assertEqual(result.status, 'extracted')
    
    def test_create_feedback(self):
        """اختبار تسجيل التصحيحات"""
        book = Book.objects.create(
            our_number='2024-002',
            title='اختبار',
            date=timezone.now().date(),
            created_by=self.user
        )
        book.issuing_entities.add(self.entity)
        book.receiving_entities.add(self.entity)
        file = SimpleUploadedFile(name='t2.jpg', content=b'x', content_type='image/jpeg')
        attachment = Attachment.objects.create(book=book, file=file)
        ocr = OCRResult.objects.create(attachment=attachment, status='completed')
        result = DataExtractionResult.objects.create(
            ocr_result=ocr,
            attachment=attachment,
            book_number='2024-001',
            overall_confidence=0.85,
            status='extracted'
        )
        
        feedback = ExtractionFeedback.objects.create(
            extraction=result,
            field_name='title',
            feedback_type='incorrect',
            original_value='العنوان الخاطئ',
            corrected_value='العنوان الصحيح',
            reason='تصحيح يدوي',
            created_by=self.user
        )
        
        self.assertEqual(feedback.feedback_type, 'incorrect')


class ExtractionWorkflowTests(TestCase):
    """اختبارات سير عمل الاستخراج"""
    
    def setUp(self):
        """إعداد البيانات"""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        
        self.entity = Entity.objects.create(
            name='وزارة التربية',
            code='MOE',
            etype='both',
            is_active=True
        )
    
    def test_validate_attachment(self):
        """اختبار التحقق من المرفق"""
        book = Book.objects.create(
            our_number='2024-001',
            title='اختبار',
            date=timezone.now().date(),
            created_by=self.user
        )
        book.issuing_entities.add(self.entity)
        book.receiving_entities.add(self.entity)
        
        file = SimpleUploadedFile(
            name='test.jpg',
            content=b'test content',
            content_type='image/jpeg'
        )
        
        attachment = Attachment.objects.create(
            book=book,
            file=file
        )
        
        workflow = ExtractionWorkflow(attachment.id, self.user)
        is_valid, msg = workflow.validate_attachment()
        
        self.assertTrue(is_valid)
    
    def test_apply_corrections(self):
        """اختبار تطبيق التصحيحات"""
        # تجهيز سلسلة كاملة: كتاب + مرفق + OCR + نتيجة استخراج
        book = Book.objects.create(
            our_number='2024-003',
            title='كتاب',
            date=timezone.now().date(),
            created_by=self.user
        )
        book.issuing_entities.add(self.entity)
        book.receiving_entities.add(self.entity)
        file = SimpleUploadedFile(name='t3.jpg', content=b'x', content_type='image/jpeg')
        attachment = Attachment.objects.create(book=book, file=file)
        ocr = OCRResult.objects.create(attachment=attachment, status='completed')
        result = DataExtractionResult.objects.create(
            ocr_result=ocr,
            attachment=attachment,
            book_number='2024-001',
            title='العنوان الأصلي',
            overall_confidence=0.85,
            status='extracted'
        )

        workflow = ExtractionWorkflow(attachment_id=attachment.id, user=self.user)
        workflow.extraction = result
        
        corrections = {
            'title': 'العنوان المصحح',
            'book_number': '2024-002'
        }
        
        success, msg = workflow.apply_corrections(corrections)
        
        self.assertTrue(success)
        # التحقق من حفظ التصحيحات
        feedbacks = ExtractionFeedback.objects.filter(extraction=result)
        self.assertTrue(feedbacks.count() > 0)


class ConfidenceAnalyzerTests(TestCase):
    """اختبارات محلل الثقة"""
    
    def test_get_field_reliability_high(self):
        """اختبار موثوقية عالية"""
        reliability = ConfidenceAnalyzer.get_field_reliability('title', 0.95)
        
        self.assertEqual(reliability['level'], 'عالية جداً ✓')
        self.assertEqual(reliability['color'], 'success')
    
    def test_get_field_reliability_medium(self):
        """اختبار موثوقية متوسطة"""
        reliability = ConfidenceAnalyzer.get_field_reliability('title', 0.75)
        
        self.assertEqual(reliability['level'], 'متوسطة ⚠️')
        self.assertEqual(reliability['color'], 'warning')
    
    def test_get_field_reliability_low(self):
        """اختبار موثوقية منخفضة"""
        reliability = ConfidenceAnalyzer.get_field_reliability('title', 0.45)
        
        self.assertEqual(reliability['level'], 'منخفضة ❌')
        self.assertEqual(reliability['color'], 'danger')
    
    def test_get_extraction_quality_score(self):
        """اختبار درجة الجودة الكلية"""
        # تجهيز نتيجة استخراج صالحة
        user = User.objects.create_user(username='qa', password='p')
        entity = Entity.objects.create(name='جهة', code='G', etype='both', is_active=True)
        book = Book.objects.create(our_number='2024-004', title='اختبار', date=timezone.now().date(),
                                   created_by=user)
        book.issuing_entities.add(entity)
        book.receiving_entities.add(entity)
        file = SimpleUploadedFile(name='t4.jpg', content=b'x', content_type='image/jpeg')
        attachment = Attachment.objects.create(book=book, file=file)
        ocr = OCRResult.objects.create(attachment=attachment, status='completed')
        result = DataExtractionResult.objects.create(
            ocr_result=ocr,
            attachment=attachment,
            book_number='2024-001',
            book_number_confidence=0.95,
            title='اختبار',
            title_confidence=0.85,
            book_date=timezone.now().date(),
            book_date_confidence=0.90,
            secret_level='secret',
            secret_level_confidence=0.88,
            overall_confidence=0.89,
            status='extracted'
        )
        
        quality = ConfidenceAnalyzer.get_extraction_quality_score(result)
        
        self.assertIn('score', quality)
        self.assertIn('grade', quality)
        self.assertIn('recommendation', quality)


class QuickFillAssistantTests(TestCase):
    """اختبارات مساعد الملء السريع"""
    
    def setUp(self):
        """إعداد البيانات"""
        Entity.objects.create(
            name='وزارة العدل',
            code='MOJ',
            etype='both',
            is_active=True
        )
    
    def test_get_entity_suggestions(self):
        """اختبار اقتراحات الجهات"""
        suggestions = QuickFillAssistant.get_entity_suggestions('وزارة')
        
        self.assertIsInstance(suggestions, list)
        if suggestions:
            self.assertIn('id', suggestions[0])
            self.assertIn('name', suggestions[0])
    
    def test_normalize_date_string(self):
        """اختبار تحويل التاريخ من نص"""
        date_obj = QuickFillAssistant.normalize_date('2024-01-15')
        
        self.assertIsNotNone(date_obj)
        self.assertEqual(date_obj.year, 2024)
    
    def test_extract_confidence_summary(self):
        """اختبار استخراج ملخص الثقة"""
        user = User.objects.create_user(username='qa2', password='p')
        entity = Entity.objects.create(name='جهة 2', code='G2', etype='both', is_active=True)
        book = Book.objects.create(our_number='2024-005', title='اختبار', date=timezone.now().date(),
                                   created_by=user)
        book.issuing_entities.add(entity)
        book.receiving_entities.add(entity)
        file = SimpleUploadedFile(name='t5.jpg', content=b'x', content_type='image/jpeg')
        attachment = Attachment.objects.create(book=book, file=file)
        ocr = OCRResult.objects.create(attachment=attachment, status='completed')
        result = DataExtractionResult.objects.create(
            ocr_result=ocr,
            attachment=attachment,
            overall_confidence=0.92,
            status='extracted'
        )
        
        summary = QuickFillAssistant.extract_confidence_summary(result)
        
        self.assertIn('🟢', summary)  # عالي جداً


class ExtractionLearningTests(TestCase):
    """اختبارات نظام التعلم"""
    
    def setUp(self):
        """إعداد البيانات"""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        
        # إنشاء بيانات تصحيحات
        for i in range(10):
            # تجهيز كتاب/مرفق/نتيجة OCR ثم نتيجة استخراج مطابقة للموديل
            entity = Entity.objects.create(name=f'جهة {i}', code=f'C{i}', etype='both', is_active=True)
            book = Book.objects.create(
                our_number=f'2024-{i:03d}',
                title=f'كتاب {i}',
                date=timezone.now().date(),
                created_by=self.user
            )
            book.issuing_entities.add(entity)
            book.receiving_entities.add(entity)
            file = SimpleUploadedFile(name=f't{i}.jpg', content=b'x', content_type='image/jpeg')
            attachment = Attachment.objects.create(book=book, file=file)
            ocr = OCRResult.objects.create(attachment=attachment, status='completed')
            result = DataExtractionResult.objects.create(
                ocr_result=ocr,
                attachment=attachment,
                book_number=f'2024-{i:03d}',
                overall_confidence=0.80 + (i * 0.01),
                status='extracted'
            )
            ExtractionFeedback.objects.create(
                extraction=result,
                field_name='title' if i % 2 == 0 else 'book_number',
                feedback_type='incorrect',
                original_value=f'القيمة {i}',
                corrected_value=f'القيمة المصححة {i}',
                reason='تصحيح يدوي',
                created_by=self.user,
            )
    
    def test_analyze_feedback_patterns(self):
        """اختبار تحليل أنماط التصحيحات"""
        patterns = ExtractionLearningSystem.analyze_feedback_patterns(days=7)
        
        self.assertIsInstance(patterns, dict)
        self.assertIn('title', patterns)
    
    def test_get_field_accuracy_score(self):
        """اختبار حساب دقة الحقل"""
        score = ExtractionLearningSystem.get_field_accuracy_score('title', days=30)
        
        if score:
            self.assertIn('accuracy', score)
            self.assertIn('grade', score)
            self.assertTrue(0 <= score['accuracy'] <= 1)
    
    def test_get_learning_report(self):
        """اختبار تقرير التعلم"""
        report = ExtractionLearningSystem.get_learning_report(days=30)
        
        self.assertIn('period_days', report)
        self.assertIn('total_extractions', report)
        self.assertIn('total_corrections', report)
        self.assertIn('field_accuracy', report)
    
    def test_update_statistics(self):
        """اختبار تحديث الإحصائيات"""
        stats = ExtractionLearningSystem.update_statistics()
        
        self.assertIsNotNone(stats)
        self.assertEqual(stats.date, timezone.now().date())


class AIProcessingServiceTests(TestCase):
    """اختبارات خدمة المعالجة الذكية"""

    @mock.patch('core.extraction.pipeline.build_online_provider_from_settings')
    @mock.patch('core.extraction.pipeline.AIIntegrationSettings.get_active_settings')
    @mock.patch('core.extraction.pipeline.EasyOCROfflineProvider')
    @mock.patch('core.extraction.pipeline.OCRService')
    @mock.patch('core.extraction.pipeline.ImageProcessor')
    def test_invalid_image_does_not_bootstrap_ocr_stack(
        self,
        image_processor_cls,
        ocr_cls,
        offline_provider_cls,
        settings_getter,
        build_online_provider,
    ):
        """اختبار أن الملف التالف يفشل قبل تهيئة OCR الثقيلة."""
        image_processor_cls.side_effect = ValueError('bad image')

        with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp:
            tmp.write(b'bad-bytes')
            temp_path = tmp.name

        self.addCleanup(lambda: os.path.exists(temp_path) and os.remove(temp_path))

        service = AIExtractionService()
        result = service.process_image(temp_path)

        self.assertEqual(result.status, 'failed')
        self.assertEqual(result.error_message, 'bad image')
        ocr_cls.assert_not_called()
        offline_provider_cls.assert_not_called()
        settings_getter.assert_not_called()
        build_online_provider.assert_not_called()


class APITests(TestCase):
    """اختبارات الـ APIs"""
    
    def setUp(self):
        """إعداد البيانات"""
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        self.client.login(username='testuser', password='testpass123')
        
        self.entity = Entity.objects.create(
            name='جهة تجريبية',
            code='TEST',
            etype='both',
            is_active=True
        )

    def _create_extraction(self, *, kind='incoming_internal'):
        book = Book.objects.create(
            our_number='2024-API-001',
            title='اختبار API',
            date=timezone.now().date(),
            created_by=self.user,
        )
        book.issuing_entities.add(self.entity)
        book.receiving_entities.add(self.entity)

        file = SimpleUploadedFile(name='api.jpg', content=b'x', content_type='image/jpeg')
        attachment = Attachment.objects.create(book=book, file=file)
        ocr = OCRResult.objects.create(attachment=attachment, status='completed')
        extraction = DataExtractionResult.objects.create(
            ocr_result=ocr,
            attachment=attachment,
            book_number='2024-API-001',
            title='اختبار API',
            book_kind=kind,
            overall_confidence=0.88,
            status='extracted',
        )
        return book, attachment, extraction
    
    def test_extraction_statistics_api(self):
        """اختبار API الإحصائيات"""
        # إنشاء إحصائيات
        ExtractionStatistics.objects.create(
            total_images_processed=10,
            successful_extractions=8,
            failed_extractions=2,
            manual_review_required=3,
            average_confidence=0.82,
            average_processing_time=1.25,
            field_stats={'title': {'avg': 0.9}}
        )
        
        response = self.client.get('/books/api/extract/statistics/')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        # الخدمة تُرجع إحصائيات مدمجة من أحدث سجل
        self.assertIn('total_images_processed', data)
        self.assertIn('average_confidence', data)
    
    def test_extraction_workflow_api(self):
        """اختبار API سير العمل"""
        book = Book.objects.create(
            our_number='2024-001',
            title='اختبار',
            date=timezone.now().date(),
            created_by=self.user
        )
        book.issuing_entities.add(self.entity)
        book.receiving_entities.add(self.entity)
        
        # إنشاء مرفق ثم بدء الاستخراج عبر attachment_id
        file = SimpleUploadedFile(name='api.jpg', content=b'x', content_type='image/jpeg')
        attachment = Attachment.objects.create(book=book, file=file)

        response = self.client.post(
            '/books/api/extract/',
            {'attachment_id': attachment.id},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )

        # متوقع 202 مع task_id
        self.assertEqual(response.status_code, 202)
        payload = response.json()
        self.assertIn('task_id', payload)

    def test_extraction_results_ui_route(self):
        """اختبار أن صفحة نتائج الاستخراج مربوطة ضمن المسارات الحية."""
        _, _, extraction = self._create_extraction(kind='incoming')

        response = self.client.get(reverse('extraction-results-ui', args=[extraction.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'مراجعة الاستخراج الذكي')
        self.assertContains(response, 'وارد داخلي')

    def test_extraction_wizard_redirects_to_smart_desktop(self):
        """اختبار أن المسار القديم للمعالج يمر عبر الواجهة الذكية الموحدة."""
        response = self.client.get(
            reverse('extraction-wizard') + '?kind=outgoing_external',
            follow=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response['Location'],
            reverse('extraction-smart-desktop') + '?kind=outgoing_external',
        )

    def test_extraction_quick_start_redirects_to_smart_desktop(self):
        """extraction_quick_start يُعيد توجيهاً للواجهة الذكية الجديدة."""
        response = self.client.get(reverse('extraction-quick-start'))
        self.assertRedirects(response, reverse('extraction-smart-desktop'), fetch_redirect_response=False)

    def test_submit_feedback_accepts_notes_alias(self):
        """اختبار التوافق الخلفي مع العملاء الذين يرسلون notes بدلاً من reason."""
        _, _, extraction = self._create_extraction()

        response = self.client.post(
            reverse('ai_submit_feedback', args=[extraction.id]),
            data=json.dumps({
                'field_name': 'title',
                'feedback_type': 'incorrect',
                'original_value': 'عنوان قديم',
                'corrected_value': 'عنوان صحيح',
                'notes': 'ملاحظة من عميل قديم',
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 201)
        feedback = ExtractionFeedback.objects.get(extraction=extraction, field_name='title')
        self.assertEqual(feedback.reason, 'ملاحظة من عميل قديم')

    def test_save_book_api_accepts_entity_ids_and_legacy_secret_aliases(self):
        """اختبار حفظ كتاب عبر API باستخدام IDs للجهات وقيم سرية قديمة."""
        response = self.client.post(
            reverse('save-book-api'),
            {
                'book_number': '2024-API-NEW',
                'date': timezone.now().date().isoformat(),
                'title': 'كتاب جديد',
                'secret_level': 'confidential',
                'book_kind': 'outgoing',
                'issuing_entity_id': str(self.entity.id),
                'receiving_entity_id': str(self.entity.id),
                'margin_text': 'هامش تجريبي',
            },
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        saved_book = Book.objects.get(pk=payload['book_id'])
        self.assertEqual(saved_book.secret_level, 'secret')
        self.assertEqual(saved_book.kind, 'outgoing_internal')
        self.assertEqual(saved_book.margin, 'هامش تجريبي')
        self.assertEqual(saved_book.document_type, 'مذكرة داخلية')
        self.assertEqual(saved_book.first_issuing_entity, self.entity)
        self.assertEqual(saved_book.first_receiving_entity, self.entity)

    def test_save_book_api_accepts_custom_document_type(self):
        """اختبار حفظ نوع مستند مخصص غير موجود ضمن القائمة القياسية."""
        response = self.client.post(
            reverse('save-book-api'),
            {
                'book_number': '2024-API-CUSTOM',
                'date': timezone.now().date().isoformat(),
                'title': 'كتاب بنوع مخصص',
                'kind': 'incoming_external',
                'document_type': 'قرار خاص',
                'issuing_entity_id': str(self.entity.id),
                'receiving_entity_id': str(self.entity.id),
            },
        )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        saved_book = Book.objects.get(pk=payload['book_id'])
        self.assertEqual(saved_book.document_type, 'قرار خاص')

    def test_save_book_api_returns_explicit_error_for_used_reservation(self):
        """اختبار أن الحجز المستخدم سابقاً لا يعود برسالة غامضة ولا يُعاد حفظ الكتاب تلقائياً."""
        reservation = BookNumberReservation.reserve(self.user, 'incoming_internal', expire_minutes=45)
        used_book = Book.objects.create(
            our_number=reservation.formatted,
            title='كتاب محفوظ مسبقاً',
            date=timezone.now().date(),
            created_by=self.user,
            kind='incoming_internal',
            document_type='مذكرة داخلية',
        )
        used_book.issuing_entities.add(self.entity)
        used_book.receiving_entities.add(self.entity)
        reservation.mark_used(used_book)

        response = self.client.post(
            reverse('save-book-api'),
            {
                'book_number': reservation.formatted,
                'date': timezone.now().date().isoformat(),
                'title': 'محاولة ثانية',
                'kind': 'incoming_internal',
                'reservation_id': str(reservation.pk),
                'issuing_entity_id': str(self.entity.id),
                'receiving_entity_id': str(self.entity.id),
            },
        )

        self.assertEqual(response.status_code, 409)
        payload = response.json()
        self.assertEqual(payload['error_code'], 'RESERVATION_ALREADY_USED')
        self.assertEqual(payload['book_id'], used_book.pk)

    def test_save_book_api_treats_expired_reactivated_reservation_as_expired(self):
        """اختبار أن الحجز المُعاد تفعيله ثم انتهت صلاحيته يُرفض كمنتهي لا كحجز صالح."""
        reservation = BookNumberReservation.reserve(self.user, 'incoming_internal', expire_minutes=45)
        reservation.status = BookNumberReservation.STATUS_REACTIVATED
        reservation.expires_at = timezone.now() - timedelta(minutes=5)
        reservation.save(update_fields=['status', 'expires_at'])

        response = self.client.post(
            reverse('save-book-api'),
            {
                'book_number': reservation.formatted,
                'date': timezone.now().date().isoformat(),
                'title': 'حجز منتهي بعد إعادة التفعيل',
                'kind': 'incoming_internal',
                'reservation_id': str(reservation.pk),
                'issuing_entity_id': str(self.entity.id),
                'receiving_entity_id': str(self.entity.id),
            },
        )

        self.assertEqual(response.status_code, 409)
        payload = response.json()
        self.assertEqual(payload['error_code'], 'RESERVATION_EXPIRED')

        reservation.refresh_from_db()
        self.assertEqual(reservation.status, BookNumberReservation.STATUS_EXPIRED)

    def test_save_book_api_keeps_reservation_active_when_save_fails(self):
        """عند فشل الحفظ بسبب خطأ خادم، يجب أن يبقى الحجز نشطاً ليُعيد المستخدم المحاولة بنفس الرقم."""
        reservation = BookNumberReservation.reserve(self.user, 'incoming_internal', expire_minutes=45)

        with mock.patch('core.views.books_api.Book.objects.create', side_effect=RuntimeError('boom')):
            response = self.client.post(
                reverse('save-book-api'),
                {
                    'book_number': reservation.formatted,
                    'date': timezone.now().date().isoformat(),
                    'title': 'محاولة فاشلة',
                    'kind': 'incoming_internal',
                    'reservation_id': str(reservation.pk),
                    'issuing_entity_id': str(self.entity.id),
                    'receiving_entity_id': str(self.entity.id),
                },
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()['error_code'], 'SERVER_ERROR')

        reservation.refresh_from_db()
        self.assertEqual(reservation.status, BookNumberReservation.STATUS_ACTIVE)
        self.assertIsNone(reservation.book_id)

    @mock.patch('core.extraction.api.endpoints.AIExtractionService')
    def test_smart_extract_returns_error_when_mock_fallback_disabled(self, service_cls):
        """اختبار أن الإخفاق لا يعود بنجاح وهمي إلا إذا فُعّل ذلك صراحة."""
        service_cls.return_value.process_image.side_effect = ValueError('bad image')

        with self.settings(AI_ALLOW_MOCK_EXTRACTION=False):
            response = self.client.post(
                reverse('ai_smart_extract'),
                {'file': SimpleUploadedFile('bad.jpg', b'bad-bytes', content_type='image/jpeg')},
            )

        self.assertEqual(response.status_code, 500)
        payload = response.json()
        self.assertFalse(payload['success'])
        self.assertEqual(payload['error_code'], 'EXTRACTION_FAILED')

    @mock.patch('core.extraction.api.endpoints.AIExtractionService')
    def test_smart_extract_can_use_mock_when_explicitly_enabled(self, service_cls):
        """اختبار أن mock fallback يبقى متاحاً فقط عند تفعيله بإعداد واضح."""
        service_cls.return_value.process_image.side_effect = ValueError('bad image')

        with self.settings(AI_ALLOW_MOCK_EXTRACTION=True):
            response = self.client.post(
                reverse('ai_smart_extract'),
                {'file': SimpleUploadedFile('bad.jpg', b'bad-bytes', content_type='image/jpeg')},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['success'])
        self.assertTrue(payload['details']['fallback'])

    @mock.patch('core.extraction.api.endpoints.AIExtractionService')
    def test_smart_extract_failed_result_returns_error_when_mock_disabled(self, service_cls):
        """اختبار أن نتيجة failed من خدمة الذكاء تُعامل كفشل فعلي."""
        service_cls.return_value.process_image.return_value = SimpleNamespace(
            status='failed',
            error_message='bad image',
        )

        with self.settings(AI_ALLOW_MOCK_EXTRACTION=False):
            response = self.client.post(
                reverse('ai_smart_extract'),
                {'file': SimpleUploadedFile('bad.jpg', b'bad-bytes', content_type='image/jpeg')},
            )

        self.assertEqual(response.status_code, 500)
        payload = response.json()
        self.assertFalse(payload['success'])
        self.assertEqual(payload['error_code'], 'EXTRACTION_FAILED')

    @mock.patch('core.extraction.api.endpoints.AIExtractionService')
    def test_smart_extract_failed_result_can_use_mock_when_enabled(self, service_cls):
        """اختبار أن نتيجة failed يمكن تحويلها إلى mock فقط عند التفعيل الصريح."""
        service_cls.return_value.process_image.return_value = SimpleNamespace(
            status='failed',
            error_message='bad image',
        )

        with self.settings(AI_ALLOW_MOCK_EXTRACTION=True):
            response = self.client.post(
                reverse('ai_smart_extract'),
                {'file': SimpleUploadedFile('bad.jpg', b'bad-bytes', content_type='image/jpeg')},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['success'])
        self.assertTrue(payload['details']['fallback'])


class IntegrationTests(TestCase):
    """اختبارات التكامل الشاملة"""
    
    def setUp(self):
        """إعداد البيانات"""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123'
        )
        
        self.entity = Entity.objects.create(
            name='جهة تكامل',
            code='INTEG',
            etype='both',
            is_active=True
        )
    
    def test_full_workflow(self):
        """اختبار سير العمل الكامل"""
        # 1. إنشاء كتاب
        book = Book.objects.create(
            our_number='2024-TEST-001',
            title='اختبار التكامل',
            date=timezone.now().date(),
            created_by=self.user
        )
        book.issuing_entities.add(self.entity)
        book.receiving_entities.add(self.entity)
        
        # 2. إنشاء مرفق
        file = SimpleUploadedFile(
            name='test.jpg',
            content=b'test',
            content_type='image/jpeg'
        )
        attachment = Attachment.objects.create(
            book=book,
            file=file
        )
        
        # 3. إنشاء نتيجة استخراج
        ocr = OCRResult.objects.create(attachment=attachment, status='completed')
        result = DataExtractionResult.objects.create(
            ocr_result=ocr,
            attachment=attachment,
            book_number='2024-TEST-001',
            title='اختبار التكامل',
            overall_confidence=0.88,
            status='extracted'
        )
        
        # 4. إضافة تصحيحات
        feedback = ExtractionFeedback.objects.create(
            extraction=result,
            field_name='title',
            feedback_type='incorrect',
            original_value='عنوان خاطئ',
            corrected_value='عنوان صحيح',
            reason='تصحيح يدوي',
            created_by=self.user
        )
        
        # 5. التحقق من النتائج
        self.assertEqual(book.our_number, '2024-TEST-001')
        self.assertEqual(attachment.book, book)
        self.assertEqual(result.overall_confidence, 0.88)
        
        # 6. تحليل التعلم
        patterns = ExtractionLearningSystem.analyze_feedback_patterns()
        self.assertIsInstance(patterns, dict)
