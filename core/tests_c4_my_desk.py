# -*- coding: utf-8 -*-
"""(ج‑4) «طاولتي» — طاولةُ عمل مسؤول الشعبة أو الوحدة (قرارُ المالك 11‑02، المستويان 2 و3).

ما أُحيل إلى شجرته فقط، في طوابير العمل الأربعة، بلا «آخر القيود» ولا طوابير الرقابة ولا الدفتر والكشف.
والسرّيُّ رقمٌ بلا موضوع: مسؤولُ الشعبة أو الوحدة لا يفتح سرّيَّ وحدته (``secret.own`` لرئيس القسم).
"""
import datetime

from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Book, BookReferral, Department, UserProfile
from core.roles import EXECUTOR_GROUP_NAME, ensure_role_groups
from core.scoping import STUB_TITLE

URL = reverse('desk_mine')


class MyDeskCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_role_groups()
        executors = Group.objects.get_or_create(name=EXECUTOR_GROUP_NAME)[0]
        cls.dept = Department.objects.create(name='قسم الطاولة', code='طا1')
        cls.section = Department.objects.create(name='شعبة الطاولة', code='طا1ش', parent=cls.dept, holds_register=False)
        cls.unit = Department.objects.create(name='وحدة الطاولة', code='طا1و', parent=cls.section, holds_register=False)
        cls.other = Department.objects.create(name='شعبة أخرى', code='طا1خ', parent=cls.dept, holds_register=False)
        cls.root = User.objects.create_superuser('c4d_root', password='pw-c4d-1111')
        cls.head = cls.person('c4d_head', cls.dept, head=True)
        cls.unit_head = cls.person('c4d_unithead', cls.section, head=True)
        cls.executor = cls.person('c4d_exec', cls.unit)
        cls.executor.groups.add(executors)
        today = timezone.localdate()
        cls.late = cls.refer('متأخّر على الوحدة', cls.unit, BookReferral.RECEIVED, today - datetime.timedelta(days=3))
        cls.new = cls.refer('وصل الشعبة ولم يُستلم', cls.section, BookReferral.SENT, None)
        cls.elsewhere = cls.refer('إلى الشعبة الأخرى', cls.other, BookReferral.SENT, None)
        cls.secret = cls.refer('موضوعٌ سرّيّ', cls.unit, BookReferral.SENT, None, secret_level='secret')
        out = Book.objects.create(kind='outgoing_internal', title='صادرٌ من الشعبة', created_by=cls.head,
                                  department=cls.dept, our_number='75')
        BookReferral.objects.create(book=out, from_department=cls.section, to_department=cls.other,
                                    status=BookReferral.SENT, purpose=BookReferral.ACTION, created_by=cls.head)

    @classmethod
    def person(cls, name, dept, head=False):
        user = User.objects.create_user(name, password='pw-c4d-1111')
        UserProfile.objects.update_or_create(user=user, defaults={'department': dept, 'is_department_head': head})
        return user

    @classmethod
    def refer(cls, title, to, status, due, **book):
        number = str(70 + Book.objects.count())
        item = Book.objects.create(kind='incoming_internal', title=title, created_by=cls.head,
                                   department=cls.dept, our_number=number, **book)
        BookReferral.objects.create(book=item, from_department=cls.dept, to_department=to, status=status,
                                    purpose=BookReferral.ACTION, due_date=due, created_by=cls.head)
        return item

    def setUp(self):
        cache.clear()

    def page(self, user, query=''):
        self.client.force_login(user)
        return self.client.get(URL + query)


class GateTests(MyDeskCase):
    def test_only_the_section_or_unit_head_has_it(self):
        self.assertEqual(self.page(self.unit_head).status_code, 200)
        for user in (self.head, self.executor):
            with self.subTest(user=user.username):
                self.assertEqual(self.page(user).status_code, 403)
        self.assertTrue(self.page(self.unit_head).context['nav']['my_desk'])
        response = self.page(self.root)   # بلا قسمٍ طاولةٌ فارغةٌ أبداً
        self.assertEqual(response.status_code, 403)
        self.client.force_login(self.root)
        self.assertFalse(self.client.get(reverse('desk_board')).context['nav']['my_desk'])

    def test_the_mail_desk_keeps_its_queues_and_recent_entries(self):
        self.client.force_login(self.head)
        body = self.client.get(reverse('desk_board')).content.decode()
        self.assertIn('آخر القيود', body)
        self.assertIn('data-desk-queue="no_reply"', body)
        self.assertNotIn(reverse('desk_mine'), body)


class ScopeTests(MyDeskCase):
    def test_it_shows_what_reached_his_tree_only(self):
        response = self.page(self.unit_head)
        books = {row['book'].pk for q in response.context['queues'] for row in q['rows']}
        self.assertEqual(books, {self.late.pk, self.new.pk, self.secret.pk})

    def test_four_work_queues_and_no_oversight(self):
        response = self.page(self.unit_head)
        self.assertEqual([q['key'] for q in response.context['queues']],
                         ['overdue', 'unreceived', 'received_action', 'today'])
        body = response.content.decode()
        for absent in ('آخر القيود', 'data-desk-queue="no_reply"', 'data-desk-queue="secret"',
                       reverse('desk_ledger'), reverse('desk_handover'), 'href="' + reverse('desk_board') + '"'):
            with self.subTest(absent=absent):
                self.assertNotIn(absent, body)
        self.assertIn('href="' + URL + '" aria-current="page"', body)

    def test_the_first_busy_queue_opens_and_a_wrong_one_is_404(self):
        response = self.page(self.unit_head)
        self.assertEqual(response.context['selected_queue']['key'], 'overdue')
        empty = self.page(self.unit_head, '?queue=today')
        self.assertEqual(empty.context['selected_queue']['key'], 'today')
        self.assertContains(empty, 'لا إحالات في هذا التصنيف حالياً.')
        self.assertNotContains(empty, 'العودة إلى آخر القيود')   # لا «آخر قيود» في طاولته
        self.assertEqual(self.page(self.unit_head, '?queue=no_reply').status_code, 404)

    def test_a_secret_shows_its_number_not_its_subject(self):
        body = self.page(self.unit_head, '?queue=unreceived').content.decode()
        self.assertIn(STUB_TITLE, body)
        self.assertNotIn('موضوعٌ سرّيّ', body)
        self.assertIn('وصل الشعبة ولم يُستلم', body)

    def test_an_empty_desk_says_so(self):
        BookReferral.objects.filter(to_department__in=(self.section, self.unit)).update(status=BookReferral.DONE)
        response = self.page(self.unit_head)
        self.assertIsNone(response.context['selected_queue'])
        self.assertContains(response, 'الطاولةُ نظيفة')
        self.assertNotContains(response, 'العودة إلى آخر القيود')
