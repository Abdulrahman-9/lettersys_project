# -*- coding: utf-8 -*-
"""الحيُّ وحدَه في لوحة القيادة والقائمة — قرارُ المالك 2026‑10‑06 («نعم»).

كلُّ رقمٍ في اللوحة رابطٌ إلى القائمة؛ وكانت اللوحةُ تعدّ الكتبَ كلَّها (ومنها
11 ألفاً منقولةٌ من الورق وكتبُ التدريب) بينما التقاريرُ تعدّ الحيَّ — فيتخالف
الرقمُ وما يُفتح. الآن: المصدرُ واحد (``books_in_scope``)، والقائمةُ حيّةٌ افتراضاً
بمفتاح «يشمل الورق القديم»، **والبحثُ يجد الكلّ** والعدّاداتُ تتبع المفتاح لا النصّ.
(مراجعةُ فيبل 2026‑10‑06: D:/migration/fable_live_counts_20261006.md.)
"""
import inspect
import io
from datetime import date, timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Book, BookHistory, Department, UserProfile
from core.testing import as_writer


class LiveCountsTestCase(TestCase):
    """قسمٌ بكتبٍ حيّة، وورقٍ قديم (أحدُه أُعيد فتحُ متابعته فتأخّر، وآخرُ بتاريخ اليوم)،
    وكتابِ تدريبٍ بموعد — الحالاتُ التي تُفرّق بين العدّين."""

    @classmethod
    def setUpTestData(cls):
        cls.today = timezone.localdate()
        cls.dept = Department.objects.create(name='قسمُ العدّ', code='ع.ق')
        cls.clerk = as_writer(User.objects.create_user('lclerk', password='pw-lclerk-1111'))
        UserProfile.objects.update_or_create(user=cls.clerk, defaults={'department': cls.dept})

        def book(num, *, kind='incoming_internal', due=None, **kw):
            return Book.objects.create(
                kind=kind, title=kw.pop('title', 'كتابٌ للعدّ'), our_number=num,
                created_by=cls.clerk, department=cls.dept, date=kw.pop('date', cls.today),
                due_date=cls.today + timedelta(days=due) if due is not None else None,
                is_archived=due is None, **kw)

        cls.live_pending = book('7001', due=3)
        cls.live_overdue = book('7002', due=-2)
        cls.live_done = book('7003')
        cls.live_out = book('7004', kind='outgoing_internal', due=2)
        cls.paper_overdue = book('20250825', due=-5, source_ref='IIMAIL_2025#1',
                                 date=date(2025, 4, 1), title='منقولٌ أُعيد فتحُه')
        cls.paper_today = book('20250826', source_ref='IIMAIL_2025#2', legacy_number='قديم-544',
                               title='منقولٌ بتاريخ اليوم')
        cls.training = book('T131', due=1, is_training=True, title='كتابُ تدريب')

    def _list(self, **params):
        self.client.force_login(self.clerk)
        resp = self.client.get(reverse('book_unified'), params)
        self.assertEqual(resp.status_code, 200)
        return resp.context

    def _api(self, **params):
        self.client.force_login(self.clerk)
        resp = self.client.get(reverse('api_unified_data'), params)
        self.assertEqual(resp.status_code, 200)
        return resp.json()


class TileEqualsListTests(LiveCountsTestCase):

    def test_every_dashboard_number_is_the_list_it_opens(self):
        self.client.force_login(self.clerk)
        dash = self.client.get(reverse('dashboard')).context
        week_ago = (self.today - timedelta(days=7)).isoformat()
        links = {
            'overdue': {'tab': 'all', 'followup': 'overdue'},
            'incoming_total': {'tab': 'incoming'},
            'incoming_pending': {'tab': 'incoming', 'followup': 'active'},
            'incoming_done': {'tab': 'incoming', 'followup': 'archived'},
            'outgoing_total': {'tab': 'outgoing'},
            'outgoing_pending': {'tab': 'outgoing', 'followup': 'active'},
            'total': {'tab': 'all'},
            'today_count': {'tab': 'all', 'date_from': self.today.isoformat(),
                            'date_to': self.today.isoformat()},
            'week_count': {'tab': 'all', 'date_from': week_ago, 'date_to': self.today.isoformat()},
        }
        for key, params in links.items():
            with self.subTest(tile=key):
                self.assertEqual(dash[key], self._list(**params)['total_count'])

    def test_the_numbers_count_paper_books_too_but_not_training(self):
        """أعدادٌ مطلقة: حيّ 4 + ورق 2، وكتابُ التدريب خارجها."""
        self.client.force_login(self.clerk)
        dash = self.client.get(reverse('dashboard')).context
        self.assertEqual((dash['total'], dash['overdue'], dash['incoming_pending']), (6, 2, 3))

    def test_an_old_link_with_the_retired_switch_changes_nothing(self):
        self.assertEqual(self._list(tab='all', legacy='1')['total_count'], 6)
        self.assertEqual(self._list(tab='all', legacy='0')['total_count'], 6)


