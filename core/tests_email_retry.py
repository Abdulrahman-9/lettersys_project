"""
حلقة إعادة الإرسال — اختبارات انحدار لسجلّ العيوب ح2.

الحالة قبلها: التوثيق يدّعي «محاولةً واحدةً لكلّ سجلّ (تجنّب حلقة لانهائية)»
والكود لا ينفّذه — المُرسِل يُنشئ صفّاً جديداً ولا يمسّ الأصل، فيبقى الأصل
`failed` أبداً ويُعاد إرساله كلّ تشغيل، وكلّ محاولةٍ فاشلة تُضيف مرشَّحاً جديداً.
عدمُ جدولة المهمّة كان سترًا عرضيّاً: أوّلُ خادمٍ فيه Redis وbeat يُفجّرها.
"""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from core.models import Book, BookEmailLog, EmailSettings
from core.tasks import retry_failed_emails_task


def _stale(log, minutes=30):
    """‏sent_at بـauto_now_add — نُقدِّمه بتحديثٍ مباشر ليتجاوز عتبة الخمس دقائق."""
    BookEmailLog.objects.filter(pk=log.pk).update(
        sent_at=timezone.now() - timedelta(minutes=minutes)
    )
    log.refresh_from_db()
    return log


class RetryLoopTests(TestCase):

    def setUp(self):
        cache.clear()
        cfg = EmailSettings.get()
        cfg.is_active = True
        cfg.save()
        self.user = User.objects.create_user('sender', password='pw-sender-1')
        self.book = Book.objects.create(
            kind='incoming_internal', title='كتاب', created_by=self.user,
        )
        self.failed = _stale(BookEmailLog.objects.create(
            book=self.book, to_address='x@example.com', subject='فشل',
            status=BookEmailLog.STATUS_FAILED, sent_by=self.user,
        ))

    def _run_with_failing_sender(self, times=1):
        """كلّ محاولةٍ تُنشئ صفّاً فاشلاً جديداً — سلوك المُرسِل الحقيقيّ."""
        def fake_send(book=None, recipients=None, subject='', html_body='',
                      cc=None, trigger='auto', sent_by=None, entity=None, **kw):
            return BookEmailLog.objects.create(
                book=book, to_address=recipients[0], subject=subject,
                status=BookEmailLog.STATUS_FAILED, sent_by=sent_by,
            )

        results = []
        with patch('core.messaging.engines.smtp.send_book_notification', side_effect=fake_send):
            for _ in range(times):
                results.append(retry_failed_emails_task())
                for log in BookEmailLog.objects.all():
                    _stale(log)
                cache.delete('lock:retry_failed_emails')
        return results

    def test_original_is_abandoned_after_max_retries(self):
        self._run_with_failing_sender(times=BookEmailLog.MAX_RETRIES + 2)
        self.failed.refresh_from_db()
        self.assertEqual(self.failed.status, BookEmailLog.STATUS_ABANDONED)
        self.assertEqual(self.failed.retry_count, BookEmailLog.MAX_RETRIES)

    def test_retry_rows_never_enter_the_queue(self):
        """الحشد المتنامي: كانت صفوف المحاولات نفسها تصير مرشَّحاتٍ بدورها."""
        self._run_with_failing_sender(times=BookEmailLog.MAX_RETRIES + 2)
        attempts = BookEmailLog.objects.filter(retry_of__isnull=False)
        self.assertEqual(attempts.count(), BookEmailLog.MAX_RETRIES,
                         'عدد المحاولات تجاوز الحدّ — الحشد ما زال ينمو')
        self.assertTrue(all(a.retry_count == 0 for a in attempts))

    def test_queue_dries_up(self):
        """التشغيلة التالية بعد استنفاد المحاولات لا تجد شيئاً."""
        self._run_with_failing_sender(times=BookEmailLog.MAX_RETRIES)
        last = self._run_with_failing_sender(times=1)[0]
        self.assertEqual(last.get('candidates'), 0, 'الطابور لم يجفّ')

    def test_success_closes_the_original(self):
        def ok_send(book=None, recipients=None, subject='', html_body='',
                    cc=None, trigger='auto', sent_by=None, entity=None, **kw):
            return BookEmailLog.objects.create(
                book=book, to_address=recipients[0], subject=subject,
                status=BookEmailLog.STATUS_SENT, sent_by=sent_by,
            )

        with patch('core.messaging.engines.smtp.send_book_notification', side_effect=ok_send):
            retry_failed_emails_task()
        self.failed.refresh_from_db()
        self.assertEqual(self.failed.status, BookEmailLog.STATUS_SENT)

    def test_concurrent_runs_are_locked_out(self):
        cache.add('lock:retry_failed_emails', 1, timeout=600)
        self.assertEqual(retry_failed_emails_task(), {'skipped': 'already running'})

    def test_inactive_email_is_a_noop(self):
        cfg = EmailSettings.get()
        cfg.is_active = False
        cfg.save()
        self.assertEqual(retry_failed_emails_task(), {'skipped': 'email not active'})


class BeatScheduleTests(TestCase):
    """الجدولة لا تُضاف إلّا بعد أن يصير الوعد صادقاً — هذا الاختبار يوثّق الترتيب."""

    def test_task_is_scheduled(self):
        from django.conf import settings

        tasks = {entry['task'] for entry in settings.CELERY_BEAT_SCHEDULE.values()}
        self.assertIn('core.tasks.retry_failed_emails_task', tasks)
