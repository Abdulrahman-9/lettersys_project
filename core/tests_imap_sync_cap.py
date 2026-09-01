# -*- coding: utf-8 -*-
"""سقف سلامة مزامنة IMAP.

اللغم الذي تحرسه: ``sync_inbox`` كان يجلب **كل** رسالة غير مقروءة، كاملةً
(RFC822). على صندوق حقيقي قيس فعلياً **13,442 رسالة غير مقروءة** — أي أن ضغطة
زر واحدة كانت ستنزّل 13 ألف رسالة دفعةً واحدة وتُجمّد جهاز 8GB أو تُنفِد ذاكرته.

القاعدة: لا تُجلب أكثر من ``MAX_SYNC_MESSAGES`` في مزامنة واحدة، وتُؤخذ **الأحدث**
(هي وحدها ردودٌ محتملة)، ويُبلَّغ عن المتروك في ``skipped`` — لا اقتطاع صامت.
"""

from unittest.mock import MagicMock, patch

from django.test import TestCase

from core.messaging.engines.imap import IMAPEngine
from core.models import EmailSettings


def _conn_with_unseen(count, from_addr=b'stranger@example.com'):
    """اتصال IMAP وهمي يُبلّغ عن ``count`` رسالة غير مقروءة.

    المزامنة تجلب الترويسات أوّلاً (BODY.PEEK[HEADER]) ثم الجسم لما يخصّنا فقط،
    فالوهمي يردّ على الاثنين. الافتراض هنا: مُرسِل غريب (لا يجتاز بوّابة الصلة) —
    فهذه الاختبارات تحرس **السقف** لا الابتلاع.
    """
    conn = MagicMock()
    uids = b' '.join(str(i).encode() for i in range(1, count + 1))
    conn.search.return_value = ('OK', [uids])
    raw = b'From: ' + from_addr + b'\r\nSubject: x\r\nMessage-ID: <x>\r\n\r\nbody'
    conn.fetch.return_value = ('OK', [(b'1', raw)])
    return conn


class IMAPSyncCapTests(TestCase):

    def setUp(self):
        cfg = EmailSettings.get()
        cfg.imap_host = 'imap.gmail.com'
        cfg.imap_user = 'someone@gmail.com'
        cfg.imap_password = 'app-password-16'
        cfg.imap_sync_enabled = True
        cfg.save()
        self.cfg = cfg

    @patch.object(IMAPEngine, 'get_connection')
    def test_huge_inbox_is_capped_not_downloaded_whole(self, mock_conn):
        """الحالة الواقعية: 13,442 غير مقروءة — يجب ألّا تُجلب كلها."""
        conn = _conn_with_unseen(13442)
        mock_conn.return_value = conn

        stats = IMAPEngine(self.cfg).sync_inbox()

        self.assertLessEqual(
            conn.fetch.call_count, IMAPEngine.MAX_SYNC_MESSAGES,
            'كارثة: المزامنة تجلب أكثر من السقف — تُجمّد الجهاز',
        )
        self.assertEqual(stats['fetched'], IMAPEngine.MAX_SYNC_MESSAGES)
        self.assertEqual(stats['skipped'], 13442 - IMAPEngine.MAX_SYNC_MESSAGES)

    @patch.object(IMAPEngine, 'get_connection')
    def test_newest_messages_are_the_ones_fetched(self, mock_conn):
        """الردود هي الأحدث — يجب أخذ ذيل القائمة لا رأسها."""
        conn = _conn_with_unseen(200)
        mock_conn.return_value = conn

        IMAPEngine(self.cfg).sync_inbox(max_messages=3)

        fetched_uids = [c.args[0] for c in conn.fetch.call_args_list]
        self.assertEqual(fetched_uids, [b'198', b'199', b'200'])

    @patch.object(IMAPEngine, 'get_connection')
    def test_small_inbox_fetches_everything_and_skips_nothing(self, mock_conn):
        conn = _conn_with_unseen(4)
        mock_conn.return_value = conn

        stats = IMAPEngine(self.cfg).sync_inbox()

        self.assertEqual(conn.fetch.call_count, 4)
        self.assertEqual(stats['skipped'], 0)

    @patch.object(IMAPEngine, 'get_connection')
    def test_sync_disabled_fetches_nothing(self, mock_conn):
        self.cfg.imap_sync_enabled = False
        self.cfg.save()

        stats = IMAPEngine(self.cfg).sync_inbox()

        mock_conn.assert_not_called()
        self.assertEqual(stats['fetched'], 0)
