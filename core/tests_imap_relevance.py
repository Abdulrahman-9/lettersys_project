# -*- coding: utf-8 -*-
"""بوّابة الصلة — ما الذي يدخل «وارد» النظام؟

المشكلة الواقعية: صندوق البريد المستخدَم شخصي، وفيه (قيس فعلياً) **13,442 رسالة
غير مقروءة** — إعلانات واشتراكات وبريد جامعي. وكان ``sync_inbox`` يحوّل *كل*
رسالة غير مقروءة إلى ``IncomingEmail`` وينشئ لها «خيطاً يتيماً» — فيتحوّل وارد
النظام إلى صندوق قمامة بلا قيمة.

القاعدة الآن: لا يدخل إلا
  1. ردٌّ على رسالة أرسلها النظام (مطابقة ``BookEmailLog.smtp_message_id``)، أو
  2. رسالة من بريد جهة مسجّلة ونشِطة.
وما عداهما يُحصى في ``ignored`` ولا يُخزَّن.

ملاحظة: البند 1 يتطلّب حفظ Message-ID لكل رسالة صادرة — وهو حقل كان موجوداً في
النموذج و**لا يُملأ أبداً**؛ يملؤه ``SMTPEngine`` الآن.
"""

from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from core.messaging.engines.imap import IMAPEngine
from core.models import Book, BookEmailLog, EmailSettings, Entity, IncomingEmail


class RelevanceGateTests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user(username='rel', password='pw-rel-12345')
        self.entity = Entity.objects.create(name='وزارة', email='ministry@example.gov')
        self.book = Book.objects.create(
            title='كتاب', kind='outgoing_external', our_number='20260010',
            date=timezone.now().date(), created_by=self.user,
        )
        self.log = BookEmailLog.objects.create(
            book=self.book, to_address='ministry@example.gov', subject='كتاب',
            status=BookEmailLog.STATUS_SENT, smtp_message_id='<our-sent-msg@lettersys>',
        )

    def test_reply_to_our_message_is_relevant(self):
        self.assertTrue(IMAPEngine.is_relevant(
            'anyone@wherever.com', '<our-sent-msg@lettersys>', '',
        ))

    def test_reply_found_via_references_chain(self):
        """الردود المتسلسلة تحمل السلسلة في References لا في In-Reply-To وحده."""
        self.assertTrue(IMAPEngine.is_relevant(
            'anyone@wherever.com', '', '<x@a> <our-sent-msg@lettersys> <y@b>',
        ))

    def test_mail_from_registered_entity_is_relevant(self):
        self.assertTrue(IMAPEngine.is_relevant('ministry@example.gov', '', ''))

    def test_entity_match_is_case_insensitive(self):
        self.assertTrue(IMAPEngine.is_relevant('MINISTRY@Example.Gov', '', ''))

    def test_random_personal_mail_is_ignored(self):
        """جوهر الفلتر: البريد الشخصي/الإعلاني لا يدخل النظام."""
        self.assertFalse(IMAPEngine.is_relevant('newsletter@shop.com', '', ''))

    def test_inactive_entity_is_not_a_pass(self):
        self.entity.is_active = False
        self.entity.save(update_fields=['is_active'])
        self.assertFalse(IMAPEngine.is_relevant('ministry@example.gov', '', ''))

    def test_unknown_reference_is_not_a_pass(self):
        self.assertFalse(IMAPEngine.is_relevant('spam@x.com', '<not-ours@elsewhere>', ''))


