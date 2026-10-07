# -*- coding: utf-8 -*-
"""أعطالٌ كشفها تدقيقُ نيلسن لكلّ الصفحات (2026‑10‑07) — حارسٌ لكلٍّ منها.

D#3 صفحةُ الجهة بلا حارس دخولٍ ولا نطاقٍ ولا حجب · D#1 «حذف نهائي» يلقى 404 دائماً ·
A#1 حوارُ التحديث الجماعيّ يرسل قيماً يرفضها الخادم · A#3 شارةُ التنبيهات للمدير وحدَه.
"""
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Attachment, Book, Department, Entity, Notification, UserProfile
from core.scoping import STUB_TITLE


class EntityDetailGuardTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.q = Department.objects.create(name='قسمُ الجهة', code='ج.ق')
        cls.kh = Department.objects.create(name='قسمٌ بعيد', code='ج.خ')

        def member(name, dept):
            u = User.objects.create_user(name, password=f'pw-{name}-1111')
            UserProfile.objects.update_or_create(user=u, defaults={'department': dept})
            return u

        cls.author = member('eauthor', cls.q)
        cls.colleague = member('ecolleague', cls.q)
        cls.stranger = member('estranger', cls.kh)
        cls.entity = Entity.objects.create(name='جهةٌ تُراسَل')
        today = timezone.localdate()

        def book(num, title, dept, by, **kw):
            b = Book.objects.create(kind='incoming_external', title=title, our_number=num,
                                    created_by=by, department=dept, date=today, **kw)
            b.issuing_entities.add(cls.entity)
            return b

        cls.plain = book('8101', 'كتابُ القسم العلنيّ', cls.q, cls.author)
        cls.secret = book('8102', 'مناقصةٌ سرّيّةٌ محجوبة', cls.q, cls.author, secret_level='secret')
        cls.far = book('8103', 'كتابُ القسم البعيد', cls.kh, cls.stranger)

    def _page(self, user=None):
        if user:
            self.client.force_login(user)
        return self.client.get(reverse('entity_detail', args=[self.entity.pk]))

    def test_anonymous_is_sent_to_login(self):
        resp = self._page()
        self.assertEqual(resp.status_code, 302)
        self.assertIn(settings.LOGIN_URL.rstrip('/'), resp['Location'])

    def test_the_page_shows_only_the_readers_scope_and_masks_the_secret(self):
        body = self._page(self.colleague).content.decode('utf-8')
        self.assertIn('كتابُ القسم العلنيّ', body)
        self.assertNotIn('كتابُ القسم البعيد', body)
        self.assertNotIn('مناقصةٌ سرّيّةٌ محجوبة', body)
        self.assertIn(STUB_TITLE, body)

    def test_the_author_still_reads_the_secret(self):
        self.assertIn('مناقصةٌ سرّيّةٌ محجوبة', self._page(self.author).content.decode('utf-8'))


class PurgeFromTrashTests(TestCase):

    def setUp(self):
        self.admin = User.objects.create_superuser('padmin', 'p@x.co', 'pw-padmin-1111')
        self.client.force_login(self.admin)
        self.book = Book.objects.create(kind='incoming_internal', title='للحذف', our_number='8201',
                                        created_by=self.admin, is_deleted=True,
                                        deleted_at=timezone.now())

    def test_purge_book_deletes_a_book_in_the_trash(self):
        resp = self.client.post(reverse('purge_book', args=[self.book.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Book.all_objects.filter(pk=self.book.pk).exists())

    def test_purge_attachment_deletes_an_attachment_in_the_trash(self):
        live = Book.objects.create(kind='incoming_internal', title='حيّ', our_number='8202',
                                   created_by=self.admin)
        att = Attachment.objects.create(book=live, file='', is_deleted=True, deleted_at=timezone.now())
        resp = self.client.post(reverse('purge_attachment', args=[att.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Attachment.all_objects.filter(pk=att.pk).exists())


class BulkStatusDialogTests(SimpleTestCase):

    def test_the_dialog_offers_only_what_the_server_accepts(self):
        src = (Path(settings.BASE_DIR) / 'templates' / 'core' / 'book_unified.html').read_text(encoding='utf-8')
        dialog = src[src.index('id="bulkStatusSelect"'):]
        dialog = dialog[:dialog.index('</select>')]
        values = {v for v in __import__('re').findall(r'<option value="([^"]*)"', dialog) if v}
        self.assertEqual(values, {'archived', 'reopen'})


class NotificationBadgeTests(TestCase):

    def test_a_clerk_sees_the_unread_count(self):
        clerk = User.objects.create_user('nclerk', password='pw-nclerk-1111')
        Notification.objects.create(user=clerk, message='أُحيل إليك كتاب')
        self.client.force_login(clerk)
        resp = self.client.get(reverse('dashboard'))
        self.assertEqual(resp.context['navbar_unread_notifications'], 1)
