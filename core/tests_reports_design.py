# -*- coding: utf-8 -*-
"""«سجلّ المتابعة» — حرّاسُ الأسطح الجديدة في صفحة التقارير (قرارُ المالك 2026‑10‑06).

البلاطاتُ صارت فلترَ الحالة، وظهر عمودُ «بعهدة» وقائمةُ «أقدم المتأخّرات»
وشرائطُ القسم. كلُّ سطحٍ جديدٍ بابٌ جديدٌ للسرّيّ — فالحاملُ يُحجب كالجهات في
الجدول والقائمة والـCSV معاً (مراجعةُ فيبل 2026‑10‑06).
"""
import csv
import io
import re
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth.models import User
from django.db import connection
from django.template import Context, Template
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from core.custody_service import record_custody
from core.models import Book, CustodyEvent, Department, Entity, UserProfile
from core.scoping import STUB_TITLE
from core.views.filter_helpers import FOLLOWUP_LABELS, day_unit_ar, days_ar, followup_phrase


def _section(html, pattern):
    m = re.search(pattern, html, re.S)
    assert m, pattern
    return m.group(1)


def _tbody(html):
    return _section(html, r'id="reportTable".*?<tbody>(.*?)</tbody>')


def _late(html):
    return _section(html, r'id="reportLate"(.*?)</ul>')


class ReportsDesignTestCase(TestCase):
    """قسمٌ «ق» بشعبته «ش»؛ ورئيسُ «ق» لا يملك محتوى سرّيِّ «ش» (الحقُّ بالدور
    على قسمه لا على شجرته — ``secret_access``)، والمديرُ يملكه."""

    @classmethod
    def setUpTestData(cls):
        cls.today = timezone.localdate()
        cls.q = Department.objects.create(name='قسمُ السجلّ', code='س.ق')
        cls.sh = Department.objects.create(name='شعبةُ السجلّ', code='س.ش', parent=cls.q)

        def member(name, dept, *, head=False, full=('', '')):
            u = User.objects.create_user(name, password=f'pw-{name}-1111',
                                         first_name=full[0], last_name=full[1])
            UserProfile.objects.update_or_create(
                user=u, defaults={'department': dept, 'is_department_head': head})
            return u

        cls.head = member('dhead', cls.q, head=True)
        cls.unit = member('dunit', cls.sh)
        cls.secret_keeper = member('dkeeper', cls.sh, full=('حاملُ', 'السرّ'))
        cls.public_keeper = member('dpublic', cls.q, full=('حاملُ', 'العلن'))
        cls.admin = User.objects.create_superuser('dadmin', 'd@x.co', 'pw-dadmin-1111')
        cls.ent = Entity.objects.create(name='جهةُ السجلّ')

        def book(num, dept, due, by=None, **kw):
            return Book.objects.create(
                kind=kw.pop('kind', 'incoming_internal'), title=kw.pop('title', f'كتابُ {num}'),
                created_by=by or cls.head, department=dept, our_number=num, date=cls.today,
                due_date=cls.today + timedelta(days=due) if due is not None else None,
                is_archived=due is None, **kw)

        # المتأخّرةُ بأعمارٍ معروفة: الأربعُ الأقدم -10 -8 -6 -5، وخارجها -3 -1
        cls.o10 = book('5110', cls.q, -10)
        cls.o8 = book('5108', cls.q, -8)
        cls.o6 = book('5106', cls.q, -6)
        cls.secret_sh = book('5105', cls.sh, -5, by=cls.unit, title='تقريرُ السجلّ السرّيّ',
                             secret_level='secret')
        cls.plain = book('5103', cls.q, -3, title='كتابٌ علنيٌّ بعهدة')
        cls.o1 = book('5101', cls.q, -1)
        cls.later = book('5202', cls.q, 2)                  # قيد المتابعة، بلا عهدة
        cls.done = book('5300', cls.q, None)                # مُنجَز
        cls.loose = book('5400', None, 4, by=cls.admin)     # «بلا قسم» — يراه المديرُ وحده

        record_custody(cls.secret_sh, CustodyEvent.UNIT_RECEIPT, to_user=cls.secret_keeper, by=cls.admin)
        record_custody(cls.plain, CustodyEvent.UNIT_RECEIPT, to_user=cls.public_keeper, by=cls.admin)

    def _get(self, user, name='reports', **params):
        self.client.force_login(user)
        params.setdefault('bucket', 'all')
        return self.client.get(reverse(name), params)

    def _csv(self, user, **params):
        resp = self._get(user, 'reports_export', **params)
        body = b''.join(resp.streaming_content).decode('utf-8').lstrip('﻿')
        return list(csv.reader(io.StringIO(body)))


