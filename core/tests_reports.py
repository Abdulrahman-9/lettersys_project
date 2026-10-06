# -*- coding: utf-8 -*-
"""اختبارات عرض التقارير core/views/dashboard.py::reports.

يتحقّق من إحصاءات التجميع عبر DB (بدل المرور على كل الصفوف في الذاكرة)
ومن الترقيم — بعد إعادة الكتابة لمعالجة استهلاك الذاكرة.
"""
import csv
import io
import re
from datetime import date, datetime, timedelta, timezone as dt_timezone
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase, override_settings
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
        """الدلوُ يحصر الجدولَ و``total`` — وعدّاداتُ الحالات على المجموعة كلّها
        (كالقائمة)؛ كانت تُحسب بعد الدلو فيصير كلُّ ما خارجه صفراً بنائيّاً."""
        stats = self._get(bucket='overdue').context['stats']
        self.assertEqual(stats['total'], 2)      # المتأخرة فقط
        self.assertEqual(stats['overdue'], 2)
        self.assertEqual(stats['pending'], 1)

    def test_active_bucket_matches_dashboard(self):
        """«متابعة جارية» في التقارير = رقمُ اللوحة (``followup_q('active')``)."""
        dash = self.client.get(reverse('dashboard')).context
        total = self._get(bucket='active').context['total']
        self.assertEqual(total, dash['incoming_pending'] + dash['outgoing_pending'])
        self.assertEqual(total, 4)

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


class ReportsVocabularyTests(TestCase):
    """مفرداتُ المتابعة من مصدرها الوحيد (``FOLLOWUP_LABELS``/``followup_q``) —
    ومفاتيحُ الدلو مفاتيحُ القائمة، والقديمةُ تُترجَم فلا تنكسر الروابطُ المحفوظة."""

    def setUp(self):
        self.admin = User.objects.create_superuser('vadmin', 'v@x.com', 'pass1234')
        self.client.force_login(self.admin)
        from .models import Book
        today = date.today()
        Book.objects.create(our_number='v-1', title='ك', date=today, kind='incoming_internal',
                            created_by=self.admin, due_date=today - timedelta(days=2))
        Book.objects.create(our_number='v-2', title='ك', date=today, kind='incoming_internal',
                            created_by=self.admin, is_archived=True)

    def _ctx(self, **params):
        return self.client.get(reverse('reports'), params).context

    def test_no_archive_word_and_the_followup_label_instead(self):
        """«مؤرشف» كلمةُ الورق لا المتابعة: لا يحملها قالبُ التقارير، وما يرسمه
        في الجدول وبلاطات الحالة هو ``FOLLOWUP_LABELS``. (نافذةُ المعاينة العامّة في
        ``base.html`` تحمل مفرداتِ القائمة — دفعةُ القائمة لا هذه.)"""
        from .views.filter_helpers import FOLLOWUP_LABELS
        src = (Path(settings.BASE_DIR) / 'templates' / 'core' / 'reports.html').read_text(encoding='utf-8')
        self.assertNotIn('مؤرشف', src)
        html = self.client.get(reverse('reports'), {'bucket': 'all'}).content.decode('utf-8')
        tbody = re.search(r'id="reportTable".*?<tbody>(.*?)</tbody>', html, re.S).group(1)
        cards = re.search(r'<nav class="rx-states"(.*?)</nav>', html, re.S).group(1)
        for part in (tbody, cards):
            self.assertIn(FOLLOWUP_LABELS['archived'], part)
            self.assertNotIn('مؤرشف', part)

    def test_legacy_bucket_keys_map_to_the_unified_ones(self):
        for old, new in (('completed', 'archived'), ('today_overdue', 'active'),
                         ('today', 'due_today'), ('upcoming', 'pending')):
            with self.subTest(old=old):
                self.assertEqual(self._ctx(bucket=old)['bucket'], new)

    def test_the_default_bucket_is_the_dashboards_active(self):
        from .views.filter_helpers import FOLLOWUP_LABELS
        for ctx in (self._ctx(), self._ctx(bucket='nonsense')):
            self.assertEqual(ctx['bucket'], 'active')
            self.assertEqual(ctx['bucket_label'], FOLLOWUP_LABELS['active'])

    def test_bucket_keys_are_the_lists_followup_keys(self):
        """البلاطاتُ هي فلترُ الحالة (حلّت محلّ القائمة المنسدلة): مفاتيحُها مفاتيحُ
        القائمة، و«كل الحالات» رابطٌ في رأس الجدول."""
        from .views.dashboard import REPORT_BUCKETS
        from .views.filter_helpers import _FOLLOWUP_TABS
        self.assertEqual(set(REPORT_BUCKETS), {'all'} | _FOLLOWUP_TABS)
        ctx = self._ctx()
        self.assertEqual({t['key'] for t in ctx['tiles']} | {'all'}, set(REPORT_BUCKETS))
        self.assertIn('bucket=all', ctx['all_buckets_url'])

    def test_dead_context_is_gone(self):
        ctx = self._ctx()
        self.assertNotIn('time_stats', ctx)
        self.assertNotIn('bucket_options', ctx)   # القائمةُ المنسدلة حلّت محلَّها البلاطات


class ReportsExportTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('xadmin', 'x@x.com', 'pass1234')
        self.client.force_login(self.admin)
        from .models import Book
        self.book = Book.objects.create(our_number='20250825', title='موسومٌ', kind='incoming_internal',
                                        date=date(2025, 3, 1), created_by=self.admin)

    def _rows(self):
        resp = self.client.get(reverse('reports_export'), {'bucket': 'all'})
        body = b''.join(resp.streaming_content).decode('utf-8').lstrip('\ufeff')
        return list(csv.reader(io.StringIO(body)))

    def test_number_is_the_display_form(self):
        """الرقمُ كما تعرضه الصفحةُ ويُطبع — ``core/numbering.py`` لا المخزَّنُ الخام."""
        self.assertEqual(self._rows()[1][0], '825/2025')

    @override_settings(TIME_ZONE='Asia/Baghdad')
    def test_entry_date_is_local(self):
        """22:30 UTC = 01:30 ببغداد من اليوم التالي — يومُ الإدخال محلّيّ."""
        from .models import Book
        Book.objects.filter(pk=self.book.pk).update(
            created_at=datetime(2026, 9, 28, 22, 30, tzinfo=dt_timezone.utc))
        self.assertEqual(self._rows()[1][8], '2026-09-29')

    def test_status_column_is_the_followup_label(self):
        from .views.filter_helpers import FOLLOWUP_LABELS
        self.assertEqual(self._rows()[1][10], FOLLOWUP_LABELS['archived'])

    def test_export_is_an_audited_event(self):
        from core.logging_models import UserActivityLog
        before = UserActivityLog.objects.filter(action='EXPORT_DATA').count()
        self._rows()
        self.assertEqual(UserActivityLog.objects.filter(action='EXPORT_DATA').count(), before + 1)


class ReportsTemplateBalanceTests(SimpleTestCase):
    def test_divs_are_balanced(self):
        """كان في القالب وسمُ ``</div>`` زائدٌ يُغلق حاويةَ الصفحة قبل أوانها."""
        text = (Path(settings.BASE_DIR) / 'templates' / 'core' / 'reports.html').read_text(encoding='utf-8')
        self.assertEqual(text.count('<div'), text.count('</div>'))


class ReportsLegacyPaperTests(TestCase):
    """المنقولُ من الورق خارج التقرير افتراضاً (``Book.objects.live()``، قرارُ المالك
    2026‑09‑29) — ومفتاحُ «يشمل الورق القديم» يُدخله في الصفحة والـCSV معاً."""

    def setUp(self):
        self.admin = User.objects.create_superuser('ladmin', 'l@x.com', 'pass1234')
        self.client.force_login(self.admin)
        from .models import Book
        today = date.today()
        self.live = Book.objects.create(our_number='2451', title='حيّ', date=today,
                                        kind='incoming_internal', created_by=self.admin,
                                        due_date=today + timedelta(days=4))
        self.paper = Book.objects.create(our_number='20250821', title='منقولٌ من الورق',
                                         date=date(2025, 5, 4), kind='incoming_internal',
                                         created_by=self.admin, source_ref='IIMAIL_2025#1')

    def _page(self, **params):
        html = self.client.get(reverse('reports'), {'bucket': 'all', **params}).content.decode('utf-8')
        return re.search(r'id="reportTable".*?<tbody>(.*?)</tbody>', html, re.S).group(1), html

    def _csv(self, **params):
        resp = self.client.get(reverse('reports_export'), {'bucket': 'all', **params})
        body = b''.join(resp.streaming_content).decode('utf-8').lstrip('﻿')
        return [r[0] for r in list(csv.reader(io.StringIO(body)))[1:]]

    def test_paper_books_are_out_by_default(self):
        tbody, html = self._page()
        self.assertIn(self.live.our_number_display, tbody)
        self.assertNotIn(self.paper.our_number_display, tbody)
        self.assertEqual(self._csv(), [self.live.our_number_display])
        self.assertIn('name="legacy"', html)
        self.assertNotIn('id="reportLegacy" checked', html)

    def test_the_toggle_brings_them_in_everywhere(self):
        tbody, html = self._page(legacy='1')
        self.assertIn(self.paper.our_number_display, tbody)
        self.assertEqual(set(self._csv(legacy='1')),
                         {self.live.our_number_display, self.paper.our_number_display})
        self.assertIn('id="reportLegacy" checked', html)
        self.assertIn('legacy=1', html)   # يمرّ في رابط التصدير والترقيم


class ActivityReportRemovedTests(SimpleTestCase):
    """قرارُ المالك 2026‑09‑29: «تقريرُ الحركة» حُذف (رؤيةٌ خاصّة، سقفُ 50، فعلٌ بلا جدولة)."""

    def test_the_route_and_the_template_are_gone(self):
        from django.template import TemplateDoesNotExist
        from django.template.loader import get_template
        from django.urls import NoReverseMatch
        with self.assertRaises(NoReverseMatch):
            reverse('followup_activity_report')
        with self.assertRaises(TemplateDoesNotExist):
            get_template('core/followup_activity_report.html')
