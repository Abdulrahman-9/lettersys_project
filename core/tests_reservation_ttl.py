# -*- coding: utf-8 -*-
"""عقدُ «مدّةُ حجز الرقم بيانٌ في القاعدة لا سطرٌ في ملفّ البيئة».

كانت الصفحةُ تكتب ``RESERVATION_EXPIRE_MINUTES`` في ``.env`` — مفتاحٌ لا يقرؤه
``settings.py`` **أبداً** — ثمّ تُطفِّر ثابتَ وحدةٍ في الذاكرة. فكان الأثرُ
لحظيّاً في العمليّة الواحدة وزائلاً مع كلّ إقلاع؛ وتحت ACL الإنتاج (ملفُّ
البيئة للقراءة فقط) لا يحدث شيءٌ أصلاً بينما تُعلن الواجهةُ النجاح.

الاختبارُ الحاكم هنا هو ``test_survives_a_fresh_process``: يُعيد استيرادَ
``core.reservation_api`` (محاكاةُ عمليّةٍ جديدة) ويتحقّق أنّ القيمةَ صمدت.
"""
import importlib

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import BookNumberReservation, SystemSettings

KIND = 'incoming_internal'


def _minutes_until(dt):
    return (dt - timezone.now()).total_seconds() / 60.0


class ReservationTtlContractTests(TestCase):
    """المصدرُ الوحيد للمدّة هو ``SystemSettings.reservation_expire_minutes``."""

    def setUp(self):
        self.staff = User.objects.create_user('boss', password='p', is_staff=True)
        self.clerk = User.objects.create_user('clerk', password='p')
        self.c = Client()
        self.c.force_login(self.staff)

    # ── 1) الافتراضُ 45: صفرُ تغييرٍ سلوكيٍّ عند الترقية ────────────────────
    def test_default_is_forty_five_and_stamps_the_reservation(self):
        self.assertEqual(SystemSettings.reservation_ttl(),
                         SystemSettings.RESERVATION_TTL_DEFAULT)
        self.assertEqual(SystemSettings.RESERVATION_TTL_DEFAULT, 45)
        from .reservation_service import reserve_number
        r, outcome = reserve_number(self.clerk, KIND)
        self.assertEqual(outcome, 'new')
        self.assertAlmostEqual(_minutes_until(r.expires_at), 45, delta=1)

    # ── 2) الأثرُ فوريٌّ بلا إعادةِ تشغيل ──────────────────────────────────
    def test_takes_effect_immediately_for_new_reservations(self):
        resp = self.c.post(reverse('sequence_settings'),
                           {'reservation_expire_minutes': '15'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(SystemSettings.reservation_ttl(), 15)

        self.c.force_login(self.clerk)
        api = self.c.post(reverse('reservation-reserve'),
                          data='{"kind": "%s"}' % KIND,
                          content_type='application/json')
        self.assertEqual(api.status_code, 200, api.content)
        res_id = api.json()['reservation']['id']
        r = BookNumberReservation.objects.get(pk=res_id)
        self.assertAlmostEqual(_minutes_until(r.expires_at), 15, delta=1)

    # ── 3) الصمودُ لعمليّةٍ جديدة — هذا هو الاختبارُ الذي يمنع التراجع ─────
    def test_survives_a_fresh_process(self):
        self.c.post(reverse('sequence_settings'),
                    {'reservation_expire_minutes': '15'})

        # محاكاةُ إقلاعٍ جديد: أيُّ ثابتِ وحدةٍ مُجمَّدٍ يُعاد حسابُه الآن،
        # وأيُّ طفرةٍ على كائن الإعدادات تزول.
        import core.reservation_api as rapi
        importlib.reload(rapi)
        import core.reservation_service as rsvc
        importlib.reload(rsvc)

        from .reservation_service import reserve_number
        r, _ = reserve_number(self.clerk, KIND)
        self.assertAlmostEqual(_minutes_until(r.expires_at), 15, delta=1)

    # ── 4) حدودُ المدى من ثوابت النموذج لا من رقمٍ في الاختبار ─────────────
    def test_range_is_enforced_from_model_constants(self):
        lo = SystemSettings.RESERVATION_TTL_MIN
        hi = SystemSettings.RESERVATION_TTL_MAX
        for bad in (str(lo - 1), str(hi + 1), 'abc', '', '-5'):
            self.c.post(reverse('sequence_settings'),
                        {'reservation_expire_minutes': bad})
            self.assertEqual(
                SystemSettings.reservation_ttl(),
                SystemSettings.RESERVATION_TTL_DEFAULT,
                f'قيمةٌ خارجُ المدى غيّرت الإعداد: {bad!r}')
        for good in (str(lo), str(hi)):
            self.c.post(reverse('sequence_settings'),
                        {'reservation_expire_minutes': good})
            self.assertEqual(SystemSettings.reservation_ttl(), int(good))

    # ── 5) الحجوزاتُ القائمةُ لا تُقصَّر ───────────────────────────────────
    def test_existing_reservations_keep_their_stamp(self):
        from .reservation_service import reserve_number
        r, _ = reserve_number(self.clerk, KIND)
        before = r.expires_at
        self.c.post(reverse('sequence_settings'),
                    {'reservation_expire_minutes': '15'})
        r.refresh_from_db()
        self.assertEqual(r.expires_at, before)

    # ── 6) إعادةُ التفعيل تستعمل القيمةَ الجديدة ───────────────────────────
    def test_reactivate_uses_the_stored_value(self):
        from .reservation_service import reserve_number
        r, _ = reserve_number(self.clerk, KIND)
        r.mark_expired()
        self.c.post(reverse('sequence_settings'),
                    {'reservation_expire_minutes': '20'})
        self.c.force_login(self.clerk)
        resp = self.c.post(reverse('reservation-reactivate'),
                           data='{"reservation_id": %d}' % r.pk,
                           content_type='application/json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertIn('20', resp.json()['message'])
        r.refresh_from_db()
        self.assertAlmostEqual(_minutes_until(r.expires_at), 20, delta=1)

    # ── 7) الحراسة ─────────────────────────────────────────────────────────
    def test_anonymous_and_plain_user_cannot_change_it(self):
        anon = Client()
        resp = anon.post(reverse('sequence_settings'),
                         {'reservation_expire_minutes': '99'})
        self.assertIn(resp.status_code, (301, 302))
        self.assertEqual(SystemSettings.reservation_ttl(),
                         SystemSettings.RESERVATION_TTL_DEFAULT)

        plain = Client()
        plain.force_login(self.clerk)
        resp = plain.post(reverse('sequence_settings'),
                          {'reservation_expire_minutes': '99'})
        self.assertIn(resp.status_code, (302, 403))
        self.assertEqual(SystemSettings.reservation_ttl(),
                         SystemSettings.RESERVATION_TTL_DEFAULT)
