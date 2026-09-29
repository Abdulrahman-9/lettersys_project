"""
نطاق رؤية البريد — اختبارات انحدار لسجلّ العيوب ح1.

الحالة قبل هذه الاختبارات: **صفر** اختبار يمسّ عروض البريد، بينما `mail_sent`
و`mail_inbox` و`mail_thread` و`mail_compose` و`book_email_logs` تعرض بريد كلّ
الكتب لأيّ مستخدمٍ مسجَّل، وعدّاد غير المقروء يُحسب على النظام كلّه.

كلّ اختبار هنا يفشل على الكود القديم وينجح على الجديد.
"""

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from core.models import Book, BookEmailLog, EmailThread, IncomingEmail


class MailScopeTestCase(TestCase):
    """كتابان لمالكين مختلفين، ولكلٍّ بريدٌ صادر ووارد."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user('alice', password='pw-alice-1')
        cls.bob   = User.objects.create_user('bob',   password='pw-bob-111')
        # مدير النظام هو من يرى الكلّ الآن — `is_staff` صارت صفةً إداريّةً
        # لواجهات الإدارة لا توسيعاً للرؤية (المرحلة أ).
        cls.staff = User.objects.create_superuser('boss', 'boss@x.com', 'pw-boss-11')

        cls.book_a = Book.objects.create(
            kind='incoming_internal', title='كتاب أليس', created_by=cls.alice,
        )
        cls.book_b = Book.objects.create(
            kind='incoming_internal', title='كتاب بوب', created_by=cls.bob,
        )

        cls.log_a = BookEmailLog.objects.create(
            book=cls.book_a, to_address='a@example.com', subject='صادر أليس', status='sent',
        )
        cls.log_b = BookEmailLog.objects.create(
            book=cls.book_b, to_address='b@example.com', subject='صادر بوب', status='sent',
        )

        cls.thread_a = EmailThread.objects.create(book=cls.book_a, subject='خيط أليس')
        cls.thread_b = EmailThread.objects.create(book=cls.book_b, subject='خيط بوب')
        cls.orphan_thread = EmailThread.objects.create(subject='خيط بلا كتاب')

        cls.inc_a = IncomingEmail.objects.create(
            thread=cls.thread_a, message_id='<a@x>', from_address='x@example.com',
            subject='وارد أليس', received_at=timezone.now(), is_read=False,
        )
        cls.inc_b = IncomingEmail.objects.create(
            thread=cls.thread_b, message_id='<b@x>', from_address='y@example.com',
            subject='وارد بوب', received_at=timezone.now(), is_read=False,
        )
        cls.inc_orphan = IncomingEmail.objects.create(
            thread=cls.orphan_thread, message_id='<o@x>', from_address='z@example.com',
            subject='وارد يتيم', received_at=timezone.now(), is_read=False,
        )


class SentMailScopeTests(MailScopeTestCase):

    def test_user_sees_only_own_book_mail(self):
        self.client.force_login(self.alice)
        page = self.client.get('/books/mail/sent/').context['page_obj']
        subjects = {log.subject for log in page.object_list}
        self.assertIn('صادر أليس', subjects)
        self.assertNotIn('صادر بوب', subjects, 'بريد كتابِ غيره ظهر في صادره')

    def test_stats_match_the_filtered_set(self):
        """العدّاد لا يُسرّب ما تُخفيه القائمة."""
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get('/books/mail/sent/').context['stats']['total'], 1)

    def test_staff_still_sees_everything(self):
        self.client.force_login(self.staff)
        page = self.client.get('/books/mail/sent/').context['page_obj']
        self.assertEqual({log.subject for log in page.object_list}, {'صادر أليس', 'صادر بوب'})


class InboxScopeTests(MailScopeTestCase):

    def test_user_sees_only_replies_to_own_books(self):
        self.client.force_login(self.alice)
        page = self.client.get('/books/mail/inbox/').context['page_obj']
        subjects = {m.subject for m in page.object_list}
        self.assertEqual(subjects, {'وارد أليس'})

    def test_unread_counter_is_scoped(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get('/books/mail/inbox/').context['unread_count'], 1)

    def test_orphan_mail_is_admin_only(self):
        """رسالةٌ بلا كتابٍ مرتبط لا مالك لها ⟵ الإداريّ وحده."""
        self.client.force_login(self.staff)
        page = self.client.get('/books/mail/inbox/').context['page_obj']
        self.assertIn('وارد يتيم', {m.subject for m in page.object_list})
        self.assertEqual(self.client.get('/books/mail/inbox/').context['unread_count'], 3)


class ThreadAccessTests(MailScopeTestCase):

    def test_cannot_open_foreign_thread(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(f'/books/mail/thread/{self.thread_b.pk}/').status_code, 403)

    def test_can_open_own_thread(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(f'/books/mail/thread/{self.thread_a.pk}/').status_code, 200)

    def test_foreign_thread_stays_unread(self):
        """الفشل الصامت الأسوأ: فتحُ خيطِ غيرك كان يؤشّره مقروءاً له أيضاً."""
        self.client.force_login(self.alice)
        self.client.get(f'/books/mail/thread/{self.thread_b.pk}/')
        self.inc_b.refresh_from_db()
        self.assertFalse(self.inc_b.is_read)

    def test_staff_opens_any_thread(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(f'/books/mail/thread/{self.thread_b.pk}/').status_code, 200)


class ComposeScopeTests(MailScopeTestCase):

    def test_cannot_prefill_from_foreign_book(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(f'/books/mail/compose/{self.book_b.pk}/').status_code, 404)

    def test_own_book_prefills(self):
        self.client.force_login(self.alice)
        resp = self.client.get(f'/books/mail/compose/{self.book_a.pk}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['book'].pk, self.book_a.pk)


class BookEmailLogsApiTests(MailScopeTestCase):
    """IDOR: سجلّات بريد أيّ كتاب كانت تُقرأ برقمه."""

    URL = '/books/api/email/logs/{}/'

    def test_foreign_book_logs_are_not_readable(self):
        self.client.force_login(self.alice)
        resp = self.client.get(self.URL.format(self.book_b.pk))
        self.assertEqual(resp.status_code, 404)
        self.assertNotIn('b@example.com', resp.content.decode('utf-8'))

    def test_own_book_logs_readable(self):
        self.client.force_login(self.alice)
        resp = self.client.get(self.URL.format(self.book_a.pk))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('a@example.com', resp.content.decode('utf-8'))

    def test_staff_reads_any(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(self.URL.format(self.book_b.pk)).status_code, 200)


class MailApiScopeTests(MailScopeTestCase):
    """نقاط الـAPI العشر — سبعٌ منها كانت IDOR قراءةً أو كتابةً."""

    def setUp(self):
        self.client.force_login(self.alice)

    # ── قراءة ──
    def test_thread_detail_is_scoped(self):
        resp = self.client.get(f'/books/mail/api/thread/{self.thread_b.pk}/')
        self.assertEqual(resp.status_code, 404)
        self.assertNotIn('خيط بوب', resp.content.decode('utf-8'))

    def test_own_thread_detail_works(self):
        self.assertEqual(self.client.get(f'/books/mail/api/thread/{self.thread_a.pk}/').status_code, 200)

    def test_stats_are_scoped(self):
        data = self.client.get('/books/mail/api/stats/').json()
        self.assertEqual(data['sent_total'], 1)
        self.assertEqual(data['inbox_total'], 1)

    def test_template_preview_cannot_leak_foreign_book(self):
        from core.models import EmailTemplate

        tpl = EmailTemplate.objects.create(
            name='قالب', slug='t1',
            subject_template='{{ book.title }}', body_html='{{ book.title }}',
        )
        body = self.client.get(
            f'/books/mail/api/template/{tpl.pk}/preview/?book_id={self.book_b.pk}'
        ).json()['body']
        self.assertNotIn('كتاب بوب', body)

    # ── كتابة ──
    def test_cannot_mark_foreign_message_read(self):
        resp = self.client.post(f'/books/mail/api/inbox/{self.inc_b.pk}/read/')
        self.assertEqual(resp.status_code, 404)
        self.inc_b.refresh_from_db()
        self.assertFalse(self.inc_b.is_read)

    def test_can_mark_own_message_read(self):
        self.assertEqual(self.client.post(f'/books/mail/api/inbox/{self.inc_a.pk}/read/').status_code, 200)
        self.inc_a.refresh_from_db()
        self.assertTrue(self.inc_a.is_read)

    def test_cannot_change_foreign_thread_status(self):
        before = self.thread_b.status
        resp = self.client.post(
            f'/books/mail/api/thread/{self.thread_b.pk}/status/',
            data='{"status": "closed"}', content_type='application/json',
        )
        self.assertEqual(resp.status_code, 404)
        self.thread_b.refresh_from_db()
        self.assertEqual(self.thread_b.status, before)


class NavbarUnreadBadgeTests(MailScopeTestCase):
    """عدّاد الشريط العلوي كان عامّاً بمفتاح كاشٍ مشترك — يظهر في كلّ صفحة."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def test_badge_counts_only_visible_mail(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get('/').context['mail_inbox_unread'], 1)

    def test_cache_key_is_per_user(self):
        """المستخدم الثاني لا يرث عدّاد الأوّل من الكاش."""
        self.client.force_login(self.alice)
        self.client.get('/')
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get('/').context['mail_inbox_unread'], 3)


