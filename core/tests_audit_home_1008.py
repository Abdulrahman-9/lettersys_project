# -*- coding: utf-8 -*-
"""تدقيقُ 2026-10-08، مجموعةُ «اللوحة وما يخصّني والطاولات».

١. **«ما يخصّني اليوم» كانت تدلّ الموظّفَ على 403**: «طاولةُ الوارد» و«سجلّي» لكلّ أحد، والصفحتان
   محروستان (``can_use_desk`` · ``can_view_audit``). الآن الرابطُ لمن يفتحه (``nav.desk`` · ``nav.audit``).
٢. **بلاطةُ «الأسبوع» تعدّ ما لا يفتحه رابطُها**: كانت بلا حدٍّ أعلى فتعدّ الكتبَ المؤرَّخة في المستقبل.
٣. **زرُّ فعلٍ بلا معالج** في لوحة الطوابير (`data-qb-act`) لم يُصرّح به طابورٌ قطّ — حُذف.
"""
import datetime
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Book, Department, UserProfile

ROOT = Path(__file__).resolve().parent.parent
User = get_user_model()


class MyTodayLinksFollowGatesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dept = Department.objects.create(name='قسم اليوم', code='ي.م')
        cls.clerk = User.objects.create_user('today_clerk', password='pw-today-clerk-1')
        UserProfile.objects.update_or_create(user=cls.clerk, defaults={'department': cls.dept})
        cls.head = User.objects.create_user('today_head', password='pw-today-head-1')
        UserProfile.objects.update_or_create(user=cls.head, defaults={'department': cls.dept,
                                                                      'is_department_head': True})

    def html(self, user):
        self.client.force_login(user)
        return self.client.get(reverse('my_today')).content.decode('utf-8')

    def test_a_clerk_is_not_sent_to_a_403(self):
        html = self.html(self.clerk)
        for name in ('desk_board', 'audit_log'):
            with self.subTest(page=name):
                self.assertNotIn('href="%s"' % reverse(name), html)
                # والصفحةُ نفسُها فعلاً مغلقةٌ عليه — فالرابطُ كان طريقاً مسدوداً
                self.assertEqual(self.client.get(reverse(name)).status_code, 403)
        self.assertIn('href="%s"' % reverse('book_unified'), html)

    def test_a_head_keeps_both(self):
        html = self.html(self.head)
        for name in ('desk_board', 'audit_log'):
            with self.subTest(page=name):
                self.assertIn('href="%s"' % reverse(name), html)


class WeekTileEqualsItsListTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.boss = User.objects.create_superuser('week_boss', 'w@x.co', 'pw-week-boss-1')
        today = timezone.localdate()
        Book.objects.create(kind='incoming_external', our_number='7401', title='هذا الأسبوع',
                            date=today - datetime.timedelta(days=2), created_by=cls.boss)
        # خطأُ سنةٍ في الإدخال: مؤرَّخٌ بعد اليوم
        Book.objects.create(kind='incoming_external', our_number='7402', title='مؤرَّخٌ في المستقبل',
                            date=today + datetime.timedelta(days=3), created_by=cls.boss)

    def test_week_count_matches_the_link(self):
        self.client.force_login(self.boss)
        ctx = self.client.get(reverse('dashboard')).context
        today = timezone.localdate()
        listed = self.client.get(reverse('book_unified'), {
            'tab': 'all', 'date_from': (today - datetime.timedelta(days=7)).isoformat(),
            'date_to': today.isoformat()}).context['total_count']
        self.assertEqual(ctx['week_count'], listed)
        self.assertEqual(ctx['week_count'], 1)


class QueueBoardHasNoDeadButtonTests(SimpleTestCase):
    def test_no_unhandled_row_action(self):
        src = (ROOT / 'templates' / 'core' / '_queue_board.html').read_text(encoding='utf-8')
        self.assertNotIn('data-qb-act', src)
