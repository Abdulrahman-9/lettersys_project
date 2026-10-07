# -*- coding: utf-8 -*-
"""الدفعةُ الثالثة — بنودُ مذكّرة فيبل (D:/migration/fable_batch3_design_20261007.md).

E#2 الردُّ يبقى في خيطه، والخيطُ ضمن النطاق (كان ``api_compose`` يأخذه بالرقم مطلقاً — IDOR) ·
A#6 «الكلّ» حالةٌ صريحة بنطاقها · B#1 التقريرُ المطبوع يقرأ دورةَ الحياة من بانيها الواحد.
"""
import json
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Book, BookEmailLog, EmailThread
from core.tests_live_counts import LiveCountsTestCase
from core.tests_mail_scope import MailScopeTestCase

SEND = 'core.messaging.engines.smtp.SMTPEngine.send_book_notification'


class MailReplyTests(MailScopeTestCase):

    def _compose(self, **payload):
        body = {'to': 'x@example.com', 'subject': 'رد: خيط', 'body': 'نصّ'}
        body.update(payload)
        return self.client.post(reverse('mail-api-compose'), data=json.dumps(body),
                                content_type='application/json')

    def test_reply_prefills_from_its_thread(self):
        self.client.force_login(self.alice)
        resp = self.client.get(reverse('mail_compose'), {'thread': self.thread_a.pk})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['prefill']['subject'], 'رد: خيط أليس')
        self.assertEqual(resp.context['prefill']['to'], 'x@example.com')
        self.assertContains(resp, 'id="f_thread_id" value="%d"' % self.thread_a.pk)

    def test_a_foreign_thread_is_404_in_the_page(self):
        self.client.force_login(self.alice)
        resp = self.client.get(reverse('mail_compose'), {'thread': self.thread_b.pk})
        self.assertEqual(resp.status_code, 404)

    def test_the_compose_api_refuses_a_foreign_thread(self):
        # خيطُ بوب يحرسه كتابُه أيضاً (الردُّ يرث الكتاب) — أمّا الخيطُ بلا كتاب فلا يحرسه
        # إلّا النطاق: هو ما يقتل طفرةَ الرجوع إلى ``EmailThread.objects.filter(pk=…)``.
        self.client.force_login(self.alice)
        before = BookEmailLog.objects.count()
        for foreign in (self.thread_b, self.orphan_thread):
            with self.subTest(thread=foreign.subject), patch(SEND) as send:
                resp = self._compose(thread_id=foreign.pk)
                self.assertEqual(resp.status_code, 404)
                send.assert_not_called()
        self.assertEqual(BookEmailLog.objects.count(), before)

    def test_a_reply_lands_in_its_thread_without_a_new_one(self):
        self.client.force_login(self.alice)
        threads = EmailThread.objects.count()
        with patch(SEND) as send:
            send.return_value = BookEmailLog.objects.create(
                book=self.book_a, to_address='x@example.com', subject='رد: خيط أليس',
                status='sent', sent_by=self.alice)
            resp = self._compose(thread_id=self.thread_a.pk)
        self.assertEqual(resp.json()['thread_id'], self.thread_a.pk)
        self.assertEqual(EmailThread.objects.count(), threads)
        self.thread_a.refresh_from_db()
        self.assertEqual(self.thread_a.status, EmailThread.STATUS_WAITING)
        log = send.return_value
        log.refresh_from_db()
        self.assertEqual(log.thread_id, self.thread_a.pk)

    def test_the_reply_prefix_is_not_doubled_and_fits_the_log(self):
        from core.messaging.views.ui import reply_subject
        for already in ('رد: س', 'Re: s', 'RE: s', 'ردّ: س'):
            self.assertEqual(reply_subject(already), already)
        self.assertEqual(reply_subject('س'), 'رد: س')
        self.assertLessEqual(len(reply_subject('x' * 300)),
                             BookEmailLog._meta.get_field('subject').max_length)

    def test_a_subject_longer_than_the_log_is_refused_before_sending(self):
        self.client.force_login(self.alice)
        with patch(SEND) as send:
            resp = self._compose(subject='س' * 300)
        self.assertEqual(resp.status_code, 400)
        send.assert_not_called()


