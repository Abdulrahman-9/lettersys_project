# -*- coding: utf-8 -*-
"""الحيُّ وحدَه في لوحة القيادة والقائمة — قرارُ المالك 2026‑10‑06 («نعم»).

كلُّ رقمٍ في اللوحة رابطٌ إلى القائمة؛ وكانت اللوحةُ تعدّ الكتبَ كلَّها (ومنها
11 ألفاً منقولةٌ من الورق وكتبُ التدريب) بينما التقاريرُ تعدّ الحيَّ — فيتخالف
الرقمُ وما يُفتح. الآن: المصدرُ واحد (``books_in_scope``)، والقائمةُ حيّةٌ افتراضاً
بمفتاح «يشمل الورق القديم»، **والبحثُ يجد الكلّ** والعدّاداتُ تتبع المفتاح لا النصّ.
(مراجعةُ فيبل 2026‑10‑06: D:/migration/fable_live_counts_20261006.md.)
"""
import csv
import inspect
import io
import json
from datetime import date, timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Book, BookHistory, Department, UserProfile


class LiveCountsTestCase(TestCase):
    """قسمٌ بكتبٍ حيّة، وورقٍ قديم (أحدُه أُعيد فتحُ متابعته فتأخّر، وآخرُ بتاريخ اليوم)،
    وكتابِ تدريبٍ بموعد — الحالاتُ التي تُفرّق بين العدّين."""

    @classmethod
    def setUpTestData(cls):
        cls.today = timezone.localdate()
        cls.dept = Department.objects.create(name='قسمُ العدّ', code='ع.ق')
        cls.clerk = User.objects.create_user('lclerk', password='pw-lclerk-1111')
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

    def test_the_numbers_count_live_books_only(self):
        """أعدادٌ مطلقة — ولا يكفي التساوي: لو عدّ الطرفان التدريبَ معاً لتساويا."""
        self.client.force_login(self.clerk)
        dash = self.client.get(reverse('dashboard')).context
        self.assertEqual((dash['total'], dash['overdue'], dash['incoming_pending'],
                          dash['today_count']), (4, 1, 2, 4))

    def test_the_switch_brings_the_paper_and_training_back(self):
        self.assertEqual(self._list(tab='all', followup='overdue', legacy='1')['total_count'], 2)
        self.assertEqual(self._list(tab='all', legacy='1')['total_count'], 7)


class SearchFindsEverythingTests(LiveCountsTestCase):
    """أرقامُ الدفتر القديم أوّلُ ما يُبحث عنه — والمفتاحُ مطفأ."""

    def test_a_tagged_number_and_a_legacy_number_find_the_paper_book(self):
        for q, book in (('825', self.paper_overdue), ('قديم-544', self.paper_today)):
            with self.subTest(q=q):
                ctx = self._list(tab='all', q=q)
                self.assertIn(book.pk, [b.pk for b in ctx['books']])
                self.assertTrue(ctx['search_widened'])
                data = self._api(tab='all', q=q)
                self.assertIn(book.pk, [b['id'] for b in data['books']])
                self.assertTrue(data['search_widened'])

    def test_without_a_search_the_paper_book_stays_out(self):
        ctx = self._list(tab='all')
        self.assertNotIn(self.paper_overdue.pk, [b.pk for b in ctx['books']])
        self.assertFalse(ctx['search_widened'])

    def test_the_export_follows_the_same_rule(self):
        self.client.force_login(self.clerk)

        def numbers(**params):
            resp = self.client.get(reverse('api_export_csv'), params)
            body = b''.join(resp.streaming_content).decode('utf-8')
            # BOM \u0648\u0627\u062d\u062f\u064c \u0641\u064a \u0623\u0648\u0651\u0644 \u0627\u0644\u0645\u0644\u0641\u0651 \u0644\u0627 \u0641\u064a \u0623\u0648\u0651\u0644 \u0643\u0644\u0651 \u0635\u0641\u0651 (\u0643\u0627\u0646 ``utf-8-sig`` \u064a\u064f\u0644\u0635\u0642\u0647 \u0628\u0643\u0644\u0651 \u062f\u0641\u0639\u0629)
            self.assertEqual(body.count('\ufeff'), 1)
            return [r[0] for r in list(csv.reader(io.StringIO(body.lstrip('\ufeff'))))[1:]]

        # تصديرُ القائمة يكتب الرقمَ المخزَّن كما هو (``our_number``)
        self.assertNotIn(self.paper_overdue.our_number, numbers(tab='all'))
        self.assertIn(self.paper_overdue.our_number, numbers(tab='all', q='825'))

    def test_the_counters_follow_the_switch_not_the_search(self):
        live = self._api(tab='all')['badges']
        self.assertEqual(self._api(tab='all', q='825')['badges'], live)
        self.assertEqual(self._api(tab='all', legacy='1')['badges']['overdue'], live['overdue'] + 1)

    def test_the_hint_says_it(self):
        self.client.force_login(self.clerk)
        html = self.client.get(reverse('book_unified'), {'q': '825'}).content.decode('utf-8')
        self.assertRegex(html, r'id="searchWidenedHint" role="status">')
        html = self.client.get(reverse('book_unified')).content.decode('utf-8')
        self.assertRegex(html, r'id="searchWidenedHint" role="status" hidden>')


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

    def test_the_list_script_keeps_the_switch(self):
        src = (Path(settings.BASE_DIR) / 'static' / 'js' / 'book_unified_ajax_manager.js').read_text(encoding='utf-8')
        self.assertIn("legacy: '',", src)                                   # الحالةُ الأولى
        self.assertIn('params.legacy     = this.currentState.legacy', src)  # الرابطُ والجلب
        self.assertIn("p.get('legacy') === '1'", src)                       # الاستعادةُ من الرابط
        self.assertIn("e.target.checked ? '1' : ''", src)                   # التأشيرُ لا القيمة
        self.assertRegex(src, r"entityId: '', status: '', legacy: '',")     # المسحُ يُطفئه
