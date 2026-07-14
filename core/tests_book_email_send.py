# -*- coding: utf-8 -*-
"""إرسال الكتاب إلى الجهة المعنيّة مع مرفقاته + الروابط الموقّعة.

الخلل الذي عالجته هذه الميزة: محرّك SMTP يدعم المرفقات منذ البداية
(``send_book_notification(attachments=...)``) لكن **لم يكن أي مسار يمرّرها** — فكان
النظام يرسل إشعاراً نصّياً عن الكتاب ولا يُرسل الملفات الممسوحة أبداً.

وحدّ البريد (Gmail ~25MB) يُقاس على الرسالة **بعد** ترميز base64 (تضخيم ~37%)،
فالميزانية الخام 18MB، وما يتجاوزها يُستبدَل برابط موقّع محدود المدة.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.attachment_sharing import (
    MAX_EMAIL_ATTACH_BYTES,
    make_share_token,
    plan_book_attachments,
    read_share_token,
)
from core.models import Attachment, Book, EmailSettings, Entity


def _make_attachment(book, name, size):
    return Attachment.objects.create(
        book=book,
        file=SimpleUploadedFile(name, b'x' * size, content_type='application/pdf'),
    )


class ShareTokenTests(TestCase):
    """الرابط الموقّع: لا يُزوَّر، ينتهي، ويفتح مرفقاً واحداً بعينه."""

    def test_token_roundtrip(self):
        self.assertEqual(read_share_token(make_share_token(77)), 77)

    def test_tampered_token_is_rejected(self):
        token = make_share_token(77)
        self.assertIsNone(read_share_token(token + 'x'))

    def test_expired_token_is_rejected(self):
        self.assertIsNone(read_share_token(make_share_token(77), max_age=-1))


class SharedDownloadViewTests(TestCase):
    """نقطة التحميل العامّة — المسار الوحيد المفتوح على المرفقات."""

    def setUp(self):
        user = get_user_model().objects.create_user(username='dl', password='pw-dl-12345')
        self.book = Book.objects.create(
            title='كتاب', kind='outgoing_external', our_number='20260001',
            date=timezone.now().date(), created_by=user,
        )
        self.att = _make_attachment(self.book, 'doc.pdf', 1024)

    def test_valid_token_downloads_without_login(self):
        """الجهة الخارجية لا حساب لها — الرابط يجب أن يعمل دون تسجيل دخول."""
        url = reverse('attachment_share', args=[make_share_token(self.att.pk)])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('attachment', resp['Content-Disposition'])

    def test_forged_token_is_404(self):
        resp = self.client.get(reverse('attachment_share', args=['not-a-real-token']))
        self.assertEqual(resp.status_code, 404)

    def test_deleted_attachment_is_not_served_even_with_valid_token(self):
        url = reverse('attachment_share', args=[make_share_token(self.att.pk)])
        self.att.is_deleted = True
        self.att.save(update_fields=['is_deleted'])
        self.assertEqual(self.client.get(url).status_code, 404)


class AttachmentBudgetTests(TestCase):
    """ميزانية الإرفاق: الأصغر أولاً، وما يتجاوزها يصير رابطاً — بلا اقتطاع صامت."""

    def setUp(self):
        user = get_user_model().objects.create_user(username='bud', password='pw-bud-12345')
        self.book = Book.objects.create(
            title='كتاب', kind='outgoing_external', our_number='20260002',
            date=timezone.now().date(), created_by=user,
        )

    def test_small_files_are_all_attached(self):
        _make_attachment(self.book, 'a.pdf', 1000)
        _make_attachment(self.book, 'b.pdf', 2000)

        plan = plan_book_attachments(self.book)

        self.assertEqual(len(plan['attach']), 2)
        self.assertEqual(plan['link'], [])

    def test_oversized_file_becomes_a_link_not_an_attachment(self):
        _make_attachment(self.book, 'small.pdf', 1000)
        _make_attachment(self.book, 'huge.pdf', MAX_EMAIL_ATTACH_BYTES + 1)

        plan = plan_book_attachments(self.book)

        self.assertEqual(len(plan['attach']), 1)
        self.assertEqual(len(plan['link']), 1)
        # الأصغر يُرفَق والأكبر يصير رابطاً
        self.assertLess(plan['attach'][0]['size'], plan['link'][0]['size'])

    def test_recipient_sees_an_official_name_not_internal_storage_name(self):
        """اسم التخزين (20260002_scan_JZM9Kks.pdf) لا يليق بمستند رسمي."""
        _make_attachment(self.book, 'scan.pdf', 1000)

        plan = plan_book_attachments(self.book)

        self.assertEqual(plan['attach'][0]['name'], '20260002.pdf')

    def test_multiple_files_are_numbered(self):
        _make_attachment(self.book, 'a.pdf', 1000)
        _make_attachment(self.book, 'b.pdf', 2000)

        plan = plan_book_attachments(self.book)

        self.assertEqual(
            sorted(i['name'] for i in plan['attach']),
            ['20260002_1.pdf', '20260002_2.pdf'],
        )

    def test_budget_is_shared_across_files(self):
        """ملفان كلٌّ منهما تحت الحد، ومجموعهما فوقه ⇒ الثاني يصير رابطاً."""
        half = MAX_EMAIL_ATTACH_BYTES // 2 + 10
        _make_attachment(self.book, 'one.pdf', half)
        _make_attachment(self.book, 'two.pdf', half)

        plan = plan_book_attachments(self.book)

        self.assertEqual(len(plan['attach']), 1)
        self.assertEqual(len(plan['link']), 1)

    def test_no_file_is_silently_dropped(self):
        for i in range(3):
            _make_attachment(self.book, f'f{i}.pdf', MAX_EMAIL_ATTACH_BYTES)

        plan = plan_book_attachments(self.book)

        self.assertEqual(len(plan['attach']) + len(plan['link']) + len(plan['failed']), 3)


class SendBookToEntityTests(TestCase):
    """نقطة الإرسال: ترفض بصدق حين لا تستطيع، وتُمرّر المرفقات حين تستطيع."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='sender', password='pw-send-12345', is_staff=True,
        )
        self.client.force_login(self.user)

        self.entity = Entity.objects.create(name='وزارة الاختبار', email='dest@example.com')
        self.book = Book.objects.create(
            title='كتاب رسمي', kind='outgoing_external', our_number='20260003',
            date=timezone.now().date(), created_by=self.user,
        )
        self.book.receiving_entities.add(self.entity)
        _make_attachment(self.book, 'scan.pdf', 2048)

        cfg = EmailSettings.get()
        cfg.smtp_host = 'smtp.gmail.com'
        cfg.smtp_user = 'me@gmail.com'
        cfg.smtp_password = 'app-password-16'
        cfg.is_active = True
        cfg.save()

    def test_preview_lists_entity_and_files(self):
        resp = self.client.get(reverse('book-email-preview', args=[self.book.pk]))
        data = resp.json()

        self.assertTrue(data['success'])
        self.assertEqual(data['entity']['email'], 'dest@example.com')
        self.assertEqual([f['name'] for f in data['files']], ['20260003.pdf'])
        self.assertEqual(data['files'][0]['mode'], 'attach')

    @patch('core.messaging.engines.smtp.SMTPEngine.send_book_notification')
    def test_send_passes_the_files_to_the_engine(self, mock_send):
        """جوهر الإصلاح: الملفات تصل فعلاً إلى محرّك الإرسال."""
        mock_send.return_value = type('L', (), {'status': 'sent', 'error_msg': ''})()

        resp = self.client.post(reverse('book-email-send', args=[self.book.pk]),
                                data='{}', content_type='application/json')

        self.assertEqual(resp.status_code, 200)
        attachments = mock_send.call_args.kwargs['attachments']
        self.assertEqual(len(attachments), 1)
        name, content, mime = attachments[0]
        self.assertEqual(name, '20260003.pdf')      # اسم رسمي، لا اسم تخزين
        self.assertEqual(len(content), 2048)
        self.assertEqual(mime, 'application/pdf')

    def test_send_is_refused_when_email_is_disabled(self):
        cfg = EmailSettings.get()
        cfg.is_active = False
        cfg.save()

        resp = self.client.post(reverse('book-email-send', args=[self.book.pk]),
                                data='{}', content_type='application/json')

        self.assertEqual(resp.status_code, 400)
        self.assertIn('معطّل', resp.json()['message'])

    def test_send_is_refused_when_entity_has_no_email(self):
        self.entity.email = ''
        self.entity.save(update_fields=['email'])

        resp = self.client.post(reverse('book-email-send', args=[self.book.pk]),
                                data='{}', content_type='application/json')

        self.assertEqual(resp.status_code, 400)
        self.assertIn('بريد', resp.json()['message'])
