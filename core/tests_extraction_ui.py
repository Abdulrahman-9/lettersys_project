# -*- coding: utf-8 -*-
"""اختبارات واجهة الاستخراج الذكية (طبقة العرض):
- ودجة «آخر الكتب»: نطاق الوصول (created_by) + الترتيب (-created_at) + السقف + الغياب في التعديل.
- زر الإلغاء: بنية <button> + backTarget مُصلَّب + تتبّع dirty + beforeunload.
- بطاقتا P1 (quality-hero + needs_review) حاضرتان في وضع الإدخال.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Book

URL = "extraction-smart-desktop"


class RecentBooksWidgetTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("a", "a@x.com", "pass1234")
        self.clerk = User.objects.create_user("c", "c@x.com", "pass1234")
        self.other = User.objects.create_user("o", "o@x.com", "pass1234")
        self.today = timezone.now().date()

    def _book(self, num, owner):
        return Book.objects.create(our_number=num, title="ك" + num, date=self.today, created_by=owner)

    def test_scope_regular_user_sees_only_own(self):
        self._book("c1", self.clerk)
        self._book("o1", self.other)
        self.client.force_login(self.clerk)
        nums = {b.our_number for b in self.client.get(reverse(URL)).context["recent_books"]}
        self.assertIn("c1", nums)
        self.assertNotIn("o1", nums)          # لا تسرّب كتب مستخدم آخر

    def test_scope_superuser_sees_all(self):
        self._book("c1", self.clerk)
        self._book("o1", self.other)
        self.client.force_login(self.admin)
        nums = {b.our_number for b in self.client.get(reverse(URL)).context["recent_books"]}
        self.assertTrue({"c1", "o1"} <= nums)

    def test_ordering_newest_registered_first(self):
        self.client.force_login(self.admin)
        self._book("old", self.admin)
        self._book("new", self.admin)
        rb = self.client.get(reverse(URL)).context["recent_books"]
        self.assertEqual(rb[0].our_number, "new")   # -created_at

    def test_capped_at_four(self):
        self.client.force_login(self.admin)
        for i in range(6):
            self._book("n%d" % i, self.admin)
        self.assertLessEqual(len(self.client.get(reverse(URL)).context["recent_books"]), 4)

    def test_absent_in_edit_mode(self):
        b = self._book("e1", self.admin)
        self.client.force_login(self.admin)
        rb = self.client.get(reverse(URL) + "?edit_pk=%d" % b.id).context["recent_books"]
        self.assertEqual(list(rb), [])


class CancelButtonStructureTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("a", "a@x.com", "pass1234")
        self.client.force_login(self.admin)

    def test_button_and_guards_present(self):
        body = self.client.get(reverse(URL)).content.decode()
        self.assertIn('<button type="button" class="btn-action-neutral" id="cancelEditButton"', body)
        self.assertIn("bi bi-x-lg", body)
        self.assertNotIn("✕ إلغاء", body)
        self.assertIn("new URL(ref).origin === window.location.origin", body)   # backTarget مُصلَّب
        self.assertIn("__setExtractionBaseline", body)                          # تتبّع dirty
        self.assertIn("addEventListener('beforeunload'", body)                  # شبكة أمان


class ExtractionP1CardsTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("a", "a@x.com", "pass1234")
        self.client.force_login(self.admin)

    def test_p1_cards_present_in_create_mode(self):
        body = self.client.get(reverse(URL)).content.decode()
        self.assertIn('id="qualityHero"', body)
        self.assertIn('id="needsReviewCard"', body)