class AllTabTests(LiveCountsTestCase):

    def test_tab_all_is_its_own_lit_state(self):
        self.client.force_login(self.clerk)
        resp = self.client.get(reverse('book_unified'), {'tab': 'all', 'followup': 'overdue'})
        body = resp.content.decode('utf-8')
        self.assertIn('data-theme="all"', body)
        self.assertRegex(body, r'data-tab="all"\s+aria-selected="true"')
        self.assertRegex(body, r'data-tab="incoming"\s+aria-selected="false"')
        self.assertIn('id="badge-all">%s<' % resp.context['total_books'], body)

    def test_scope_inside_all_keeps_both_directions(self):
        external = Book.objects.create(
            kind='incoming_external', title='خارجيٌّ حيّ', our_number='7009',
            created_by=self.clerk, department=self.dept, date=self.today, is_archived=False,
            due_date=self.today)
        ids = {b['id'] for b in self._api(tab='all_internal')['books']}
        self.assertIn(self.live_pending.pk, ids)
        self.assertIn(self.live_out.pk, ids)
        self.assertNotIn(external.pk, ids)

    def test_all_is_not_counted_as_a_filter(self):
        from core.views.filter_helpers import BookFilterEngine
        self.assertEqual(BookFilterEngine.active_filters_summary(tab='all')['count'], 0)
        self.assertEqual(BookFilterEngine.active_filters_summary(tab='all_internal')['labels'], ['داخلي'])


def _facts():
    """وقائعُ مصنوعة بالشكل الذي تعيده الخدماتُ — القالبُ يُختبر وحدَه، والخدماتُ لها اختباراتُها."""
    who = SimpleNamespace(get_full_name=lambda: 'منى الموقِّعة', username='mona')
    return {
        'referrals': [{
            'referral': SimpleNamespace(created_by=None, margin=''), 'target': 'وحدةُ التدقيق',
            'purpose': 'للتنفيذ', 'status': 'مُرسَل', 'is_open': True, 'is_overdue': True,
            'due_date': None, 'reminded_at': None, 'reply_number': '2440'}],
        'open_referrals': [1], 'overdue_referrals': [1],
        'custody': [SimpleNamespace(signed_at=timezone.now(), get_event_display=lambda: 'استلام',
                                    holder_name='حامدُ الحامل', recorded_by=None,
                                    get_signature_mode_display=lambda: 'ورقيّ', note='')],
        'links': [{'relation_label': 'جوابٌ عليه', 'number': '2441', 'date': None,
                   'title': 'كتاب مقيَّد', 'restricted': True, 'note': ''}],
        'registrations': [],
        'signatures': [SimpleNamespace(signer=who, get_capacity_display=lambda: 'رئيس القسم',
                                       signed_at=timezone.now(), is_valid=True, revoke_reason='',
                                       verify_token='T0K3N', digest='ab' * 32)],
    }


class ReportLifecycleTests(TestCase):

    def setUp(self):
        self.admin = User.objects.create_superuser('radm', 'r@x.co', 'pw-radm-1111')
        self.client.force_login(self.admin)
        self.book = Book.objects.create(kind='incoming_internal', title='كتابُ التقرير',
                                        our_number='8501', created_by=self.admin)

    def test_the_report_prints_distribution_custody_links_and_signatures(self):
        with patch('core.views.books_detail.lifecycle_facts', return_value=_facts()):
            body = self.client.get(reverse('book_report', args=[self.book.pk])).content.decode('utf-8')
        for needle in ('③ التفريق والردود', 'وحدةُ التدقيق', '2440', '④ سلسلة العهدة', 'حامدُ الحامل',
                       '⑤ كتبٌ مرتبطة', 'مقيَّد', '⑥ التواقيع', 'منى الموقِّعة', 'T0K3N', '⑪ سجلّ'):
            self.assertIn(needle, body)

    def test_a_book_that_never_moved_prints_one_honest_line(self):
        body = self.client.get(reverse('book_report', args=[self.book.pk])).content.decode('utf-8')
        self.assertIn('③ مسار الكتاب', body)
        self.assertNotIn('③ التفريق والردود', body)
        self.assertIn('⑧ سجلّ', body)

    def test_detail_and_report_read_one_builder(self):
        from core.views import books_detail
        real = books_detail.lifecycle_facts
        with patch('core.views.books_detail.lifecycle_facts', wraps=real) as facts:
            self.client.get(reverse('book_detail', args=[self.book.pk]))
            self.client.get(reverse('book_report', args=[self.book.pk]))
        self.assertEqual(facts.call_count, 2)
        for call in facts.call_args_list:
            self.assertEqual(call.args[0].pk, self.book.pk)
            self.assertEqual(call.args[1], self.admin)
