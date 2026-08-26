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
    BookNumberReservation, LetterheadMemory,
)
from .extraction.pipeline import AIExtractionService
from .extraction.helpers import ExtractionWorkflow, ConfidenceAnalyzer, QuickFillAssistant


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


class ExtractionCaptureTests(TestCase):
    """حلقة التقاط التدريب: persist_extraction_capture (الأساس لتدريب النماذج)."""

    def setUp(self):
        self.user = User.objects.create_user(username='cap', password='p')
        self.book = Book.objects.create(
            our_number='2025-1-0009', title='العنوان النهائي',
            date=timezone.now().date(), created_by=self.user,
        )
        file = SimpleUploadedFile(name='c.jpg', content=b'x', content_type='image/jpeg')
        self.attachment = Attachment.objects.create(book=self.book, file=file)

    def test_capture_persists_ocr_extraction_and_clean_feedback(self):
        from core.extraction.capture import persist_extraction_capture
        suggested = {
            'raw_text': 'نصّ ممسوح من المستند',
            'ocr_engine': 'tesseract',
            'book_number': '99',                # صيغة مختلفة عن our_number → لا feedback
            'title': 'عنوان مُقترَح خاطئ',        # يختلف عن النهائي → feedback
            'secret_level': 'normal',           # مطابق → لا feedback
            'book_kind': 'incoming',
            'overall_confidence': 0.8,
        }
        final = {'our_number': '2025-1-0009', 'title': 'العنوان النهائي',
                 'secret_level': 'normal', 'kind': 'incoming_internal'}

        extraction = persist_extraction_capture(
            book=self.book, attachment=self.attachment,
            suggested=suggested, final=final, user=self.user)

        self.assertIsNotNone(extraction)
        ocr = OCRResult.objects.get(attachment=self.attachment)
        self.assertEqual(ocr.raw_text, 'نصّ ممسوح من المستند')
        self.assertEqual(ocr.processed_by, 'tesseract')
        self.assertEqual(extraction.book_id, self.book.id)
        # تصحيح نظيف واحد فقط: title (secret_level مطابق، والرقم/النوع مستبعدان عمداً)
        fb = {f.field_name for f in ExtractionFeedback.objects.filter(extraction=extraction)}
        self.assertEqual(fb, {'title'})

    def test_capture_without_text_returns_none(self):
        from core.extraction.capture import persist_extraction_capture
        out = persist_extraction_capture(
            book=self.book, attachment=self.attachment,
            suggested={'book_number': '1'}, final={}, user=self.user)
        self.assertIsNone(out)
        self.assertFalse(OCRResult.objects.filter(attachment=self.attachment).exists())

    def test_capture_never_raises(self):
        from core.extraction.capture import persist_extraction_capture
        # attachment=None → يعيد None بهدوء بلا استثناء (الالتقاط لا يُفشل الحفظ)
        self.assertIsNone(persist_extraction_capture(
            book=self.book, attachment=None,
            suggested={'raw_text': 'x'}, final={}, user=self.user))

    def test_capture_populates_letterhead_memory(self):
        """حفظ كتاب بجهة مؤكَّدة يُنشئ ذاكرة ترويسة (تعلّمٌ تراكمي لاقتراح الجهة)."""
        from core.extraction.capture import persist_extraction_capture
        ent = Entity.objects.create(name='قسم المتابعة', code='ش13',
                                    etype='issuer', is_active=True)
        self.book.issuing_entities.add(ent)
        suggested = {'raw_text': 'جمهورية العراق\nشركة نفط الوسط\nالعدد\nم/ طلب',
                     'ocr_engine': 'tesseract', 'overall_confidence': 0.7}
        persist_extraction_capture(book=self.book, attachment=self.attachment,
                                   suggested=suggested, final={'title': 'x'}, user=self.user)
        mem = LetterheadMemory.objects.filter(book=self.book)
        self.assertEqual(mem.count(), 1)
        self.assertEqual(mem.first().issuing_entity_id, ent.id)
        self.assertIn('نفط الوسط', mem.first().letterhead)


