# -*- coding: utf-8 -*-
"""تدقيقُ 2026-10-08، مجموعةُ «التقارير وسجلّ الحركات والسلّة».

١. **السلّةُ تعرض معرّفَ القاعدة رقماً (H2)**: الكتابُ بلا رقمٍ كان يظهر بمعرّفه الداخليّ (13456) فيُحسب
   رقمَ قيد؛ الآن «بلا رقم». والتاريخُ ISO ⟵ يوم/شهر/سنة كبقيّة التطبيق (H4).
٢. **رابطُ الكتاب في السجلّ مسارٌ مكتوبٌ باليد** ⟵ `{% url 'book_detail' %}`.
"""
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Book

ROOT = Path(__file__).resolve().parent.parent
User = get_user_model()


class TrashRowsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.boss = User.objects.create_superuser('trash_boss', 't@x.co', 'pw-trash-boss-1')
        cls.book = Book.objects.create(kind='outgoing_external', our_number='', title='بلا رقمٍ محذوف',
                                       created_by=cls.boss)
        Book.all_objects.filter(pk=cls.book.pk).update(
            is_deleted=True, deleted_at=timezone.make_aware(timezone.datetime(2026, 10, 8, 9, 5)),
            deleted_by=cls.boss)

    def test_numberless_row_and_date(self):
        self.client.force_login(self.boss)
        html = self.client.get(reverse('trash_list')).content.decode('utf-8')
        self.assertIn('<td>بلا رقم</td>', html)
        self.assertNotIn('<td>%d</td>' % self.book.pk, html)
        self.assertIn('08/10/2026', html)
        self.assertNotIn('2026-10-08 ', html)


class AuditLinkTests(SimpleTestCase):
    def test_book_link_is_reversed(self):
        src = (ROOT / 'templates' / 'core' / 'audit_log.html').read_text(encoding='utf-8')
        self.assertNotIn('href="/books/{{ row.book_id }}/"', src)
        self.assertIn("{% url 'book_detail' row.book_id %}", src)
