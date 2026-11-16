"""الدفعة 1 (قرارُ المالك 11-16): تبويباتُ اللوحة المستقلّة المكرّرة صارت صفحاتِها في البرنامج.

العناقيدُ ⟵ ورشتُها في الجهات · الحجوزاتُ ⟵ صفحةٌ جديدة في إطار البرنامج · سجلُّ الحركات
والإعدادات ⟵ صفحتاهما القائمتان. الحفظُ (POST) باقٍ على ``/books/admin/`` حتّى الدفعة 4.

كلُّ حارسٍ هنا يُطفَّر (قواعدُ الحرفة §9.4): التحويلُ ووجهتُه ومعاملاتُه الرقميّة، وبقاءُ رئيس
القسم على «نظرة عامة»، وصفحةُ الحجوزات (مديرُ النظام وحده · لا ذاكرة · للقراءة · نبرةُ الفائت).
"""
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import BookNumberReservation, Department, UserProfile

MOVED = ('groups', 'reservations', 'audit', 'settings')


class MovedTabsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.root = User.objects.create_superuser('b1-root', password='b1-root-pass-1234')
        UserProfile.objects.create(user=cls.root)
        cls.dept = Department.objects.create(name='قسم الاختبار', code='ت-1')
        cls.head = User.objects.create_user('b1-head', password='b1-head-pass-1234')
        UserProfile.objects.create(user=cls.head, department=cls.dept, is_department_head=True)

    def _old(self, user, **params):
        self.client.force_login(user)
        return self.client.get(reverse('admin_panel'), params)

    def test_each_moved_tab_leads_to_its_page(self):
        expected = {
            'groups': reverse('entity_list') + '?view=groups',
            'reservations': reverse('system_reservations'),
            'audit': reverse('audit_log'),
            'settings': reverse('settings_hub'),
        }
        for tab, url in expected.items():
            with self.subTest(tab=tab):
                response = self._old(self.root, tab=tab)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response['Location'], url)
                # والوجهةُ تُفتح فعلاً لمن حُوِّل إليها — لا تحويلٌ إلى رفض
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_only_numeric_parameters_travel(self):
        """الوجهةُ من قائمةٍ ثابتة، ومعاملاتُها أرقامٌ أو لا شيء — لا يُحمل نصٌّ حرٌّ في عنوان."""
        workshop = reverse('entity_list') + '?view=groups'
        reservations = reverse('system_reservations')
        cases = [
            ({'tab': 'groups', 'edit': '7'}, workshop + '&edit=7'),
            ({'tab': 'groups', 'edit': '7&view=entities'}, workshop),
            ({'tab': 'reservations', 'days': '30', 'page': 'abc'}, reservations + '?days=30'),
            ({'tab': 'reservations', 'days': '//evil.example'}, reservations),
            # «²» رقمٌ عند isdigit ويُسقط int() بخطأ 500 في الوجهة — isdecimal يرفضه هنا
            ({'tab': 'groups', 'edit': '²'}, workshop),
            ({'tab': 'reservations', 'days': '²', 'page': '²'}, reservations),
        ]
        for params, location in cases:
            with self.subTest(params=params):
                self.assertEqual(self._old(self.root, **params)['Location'], location)

    def test_a_superscript_digit_does_not_break_the_destinations(self):
        self.client.force_login(self.root)
        workshop = self.client.get(reverse('entity_list'), {'view': 'groups', 'edit': '²'})
        self.assertEqual(workshop.status_code, 200)
        self.assertIsNone(workshop.context['editing_group'])

    def test_a_head_stays_on_the_overview(self):
        """رئيسُ القسم لا يملك هذه الصفحات — فلا يُحوَّل إلى رفض، ويبقى حيث كان."""
        for tab in MOVED:
            with self.subTest(tab=tab):
                response = self._old(self.head, tab=tab)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context['tab'], 'overview')

    def test_a_head_sees_no_link_to_a_moved_tab(self):
        """شريطُ رئيس القسم (لا يرى شريطَ النظام) — لا رابطَ فيه إلى تبويبٍ صار صفحة."""
        body = self._old(self.head).content.decode()
        for tab in MOVED:
            with self.subTest(tab=tab):
                self.assertNotIn('?tab=%s' % tab, body)

    def test_a_head_posting_a_group_returns_to_the_panel(self):
        """لا يملك الورشة — فرسالةُ الرفض تُعرض في اللوحة لا خلف تحويلٍ إلى صفحةٍ مرفوضة."""
        from core.models import EntityGroup

        self.client.force_login(self.head)
        response = self.client.post(reverse('admin_panel'), {
            'action': 'save_group', 'tab': 'groups', 'name': 'عنقود رئيس القسم',
            'auto_rule': '', 'members_submitted': '1',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], '/books/admin/?tab=departments')
        self.assertFalse(EntityGroup.objects.filter(name='عنقود رئيس القسم').exists())

    def test_the_kept_tabs_still_open_in_the_panel(self):
        for tab in ('overview', 'departments', 'users'):
            with self.subTest(tab=tab):
                response = self._old(self.root, tab=tab)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context['tab'], tab)

    def test_the_panel_carries_links_not_copies(self):
        body = self._old(self.root).content.decode()
        for gone in ('id="ent"', 'id="res"', 'id="aud"', 'id="set"',
                     "go('aud')", "go('set')", 'id="aud-q"', 'grp-members'):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, body)
        for href in (reverse('system_reservations'), reverse('audit_log'), reverse('settings_hub')):
            with self.subTest(href=href):
                self.assertIn('href="%s"' % href, body)

    def test_the_new_unit_dialog_still_offers_entities(self):
        """سياقُ العناقيد حُذف من اللوحة — وجهاتُ نافذة «وحدة جديدة» باقيةٌ لأنّها تخصّها هي."""
        from core.models import Entity

        entity = Entity.objects.create(name='جهة الاختبار')
        body = self._old(self.root, tab='departments').content.decode()
        self.assertIn('<option value="%d">جهة الاختبار</option>' % entity.pk, body)

    def test_saving_a_group_still_posts_to_the_panel(self):
        """الكتابةُ لم تنتقل بعد (الدفعة 4) — والرجوعُ إلى الورشة لا إلى تبويبٍ يُحوَّل."""
        self.client.force_login(self.root)
        response = self.client.post(reverse('admin_panel'), {
            'action': 'save_group', 'tab': 'groups', 'name': 'عنقود الدفعة',
            'auto_rule': '', 'members_submitted': '1',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('entity_list') + '?view=groups')
        # الحفظُ حدث فعلاً — الخطأُ المُلتقَط يُحوِّل إلى الوجهة نفسِها، فالعنوانُ وحده لا يكفي
        from core.models import EntityGroup
        self.assertTrue(EntityGroup.objects.filter(name='عنقود الدفعة').exists())


class ReservationsPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.root = User.objects.create_superuser('b1-res-root', password='b1-res-root-pass-1234')
        UserProfile.objects.create(user=cls.root)
        cls.writer = User.objects.create_user('b1-res-writer', password='b1-res-writer-pass-1234')
        dept = Department.objects.create(name='قسم الحجوزات', code='ت-2')
        cls.head = User.objects.create_user('b1-res-head', password='b1-res-head-pass-1234')
        UserProfile.objects.create(user=cls.head, department=dept, is_department_head=True)

    def _reservation(self, number, *, hours_left):
        now = timezone.now()
        return BookNumberReservation.objects.create(
            user=self.writer, kind='incoming_internal', number=number, year=now.year,
            formatted=str(number), status=BookNumberReservation.STATUS_ACTIVE,
            assigned_at=now - timedelta(hours=2), last_heartbeat=now,
            expires_at=now + timedelta(hours=hours_left))

    def _page(self, **params):
        self.client.force_login(self.root)
        response = self.client.get(reverse('system_reservations'), params)
        self.assertEqual(response.status_code, 200)
        return response

    def test_only_the_system_admin_opens_it(self):
        """أسماءُ كلّ المستخدمين وأعمارُ حجوزاتهم — لا للكاتب ولا لرئيس القسم (بوّابةُ اللوحة أوسع)."""
        for user in (self.writer, self.head):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                self.assertEqual(self.client.get(reverse('system_reservations')).status_code, 403)

    def test_a_superscript_digit_falls_back_to_a_week(self):
        self.assertEqual(self._page(days='²').context['reservation_days'], 7)

    def test_it_is_read_only_and_never_cached(self):
        self.assertIn('no-store', self._page()['Cache-Control'])
        self.assertEqual(self.client.post(reverse('system_reservations')).status_code, 405)

    def test_it_lives_in_the_programme_frame(self):
        response = self._page()
        self.assertTemplateUsed(response, 'base.html')
        self.assertContains(response, 'class="sa-sysbar"')
        self.assertContains(response, '<table class="sa-reg sa-res">')   # خلاياه على سطرٍ واحد (PhoneReflowTests)
        url = reverse('system_reservations')
        self.assertContains(response, 'class="on" href="%s" aria-current="page"' % url)
        for days in (7, 30, 90):
            self.assertContains(response, '<option value="%d"' % days)

    def test_a_stale_reservation_is_toned_and_a_fresh_one_is_not(self):
        self._reservation(501, hours_left=-1)
        self._reservation(502, hours_left=1)

        response = self._page()

        rows = {row['reservation'].number: row for row in response.context['reservation_rows']}
        self.assertTrue(rows[501]['stale'])
        self.assertFalse(rows[502]['stale'])
        self.assertContains(response, '<span class="sa-chip warn">انتهت المهلة — بانتظار التنظيف</span>',
                            html=True)
        self.assertContains(response, 'class="sa-dot bad"')

    def test_no_overdue_means_no_red_dot(self):
        self._reservation(503, hours_left=1)

        response = self._page()

        self.assertNotContains(response, 'sa-dot bad')
        self.assertNotContains(response, 'sa-chip warn')

    def test_the_legacy_note_is_said_once_and_only_when_needed(self):
        """حجزٌ سابقٌ لتتبّع الإسناد: كلمةٌ في الخليّة وشرحٌ واحدٌ تحت الجدول — لا جملةٌ مكرّرةٌ في كلّ صفّ."""
        note = 'حجزٌ سابقٌ لإضافة تتبّع الإسناد'
        self._reservation(504, hours_left=1)
        self.assertNotContains(self._page(), note)

        self._reservation(505, hours_left=1)
        self._reservation(506, hours_left=1)
        BookNumberReservation.objects.filter(number__in=[505, 506]).update(assigned_at=None)

        response = self._page()
        self.assertContains(response, note, count=1)
        self.assertContains(response, '<td class="sa-when">غير متاح</td>', count=2, html=True)

    def test_an_empty_period_says_so(self):
        self.assertContains(self._page(days='30'), 'لا حجوزات قائمة ولا سجلّات في آخر 30 يوماً')


class PhoneReflowTests(SimpleTestCase):
    """على 390px كانت الصفحةُ كلُّها تنزلق أفقيّاً — قيسَ في Chromium: الحجوزاتُ 1021px ومركزُ الأقسام 797px.

    سببان في system_admin.css: مسارُ الشبكة الضمنيّ (auto) يتّسع لعرض أوسع جدول، ونصٌّ مخفيٌّ بصريّاً
    (absolute) في خليّةٍ يفلت من قصّ إطار التمرير لأنّ الإطارَ ليس كتلةَ احتواء.
    """

    def _rule(self, selector):
        css = (Path(settings.BASE_DIR) / 'static' / 'css' / 'system_admin.css').read_text(encoding='utf-8')
        start = css.index('\n%s {' % selector) + 1
        return css[start:css.index('}', start)]

    def test_the_page_column_can_shrink_below_its_widest_table(self):
        self.assertIn('grid-template-columns: minmax(0, 1fr)', self._rule('.sa-page'))

    def test_the_table_scroller_clips_what_hides_inside_it(self):
        self.assertIn('position: relative', self._rule('.sa-scroll'))

    def test_reservation_cells_stay_on_one_line(self):
        """«وارد داخلي» و«قسم المتابعة» كانتا تنكسران فيتضاعف ارتفاعُ الصفّ (لقطةُ 1440px)."""
        self.assertIn('white-space: nowrap', self._rule('.sa-res td'))
