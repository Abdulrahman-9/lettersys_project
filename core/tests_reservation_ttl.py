# -*- coding: utf-8 -*-
"""عقدُ «مدّةُ حجز الرقم بيانٌ في القاعدة لا سطرٌ في ملفّ البيئة».

كانت الصفحةُ تكتب ``RESERVATION_EXPIRE_MINUTES`` في ``.env`` — مفتاحٌ لا يقرؤه
``settings.py`` **أبداً** — ثمّ تُطفِّر ثابتَ وحدةٍ في الذاكرة. فكان الأثرُ
لحظيّاً في العمليّة الواحدة وزائلاً مع كلّ إقلاع؛ وتحت ACL الإنتاج (ملفُّ
البيئة للقراءة فقط) لا يحدث شيءٌ أصلاً بينما تُعلن الواجهةُ النجاح.

الاختبارُ الحاكم هنا هو ``DbIsTheOnlyChannelTests``: يُغيّر القيمةَ
بـ``queryset.update()`` — **لا عبر الواجهة** — فلا ``save()`` يُبطل الكاش ولا
طفرةَ على كائن الإعدادات، ثمّ يقرأ عبر واجهةِ الحجز الحقيقيّة. بذلك يسقط
أيُّ تراجعٍ يُمرّر القيمةَ في ذاكرةِ العمليّة (وهو بالضبط ما كان يفعله الكودُ
القديم) أو يقرؤها من كاش LocMem.
"""
import importlib

from django.conf import settings as dj_settings
from django.contrib.auth.models import User
from django.core.cache import cache
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

    # ── 3) الصمودُ لعمليّةٍ جديدة ──────────────────────────────────────────
    def test_survives_a_fresh_process(self):
        self.c.post(reverse('sequence_settings'),
                    {'reservation_expire_minutes': '15'})

        # الحفظُ لا يجوز أن يُخزّن القيمةَ على كائن الإعدادات: تلك كانت القناةَ
        # القديمةَ (``dj_settings.RESERVATION_EXPIRE_MINUTES = minutes``) وهي
        # تزول مع كلّ إقلاع. لو عادت لَما أمسكها إعادةُ الاستيراد أدناه.
        self.assertFalse(hasattr(dj_settings, 'RESERVATION_EXPIRE_MINUTES'),
                         'الحفظُ طفَّر كائنَ الإعدادات — القناةُ الزائلةُ عادت')

        # محاكاةُ إقلاعٍ جديد: أيُّ ثابتِ وحدةٍ مُجمَّدٍ يُعاد حسابُه الآن.
        import core.reservation_api as rapi
        importlib.reload(rapi)
        import core.reservation_service as rsvc
        importlib.reload(rsvc)

        # القراءةُ عبر الواجهةِ الحقيقيّة بعد إعادة الاستيراد، لا عبر الخدمة
        # مباشرةً — فالواجهةُ هي ما تضربه الكاتبة.
        self.c.force_login(self.clerk)
        api = self.c.post(reverse('reservation-reserve'),
                          data='{"kind": "%s"}' % KIND,
                          content_type='application/json')
        self.assertEqual(api.status_code, 200, api.content)
        r = BookNumberReservation.objects.get(pk=api.json()['reservation']['id'])
        self.assertAlmostEqual(_minutes_until(r.expires_at), 15, delta=1)

    # ── 4) حدودُ المدى من ثوابت النموذج لا من رقمٍ في الاختبار ─────────────
    def test_range_is_enforced_from_model_constants(self):
        lo = SystemSettings.RESERVATION_TTL_MIN
        hi = SystemSettings.RESERVATION_TTL_MAX
        # ``'²'`` فخُّ ``isdigit()``: صحيحٌ لها و``int()`` يرفع ⟵ 500 بعد أن
        # حُفظت العدّادات. و``'٤٥'`` عكسُها: رقمٌ عربيٌّ هنديٌّ ``int`` يقبله.
        for bad in (str(lo - 1), str(hi + 1), 'abc', '-5', '²', '4.5'):
            resp = self.c.post(reverse('sequence_settings'),
                               {'reservation_expire_minutes': bad}, follow=True)
            self.assertEqual(resp.status_code, 200, f'{bad!r} ⟵ {resp.status_code}')
            self.assertEqual(
                SystemSettings.reservation_ttl(),
                SystemSettings.RESERVATION_TTL_DEFAULT,
                f'قيمةٌ خارجُ المدى غيّرت الإعداد: {bad!r}')
            # **الرفضُ يُقال**: كانت رسالةُ النجاح تُطلَق على كلّ طلب.
            texts = [m.message for m in resp.context['messages']]
            self.assertTrue(any('مرفوضة' in t for t in texts),
                            f'رفضٌ صامت: {bad!r} ⟵ {texts}')
            self.assertFalse(any('والحجز بنجاح' in t for t in texts),
                             f'قالت «حُفظ» وهي لم تحفظ: {bad!r} ⟵ {texts}')
        # الفراغُ يعني «لا تغيير» لا رفضاً — ولا رسالةَ خطأ له.
        resp = self.c.post(reverse('sequence_settings'),
                           {'reservation_expire_minutes': ''}, follow=True)
        texts = [m.message for m in resp.context['messages']]
        self.assertTrue(any('والحجز بنجاح' in t for t in texts), texts)
        for good in (str(lo), str(hi)):
            resp = self.c.post(reverse('sequence_settings'),
                               {'reservation_expire_minutes': good}, follow=True)
            self.assertEqual(SystemSettings.reservation_ttl(), int(good))
            texts = [m.message for m in resp.context['messages']]
            self.assertTrue(any('والحجز بنجاح' in t for t in texts), texts)

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


