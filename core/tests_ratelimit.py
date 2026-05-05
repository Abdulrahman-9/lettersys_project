# -*- coding: utf-8 -*-
"""
اختبارات Rate Limiting

تتحقق أن الـ decorator rate_limit يُعيد 429 بعد تجاوز الحد المسموح،
ويسمح بالطلبات الأولى بشكل طبيعي.

تشغيل:
    python manage.py test core.tests_ratelimit --settings=lettersys.settings_test
"""
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse


class RateLimitBaseTest(TestCase):
    """قاعدة مشتركة: مستخدم ومسح الكاش بين الاختبارات."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username='rltestuser', password='testpass123'
        )
        self.client = Client()
        self.client.login(username='rltestuser', password='testpass123')

    def tearDown(self):
        cache.clear()


# ─── save_book_api — 30/60s ────────────────────────────────────────────────


class SaveBookRateLimitTests(RateLimitBaseTest):
    """save_book_api محدود بـ 30 طلب/دقيقة لكل مستخدم."""

    URL = '/books/api/book/save/'

    def _valid_post(self):
        return self.client.post(self.URL, {
            'our_number': 'RL-TEST',
            'title': 'عنوان تجريبي',
            'date': '2026-01-01',
        })

    def test_requests_within_limit_succeed(self):
        """الطلبات ضمن الحد تنجح (أول طلب)."""
        resp = self._valid_post()
        # 400 أو 201 — أي شيء غير 429 يعني أن الـ rate limiter سمح بالمرور
        self.assertNotEqual(resp.status_code, 429)

    def test_exceeds_limit_returns_429(self):
        """تجاوز 30 طلب يُعيد 429."""
        # محاكاة 30 طلب سابقة في الكاش
        import time
        now = time.time()
        cache_key = f"rl:save_book:u{self.user.id}"
        cache.set(cache_key, [now] * 30, 60)

        resp = self._valid_post()
        self.assertEqual(resp.status_code, 429)

    def test_429_response_has_correct_structure(self):
        """استجابة 429 تحتوي على الحقول المطلوبة."""
        import time
        now = time.time()
        cache_key = f"rl:save_book:u{self.user.id}"
        cache.set(cache_key, [now] * 30, 60)

        resp = self._valid_post()
        self.assertEqual(resp.status_code, 429)
        data = resp.json()
        self.assertEqual(data['error_code'], 'RATE_LIMIT_EXCEEDED')
        self.assertIn('retry_after', data)
        self.assertGreater(data['retry_after'], 0)

    def test_429_has_retry_after_header(self):
        """استجابة 429 تحمل رأس Retry-After."""
        import time
        now = time.time()
        cache.set(f"rl:save_book:u{self.user.id}", [now] * 30, 60)

        resp = self._valid_post()
        self.assertEqual(resp.status_code, 429)
        self.assertIn('Retry-After', resp)

    def test_unauthenticated_falls_back_to_ip_key(self):
        """مستخدم غير مسجّل: يُعاد توجيهه للتسجيل (لا 429)."""
        anon_client = Client()
        resp = anon_client.post(self.URL, {
            'our_number': 'X', 'title': 'Y', 'date': '2026-01-01',
        })
        # login_required يُعيد redirect (302) — ليس 429
        self.assertEqual(resp.status_code, 302)


# ─── api_bulk_delete_books — 10/60s ───────────────────────────────────────


class BulkDeleteRateLimitTests(RateLimitBaseTest):
    """api_bulk_delete_books محدود بـ 10 طلبات/دقيقة."""

    URL = '/books/api/books/bulk-delete/'

    def _post(self, ids=None):
        import json
        return self.client.post(
            self.URL,
            data=json.dumps({'ids': ids or []}),
            content_type='application/json',
        )

    def test_first_request_not_429(self):
        resp = self._post()
        self.assertNotEqual(resp.status_code, 429)

    def test_exceeds_10_returns_429(self):
        import time
        now = time.time()
        cache.set(f"rl:bulk_delete_books:u{self.user.id}", [now] * 10, 60)
        resp = self._post([1, 2, 3])
        self.assertEqual(resp.status_code, 429)


# ─── api_bulk_update_status_books — 20/60s ────────────────────────────────


class BulkUpdateStatusRateLimitTests(RateLimitBaseTest):
    """api_bulk_update_status_books محدود بـ 20 طلبات/دقيقة."""

    URL = '/books/api/books/bulk-status/'

    def _post(self):
        import json
        return self.client.post(
            self.URL,
            data=json.dumps({'ids': [], 'status': 'done'}),
            content_type='application/json',
        )

    def test_first_request_not_429(self):
        resp = self._post()
        self.assertNotEqual(resp.status_code, 429)

    def test_exceeds_20_returns_429(self):
        import time
        now = time.time()
        cache.set(f"rl:bulk_update_status:u{self.user.id}", [now] * 20, 60)
        resp = self._post()
        self.assertEqual(resp.status_code, 429)


# ─── api_delete_book — 30/60s ─────────────────────────────────────────────


class DeleteBookRateLimitTests(RateLimitBaseTest):
    """api_delete_book محدود بـ 30 طلبات/دقيقة."""

    def test_first_request_not_429(self):
        """أول طلب لا يُعيد 429 (404 لأن الكتاب غير موجود — وهذا مقبول)."""
        resp = self.client.post('/books/api/book/999/delete/')
        self.assertNotEqual(resp.status_code, 429)

    def test_exceeds_limit_returns_429(self):
        import time
        now = time.time()
        cache.set(f"rl:delete_book:u{self.user.id}", [now] * 30, 60)
        resp = self.client.post('/books/api/book/999/delete/')
        self.assertEqual(resp.status_code, 429)


# ─── network scan — 3/300s ────────────────────────────────────────────────


class NetworkScanRateLimitTests(RateLimitBaseTest):
    """network_scan_subnet محدود بـ 3 طلبات/5 دقائق (staff فقط)."""

    def setUp(self):
        super().setUp()
        self.user.is_staff = True
        self.user.save()

    def test_exceeds_3_returns_429(self):
        import json, time
        now = time.time()
        cache.set(f"rl:network_scan_subnet:u{self.user.id}", [now] * 3, 300)
        resp = self.client.post(
            '/books/api/network/scan-subnet/',
            data=json.dumps({}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 429)

    def test_non_staff_blocked_before_rate_limit(self):
        """مستخدم عادي يحصل على 302 redirect (user_passes_test)."""
        self.user.is_staff = False
        self.user.save()
        resp = self.client.post('/books/api/network/scan-subnet/')
        self.assertIn(resp.status_code, [302, 403])


# ─── search_entities — 60/60s ─────────────────────────────────────────────


class SearchEntitiesRateLimitTests(RateLimitBaseTest):
    """search_entities محدود بـ 60 طلبات/دقيقة."""

    URL = '/books/api/search/entities/?q=test'

    def test_first_request_not_429(self):
        # search_entities يستخدم PostgreSQL Trigram — يفشل مع SQLite بـ 500
        # المهم: الـ rate limiter يسمح بالمرور (لا 429)
        self.client.raise_request_exception = False
        resp = self.client.get(self.URL)
        self.assertNotEqual(resp.status_code, 429)

    def test_exceeds_60_returns_429(self):
        import time
        now = time.time()
        cache.set(f"rl:search_entities:u{self.user.id}", [now] * 60, 60)
        resp = self.client.get(self.URL)
        self.assertEqual(resp.status_code, 429)


# ─── login — 10/300s by IP ────────────────────────────────────────────────


class LoginRateLimitTests(TestCase):
    """login محدود بـ 10 محاولات/5 دقائق بحسب IP."""

    def setUp(self):
        cache.clear()
        User.objects.create_user(username='loginuser', password='testpass123')

    def tearDown(self):
        cache.clear()

    def test_exceeds_login_attempts_returns_429(self):
        """بعد 10 محاولات POST يُعيد 429."""
        import time
        now = time.time()
        # العنوان IP الافتراضي في Django test client هو 127.0.0.1
        cache.set('rl:login:127.0.0.1', [now] * 10, 300)

        resp = Client().post('/login/', {
            'username': 'loginuser',
            'password': 'wrongpassword',
        })
        self.assertEqual(resp.status_code, 429)

    def test_login_succeeds_within_limit(self):
        """طلب POST ضمن الحد لا يُعيد 429."""
        resp = Client().post('/login/', {
            'username': 'loginuser',
            'password': 'testpass123',
        })
        self.assertNotEqual(resp.status_code, 429)


# ─── reservation — 30/60s ─────────────────────────────────────────────────


class ReserveNumberRateLimitTests(RateLimitBaseTest):
    """reserve_number محدود بـ 30 طلبات/دقيقة."""

    URL = '/books/api/reservation/reserve/'

    def test_first_request_not_429(self):
        import json
        resp = self.client.post(
            self.URL,
            data=json.dumps({'kind': 'incoming_internal'}),
            content_type='application/json',
        )
        self.assertNotEqual(resp.status_code, 429)

    def test_exceeds_30_returns_429(self):
        import json, time
        now = time.time()
        cache.set(f"rl:reserve_number:u{self.user.id}", [now] * 30, 60)
        resp = self.client.post(
            self.URL,
            data=json.dumps({'kind': 'incoming_internal'}),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 429)


# ─── sliding window: طلبات قديمة لا تُحتسب ──────────────────────────────


class SlidingWindowTests(RateLimitBaseTest):
    """التحقق من أن النافذة المنزلقة تتجاهل الطلبات القديمة."""

    def test_old_attempts_outside_window_not_counted(self):
        """
        طلبات قديمة خارج النافذة لا تُحتسب ضمن الحد،
        فيُسمح بطلب جديد رغم وجود سجل سابق.
        """
        import time
        old_time = time.time() - 120  # قبل دقيقتين — خارج نافذة 60 ثانية
        # 30 طلب قديمة جداً لـ save_book
        cache.set(f"rl:save_book:u{self.user.id}", [old_time] * 30, 60)

        resp = self.client.post('/books/api/book/save/', {
            'our_number': 'SLD-1',
            'title': 'نافذة منزلقة',
            'date': '2026-01-01',
        })
        # الـ decorator يُصفّي الطلبات القديمة — لا 429
        self.assertNotEqual(resp.status_code, 429)