class EntityMatcherTfidfTests(TestCase):
    """رابط الجهات TF-IDF: يرتّب الجهة الصحيحة أولاً + تطبيع عربي + فلترة النوع."""

    def setUp(self):
        self.e1 = Entity.objects.create(name='وزارة الكهرباء', code='ELEC', etype='issuer', is_active=True)
        self.e2 = Entity.objects.create(name='وزارة الصحة', code='HLTH', etype='issuer', is_active=True)
        self.e3 = Entity.objects.create(name='شركة نفط الوسط', code='MDOC', etype='receiver', is_active=True)

    def test_ranks_correct_entity_first(self):
        from core.extraction.matchers.entity import EntityMatcher
        matches = EntityMatcher().match_entity('وزارة الكهرباء')
        self.assertTrue(matches)
        self.assertEqual(matches[0]['entity_id'], self.e1.id)
        self.assertEqual(matches[0]['match_type'], 'tfidf')

    def test_arabic_normalization_tolerant(self):
        from core.extraction.matchers.entity import EntityMatcher
        # تاء مربوطة → هاء (اختلاف إملائي) يجب أن يطابق رغمه
        matches = EntityMatcher().match_entity('وزاره الكهرباء')
        self.assertTrue(matches)
        self.assertEqual(matches[0]['entity_id'], self.e1.id)

    def test_type_filter_excludes_wrong_type(self):
        from core.extraction.matchers.entity import EntityMatcher
        m = EntityMatcher()
        rec = m.match_entity('شركة نفط الوسط', entity_type='receiver')
        self.assertTrue(rec and rec[0]['entity_id'] == self.e3.id)
        iss = m.match_entity('شركة نفط الوسط', entity_type='issuer')
        self.assertFalse(any(x['entity_id'] == self.e3.id for x in iss))

    def test_letterhead_suggests_issuer_from_top_lines(self):
        """اسم الجهة في ترويسة المستند (لا في «من X») يجب أن يظهر ضمن أفضل-3."""
        from core.extraction.matchers.entity import EntityMatcher
        text = (
            'جمهورية العراق\n'
            'وزارة الكهرباء\n'          # الجهة المُرسِلة في الترويسة
            'العدد: 12345\n'
            'التاريخ: 2026/01/15\n'
            'إلى / وزارة الصحة المحترمة\n'
            'م/ طلب تزويد بالطاقة\n'
            'نرجو تزويدنا بالمعلومات المطلوبة وتفضلوا بقبول الاحترام\n'
        )
        matches = EntityMatcher().match_from_letterhead(text, entity_type='issuer', top_k=3)
        self.assertTrue(matches, 'يجب أن يُرجِع اقتراحات من الترويسة')
        self.assertIn(self.e1.id, [m['entity_id'] for m in matches])
        self.assertEqual(matches[0]['match_type'], 'letterhead')

    def test_letterhead_empty_text_is_safe(self):
        from core.extraction.matchers.entity import EntityMatcher
        self.assertEqual(EntityMatcher().match_from_letterhead('', entity_type='issuer'), [])
        self.assertEqual(EntityMatcher().match_from_letterhead('   ', entity_type='issuer'), [])