class DbIsTheOnlyChannelTests(TestCase):
    """**الحارسُ الحاكم**: القاعدةُ هي القناة، وقتَ الاستعمال، بلا كاش.

    كلُّ اختبارٍ في الصنف السابق يُغيّر القيمةَ عبر الواجهة — وهي تنادي
    ``cfg.save()`` الذي يُبطل الكاش في العمليّة نفسِها، فلا يُمسك تراجُعاً
    يُمرّر القيمةَ في ذاكرةِ العمليّة أو يقرؤها من كاش LocMem. هنا القيمةُ
    تُغيَّر بـ``queryset.update()``: لا ``save()``، لا إبطالَ كاش، لا طفرةَ
    إعدادات. فإن لم تظهر في مسار الحجز فالقناةُ ليست القاعدة.
    """

    def setUp(self):
        self.clerk = User.objects.create_user('clerk2', password='p')
        self.c = Client()
        cache.delete(SystemSettings.CACHE_KEY)

    @staticmethod
    def _set_ttl_in_db_only(minutes):
        """يكتب العمودَ مباشرةً: ``update()`` لا يمرّ بـ``save()`` أبداً."""
        SystemSettings.get()          # يضمن وجودَ الصفّ
        n = SystemSettings.objects.filter(singleton=1).update(
            reservation_expire_minutes=minutes)
        assert n == 1, n

    def test_ttl_is_read_from_the_database_at_use_time(self):
        self._set_ttl_in_db_only(15)
        self.assertEqual(SystemSettings.reservation_ttl(), 15)

        self.c.force_login(self.clerk)
        api = self.c.post(reverse('reservation-reserve'),
                          data='{"kind": "%s"}' % KIND,
                          content_type='application/json')
        self.assertEqual(api.status_code, 200, api.content)
        r = BookNumberReservation.objects.get(pk=api.json()['reservation']['id'])
        self.assertAlmostEqual(_minutes_until(r.expires_at), 15, delta=1)

        # وإعادةُ التفعيل كذلك — عبر الواجهة، بلا أيّ لمسٍ للإعدادات.
        r.mark_expired()
        self._set_ttl_in_db_only(20)
        resp = self.c.post(reverse('reservation-reactivate'),
                           data='{"reservation_id": %d}' % r.pk,
                           content_type='application/json')
        self.assertEqual(resp.status_code, 200, resp.content)
        r.refresh_from_db()
        self.assertAlmostEqual(_minutes_until(r.expires_at), 20, delta=1)

    def test_ttl_ignores_the_display_cache(self):
        """حارسُ «لا تقرأ من الكاش» في ``reservation_ttl`` — مُطفَّرٌ فعلاً.

        كاشُ ``CACHE_KEY`` للعرض وحدَه وهو LocMem: لا يُبطَل إلّا في العمليّة
        التي حفظت. لو قرأ مسارُ الحجز منه، لَبقيَ عاملاً على كائنٍ قديمٍ في
        كلّ عمليّةٍ أخرى. نُسخّن الكاشَ بطلبٍ حقيقيّ (يمرّ بـ
        ``context_processors.system_settings``) ثمّ نكتب في القاعدة وحدَها.
        """
        staff = User.objects.create_user('boss3', password='p', is_staff=True)
        warm = Client()
        warm.force_login(staff)
        self.assertEqual(warm.get(reverse('sequence_settings')).status_code, 200)
        cached = cache.get(SystemSettings.CACHE_KEY)
        self.assertIsNotNone(cached, 'الكاشُ لم يُسخَّن ⟵ الاختبارُ صار أجوف')
        self.assertEqual(cached.reservation_expire_minutes,
                         SystemSettings.RESERVATION_TTL_DEFAULT)

        self._set_ttl_in_db_only(15)
        # الكاشُ ما زال يحمل الكائنَ القديم — وهذا هو جوهرُ الاختبار.
        stale = cache.get(SystemSettings.CACHE_KEY)
        self.assertIsNotNone(stale)
        self.assertEqual(stale.reservation_expire_minutes,
                         SystemSettings.RESERVATION_TTL_DEFAULT)
        self.assertEqual(SystemSettings.reservation_ttl(), 15,
                         'مسارُ الحجز يقرأ من كاش العرض')

        self.c.force_login(self.clerk)
        api = self.c.post(reverse('reservation-reserve'),
                          data='{"kind": "%s"}' % KIND,
                          content_type='application/json')
        r = BookNumberReservation.objects.get(pk=api.json()['reservation']['id'])
        self.assertAlmostEqual(_minutes_until(r.expires_at), 15, delta=1)