class HolderMaskingTests(ReportsDesignTestCase):
    """حاملُ السرّيّ يدلّ عليه: محجوبٌ كالجهات حيثما ظهر الحامل."""

    def test_the_head_sees_no_holder_of_the_secret_anywhere(self):
        resp = self._get(self.head)
        html = resp.content.decode('utf-8')
        for where, part in (('الجدول', _tbody(html)), ('أقدم المتأخّرات', _late(html))):
            with self.subTest(where=where):
                self.assertNotIn('حاملُ السرّ', part)
        self.assertNotIn('حاملُ السرّ', '\n'.join(','.join(r) for r in self._csv(self.head)))
        row = next(b for b in resp.context['books'] if b.pk == self.secret_sh.pk)
        self.assertIsNone(row.shown_holder)

    def test_the_owner_of_the_content_sees_the_holder(self):
        html = self._get(self.admin).content.decode('utf-8')
        self.assertIn('حاملُ السرّ', _tbody(html))
        self.assertIn('حاملُ السرّ', _late(html))
        rows = self._csv(self.admin)
        row = next(r for r in rows if r[0] == self.secret_sh.our_number_display)
        self.assertEqual(row[-1], 'حاملُ السرّ')

    def test_a_public_holder_shows_and_no_custody_is_empty_not_masked(self):
        """``""`` لما لم تُسجَّل له عهدة و``None`` للمحجوب — فلا يُقال عن سرّيٍّ
        له حاملٌ إنّه «لم تُسجَّل عهدة»."""
        resp = self._get(self.head)
        self.assertIn('حاملُ العلن', _tbody(resp.content.decode('utf-8')))
        later = next(b for b in resp.context['books'] if b.pk == self.later.pk)
        self.assertEqual(later.shown_holder, '')


class TileLinkTests(ReportsDesignTestCase):
    """البلاطاتُ فلترُ الحالة: الرابطُ يبدّل الحالة ويحفظ بقيّة الفلاتر ويعود إلى الصفحة الأولى."""

    def test_tiles_keep_the_filters_and_drop_the_page(self):
        tiles = self._get(self.admin, bucket='overdue', kind='incoming', legacy='1',
                          page='2').context['tiles']
        self.assertEqual([t['key'] for t in tiles],
                         ['active', 'overdue', 'due_today', 'pending', 'archived'])
        for t in tiles:
            with self.subTest(tile=t['key']):
                q = parse_qs(urlsplit(t['url']).query)
                self.assertEqual(q['bucket'], [t['key']])
                self.assertEqual(q['kind'], ['incoming'])
                self.assertEqual(q['legacy'], ['1'])
                self.assertNotIn('page', q)
                self.assertIs(t['on'], t['key'] == 'overdue')

    def test_a_tile_counts_what_it_opens(self):
        for user in (self.head, self.admin):
            for key in ('active', 'overdue', 'archived'):
                with self.subTest(user=user.username, tile=key):
                    ctx = self._get(user, bucket=key).context
                    tile = next(t for t in ctx['tiles'] if t['key'] == key)
                    self.assertEqual(tile['num'], ctx['total'])

    def test_the_shown_tile_is_marked_once(self):
        html = self._get(self.admin, bucket='pending').content.decode('utf-8')
        nav = _section(html, r'<nav class="rx-states"(.*?)</nav>')
        self.assertEqual(nav.count('aria-current="true"'), 1)
        self.assertRegex(nav, r'rx-state--pending is-on" href="[^"]*" aria-current="true"')


class DepartmentRowTests(ReportsDesignTestCase):

    def test_a_department_name_filters_and_the_departmentless_has_no_link(self):
        rows = {r['label']: r for r in self._get(self.admin, bucket='overdue').context['dept_rows']}
        self.assertEqual(rows['بلا قسم']['url'], '')
        q = parse_qs(urlsplit(rows[self.q.name]['url']).query)
        self.assertEqual(q['dept'], [str(self.q.pk)])
        self.assertEqual(q['bucket'], ['overdue'])

    def test_the_bar_is_relative_to_the_widest_department(self):
        rows = {r['label']: r for r in self._get(self.admin).context['dept_rows']}
        self.assertEqual(rows[self.q.name]['bar'], 100)          # 6 جارية — الأعرض
        self.assertEqual(rows[self.sh.name]['active'], 1)
        self.assertEqual(rows[self.sh.name]['bar'], round(100 * 1 / 6))


