# -*- coding: utf-8 -*-
"""
اختبارات نظام الحجز الذكي: إعادة تدوير بلا فجوات + أولوية عودة cooldown + heartbeat/sweep.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Book, BookNumberReservation, BookSequence
from .reservation_service import reserve_number, sweep_stale, force_cooldown_for_user

KIND = 'incoming_internal'


class RecycleNoGapTests(TestCase):
    def setUp(self):
        self.a = User.objects.create_user('a', password='p')
        self.b = User.objects.create_user('b', password='p')
        self.c = User.objects.create_user('c', password='p')

    def test_two_users_get_distinct_numbers(self):
        r1, o1 = reserve_number(self.a, KIND)
        r2, o2 = reserve_number(self.b, KIND)
        self.assertEqual((o1, o2), ('new', 'new'))
        self.assertNotEqual(r1.number, r2.number)
        self.assertEqual([r1.number, r2.number], [1, 2])

    def test_voided_number_is_recycled_no_gap(self):
        r1, _ = reserve_number(self.a, KIND)          # 1 (جديد)
        r1.mark_voided()                               # تُرك → قابل للتدوير
        r2, o2 = reserve_number(self.b, KIND)          # يُعاد تدوير 1
        self.assertEqual(o2, 'recycled')
        self.assertEqual(r2.number, r1.number)
        self.assertTrue(r2.is_recycled)
        self.assertEqual(r2.user, self.b)
        # المستخدم الثالث يأخذ الرقم الجديد التالي (2) — بلا فجوة ولا تكرار
        r3, o3 = reserve_number(self.c, KIND)
        self.assertEqual(o3, 'new')
        self.assertEqual(r3.number, 2)

    def test_used_number_not_recycled(self):
        r1, _ = reserve_number(self.a, KIND)           # 1
        book = Book.objects.create(our_number=r1.formatted, title='x',
                                   date=timezone.localdate(), kind=KIND, created_by=self.a)
        r1.mark_used(book)
        r2, o2 = reserve_number(self.b, KIND)          # لا تدوير (1 مُستخدَم) → جديد 2
        self.assertEqual(o2, 'new')
        self.assertEqual(r2.number, 2)

    def test_voided_but_number_used_by_book_is_skipped(self):
        # حالة حافّة: حجز ملغى لكن رقمه استُهلك فعلاً بكتاب (auto_number بلا حجز)
        r1, _ = reserve_number(self.a, KIND)           # 1
        Book.objects.create(our_number=r1.formatted, title='x',
                            date=timezone.localdate(), kind=KIND, created_by=self.a)
        r1.mark_voided()                               # ملغى، لكن الرقم مستخدم
        r2, o2 = reserve_number(self.b, KIND)          # يتخطّى 1 → جديد 2
        self.assertEqual(o2, 'new')
        self.assertEqual(r2.number, 2)


class CooldownPriorityTests(TestCase):
    def setUp(self):
        self.a = User.objects.create_user('a', password='p')
        self.b = User.objects.create_user('b', password='p')

    def test_cooldown_reserved_for_owner_not_recycled_early(self):
        r1, _ = reserve_number(self.a, KIND)           # 1
        r1.enter_cooldown(15)                           # انقطاع قسريّ — محجوز لـa 15د
        # b يحجز أثناء cooldown a → لا يأخذ رقم a، بل رقماً جديداً
        r2, o2 = reserve_number(self.b, KIND)
        self.assertEqual(o2, 'new')
        self.assertEqual(r2.number, 2)
        # a يعود خلال المهلة → يسترجع رقمه نفسه (كتبه ورقياً غالباً)
        r3, o3 = reserve_number(self.a, KIND)
        self.assertEqual(o3, 'resumed')
        self.assertEqual(r3.pk, r1.pk)
        self.assertEqual(r3.number, 1)
        self.assertEqual(r3.status, BookNumberReservation.STATUS_ACTIVE)

    def test_cooldown_expired_recycled_to_others(self):
        r1, _ = reserve_number(self.a, KIND)           # 1
        r1.enter_cooldown(15)
        # انقضت المهلة
        r1.cooldown_until = timezone.now() - timedelta(minutes=1)
        r1.save(update_fields=['cooldown_until'])
        r2, o2 = reserve_number(self.b, KIND)          # يُدوَّر لـb
        self.assertEqual(o2, 'recycled')
        self.assertEqual(r2.number, 1)
        self.assertEqual(r2.user, self.b)
        self.assertTrue(r2.is_recycled)

    def test_existing_active_returned_not_duplicated(self):
        r1, o1 = reserve_number(self.a, KIND)
        r2, o2 = reserve_number(self.a, KIND)          # نفس المستخدم/النوع → نفس الحجز
        self.assertEqual(o2, 'existing')
        self.assertEqual(r1.pk, r2.pk)


class HeartbeatSweepTests(TestCase):
    def setUp(self):
        self.a = User.objects.create_user('a', password='p')
        self.client = Client()

    def test_sweep_dead_heartbeat_to_cooldown(self):
        r1, _ = reserve_number(self.a, KIND)
        r1.last_heartbeat = timezone.now() - timedelta(minutes=5)
        r1.save(update_fields=['last_heartbeat'])
        n = sweep_stale()
        r1.refresh_from_db()
        self.assertGreaterEqual(n, 1)
        self.assertEqual(r1.status, BookNumberReservation.STATUS_COOLDOWN)

    def test_force_cooldown_for_user(self):
        r1, _ = reserve_number(self.a, KIND)
        moved = force_cooldown_for_user(self.a)
        r1.refresh_from_db()
        self.assertEqual(moved, 1)
        self.assertEqual(r1.status, BookNumberReservation.STATUS_COOLDOWN)
        self.assertIsNotNone(r1.cooldown_until)

    def test_heartbeat_endpoint_keeps_alive(self):
        self.client.login(username='a', password='p')
        r1, _ = reserve_number(self.a, KIND)
        resp = self.client.post(reverse('reservation-heartbeat'),
                                data='{"reservation_id": %d}' % r1.pk,
                                content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body['alive'])
        r1.refresh_from_db()
        self.assertIsNotNone(r1.last_heartbeat)

    def test_heartbeat_reports_dead_after_recycle(self):
        self.client.login(username='a', password='p')
        r1, _ = reserve_number(self.a, KIND)
        r1.mark_voided()                                # لم يعد حيّاً
        resp = self.client.post(reverse('reservation-heartbeat'),
                                data='{"reservation_id": %d}' % r1.pk,
                                content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()['alive'])
