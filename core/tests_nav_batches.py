"""تدقيقُ الانتقالات — الدفعات 3 إلى 5: الرجوعُ في مكانه، لا فعلَ بـGET، صفحاتُ خطأٍ داخل القشرة."""

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import Book, Entity, Notification


class BackLandsWhereYouCameFromTests(TestCase):

    def setUp(self):
        self.staff = User.objects.create_user('navb', password='pw-navb-11', is_staff=True)
        self.client.force_login(self.staff)

    def test_desk_print_pages_go_back_to_the_desk_board(self):
        for name in ('desk_handover', 'desk_ledger'):
            src = open(f'templates/core/{name}.html', encoding='utf-8').read()
            self.assertIn("{% url 'desk_board' %}", src, name)
            self.assertNotIn('href="/books/"', src, name)

    def test_settings_subpages_cancel_back_into_the_hub(self):
        for tpl, tab in (('scan_settings', 'scan'), ('sequence_settings', 'sequences'), ('network_settings', 'network')):
            src = open(f'templates/core/{tpl}.html', encoding='utf-8').read()
            self.assertIn(f"{{% url 'settings_hub' %}}?tab={tab}", src, tpl)
            self.assertNotIn("{% url 'book_unified' %}\" class=\"btn btn-sm btn-outline-secondary\">رجوع", src, tpl)

    def test_editing_an_entity_returns_to_its_detail_by_default(self):
        e = Entity.objects.create(name='جهةُ الرجوع')
        r = self.client.post(reverse('entity_edit', args=[e.pk]), {'name': 'جهةُ الرجوع', 'kind': 'external', 'is_active': 'on'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r['Location'], reverse('entity_detail', args=[e.pk]))

    def test_editing_an_entity_honours_an_internal_next_only(self):
        e = Entity.objects.create(name='جهةُ next')
        url = reverse('entity_edit', args=[e.pk])
        r = self.client.post(url + '?next=' + reverse('entity_list') + '%3Fq%3Dx', {'name': 'جهةُ next', 'kind': 'external', 'is_active': 'on'})
        self.assertEqual(r['Location'], reverse('entity_list') + '?q=x')
        r = self.client.post(url + '?next=https://evil.example/', {'name': 'جهةُ next', 'kind': 'external', 'is_active': 'on'})
        self.assertEqual(r['Location'], reverse('entity_detail', args=[e.pk]), 'next خارجيّ قُبل — تحويلٌ مفتوح')
        r = self.client.post(url + '?next=//evil.example/', {'name': 'جهةُ next', 'kind': 'external', 'is_active': 'on'})
        self.assertEqual(r['Location'], reverse('entity_detail', args=[e.pk]))

    def test_restore_message_links_to_the_book(self):
        from django.utils import timezone
        b = Book.objects.create(kind='incoming_internal', title='مستعاد', created_by=self.staff,
                                is_deleted=True, deleted_at=timezone.now())
        r = self.client.post(reverse('restore_book', args=[b.pk]), follow=True)
        self.assertContains(r, reverse('book_detail', args=[b.pk]))


class NoMutationOverGetTests(TestCase):

    def test_mark_read_rejects_get_and_accepts_post(self):
        u = User.objects.create_user('navn', password='pw-navn-11')
        n = Notification.objects.create(user=u, title='ت', message='م')
        self.client.force_login(u)
        self.assertEqual(self.client.get(reverse('notification_mark_read', args=[n.pk])).status_code, 405)
        self.assertFalse(Notification.objects.get(pk=n.pk).is_read)
        r = self.client.post(reverse('notification_mark_read', args=[n.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Notification.objects.get(pk=n.pk).is_read)


@override_settings(DEBUG=False)
class ErrorPagesInsideTheShellTests(TestCase):

    def test_404_carries_the_shell_and_a_way_back(self):
        u = User.objects.create_user('nav4', password='pw-nav4-11')
        self.client.force_login(u)
        r = self.client.get(reverse('book_detail', args=[999999]))
        self.assertEqual(r.status_code, 404)
        self.assertContains(r, 'app-sidebar', status_code=404)
        self.assertContains(r, 'data-error-back', status_code=404)

    def test_403_carries_the_shell(self):
        other = User.objects.create_user('nav3a', password='pw-nav3a-11')
        owner = User.objects.create_user('nav3b', password='pw-nav3b-11')
        b = Book.objects.create(kind='incoming_internal', title='ممنوع', created_by=owner)
        self.client.force_login(other)
        r = self.client.get(reverse('book_edit', args=[b.pk]))
        self.assertEqual(r.status_code, 403)
        self.assertContains(r, 'data-error-back', status_code=403)


class LifecycleRefreshInPlaceTests(TestCase):
    """ح1: أفعالُ الدورة تُعيد رسمَ مناطقَ موسومةٍ في المكان — لا إعادةَ تحميلٍ للصفحة."""

    def test_the_page_marks_the_regions_the_script_swaps(self):
        u = User.objects.create_user('navlc', password='pw-navlc-11', is_staff=True)
        b = Book.objects.create(kind='incoming_internal', title='دورة', created_by=u)
        self.client.force_login(u)
        r = self.client.get(reverse('book_detail', args=[b.pk]))
        self.assertEqual(r.status_code, 200)
        for region in ('lifecycleRegion', 'followupStateText', 'followupHistoryCard'):
            self.assertContains(r, f'id="{region}" data-lifecycle-refresh')
        self.assertContains(r, 'id="lifecycleCard"')

    def test_the_script_no_longer_reloads_on_success(self):
        src = open('static/js/book_lifecycle.js', encoding='utf-8').read()
        self.assertIn('function refreshInPlace', src)
        self.assertIn("region.addEventListener('click'", src)
        self.assertNotIn("card.addEventListener('click'", src)


class EyeOpensFullDetailTests(TestCase):
    """قرارُ المالك 2026‑09‑13: زرُّ العين في القائمة يفتح **صفحةَ الكتاب كاملةً**
    لا الحوارَ السريع (الحوارُ لا يحمل دورةَ الحياة ولا التعليقات ولا السجلّ)."""

    def setUp(self):
        self.u = User.objects.create_user('eyev', password='pw-eyev-11', is_staff=True)
        self.book = Book.objects.create(kind='incoming_internal', title='للعرض', created_by=self.u)
        self.client.force_login(self.u)

    def test_the_list_row_links_straight_to_the_detail_page(self):
        r = self.client.get(reverse('book_unified'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, reverse('book_detail', args=[self.book.pk]))
        self.assertNotContains(r, f'data-book-preview="{self.book.pk}"')

    def test_the_detail_page_carries_what_the_quick_dialog_lacked(self):
        r = self.client.get(reverse('book_detail', args=[self.book.pk]))
        for marker in ('id="lifecycleCard"', 'id="followupHistoryCard"', 'إضافة تعليق'):
            self.assertContains(r, marker)


class SettingsHubStructureTests(TestCase):
    """هيكلُ مركز الإعدادات (مراجعة 2026‑09‑13): حارسٌ واحدٌ لكلّ تبويب، ولا مساراتٍ حرفيّة."""

    def setUp(self):
        self.plain = User.objects.create_user('shp', password='pw-shp-11')
        self.staff = User.objects.create_user('shs', password='pw-shs-11', is_staff=True)

    def test_every_embedded_tab_is_guarded_like_the_hub(self):
        """كانت صفحةُ إعدادات الماسح بـlogin_required وحدَها: أيُّ مستخدمٍ يفتحها بالمسار."""
        self.client.force_login(self.plain)
        for name in ('settings_hub', 'scan_settings', 'sequence_settings', 'network_settings', 'user_roles'):
            r = self.client.get(reverse(name))
            self.assertIn(r.status_code, (302, 403), f'{name} مفتوحٌ لغير الموظّف ({r.status_code})')
        self.client.force_login(self.staff)
        for name in ('settings_hub', 'scan_settings'):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    def test_the_hub_has_no_hardcoded_admin_path(self):
        src = open('templates/core/settings/hub.html', encoding='utf-8').read()
        self.assertNotIn('href="/admin/', src)
        self.assertIn("{% url 'admin:core_aiintegrationsettings_changelist' %}", src)