class LetterheadMemoryMatchTests(TestCase):
    """ذاكرة الترويسة: تكشف الوحدة الداخلية غير المطبوعة بتشابه ترويسة مستندٍ سابق."""

    def setUp(self):
        # وحدتان داخليّتان لا تُطبعان على ورق المُرسِلين الخارجيّين المختلفين
        self.oil_dept = Entity.objects.create(name='قسم المتابعة', code='ش13',
                                              etype='issuer', is_active=True)
        self.edu_dept = Entity.objects.create(name='شعبة المناهج', code='ت5',
                                              etype='issuer', is_active=True)
        LetterheadMemory.objects.create(
            letterhead='جمهورية العراق شركة نفط الوسط المحدودة حقل بدرة العدد التاريخ',
            issuing_entity=self.oil_dept)
        LetterheadMemory.objects.create(
            letterhead='وزارة التربية المديرية العامة للمناهج والكتب المدرسية العدد',
            issuing_entity=self.edu_dept)

    def test_similar_letterhead_recovers_internal_unit(self):
        from core.extraction.matchers.entity import EntityMatcher
        # مستند جديد من نفس المُرسِل — الوحدة غير مذكورة نصّاً لكن الذاكرة تكشفها
        text = ('جمهورية العراق\nشركة نفط الوسط المحدودة\nحقل بدرة\nالعدد: 512\n'
                'التاريخ: 2026\nم/ طلب معلومات\nنرجو تزويدنا بالبيانات')
        m = EntityMatcher().match_from_memory(text, entity_type='issuer', top_k=3)
        self.assertTrue(m, 'يجب أن تُرجِع الذاكرة اقتراحاً لترويسة مشابهة')
        self.assertEqual(m[0]['entity_id'], self.oil_dept.id)
        self.assertEqual(m[0]['match_type'], 'memory')

    def test_ranking_discriminates_between_senders(self):
        """ترويسة تربية تُرتّب شعبة المناهج أولاً لا قسم المتابعة (تمييز صحيح)."""
        from core.extraction.matchers.entity import EntityMatcher
        text = ('وزارة التربية\nالمديرية العامة للمناهج والكتب المدرسية\n'
                'العدد: 33\nبخصوص توزيع المناهج')
        m = EntityMatcher().match_from_memory(text, entity_type='issuer', top_k=3)
        self.assertTrue(m)
        self.assertEqual(m[0]['entity_id'], self.edu_dept.id)

    def test_empty_or_no_memory_is_safe(self):
        from core.extraction.matchers.entity import EntityMatcher
        self.assertEqual(EntityMatcher().match_from_memory('', entity_type='issuer'), [])
        LetterheadMemory.objects.all().delete()
        self.assertEqual(
            EntityMatcher().match_from_memory('شركة نفط الوسط', entity_type='issuer'), [])


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


