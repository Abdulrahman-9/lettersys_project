"""
قطيع مزامنة الوارد — اختبارات انحدار لسجلّ العيوب م1 وم2.

كانت البوّابة تقرأ ختماً (`imap_last_sync`) لا يُكتب إلّا **بعد** انتهاء
المزامنة، والمزامنة تجري متزامنةً داخل طلب الويب. فكلّ الطلبات الواصلة أثناء
مزامنةٍ جارية تجتازها معاً وتفتح اتصالات IMAP متوازية — لا يظهر بمستخدمٍ واحد،
ويظهر يقيناً بقسمٍ كامل.
"""

from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from core.messaging.views.ui import INBOX_SYNC_LOCK_KEY, _autosync_inbox_if_due
from core.models import EmailSettings


class InboxAutosyncGuardTests(TestCase):

    def setUp(self):
        cache.clear()
        cfg = EmailSettings.get()
        cfg.imap_sync_enabled = True
        cfg.imap_last_sync = None
        cfg.save()

    def test_concurrent_callers_sync_once(self):
        """المحاكاة الدقيقة للقطيع: الثاني يصل **قبل** أن ينتهي الأوّل."""
        calls = []

        def slow_sync(self_engine, *a, **kw):
            calls.append(1)
            if len(calls) == 1:
                _autosync_inbox_if_due()      # داخلٌ ثانٍ أثناء الأولى
            return {'fetched': 0, 'new': 0}

        with patch('core.messaging.engines.imap.IMAPEngine.sync_inbox', slow_sync):
            _autosync_inbox_if_due()

        self.assertEqual(len(calls), 1, 'فُتحت مزامنةٌ ثانية بجانب الجارية')

    def test_stamp_is_written_before_the_work(self):
        """ختمُ البدء يُغلق نافذة القطيع حتى لو تعثّرت المزامنة."""
        seen = {}

        def failing_sync(self_engine, *a, **kw):
            seen['stamp'] = EmailSettings.get().imap_last_sync
            raise RuntimeError('انقطاع الشبكة')

        with patch('core.messaging.engines.imap.IMAPEngine.sync_inbox', failing_sync):
            _autosync_inbox_if_due()          # لا يجوز أن يرمي

        self.assertIsNotNone(seen.get('stamp'), 'الختم لم يُكتب قبل العمل')
        self.assertIsNotNone(EmailSettings.get().imap_last_sync)

    def test_lock_is_released_after_failure(self):
        def failing_sync(self_engine, *a, **kw):
            raise RuntimeError('انقطاع')

        with patch('core.messaging.engines.imap.IMAPEngine.sync_inbox', failing_sync):
            _autosync_inbox_if_due()

        self.assertIsNone(cache.get(INBOX_SYNC_LOCK_KEY), 'القفل بقي محتجزاً بعد الفشل')

    def test_cooldown_still_respected(self):
        cfg = EmailSettings.get()
        cfg.imap_last_sync = timezone.now()
        cfg.save()

        with patch('core.messaging.engines.imap.IMAPEngine.sync_inbox') as sync:
            _autosync_inbox_if_due()
        sync.assert_not_called()

    def test_disabled_sync_is_a_noop(self):
        cfg = EmailSettings.get()
        cfg.imap_sync_enabled = False
        cfg.save()

        with patch('core.messaging.engines.imap.IMAPEngine.sync_inbox') as sync:
            _autosync_inbox_if_due()
        sync.assert_not_called()


class ImapStampGoesThroughSaveTests(TestCase):
    """م2: ختمُ الانتهاء عبر ``save`` لا ``update`` الذي يتجاوز منطق النموذج.

    الاختبار سلوكيّ لا شكليّ: كلمةُ سرّ SMTP تُشفَّر في ``EncryptedFieldsMixin.save``
    ويفكّها ``from_db``. فلو مرّ الختم عبر ``save`` بقيت الكلمة مقروءةً صحيحة،
    ولو تجاوزه بقيت الحالة سليمةً أيضاً — لذا نحرس الأثر المباشر: الختم كُتب
    والقيمة الحسّاسة لم تُفسَد، ثمّ نتحقّق أنّ لا كتابةً تتجاوز النموذج بقيت
    في مسار المزامنة.
    """

    class _FakeConn:
        """اتصالٌ وهميّ بلا رسائل — يكفي لبلوغ سطر الختم."""

        def select(self, folder):
            return ('OK', [b'0'])

        def search(self, charset, criteria):
            return ('OK', [b''])

        def close(self):
            pass

        def logout(self):
            pass

    def test_stamp_written_and_secrets_survive(self):
        from core.messaging.engines.imap import IMAPEngine

        cfg = EmailSettings.get()
        cfg.imap_sync_enabled = True
        cfg.imap_last_sync = None
        cfg.smtp_password = 'secret-pw'
        cfg.save()

        with patch.object(IMAPEngine, 'get_connection', return_value=self._FakeConn()):
            IMAPEngine(EmailSettings.get()).sync_inbox()

        fresh = EmailSettings.get()
        self.assertIsNotNone(fresh.imap_last_sync, 'ختمُ الانتهاء لم يُكتب')
        self.assertEqual(fresh.smtp_password, 'secret-pw', 'الحقل المشفَّر فسد')

    def test_no_manager_level_update_bypasses_the_model(self):
        """حارسُ انحدار: عودةُ ``objects.filter(...).update(imap_last_sync=...)``
        تعني تجاوز منطق الحفظ ثانيةً — وهو ما سيكسر تعدّد حسابات البريد."""
        import inspect

        from core.messaging.engines import imap as imap_module

        source = inspect.getsource(imap_module)
        self.assertNotIn('.update(imap_last_sync', source)