class SyncIngestsOnlyRelevantTests(TestCase):
    """التكامل: مزامنة صندوق مختلط تُخزّن ما يخصّنا وتتجاهل الباقي."""

    def setUp(self):
        user = get_user_model().objects.create_user(username='mix', password='pw-mix-12345')
        Entity.objects.create(name='وزارة', email='ministry@example.gov')
        book = Book.objects.create(
            title='كتاب', kind='outgoing_external', our_number='20260011',
            date=timezone.now().date(), created_by=user,
        )
        BookEmailLog.objects.create(
            book=book, to_address='ministry@example.gov', subject='كتاب',
            status=BookEmailLog.STATUS_SENT, smtp_message_id='<sent-1@lettersys>',
        )

        cfg = EmailSettings.get()
        cfg.imap_host = 'imap.gmail.com'
        cfg.imap_user = 'me@gmail.com'
        cfg.imap_password = 'app-password-16'
        cfg.imap_sync_enabled = True
        cfg.save()
        self.cfg = cfg

    MESSAGES = {
        b'1': (b'From: Shop <newsletter@shop.com>\r\n'
               b'Subject: Sale\r\nMessage-ID: <n1@shop>\r\n\r\nbuy'),
        b'2': (b'From: Ministry <ministry@example.gov>\r\n'
               b'Subject: Reply\r\nMessage-ID: <r1@gov>\r\n'
               b'In-Reply-To: <sent-1@lettersys>\r\n\r\nrad'),
        b'3': (b'From: Spam <spam@x.com>\r\n'
               b'Subject: Win\r\nMessage-ID: <s1@x>\r\n\r\nwin'),
    }

    def _conn(self, uids=b'1 2 3'):
        conn = MagicMock()
        conn.search.return_value = ('OK', [uids])
        conn.fetch.side_effect = lambda uid, _spec: ('OK', [(uid, self.MESSAGES[uid])])
        return conn

    @patch.object(IMAPEngine, 'get_connection')
    def test_only_relevant_messages_are_stored(self, mock_conn):
        conn = self._conn()
        mock_conn.return_value = conn

        stats = IMAPEngine(self.cfg).sync_inbox()

        self.assertEqual(stats['new'], 1, 'يجب أن تُخزَّن رسالة واحدة فقط (الرد)')
        self.assertEqual(stats['ignored'], 2, 'الإعلان والسبام يجب أن يُتجاهلا')
        stored = list(IncomingEmail.objects.values_list('from_address', flat=True))
        self.assertEqual(stored, ['ministry@example.gov'])

    @patch.object(IMAPEngine, 'get_connection')
    def test_irrelevant_mail_body_is_never_downloaded(self, mock_conn):
        """كفاءة: لا نُنزّل جسم رسالة لا تخصّنا — الترويسة تكفي للحكم."""
        conn = self._conn()
        mock_conn.return_value = conn

        IMAPEngine(self.cfg).sync_inbox()

        specs = [c.args[1] for c in conn.fetch.call_args_list]
        self.assertEqual(specs.count('(BODY.PEEK[HEADER])'), 3)  # ترويسة لكل رسالة
        self.assertEqual(specs.count('(BODY.PEEK[])'), 1)        # جسم الرد وحده

    @patch.object(IMAPEngine, 'get_connection')
    def test_personal_mail_is_not_marked_read_on_the_real_server(self, mock_conn):
        """أثر جانبي كان قائماً: RFC822 يضع \\Seen — فكانت المزامنة «تقرأ» بريد
        المستخدم الشخصي نيابةً عنه. الآن: PEEK، ولا نضع \\Seen إلا لما ابتلعناه."""
        conn = self._conn()
        mock_conn.return_value = conn

        IMAPEngine(self.cfg).sync_inbox()

        marked = [c.args[0] for c in conn.store.call_args_list]
        self.assertEqual(marked, [b'2'], 'وُسمت رسائل لا تخصّ النظام كمقروءة')

    @patch.object(IMAPEngine, 'get_connection')
    def test_reply_is_linked_back_to_its_book(self, mock_conn):
        """الردّ يجب أن يعرف كتابه — وإلا وصل يتيماً بلا معنى."""
        mock_conn.return_value = self._conn(uids=b'2')

        IMAPEngine(self.cfg).sync_inbox()

        incoming = IncomingEmail.objects.get()
        self.assertIsNotNone(incoming.thread.book, 'الرد غير مربوط بكتاب')
        self.assertEqual(incoming.thread.book.our_number, '20260011')
        self.assertEqual(incoming.thread.status, 'replied')

    @patch.object(IMAPEngine, 'get_connection')
    def test_reply_raises_an_in_app_notification(self, mock_conn):
        """وصول رد بلا تنبيه = رد لا يعلم به أحد."""
        from core.models import Notification

        mock_conn.return_value = self._conn(uids=b'2')

        IMAPEngine(self.cfg).sync_inbox()

        notif = Notification.objects.filter(category='email')
        self.assertTrue(notif.exists(), 'لم يُنشأ أي تنبيه عند وصول الرد')
        self.assertIn('20260011', notif.first().title)


class InboxAutoSyncTests(TestCase):
    """المزامنة عند فتح الوارد — تعمل بلا Celery ولا Redis، بمهلة تبريد."""

    def setUp(self):
        cfg = EmailSettings.get()
        cfg.imap_host = 'imap.gmail.com'
        cfg.imap_user = 'me@gmail.com'
        cfg.imap_password = 'app-password-16'
        cfg.imap_sync_enabled = True
        cfg.imap_last_sync = None
        cfg.save()

    @patch('core.messaging.engines.imap.IMAPEngine.sync_inbox')
    def test_opening_inbox_syncs_when_due(self, mock_sync):
        from core.messaging.views.ui import _autosync_inbox_if_due
        mock_sync.return_value = {'new': 0}

        _autosync_inbox_if_due()

        mock_sync.assert_called_once()

    @patch('core.messaging.engines.imap.IMAPEngine.sync_inbox')
    def test_cooldown_prevents_hammering_the_imap_server(self, mock_sync):
        """تحديث الصفحة مراراً يجب ألّا يقصف خادم البريد."""
        from core.messaging.views.ui import _autosync_inbox_if_due

        cfg = EmailSettings.get()
        cfg.imap_last_sync = timezone.now()
        cfg.save(update_fields=['imap_last_sync'])

        _autosync_inbox_if_due()

        mock_sync.assert_not_called()

    @patch('core.messaging.engines.imap.IMAPEngine.sync_inbox')
    def test_disabled_sync_does_nothing(self, mock_sync):
        from core.messaging.views.ui import _autosync_inbox_if_due

        cfg = EmailSettings.get()
        cfg.imap_sync_enabled = False
        cfg.save(update_fields=['imap_sync_enabled'])

        _autosync_inbox_if_due()

        mock_sync.assert_not_called()

    @patch('core.messaging.engines.imap.IMAPEngine.sync_inbox', side_effect=OSError('IMAP down'))
    def test_imap_failure_never_breaks_the_inbox_page(self, _mock_sync):
        """الصندوق يُعرَض من قاعدة البيانات — عطل IMAP لا يجوز أن يُسقط الصفحة."""
        from core.messaging.views.ui import _autosync_inbox_if_due

        _autosync_inbox_if_due()  # لا يرمي
