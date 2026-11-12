# -*- coding: utf-8 -*-
"""تدقيقُ 2026-10-08، مجموعةُ «اللوحة والطاولات».

**بلاطةُ «الأسبوع» تعدّ ما لا يفتحه رابطُها**: كانت بلا حدٍّ أعلى فتعدّ الكتبَ المؤرَّخة في المستقبل.
(واختبارا «ما يخصّني اليوم» ولوحة الطوابير ذهبا مع الصفحة — حُذفت بقرار المالك 11‑04.)
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