class BooklessMailTests(MailScopeTestCase):
    """‏`BookEmailLog.book` صار اختياريّاً (هجرة 0061) — سجل العيوب ح3.

    كان إلزاميّاً، فسقط مسار الإنشاء إلى **أوّل كتابٍ في القاعدة** لمجرّد إرضاء
    القيد: بريدٌ إداريّ يُسجَّل في تاريخ كتابٍ لا صلة له به.
    """

    def test_compose_without_book_does_not_touch_any_book(self):
        from unittest.mock import patch

        self.client.force_login(self.alice)
        before = {log.pk: log.book_id for log in BookEmailLog.objects.all()}

        with patch('core.messaging.engines.smtp.SMTPEngine.send_book_notification') as send:
            send.return_value = BookEmailLog.objects.create(
                book=None, to_address='x@example.com', subject='بلا كتاب',
                status='sent', sent_by=self.alice,
            )
            resp = self.client.post(
                '/books/mail/api/compose/',
                data='{"to": "x@example.com", "subject": "س", "body": "ب"}',
                content_type='application/json',
            )

        self.assertNotEqual(resp.status_code, 400, 'رُفض الإرسال بلا كتاب')
        after = {log.pk: log.book_id for log in BookEmailLog.objects.filter(pk__in=before)}
        self.assertEqual(before, after, 'تغيّر ربطُ سجلٍّ قائم بكتابه')
        self.assertFalse(
            BookEmailLog.objects.filter(subject='بلا كتاب', book__isnull=False).exists(),
            'الرسالة بلا كتاب عُلّقت على كتابٍ رغم ذلك',
        )

    def test_sender_sees_own_bookless_mail(self):
        """الوصل عبر book__ يُسقط الصفوف الفارغة — فمالكها مُرسِلها."""
        BookEmailLog.objects.create(
            book=None, to_address='x@example.com', subject='رسالتي بلا كتاب',
            status='sent', sent_by=self.alice,
        )
        self.client.force_login(self.alice)
        page = self.client.get('/books/mail/sent/').context['page_obj']
        self.assertIn('رسالتي بلا كتاب', {log.subject for log in page.object_list})

    def test_others_do_not_see_it(self):
        BookEmailLog.objects.create(
            book=None, to_address='x@example.com', subject='رسالة أليس',
            status='sent', sent_by=self.alice,
        )
        self.client.force_login(self.bob)
        page = self.client.get('/books/mail/sent/').context['page_obj']
        self.assertNotIn('رسالة أليس', {log.subject for log in page.object_list})

    def test_foreign_book_id_is_refused_not_silently_dropped(self):
        """كتابٌ طُلب وهو خارج نطاقك: رفضٌ صريح لا سقوطٌ صامتٌ إلى «بلا كتاب».

        السقوط الصامت يجعل المستخدم يظنّ رسالته عُلّقت على كتابه.
        """
        self.client.force_login(self.alice)
        resp = self.client.post(
            '/books/mail/api/compose/',
            data=('{"to": "x@example.com", "subject": "س", "body": "ب", '
                  f'"book_id": {self.book_b.pk}}}'),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(BookEmailLog.objects.filter(subject='س').exists())


class SecretBookMailTests(TestCase):
    """البريدُ **محتوى** لا صفّ — تقريرُ فيبل لتفاصيل الكتاب، P0 البند 1.

    مَن لا يرى من السرّيّ إلّا كعبَه (زميلُ القسم بلا دور) كان يأخذ من أربع نقاطٍ
    ما يحجبه عنه الكعب: العنوانَ في تعبئة الموضوع، ومواضيعَ السجلّ، والعنوانَ
    وأسماءَ الملفّات في المعاينة — **ويُرسل المرفقاتِ فعلاً**. والنقاطُ كانت تسأل
    ``scope_books_for`` (الصفّ) لا ``can_open_content`` (المظروف).
    """

    TITLE = 'مناقصةُ الحفر السرّيّة'

    @classmethod
    def setUpTestData(cls):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from core.models import Attachment, Department, EmailSettings, Entity, UserProfile

        dept = Department.objects.create(name='المتابعة', code='ش13-mail')

        def member(name, head=False):
            u = User.objects.create_user(name, password=f'pw-{name}-1111')
            UserProfile.objects.create(user=u, department=dept, is_department_head=head)
            return u

        cls.head = member('mailhead', head=True)     # مخوَّلٌ بالدور داخل قسمه
        cls.member = member('mailmember')             # يرى الكعبَ وحده

        cls.entity = Entity.objects.create(name='وزارة النفط', email='oil@example.com')
        cls.book = Book.objects.create(
            kind='incoming_external', title=cls.TITLE, created_by=cls.head,
            department=dept, our_number='2440', secret_level='secret',
        )
        cls.book.issuing_entities.add(cls.entity)
        Attachment.objects.create(
            book=cls.book,
            file=SimpleUploadedFile('secret-scan.pdf', b'%PDF-1.4 x', content_type='application/pdf'),
        )
        BookEmailLog.objects.create(
            book=cls.book, to_address='oil@example.com',
            subject='بشأن ' + cls.TITLE, status='sent',
        )

        cfg = EmailSettings.get()
        cfg.smtp_host, cfg.smtp_user, cfg.smtp_password = 'smtp.x.com', 'me@x.com', 'app-pass-16'
        cfg.is_active = True
        cfg.save()

    def _get(self, user, url):
        self.client.force_login(user)
        return self.client.get(url)

    def _send(self, user):
        from unittest.mock import patch

        self.client.force_login(user)
        with patch('core.messaging.engines.smtp.SMTPEngine.send_book_notification') as send:
            send.return_value = type('L', (), {'status': 'sent', 'error_msg': '', 'pk': 1})()
            resp = self.client.post(f'/books/api/email/book/{self.book.pk}/send/',
                                    data='{}', content_type='application/json')
        return resp, send

    def assertSealed(self, resp):
        self.assertEqual(resp.status_code, 404)
        self.assertNotIn(self.TITLE, resp.content.decode('utf-8'))

    # ── الأربعُ المسمّاةُ في التقرير ──
    def test_compose_prefill_is_sealed(self):
        self.assertSealed(self._get(self.member, f'/books/mail/compose/{self.book.pk}/'))

    def test_logs_are_sealed(self):
        self.assertSealed(self._get(self.member, f'/books/api/email/logs/{self.book.pk}/'))

    def test_preview_is_sealed(self):
        resp = self._get(self.member, f'/books/api/email/book/{self.book.pk}/preview/')
        self.assertSealed(resp)
        self.assertNotIn('2440.pdf', resp.content.decode('utf-8'))

    def test_send_is_refused_and_nothing_leaves(self):
        resp, send = self._send(self.member)
        self.assertEqual(resp.status_code, 404)
        send.assert_not_called()

    # ── والمخوَّلُ يعمل كما كان ──
    def test_the_custodian_composes(self):
        resp = self._get(self.head, f'/books/mail/compose/{self.book.pk}/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(self.TITLE, resp.context['prefill']['subject'])

    def test_the_custodian_reads_logs(self):
        resp = self._get(self.head, f'/books/api/email/logs/{self.book.pk}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()['logs']), 1)

    def test_the_custodian_previews(self):
        resp = self._get(self.head, f'/books/api/email/book/{self.book.pk}/preview/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['book']['title'], self.TITLE)

    def test_the_custodian_sends(self):
        resp, send = self._send(self.head)
        self.assertEqual(resp.status_code, 200)
        send.assert_called_once()

    # ── وأخواتُها من الباب نفسِه (لم يسمّها التقرير) ──
    def test_template_preview_does_not_render_the_secret_title(self):
        from core.models import EmailTemplate

        tpl = EmailTemplate.objects.create(
            name='قالب', slug='t-secret',
            subject_template='{{ book.title }}', body_html='{{ book.title }}',
        )
        url = f'/books/mail/api/template/{tpl.pk}/preview/?book_id={self.book.pk}'
        self.assertNotIn(self.TITLE, self._get(self.member, url).json()['body'])
        self.assertIn(self.TITLE, self._get(self.head, url).json()['body'])

    def test_compose_api_refuses_to_hang_mail_on_the_sealed_book(self):
        self.client.force_login(self.member)
        resp = self.client.post(
            '/books/mail/api/compose/',
            data=('{"to": "x@example.com", "subject": "س", "body": "ب", '
                  f'"book_id": {self.book.pk}}}'),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 404)