class EveryReservationPathUsesTheStoredTtlTests(TestCase):
    """المخارجُ الأربعةُ لـ``reserve_number`` وافتراضا النموذج — كلُّها مُطفَّرة.

    كانت الاختباراتُ تصل المخرَجَ ``new`` وحدَه، فإعادةُ الرقم 45 مكتوباً بيدٍ
    في فرع ``resumed`` أو ``recycled`` أو في افتراضِ ``reactivate``/``reserve``
    تبقى خضراء. هنا لكلِّ موضعٍ منها سطرُ تحقّق.
    """

    def setUp(self):
        self.a = User.objects.create_user('clerk_a', password='p')
        self.b = User.objects.create_user('clerk_b', password='p')
        SystemSettings.get()
        SystemSettings.objects.filter(singleton=1).update(
            reservation_expire_minutes=15)

    def test_resumed_path_uses_the_stored_ttl(self):
        from .reservation_service import force_cooldown_for_user, reserve_number
        r, outcome = reserve_number(self.a, KIND)
        self.assertEqual(outcome, 'new')
        self.assertEqual(force_cooldown_for_user(self.a, KIND), 1)
        again, outcome = reserve_number(self.a, KIND)
        self.assertEqual(outcome, 'resumed')
        self.assertEqual(again.pk, r.pk)
        self.assertAlmostEqual(_minutes_until(again.expires_at), 15, delta=1)

    def test_recycled_path_uses_the_stored_ttl(self):
        from .reservation_service import reserve_number
        r, outcome = reserve_number(self.a, KIND)
        self.assertEqual(outcome, 'new')
        r.mark_voided()
        recycled, outcome = reserve_number(self.b, KIND)
        self.assertEqual(outcome, 'recycled')
        self.assertEqual(recycled.pk, r.pk)
        self.assertAlmostEqual(_minutes_until(recycled.expires_at), 15, delta=1)

    def test_model_level_defaults_resolve_from_the_database(self):
        from .reservation_service import reserve_number
        r, _ = reserve_number(self.a, KIND)
        r.mark_expired()
        # ``reactivate()`` بلا وسيط — الافتراضُ ``None`` يُحَلُّ من القاعدة.
        r.reactivate()
        self.assertAlmostEqual(_minutes_until(r.expires_at), 15, delta=1)
        # و``BookNumberReservation.reserve()`` بلا وسيط كذلك.
        SystemSettings.objects.filter(singleton=1).update(
            reservation_expire_minutes=25)
        fresh = BookNumberReservation.reserve(self.b, KIND)
        self.assertAlmostEqual(_minutes_until(fresh.expires_at), 25, delta=1)

