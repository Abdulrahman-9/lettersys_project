# -*- coding: utf-8 -*-
"""التقاريرُ **لرئيس القسم ومدير النظام حصراً** — كلٌّ بشجرته — وفلترُ القسم وجدولُه.

قرارُ المالك 2026‑09‑29 (الخطّة v2 §10): التقريرُ أداةُ إشرافٍ ومخرَجُه يخرج من
الجهاز. غيرُهما يلقى 404 (لا 403: الفرقُ يُسرّب وجودَ الصفحة) ولا يرى الرابط.
البوّابةُ ``scoping.can_view_reports`` والأقسامُ ``scoping.report_departments``.

(خطّةُ فيبل 2026‑09‑29 §3.)
"""
import csv
import io
from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.context_processors import nav_gates
from core.models import Book, Department, UserProfile
from core.roles import CONTROLLER_GROUP_NAME, ENTRY_GROUP_NAME


class _Req:
    def __init__(self, user):
        self.user = user


def _csv_numbers(resp):
    body = b''.join(resp.streaming_content).decode('utf-8').lstrip('﻿')
    return [r[0] for r in list(csv.reader(io.StringIO(body)))[1:]]


class ReportsGateTestCase(TestCase):
    """قسمٌ «ق» بشعبةٍ «ش»، وقسمٌ آخر «خ» بلا شُعب؛ وكتابٌ بلا قسم."""

    @classmethod
    def setUpTestData(cls):
        today = timezone.localdate()
        cls.q = Department.objects.create(name='قسمُ البوّابة', code='ب.ق')
        cls.sh = Department.objects.create(name='شعبةُ البوّابة', code='ب.ش', parent=cls.q)
        cls.kh = Department.objects.create(name='قسمُ البوّابة الآخر', code='ب.خ')

        def member(name, dept, *, head=False, group=None):
            u = User.objects.create_user(name, password=f'pw-{name}-1111')
            UserProfile.objects.update_or_create(
                user=u, defaults={'department': dept, 'is_department_head': head})
            if group:
                u.groups.add(Group.objects.get_or_create(name=group)[0])
            return u

        cls.clerk = member('gclerk', cls.q)
        cls.entry = member('gentry', cls.q, group=ENTRY_GROUP_NAME)
        cls.officer = member('gofficer', cls.q, group=CONTROLLER_GROUP_NAME)
        cls.head = member('ghead', cls.q, head=True)
        cls.unit = member('gunit', cls.sh)
        cls.head_kh = member('gheadkh', cls.kh, head=True)
        cls.admin = User.objects.create_superuser('gadmin', 'ga@x.co', 'pw-gadmin-1111')

        def book(num, by, dept, due):
            return Book.objects.create(
                kind='incoming_internal', title=f'كتابُ {num}', created_by=by,
                department=dept, our_number=num, date=today,
                due_date=today + timedelta(days=due) if due is not None else None,
                is_archived=due is None)

        cls.b_q_overdue = book('4101', cls.clerk, cls.q, -2)
        cls.b_q_done = book('4102', cls.clerk, cls.q, None)
        cls.b_sh = book('4103', cls.unit, cls.sh, 3)
        cls.b_kh = book('4104', cls.head_kh, cls.kh, 0)
        cls.b_none = book('4105', cls.admin, None, 5)

    def _get(self, user, name='reports', **params):
        self.client.force_login(user)
        params.setdefault('bucket', 'all')
        return self.client.get(reverse(name), params)

    def _pks(self, user, **params):
        return {b.pk for b in self._get(user, **params).context['books']}


class RoleGateTests(ReportsGateTestCase):

    def test_everyone_but_the_head_and_the_admin_gets_404(self):
        for user in (self.clerk, self.entry, self.officer, self.unit):
            for name in ('reports', 'reports_export'):
                with self.subTest(user=user.username, page=name):
                    self.assertEqual(self._get(user, name).status_code, 404)

    def test_the_head_sees_his_tree_only(self):
        resp = self._get(self.head)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual({b.pk for b in resp.context['books']},
                         {self.b_q_overdue.pk, self.b_q_done.pk, self.b_sh.pk})

    def test_the_admin_sees_everything(self):
        self.assertEqual(self._pks(self.admin),
                         {self.b_q_overdue.pk, self.b_q_done.pk, self.b_sh.pk,
                          self.b_kh.pk, self.b_none.pk})
        self.assertEqual(self._get(self.admin, 'reports_export').status_code, 200)

    def test_the_nav_link_follows_the_gate(self):
        for user, shown in ((self.clerk, False), (self.entry, False), (self.officer, False),
                            (self.head, True), (self.admin, True)):
            with self.subTest(user=user.username):
                self.assertIs(nav_gates(_Req(user))['nav']['reports'], shown)
                self.client.force_login(user)
                html = self.client.get(reverse('dashboard')).content.decode('utf-8')
                self.assertEqual(f'href="{reverse("reports")}"' in html, shown)


class DepartmentFilterTests(ReportsGateTestCase):

    def test_the_head_filters_to_his_unit(self):
        self.assertEqual(self._pks(self.head, dept=self.sh.pk), {self.b_sh.pk})
        numbers = _csv_numbers(self._get(self.head, 'reports_export', dept=self.sh.pk))
        self.assertEqual(numbers, [self.b_sh.our_number_display])

    def test_a_department_outside_the_tree_is_404(self):
        for name in ('reports', 'reports_export'):
            with self.subTest(page=name):
                self.assertEqual(self._get(self.head, name, dept=self.kh.pk).status_code, 404)
        self.assertEqual(self._get(self.head_kh, dept=self.q.pk).status_code, 404)

    def test_the_filter_flows_down_the_tree(self):
        """القسمُ يشمل شُعبَه كالنطاق — لا القسمَ وحدَه."""
        self.assertEqual(self._pks(self.admin, dept=self.q.pk),
                         {self.b_q_overdue.pk, self.b_q_done.pk, self.b_sh.pk})

    def test_a_non_numeric_department_is_ignored(self):
        self.assertEqual(self._get(self.head, dept='abc').status_code, 200)

    def test_the_department_rows_count_by_the_followup_rule(self):
        rows = self._get(self.admin, dept=self.q.pk).context['dept_rows']
        got = {r['department__code']: (r['total'], r['pending'], r['due_today'],
                                        r['overdue'], r['archived']) for r in rows}
        self.assertEqual(got, {'ب.ق': (2, 0, 0, 1, 1), 'ب.ش': (1, 1, 0, 0, 0)})

    def test_the_admin_sees_every_department_and_the_departmentless(self):
        rows = self._get(self.admin).context['dept_rows']
        labels = {r['label']: r['total'] for r in rows}
        self.assertEqual(labels.get('بلا قسم'), 1)
        self.assertEqual(labels.get(self.kh.name), 1)

    def test_a_head_without_units_gets_no_department_dimension(self):
        resp = self._get(self.head_kh)
        self.assertEqual(resp.context['dept_rows'], [])
        self.assertFalse(resp.context['show_department'])
        self.assertNotContains(resp, 'name="dept"')

    def test_the_head_with_units_gets_the_selector_and_the_column(self):
        resp = self._get(self.head)
        self.assertTrue(resp.context['show_department'])
        self.assertContains(resp, 'name="dept"')
        self.assertEqual({d.pk for d in resp.context['departments']}, {self.q.pk, self.sh.pk})
