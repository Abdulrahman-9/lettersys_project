# -*- coding: utf-8 -*-
"""ترويسةُ «ملفّ الكتاب» جدولاً — ``core/views/book_state.py`` و``secret_openers``.

الدالّاتُ خالصةٌ فتُختبر حالاتٍ لا لقطات: أيُّ خطوةٍ «الآن»، وأيُّ فعلٍ أساسيّ (Q3)،
ومتى تغيب حبّةُ الموعد، وكيف يُقرأ سطرُ الاستشهاد. (تقريرُ فيبل 2026‑10‑06 §د.)
"""
from datetime import date, timedelta

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.utils import timezone

from core.custody_service import record_custody
from core.models import Book, CustodyEvent, Department, SecretAccessGrant, UserProfile
from core.roles import CONTROLLER_GROUP_NAME
from core.scoping import ACCESS_FULL, ACCESS_STUB, secret_access, secret_openers
from core.views.book_state import citation, due_pill, journey, primary_action


def _states(steps):
    return {s['key']: s['state'] for s in steps}


class BookStateTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.today = timezone.localdate()
        cls.dept = Department.objects.create(name='قسمُ الحال', code='ح.ق')
        cls.clerk = User.objects.create_user('sclerk', password='pw-sclerk-1111')
        UserProfile.objects.update_or_create(user=cls.clerk, defaults={'department': cls.dept})

    def _book(self, **kw):
        kw.setdefault('kind', 'incoming_internal')
        kw.setdefault('due_date', self.today + timedelta(days=5))
        kw.setdefault('is_archived', kw['due_date'] is None)
        return Book.objects.create(title='ك', our_number=kw.pop('our_number', '5501'),
                                   created_by=self.clerk, department=self.dept,
                                   date=date(2026, 9, 27), **kw)

    @staticmethod
    def _open_row():
        return {'is_open': True}

    @staticmethod
    def _closed_row():
        return {'is_open': False}


class JourneyAndPrimaryTests(BookStateTestCase):

    def test_a_bare_incoming_book_asks_to_be_distributed(self):
        b = self._book()
        self.assertEqual(_states(journey(b, referrals=[])),
                         {'registered': 'done', 'distributed': 'now', 'custody': 'todo', 'closed': 'todo'})
        self.assertEqual(primary_action(b, referrals=[], can_distribute=True, can_edit=True)['key'],
                         'distribute')

    def test_distributed_without_custody_asks_for_custody(self):
        b = self._book()
        rows = [self._open_row()]
        self.assertEqual(_states(journey(b, referrals=rows))['custody'], 'now')
        self.assertEqual(primary_action(b, referrals=rows, can_distribute=True, can_edit=True)['key'],
                         'custody')

    def test_with_custody_and_an_open_due_date_the_next_step_is_closing(self):
        b = self._book()
        record_custody(b, CustodyEvent.UNIT_RECEIPT, to_department=self.dept, by=self.clerk)
        b.refresh_from_db()
        rows = [self._open_row()]
        steps = journey(b, referrals=rows)
        self.assertEqual(_states(steps)['closed'], 'now')
        self.assertEqual(steps[-1]['sub'], 'بعد 5 أيّام')
        self.assertEqual(primary_action(b, referrals=rows, can_distribute=True, can_edit=True)['key'],
                         'close')
        # ومَن لا يكتب على الكتاب لا يُعرض عليه إنهاؤه (Q1‑ج) — ولا أساسيَّ معطَّلاً
        self.assertIsNone(primary_action(b, referrals=rows, can_distribute=True, can_edit=False))

    def test_closed_is_not_measured_by_is_archived_alone(self):
        """``is_archived`` افتراضُه True لكلّ كتابٍ بلا موعد — فلا يصير «أُنجز» بذلك وحده."""
        b = self._book(due_date=None)
        self.assertTrue(b.is_archived)
        closed = journey(b, referrals=[])[-1]
        self.assertFalse(closed['done'])
        self.assertEqual(closed['sub'], 'بلا متابعة')
        self.assertTrue(journey(b, referrals=[self._closed_row()])[-1]['done'])
        self.assertTrue(journey(self._book(our_number='5502', is_archived=True),
                                referrals=[])[-1]['done'])

    def test_paper_books_have_one_done_step_and_no_primary(self):
        b = self._book(source_ref='IIMAIL_2025#4')
        states = _states(journey(b, referrals=[]))
        self.assertEqual(states.pop('registered'), 'done')
        self.assertEqual(set(states.values()), {'off'})
        self.assertIsNone(primary_action(b, referrals=[], can_distribute=True, can_edit=True))

    def test_outgoing_has_no_distribution_step_and_starts_from_custody(self):
        b = self._book(kind='outgoing_internal')
        self.assertNotIn('distributed', _states(journey(b, referrals=[])))
        self.assertEqual(primary_action(b, referrals=[], can_distribute=True, can_edit=True)['key'],
                         'custody')


class PillAndCitationTests(BookStateTestCase):

    def test_no_pill_without_a_due_date_and_reopen_once_closed(self):
        self.assertIsNone(due_pill(self._book(due_date=None)))
        pill = due_pill(self._book(our_number='5503', is_archived=True))
        self.assertTrue(pill['reopen'])
        self.assertFalse(due_pill(self._book(our_number='5504'))['reopen'])

    def test_a_numberless_book_says_so(self):
        text = ''.join(t for t, _ in citation(self._book(our_number='')))
        self.assertIn('قُيِّد عندنا بلا رقم', text)

    def test_outgoing_cites_our_number_to_the_receiver(self):
        text = ''.join(t for t, _ in citation(self._book(kind='outgoing_external', our_number='914')))
        self.assertEqual(text, 'كتابُنا 914 في 27/09/2026')


class SecretOpenersParityTests(BookStateTestCase):
    """التوأمُ المقروء لـ``secret_access``: كلُّ مَن يُسمّى يفتح، وزميلُ القسم لا."""

    def test_everyone_named_opens_and_a_plain_colleague_does_not(self):
        def member(name, *, head=False, desk=False):
            u = User.objects.create_user(name, password=f'pw-{name}-1111')
            UserProfile.objects.update_or_create(
                user=u, defaults={'department': self.dept, 'is_department_head': head})
            if desk:
                u.groups.add(Group.objects.get_or_create(name=CONTROLLER_GROUP_NAME)[0])
            return u

        head, desk, colleague = member('shead', head=True), member('sdesk', desk=True), member('scolleague')
        grantee = User.objects.create_user('sgrantee', password='pw-sgrantee-1111')
        gone = member('sgone', head=True)
        gone.is_active = False
        gone.save(update_fields=['is_active'])
        secret = self._book(secret_level='secret')
        SecretAccessGrant.objects.create(book=secret, user=grantee, granted_by=head)
        SecretAccessGrant.objects.create(book=secret, user=colleague, granted_by=head,
                                         revoked_at=timezone.now())

        named = secret_openers(secret)
        self.assertEqual({u.username for u in named}, {'sclerk', 'shead', 'sdesk', 'sgrantee'})
        for user in named:
            with self.subTest(user=user.username):
                self.assertEqual(secret_access(user, secret), ACCESS_FULL)
        self.assertEqual(secret_access(colleague, secret), ACCESS_STUB)
