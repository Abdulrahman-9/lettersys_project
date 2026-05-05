"""
اختبارات نظام الدمج الذكي — Phase 1 محدّث
"""

from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from core.models import Book, Entity, Attachment, MergeLog
from core.merge_service import SmartMergeService


class SmartMergeServiceTestCase(TestCase):
    """اختبارات خدمة الدمج الذكية"""

    def setUp(self):
        """إعداد بيانات الاختبار"""
        self.user = User.objects.create_user(username='testuser', password='testpass123')

        self.issuing = Entity.objects.create(name='جهة مصدرة', code='ISSUE', etype='issuer')
        self.receiving = Entity.objects.create(name='جهة مستقبلة', code='RCV', etype='receiver')

        self.book = Book.objects.create(
            our_number='001',
            kind='incoming_internal',
            title='كتاب اختبار',
            date=timezone.now(),
            created_by=self.user
        )
        self.book.issuing_entities.add(self.issuing)
        self.book.receiving_entities.add(self.receiving)

        self.pdf_file = SimpleUploadedFile(
            'test.pdf',
            b'%PDF-1.4\n%Test PDF',
            content_type='application/pdf'
        )
        self.attachment = Attachment.objects.create(book=self.book, file=self.pdf_file)

    def test_service_initialization(self):
        """اختبار تهيئة الخدمة"""
        service = SmartMergeService(self.attachment, self.user)
        self.assertEqual(service.attachment.id, self.attachment.id)
        self.assertEqual(service.user.id, self.user.id)

    def test_delete_file(self):
        """اختبار حذف الملف"""
        service = SmartMergeService(self.attachment, self.user)
        service.delete_current_file(reason='ملف خاطئ')

        self.attachment.refresh_from_db()
        self.assertTrue(self.attachment.is_deleted)
        self.assertEqual(self.attachment.deleted_by.id, self.user.id)

        log = MergeLog.objects.filter(attachment=self.attachment, action='delete').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.status, 'success')


class AttachmentMergeAPITestCase(TestCase):
    """اختبارات API الدمج"""

    def setUp(self):
        """إعداد بيانات الاختبار"""
        self.client = Client()

        self.user = User.objects.create_user(username='testuser', password='testpass123')
        self.issuing = Entity.objects.create(name='جهة مصدرة', code='ISSUE', etype='issuer')
        self.receiving = Entity.objects.create(name='جهة مستقبلة', code='RCV', etype='receiver')

        self.book = Book.objects.create(
            our_number='001',
            kind='incoming_internal',
            title='كتاب اختبار',
            date=timezone.now(),
            created_by=self.user
        )
        self.book.issuing_entities.add(self.issuing)
        self.book.receiving_entities.add(self.receiving)

        pdf_file = SimpleUploadedFile('test.pdf', b'%PDF-1.4')
        self.attachment = Attachment.objects.create(book=self.book, file=pdf_file)

        self.client.login(username='testuser', password='testpass123')

    def test_versions_api(self):
        """اختبار API قائمة الإصدارات"""
        url = f'/api/attachments/{self.attachment.id}/versions/'
        response = self.client.get(url)
        # Placeholder — extend based on actual API implementation