class OneViewTests(LiveCountsTestCase):
    """قرارُ المالك 2026‑11‑03: «كلّ الكتب» عرضٌ واحدٌ للقديم والجديد."""

    def test_the_list_shows_old_and_new_together(self):
        shown = {b['id'] for b in self._api(tab='all')['books']}
        self.assertIn(self.paper_today.pk, shown)
        self.assertIn(self.live_pending.pk, shown)
        self.assertEqual(self._list(tab='all')['total_count'], 6)

    def test_training_books_stay_out(self):
        self.assertNotIn(self.training.pk, {b['id'] for b in self._api(tab='all')['books']})
        self.assertEqual(self._list(tab='all', q='T131')['total_count'], 0)

    def test_a_tagged_number_and_a_legacy_number_find_the_paper_book(self):
        for query in ('825', 'قديم-544'):
            with self.subTest(query=query):
                self.assertGreaterEqual(self._list(tab='all', q=query)['total_count'], 1)

    def test_the_export_follows_the_same_rule(self):
        self.client.force_login(self.clerk)
        resp = self.client.get(reverse('api_export_csv'), {'tab': 'all'})
        body = b''.join(resp.streaming_content) if resp.streaming else resp.content
        self.assertIn('منقولٌ بتاريخ اليوم', body.decode('utf-8-sig'))

    def test_the_badges_equal_the_rows(self):
        self.assertEqual(self._api(tab='all')['badges']['all'], 6)

    def test_the_switch_and_its_lines_are_gone(self):
        self.client.force_login(self.clerk)
        html = self.client.get(reverse('book_unified')).content.decode('utf-8')
        for gone in ('filterLegacy', 'legacyHint', 'searchWidenedHint', 'يشمل الورق القديم'):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, html)

    def test_clearing_filters_keeps_every_book(self):
        """كان «مسح الفلاتر» يُطفئ المفتاح فتفرغ القائمة."""
        data = self._api(tab='all', q='', entity='', legacy='')
        self.assertEqual(len(data['books']), 6)

    def test_an_old_book_is_marked_paper_in_its_row(self):
        self.client.force_login(self.clerk)
        html = self.client.get(reverse('book_unified'), {'tab': 'all', 'q': 'قديم-544'}).content.decode('utf-8')
        self.assertIn('num-paper', html)
        new_only = self.client.get(reverse('book_unified'), {'tab': 'all', 'q': '7001'}).content.decode('utf-8')
        self.assertNotIn('class="num-paper"', new_only)

    def test_work_queues_stay_on_new_books(self):
        from core.scoping import listed_books
        self.assertIn(self.paper_today, listed_books(self.clerk))
        self.assertNotIn(self.paper_today, Book.objects.live())


class OtherCountersTests(LiveCountsTestCase):

    def test_overdue_notices_come_from_live_books(self):
        from core.models import NotificationSettings
        cfg = NotificationSettings.get()
        cfg.overdue_enabled = True
        cfg.save()
        call_command('notify_overdue_books', stdout=io.StringIO())
        noticed = set(BookHistory.objects.filter(action='overdue').values_list('book_id', flat=True))
        self.assertIn(self.live_overdue.pk, noticed)
        self.assertNotIn(self.paper_overdue.pk, noticed)

    def test_recent_books_widget_shows_what_the_list_can_focus(self):
        """بعد استيرادٍ من الورق تصير ``created_at`` الورق «الآن» — والودجةُ تفتح القائمة."""
        self.client.force_login(self.clerk)
        resp = self.client.get(reverse('extraction-smart-desktop'))
        self.assertEqual(resp.status_code, 200)
        shown = {b.pk for b in resp.context['recent_books']}
        self.assertNotIn(self.paper_today.pk, shown)
        self.assertNotIn(self.training.pk, shown)
        self.assertIn(self.live_out.pk, shown)


class OneSourceTests(SimpleTestCase):
    """لا عدَّ خارج ``books_in_scope`` في اللوحة والقائمة — وإلّا انفرج سطحٌ عن جاره."""

    def test_the_views_read_the_one_scope(self):
        import importlib
        books_list = importlib.import_module('core.views.books_list')
        dashboard = importlib.import_module('core.views.dashboard')   # الوحدةُ لا الدالّةُ المُعاد تصديرُها
        for fn in (dashboard.dashboard, books_list.book_unified, books_list.api_unified_data,
                   books_list.api_export_csv):
            with self.subTest(view=fn.__name__):
                src = inspect.getsource(fn)
                self.assertNotIn('Book.objects', src)
        for fn in (books_list.book_unified, books_list.api_unified_data, books_list.api_export_csv):
            with self.subTest(view=fn.__name__):
                self.assertIn('_list_scope(request)', inspect.getsource(fn))

    def test_the_list_script_no_longer_knows_the_switch(self):
        src = (Path(settings.BASE_DIR) / 'static' / 'js' / 'book_unified_ajax_manager.js').read_text(encoding='utf-8')
        self.assertNotIn('legacy', src.lower())

    def test_the_list_script_keeps_its_state_honest(self):
        """مراجعةُ 2026‑10‑27: مؤشّرُ الفرز يُزامَن بعد الاستعادة، والجلبُ أثناء جلبٍ لا يُرمى،
        والرجوعُ لا يدفع مدخلاً جديداً."""
        src = (Path(settings.BASE_DIR) / 'static' / 'js' / 'book_unified_ajax_manager.js').read_text(encoding='utf-8')

        def body(name):
            start = src.index(f'\n    {name}(')
            return src[start:src.index('\n    }\n', start)]

        self.assertIn('this.syncSortIndicators()', body('restoreStateFromUrl'))
        self.assertIn("(this.currentState.search ? '' : '-date')", body('syncSortIndicators'))
        load = body('async updateUrlAndLoadData')
        self.assertIn('this.pendingReload = { push }', load)
        self.assertIn('if (next) this.updateUrlAndLoadData(next)', load)
        self.assertIn('updateUrlAndLoadData({ push: false })', src)
        self.assertNotIn('history.pushState', body('clearAllFilters'))
