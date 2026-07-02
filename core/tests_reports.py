# -*- coding: utf-8 -*-
"""اختبارات عرض التقارير core/views/dashboard.py::reports.

يتحقّق من إحصاءات التجميع عبر DB (بدل المرور على كل الصفوف في الذاكرة)
ومن الترقيم — بعد إعادة الكتابة لمعالجة استهلاك الذاكرة.
"""
from datetime import date, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class ReportsViewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('admin', 'a@x.com', 'pass1234')
        self.client.force_login(self.admin)
        self.today = date.today()
        from .models import Book

        def mk(num, kind, **kw):
            return Book.objects.create(our_number=num, title='ك', date=self.today,
                                       kind=kind, created_by=self.admin, **kw)

        # توزيع معروف عبر الحالات الأربع + الاتجاهين
        mk('o-1', 'incoming_internal', due_date=self.today - timedelta(days=3), is_archived=False)  # overdue
        mk('o-2', 'outgoing_internal', due_date=self.today - timedelta(days=1), is_archived=False)  # overdue
        mk('t-1', 'incoming_external', due_date=self.today, is_archived=False)                      # due_today
        mk('p-1', 'outgoing_external', due_date=self.today + timedelta(days=5), is_archived=False)  # pending
        mk('a-1', 'incoming_internal', is_archived=True)                                            # archived (لا due_date)

    def _get(self, **params):
        params.setdefault('bucket', 'all')   # كل الحالات لرؤية الإحصاء الكامل
        return self.client.get(reverse('reports'), params)

    def test_status_ok(self):
        self.assertEqual(self._get().status_code, 200)

    def test_stats_aggregated_correctly(self):
        stats = self._get().context['stats']
        self.assertEqual(stats['total'], 5)
        self.assertEqual(stats['overdue'], 2)
        self.assertEqual(stats['due_today'], 1)
        self.assertEqual(stats['pending'], 1)
        self.assertEqual(stats['archived'], 1)
        self.assertEqual(stats['incoming'], 3)
        self.assertEqual(stats['outgoing'], 2)

    def test_total_matches_paginator_count(self):
        ctx = self._get().context
        self.assertEqual(ctx['total'], ctx['page_obj'].paginator.count)

    def test_bucket_filters_stats(self):
        stats = self._get(bucket='overdue').context['stats']
        self.assertEqual(stats['total'], 2)      # المتأخرة فقط
        self.assertEqual(stats['overdue'], 2)
        self.assertEqual(stats['pending'], 0)

    def test_kind_filter(self):
        stats = self._get(kind='incoming').context['stats']
        self.assertEqual(stats['total'], 3)
        self.assertEqual(stats['outgoing'], 0)

    def test_pagination_present_and_page_bounded(self):
        ctx = self._get().context
        self.assertIn('page_obj', ctx)
        self.assertLessEqual(len(ctx['books']), 200)
        # صفحة غير صالحة تُعالَج بأمان (get_page) ولا ترمي
        self.assertEqual(self._get(page='999').status_code, 200)

    def test_login_required(self):
        self.client.logout()
        resp = self.client.get(reverse('reports'))
        self.assertIn(resp.status_code, (301, 302))