class OldestOverdueTests(ReportsDesignTestCase):

    def test_the_four_oldest_in_order(self):
        late = self._get(self.admin, bucket='pending').context['late']   # مستقلّةٌ عن الحالة المعروضة
        self.assertEqual([b.pk for b in late], [self.o10.pk, self.o8.pk, self.o6.pk, self.secret_sh.pk])
        self.assertEqual([b.late_days for b in late], [10, 8, 6, 5])

    def test_the_late_list_wears_the_stub(self):
        html = self._get(self.head).content.decode('utf-8')
        part = _late(html)
        self.assertIn(STUB_TITLE, part)
        self.assertNotIn(self.secret_sh.title, part)
        self.assertIn('10</b><small>أيّام</small>', part)


class CsvColumnsTests(ReportsDesignTestCase):

    def test_department_and_holder_trail_the_row(self):
        """الجديدُ في الذيل: فهارسُ الأعمدة السابقة يعتمدها مَن يستورد الملفّ."""
        rows = self._csv(self.admin)
        self.assertEqual(rows[0][-2:], ['القسم', 'بعهدة'])
        self.assertEqual(rows[0][10], 'الحالة')
        row = next(r for r in rows if r[0] == self.plain.our_number_display)
        self.assertEqual(row[-2:], [self.q.name, 'حاملُ العلن'])
        loose = next(r for r in rows if r[0] == self.loose.our_number_display)
        self.assertEqual(loose[-2:], ['', ''])


class QueryCountTests(ReportsDesignTestCase):
    """جهازُ 8GB: عددُ الاستعلامات لا ينمو بعدد الصفوف (الحاملُ عبر ``select_related``)."""

    def _queries(self):
        with CaptureQueriesContext(connection) as ctx:
            resp = self.client.get(reverse('reports'), {'bucket': 'all'})
        self.assertEqual(resp.status_code, 200)
        return len(ctx)

    def test_queries_do_not_grow_with_rows(self):
        self.client.force_login(self.admin)    # الدخولُ خارج العدّ
        self._queries()                        # تحميةٌ: كاشُ الإعدادات والجلسة
        before = self._queries()
        for i in range(6):
            b = Book.objects.create(kind='incoming_internal', title=f'إضافيّ {i}', created_by=self.head,
                                    department=self.q, our_number=f'59{i:02d}', date=self.today,
                                    due_date=self.today - timedelta(days=20 + i))
            b.issuing_entities.add(self.ent)
            record_custody(b, CustodyEvent.UNIT_RECEIPT, to_user=self.public_keeper, by=self.admin)
        self.assertEqual(self._queries(), before)


class DayWordsTests(SimpleTestCase):
    """تمييزُ العدد بقاعدة العربيّة — كانت القوالبُ تكتب «2 يوم» و«5 يوم»."""

    def test_the_unit(self):
        for n, word in ((1, 'يوم'), (2, 'يومان'), (3, 'أيّام'), (10, 'أيّام'), (11, 'يوماً'),
                        (99, 'يوماً'), (100, 'يوم'), (103, 'أيّام'), (111, 'يوماً')):
            with self.subTest(n=n):
                self.assertEqual(day_unit_ar(n), word)

    def test_the_phrase(self):
        self.assertEqual(days_ar(1), 'يوم واحد')
        self.assertEqual(days_ar(2), 'يومان')
        self.assertEqual(days_ar(2, after_preposition=True), 'يومين')
        self.assertEqual(days_ar(1, after_preposition=True), 'يوم')
        self.assertEqual(days_ar(7), '7 أيّام')
        self.assertEqual(days_ar(12), '12 يوماً')

    def test_the_followup_chip(self):
        today = timezone.localdate()

        def chip(due, archived=False):
            b = Book(due_date=today + timedelta(days=due) if due is not None else None,
                     is_archived=archived)
            return followup_phrase(b, today)

        self.assertEqual(chip(-9), f"{FOLLOWUP_LABELS['overdue']} · 9 أيّام")
        self.assertEqual(chip(-2), f"{FOLLOWUP_LABELS['overdue']} · يومان")
        self.assertEqual(chip(0), FOLLOWUP_LABELS['due_today'])
        self.assertEqual(chip(1), 'بعد يوم')
        self.assertEqual(chip(2), 'بعد يومين')
        self.assertEqual(chip(11), 'بعد 11 يوماً')
        self.assertEqual(chip(None), FOLLOWUP_LABELS['archived'])
        self.assertEqual(chip(5, archived=True), FOLLOWUP_LABELS['archived'])

    def test_the_template_filters(self):
        out = Template('{% load ar_counts %}{{ n|days_ar }}|{{ n|day_unit_ar }}').render(Context({'n': 2}))
        self.assertEqual(out, 'يومان|يومان')