class AIProcessingServiceTests(TestCase):
    """اختبارات خدمة المعالجة الذكية"""

    @mock.patch('core.extraction.pipeline.build_online_provider_from_settings')
    @mock.patch('core.extraction.pipeline.AIIntegrationSettings.get_active_settings')
    @mock.patch('core.extraction.pipeline.build_offline_provider_from_settings')
    @mock.patch('core.extraction.pipeline.OCRService')
    @mock.patch('core.extraction.pipeline.ImageProcessor')
    def test_invalid_image_does_not_bootstrap_ocr_stack(
        self,
        image_processor_cls,
        ocr_cls,
        offline_factory,
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
        offline_factory.assert_not_called()
        settings_getter.assert_not_called()
        build_online_provider.assert_not_called()

    @mock.patch('core.extraction.pipeline.build_online_provider_from_settings')
    @mock.patch('core.extraction.pipeline.AIIntegrationSettings.get_active_settings')
    @mock.patch('core.extraction.pipeline.ArabicOCROptimizer')
    @mock.patch('core.extraction.pipeline.build_offline_provider_from_settings')
    @mock.patch('core.extraction.pipeline.OCRService')
    @mock.patch('core.extraction.pipeline.ImageProcessor')
    def test_pattern_and_entity_consumption_succeeds(
        self,
        image_processor_cls,
        ocr_cls,
        offline_factory,
        arabic_cls,
        settings_getter,
        build_online_provider,
    ):
        """B1/B2: استهلاك الأنماط والجهات لا يفشل، ويملأ التاريخ والجهة المُصدِرة.

        يحرس ضد خطأين كانا يُبتلَعان في except العام فتصير الحالة 'failed':
        B1 = عدم تطابق عقد بيانات الأنماط (مفتاح 'date' + قيم مفردة لا tuples).
        B2 = استهلاك extract_entities (List[Tuple]) كأنه dict عبر .get().
        """
        entity = Entity.objects.create(
            name='جهة تجريبية', code='T1', etype='both', is_active=True,
        )

        ocr_cls.return_value.clean_text.side_effect = lambda t: t
        # «التاريخ:» تسميةُ الحقل الشرعية — صيغة «بتاريخ» الظرفية صارت تُرفض عمداً
        # (إحالات المتن)، وباب التاريخ العام الخلفي اقتُلع من الأنبوب.
        offline_factory.return_value.extract.return_value = {
            'raw_text': 'كتاب وارد سري من جهة تجريبية.\nالتاريخ: 15-01-2024\nرقم الكتاب: 99',
            'avg_confidence': 0.9,
        }
        settings_getter.return_value = {'AI_PROVIDER': 'offline'}

        with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp:
            tmp.write(b'\xff\xd8\xff\xe0fake')
            temp_path = tmp.name
        self.addCleanup(lambda: os.path.exists(temp_path) and os.remove(temp_path))

        service = AIExtractionService()
        # نستدعي الدالة الداخلية مباشرة (لا process_image) لتفادي تشغيلها في thread
        # منفصل: في TestCase تعمل المعاملة بلا commit، فاتصال الـ thread الآخر لا يرى
        # الجهة المُنشأة. المنطق المُختبَر واحد — الغلاف الخارجي مجرّد مهلة زمنية.
        result = service._process_image_internal(temp_path)

        self.assertNotEqual(result.status, 'failed', msg=result.error_message)
        # B1 + قاعدة المالك: التاريخ استُخرج فعلاً، ويُسنَد لتاريخ الجهة المُرسِلة
        # (أيُّ تاريخ في المستند = تاريخ المُرسِل)؛ وتاريخنا = تاريخ الإدخال لا يُستخرَج.
        self.assertTrue(result.sender_date and result.sender_date.startswith('2024-01-15'))
        self.assertIsNone(result.book_date)
        self.assertEqual(result.book_number, '99')
        # B2: مطابقة الجهة المُصدِرة نجحت دون AttributeError
        self.assertEqual(result.issuing_entity_id, entity.id)

    @mock.patch('core.extraction.pipeline.build_online_provider_from_settings')
    @mock.patch('core.extraction.pipeline.AIIntegrationSettings.get_active_settings')
    @mock.patch('core.extraction.pipeline.build_offline_provider_from_settings')
    @mock.patch('core.extraction.pipeline.OCRService')
    @mock.patch('core.extraction.pipeline.ImageProcessor')
    def test_cache_hit_still_extracts_patterns_and_entities(
        self,
        image_processor_cls,
        ocr_cls,
        offline_factory,
        settings_getter,
        build_online_provider,
    ):
        """إصابة الكاش تختصر OCR فقط — الأنماط والجهات تُعادان حيّتين.

        بلاغ المالك (2026-07-07): نفس الكتاب، المرة الأولى استخرج الجهة والمرة
        الثانية لا — لأن الإصابة كانت تُرجِع نتيجة مجمَّدة بلا جهات ولا رقم/تاريخ
        الجهة (الكاش لا يخزّنها أصلاً). العقد الآن: الكاش ناقل نصّ، وكل تحسّن
        لاحق في المُستخرِجات/الذاكرة/دمج الجهات يسري فوراً على الوثائق المخزَّنة.
        """
        from django.utils import timezone as dj_tz

        entity = Entity.objects.create(
            name='جهة مخزَّنة', code='C1', etype='both', is_active=True,
        )
        raw = 'كتاب وارد من جهة مخزَّنة.\nالتاريخ: 20-06-2026\nرقم الكتاب: 77'

        with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp:
            tmp.write(b'\xff\xd8\xff\xe0cached-doc')
            temp_path = tmp.name
        self.addCleanup(lambda: os.path.exists(temp_path) and os.remove(temp_path))

        import hashlib
        with open(temp_path, 'rb') as f:
            file_hash = hashlib.md5(f.read()).hexdigest()
        ExtractionCache.objects.create(
            image_hash=file_hash,
            cached_extraction={'raw_text': raw, 'cleaned_text': raw,
                               'ocr_confidence': 0.9},
            hit_count=0, last_used=dj_tz.now(),
        )

        service = AIExtractionService()
        result = service._process_image_internal(temp_path)

        self.assertNotEqual(result.status, 'failed', msg=result.error_message)
        self.assertTrue(result.cached)
        # لا OCR ولا معالجة صورة — النص من الكاش
        image_processor_cls.assert_not_called()
        offline_factory.return_value.extract.assert_not_called()
        # الحقول الحيّة استُخرجت رغم الإصابة: الجهة والتاريخ والرقم
        self.assertEqual(result.issuing_entity_id, entity.id)
        self.assertTrue(result.sender_date and result.sender_date.startswith('2026-06-20'))
        self.assertEqual(result.book_number, '77')
        # الإصابة لا تعيد كتابة الصفّ (يحفظ عدّاد الاستخدام)
        self.assertEqual(ExtractionCache.objects.get(image_hash=file_hash).hit_count, 1)

    @mock.patch('core.extraction.pipeline.NUMBER_EMISSION_ENABLED', True)
    @mock.patch('core.extraction.pipeline.AIExtractionService._read_handwritten_sender_number')
    @mock.patch('core.extraction.pipeline.build_online_provider_from_settings')
    @mock.patch('core.extraction.pipeline.AIIntegrationSettings.get_active_settings')
    @mock.patch('core.extraction.pipeline.build_offline_provider_from_settings')
    @mock.patch('core.extraction.pipeline.OCRService')
    @mock.patch('core.extraction.pipeline.ImageProcessor')
    def test_handwritten_fallback_fills_missing_sender_number(
        self, image_processor_cls, ocr_cls, offline_factory,
        settings_getter, build_online_provider, hw_read,
    ):
        """مرحلة 3: حين تصمت الطبقات المطبوعة عن رقم الجهة، قارئ خط اليد يملؤه
        (فوق بوابة الثقة المُعايَرة) — ولا يمسّ رقماً وجدته الطبقات الأدنى."""
        ocr_cls.return_value.clean_text.side_effect = lambda t: t
        offline_factory.return_value.extract.return_value = {
            'raw_text': 'جمهورية العراق\nالتاريخ: 15-01-2026\nم/ اجتماع',
            'avg_confidence': 0.9,
        }
        settings_getter.return_value = {'AI_PROVIDER': 'offline'}
        # العقد الجديد (خيار F): (number_result, date_crop) — number_result=(نصّ، ثقة، صندوق)
        # العقد صار ثلاثيّاً 2026-08-18: (قراءة، قصاصة تاريخ، (صندوق الكاشف، W, H))
        # — الصندوق يُحفَظ حتى حين يمتنع القارئ، فتُلتقط الحالات الصعبة لا الناجحة وحدها.
        hw_read.return_value = (('1754', 0.95, [0.11, 0.15, 0.20, 0.18]), None, None,
                                (None, 2480, 3508))

        with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp:
            tmp.write(b'\xff\xd8\xff\xe0hw-doc')
            temp_path = tmp.name
        self.addCleanup(lambda: os.path.exists(temp_path) and os.remove(temp_path))

        service = AIExtractionService()
        result = service._process_image_internal(temp_path)

        self.assertNotEqual(result.status, 'failed', msg=result.error_message)
        hw_read.assert_called_once()                       # لا رقم مطبوع ⇒ استُدعي
        self.assertEqual(result.sender_number, '1754')
        self.assertAlmostEqual(result.sender_number_confidence, 0.95)

    @mock.patch('core.extraction.pipeline.NUMBER_EMISSION_ENABLED', True)
    @mock.patch('core.extraction.pipeline.AIExtractionService._read_handwritten_sender_number')
    @mock.patch('core.extraction.pipeline.build_online_provider_from_settings')
    @mock.patch('core.extraction.pipeline.AIIntegrationSettings.get_active_settings')
    @mock.patch('core.extraction.pipeline.build_offline_provider_from_settings')
    @mock.patch('core.extraction.pipeline.OCRService')
    @mock.patch('core.extraction.pipeline.ImageProcessor')
    def test_handwritten_fallback_skipped_when_printed_number_found(
        self, image_processor_cls, ocr_cls, offline_factory,
        settings_getter, build_online_provider, hw_read,
    ):
        ocr_cls.return_value.clean_text.side_effect = lambda t: t
        offline_factory.return_value.extract.return_value = {
            'raw_text': 'جمهورية العراق\nالعدد: 4412\nالتاريخ: 15-01-2026',
            'avg_confidence': 0.9,
        }
        settings_getter.return_value = {'AI_PROVIDER': 'offline'}

        with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp:
            tmp.write(b'\xff\xd8\xff\xe0printed-doc')
            temp_path = tmp.name
        self.addCleanup(lambda: os.path.exists(temp_path) and os.remove(temp_path))

        service = AIExtractionService()
        result = service._process_image_internal(temp_path)

        self.assertEqual(result.sender_number, '4412')     # الطبقة المطبوعة أصابت
        hw_read.assert_not_called()                        # فلا حاجة لخط اليد


class TesseractOCRProviderTests(TestCase):
    """اختبار محرّك Tesseract الجديد دون تشغيل tesseract فعلياً (يُحاكى pytesseract)."""

    def test_extract_reconstructs_lines_and_confidence(self):
        from core.extraction.ocr.providers import TesseractOCRProvider
        provider = TesseractOCRProvider()  # آمن: لا يشغّل tesseract، فقط يضبط المسارات

        fake_data = {
            'text':      ['وزارة', 'الكهرباء', '', 'أمر', 'إداري'],
            'conf':      ['96', '95', '-1', '90', '88'],  # ‑1 = لا نص، يُستثنى
            'block_num': [1, 1, 1, 2, 2],
            'par_num':   [1, 1, 1, 1, 1],
            'line_num':  [1, 1, 1, 1, 1],
        }
        with mock.patch.object(provider._pytesseract, 'image_to_data', return_value=fake_data), \
                mock.patch.object(provider, '_to_pil', return_value=object()):
            res = provider.extract('/fake/path.png')

        # إعادة بناء سطرين منفصلين (block مختلف) بترتيب الكلمات
        self.assertIn('وزارة الكهرباء', res['raw_text'])
        self.assertIn('أمر إداري', res['raw_text'])
        self.assertEqual(res['num_lines'], 2)
        # متوسّط الثقة = mean(96,95,90,88)/100 — مع استثناء ‑1 والنص الفارغ
        self.assertAlmostEqual(res['avg_confidence'], (96 + 95 + 90 + 88) / 4 / 100.0, places=3)

    def test_extract_escalates_to_binary_on_low_confidence(self):
        """ثقة رمادية منخفضة → يُجرَّب التحويل الثنائي ويُحتفَظ بالأعلى ثقةً."""
        from core.extraction.ocr.providers import TesseractOCRProvider
        from PIL import Image
        provider = TesseractOCRProvider()
        provider.adaptive_threshold = 0.75

        low = {'text': ['نص', 'ضعيف'], 'conf': ['40', '50'],
               'block_num': [1, 1], 'par_num': [1, 1], 'line_num': [1, 1]}
        high = {'text': ['نص', 'واضح'], 'conf': ['92', '94'],
                'block_num': [1, 1], 'par_num': [1, 1], 'line_num': [1, 1]}
        real_img = Image.new('L', (20, 20), 255)
        with mock.patch.object(provider, '_to_pil', return_value=real_img), \
                mock.patch.object(provider._pytesseract, 'image_to_data',
                                  side_effect=[low, high]) as m:
            res = provider.extract('/fake.png')
        self.assertEqual(m.call_count, 2)              # رمادي ثم ثنائي
        self.assertIn('نص واضح', res['raw_text'])      # احتُفظ بنتيجة الثنائي الأعلى
        self.assertAlmostEqual(res['avg_confidence'], (92 + 94) / 2 / 100.0, places=3)

    def test_extract_keeps_grayscale_when_binary_worse(self):
        """إن كان الثنائي أسوأ ثقةً → يُرفَض ويبقى الرمادي (حماية من الذيل الكارثي)."""
        from core.extraction.ocr.providers import TesseractOCRProvider
        from PIL import Image
        provider = TesseractOCRProvider()
        provider.adaptive_threshold = 0.75

        low = {'text': ['أصلي'], 'conf': ['60'],
               'block_num': [1], 'par_num': [1], 'line_num': [1]}
        worse = {'text': ['سيئ'], 'conf': ['20'],
                 'block_num': [1], 'par_num': [1], 'line_num': [1]}
        real_img = Image.new('L', (20, 20), 255)
        with mock.patch.object(provider, '_to_pil', return_value=real_img), \
                mock.patch.object(provider._pytesseract, 'image_to_data',
                                  side_effect=[low, worse]):
            res = provider.extract('/fake.png')
        self.assertIn('أصلي', res['raw_text'])         # رُفض الثنائي الأسوأ


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

    def test_save_book_api_captures_training_data_from_scan_token(self):
        """حلقة التدريب: حفظ كتاب ممسوح يُثبّت OCRResult+DataExtractionResult+ExtractionFeedback."""
        import io
        from django.core.cache import cache
        from PIL import Image

        token = 'tok-capture-1'
        cache.set(f'scan_token:{token}', {
            'raw_text': 'نصّ ممسوح كامل من المستند الإداري',
            'ocr_engine': 'tesseract',
            'title': 'عنوان مُقترَح من OCR',   # يختلف عن النهائي → feedback
            'secret_level': 'normal',          # مطابق → لا feedback
            'book_number': '88',
            'overall_confidence': 0.7,
        }, timeout=300)

        buf = io.BytesIO()
        Image.new('RGB', (12, 12), 'white').save(buf, format='JPEG')
        scan_file = SimpleUploadedFile('scan.jpg', buf.getvalue(), content_type='image/jpeg')

        response = self.client.post(reverse('save-book-api'), {
            'book_number': '2024-CAP-001',
            'date': timezone.now().date().isoformat(),
            'title': 'العنوان النهائي المؤكَّد',
            'kind': 'incoming_internal',
            'issuing_entity_id': str(self.entity.id),
            'scan_token': token,
            'file': scan_file,
        })

        self.assertEqual(response.status_code, 201, response.content)
        book = Book.objects.get(pk=response.json()['book_id'])
        extraction = DataExtractionResult.objects.get(book=book)
        self.assertEqual(extraction.ocr_result.raw_text, 'نصّ ممسوح كامل من المستند الإداري')
        self.assertTrue(ExtractionFeedback.objects.filter(
            extraction=extraction, field_name='title').exists())

    def test_save_book_api_without_scan_token_skips_capture(self):
        """بلا scan_token: لا التقاط — والحفظ العادي غير متأثّر."""
        before = OCRResult.objects.count()
        response = self.client.post(reverse('save-book-api'), {
            'book_number': '2024-CAP-002',
            'date': timezone.now().date().isoformat(),
            'title': 'بلا مسح',
            'kind': 'incoming_internal',
            'issuing_entity_id': str(self.entity.id),
        })
        self.assertEqual(response.status_code, 201)
        self.assertEqual(OCRResult.objects.count(), before)

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

        # 6. إشارةُ التعلّم مُسجَّلة (التحليلُ نفسه صار في `learning_stats`)
        self.assertEqual(feedback.extraction_id, result.id)
        self.assertEqual(
            ExtractionFeedback.objects.filter(extraction=result, field_name='title').count(), 1)
