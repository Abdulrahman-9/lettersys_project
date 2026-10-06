# -*- coding: utf-8 -*-
"""حقُّ الكتابة على الكتاب ≠ حقُّ فتحه — قرارُ المالك 2026‑09‑29 (Q1‑ج).

«التعديل/الحذف/الهامش لشجرة القسم المالك وطاولته والمدير، والوحدةُ تُبقي أفعالَ
صفّها وعهدتها، والسجلُّ يحفظ نصَّ الهامش القديم.» كانت الوحدةُ المُحالُ إليها
(أو المذكورةُ في جهات الكتاب) تمرّ من ``can_open_content`` فتعدّل عنوانَ القسم
وتحذف كتابَه وتكتب فوق هامش مديره بلا أثر. (تقريرُ فيبل 2026‑09‑29 · P0‑14.)
"""
import json
from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Book, BookHistory, BookReferral, Department, Entity, UserProfile
from core.referral_service import distribute
from core.roles import CONTROLLER_GROUP_NAME
from core.scoping import can_edit_book, can_open_content


class EditRightsTestCase(TestCase):
    """قسمٌ «ق» بشعبته «ش» وقسمٌ آخر «خ» (له توأمُ جهة). كتابُ «ق» فُرِّق إلى «ش»
    وذُكر «خ» في جهاته: كلاهما يفتحه — ولا يكتب عليه."""

    @classmethod
    def setUpTestData(cls):
        today = timezone.localdate()
        cls.q = Department.objects.create(name='قسمُ الكتابة', code='ك.ق')
        cls.sh = Department.objects.create(name='شعبةُ الكتابة', code='ك.ش', parent=cls.q)
        kh_twin = Entity.objects.create(name='قسمُ الكتابة الآخر')
        cls.kh = Department.objects.create(name='قسمُ الكتابة الآخر', code='ك.خ', entity=kh_twin)

        def member(name, dept, *, head=False, desk=False):
            u = User.objects.create_user(name, password=f'pw-{name}-1111')
            UserProfile.objects.update_or_create(
                user=u, defaults={'department': dept, 'is_department_head': head})
            if desk:
                u.groups.add(Group.objects.get_or_create(name=CONTROLLER_GROUP_NAME)[0])
            return u

        cls.clerk = member('wclerk', cls.q)
        cls.colleague = member('wcolleague', cls.q)
        cls.head = member('whead', cls.q, head=True)
        cls.desk = member('wdesk', cls.q, desk=True)
        cls.unit = member('wunit', cls.sh)
        cls.mentioned = member('wmentioned', cls.kh)
        cls.admin = User.objects.create_superuser('wadmin', 'w@x.co', 'pw-wadmin-1111')
        cls.loner = User.objects.create_user('wloner', password='pw-wloner-1111')   # بلا قسم

        def book(num, by, dept, **kw):
            return Book.objects.create(
                kind='incoming_internal', title=f'كتابُ {num}', created_by=by, department=dept,
                our_number=num, date=today, due_date=today + timedelta(days=5),
                is_archived=False, **kw)

        cls.book = book('6101', cls.clerk, cls.q, margin='هامشُ المدير الأوّل')
        cls.book.receiving_entities.add(kh_twin)                       # «خ» مذكور
        cls.referral = distribute(cls.book, [cls.sh], by=cls.clerk)[0]  # «ش» مُحالٌ إليها
        cls.unit_book = book('6102', cls.unit, cls.sh)                  # كتابُ الشعبة نفسِها
        cls.secret = book('6103', cls.clerk, cls.q, secret_level='secret')
        cls.loner_book = book('6104', cls.loner, None)


class TheRuleTests(EditRightsTestCase):

    def test_the_owning_department_its_desk_and_the_admin_write(self):
        for user in (self.clerk, self.colleague, self.head, self.desk, self.admin):
            with self.subTest(user=user.username):
                self.assertTrue(can_edit_book(self.book, user))

    def test_a_referred_or_mentioned_unit_opens_but_does_not_write(self):
        for user in (self.unit, self.mentioned):
            with self.subTest(user=user.username):
                self.assertTrue(can_open_content(self.book, user))
                self.assertFalse(can_edit_book(self.book, user))

    def test_the_tree_flows_down_not_up(self):
        """رئيسُ «ق» يكتب على كتاب شعبته؛ والشعبةُ تكتب على كتابها لا على كتاب القسم."""
        self.assertTrue(can_edit_book(self.unit_book, self.head))
        self.assertTrue(can_edit_book(self.unit_book, self.unit))
        self.assertFalse(can_edit_book(self.unit_book, self.mentioned))

    def test_no_writing_without_the_content(self):
        """زميلُ القسم يرى سطرَ السرّيّ ولا يفتحه — فلا يكتب عليه."""
        self.assertFalse(can_open_content(self.secret, self.colleague))
        self.assertFalse(can_edit_book(self.secret, self.colleague))
        self.assertTrue(can_edit_book(self.secret, self.clerk))

    def test_a_creator_who_moved_departments_opens_but_no_longer_writes(self):
        """الكتابُ ملكُ القسم لا مُدخِله: انتقل الكاتبُ إلى «خ» فبقي يرى ما أنشأه ويفتحه
        (``scope_books_for`` · ``secret_access``) ولا يكتب عليه."""
        UserProfile.objects.filter(user=self.clerk).update(department=self.kh)
        self.clerk.refresh_from_db()
        self.assertTrue(can_open_content(self.book, self.clerk))
        self.assertFalse(can_edit_book(self.book, self.clerk))

    def test_a_user_without_a_department_writes_on_what_he_created(self):
        self.assertTrue(can_edit_book(self.loner_book, self.loner))
        self.assertFalse(can_edit_book(self.book, self.loner))


class TheDoorsTests(EditRightsTestCase):
    """كلُّ بابِ كتابةٍ يسأل ``can_edit_book`` — والوحدةُ تُبقي أفعالَ صفّها."""

    def _as(self, user):
        self.client.force_login(user)
        return self.client

    def test_the_margin_is_closed_to_the_unit(self):
        resp = self._as(self.unit).post(reverse('update_book_notes', args=[self.book.pk]),
                                        json.dumps({'margin': 'فوق هامش المدير'}),
                                        content_type='application/json')
        self.assertEqual(resp.status_code, 403)
        self.book.refresh_from_db()
        self.assertEqual(self.book.margin, 'هامشُ المدير الأوّل')

    def test_the_margin_history_keeps_the_old_text(self):
        resp = self._as(self.clerk).post(reverse('update_book_notes', args=[self.book.pk]),
                                         json.dumps({'margin': 'هامشٌ ثانٍ'}),
                                         content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        note = (BookHistory.objects.filter(book=self.book, action='update_notes')
                .latest('created_at').notes)
        self.assertIn('هامشُ المدير الأوّل', note)

    def test_edit_status_and_delete_are_closed_to_the_unit(self):
        """«ممنوع» صادقةٌ لمن يفتح الكتاب ولا يكتب عليه — و«غيرُ موجود» لمن لا يفتحه."""
        c = self._as(self.unit)
        self.assertEqual(c.get(reverse('book_edit', args=[self.book.pk])).status_code, 403)
        self.assertEqual(c.get(reverse('extraction-smart-desktop'),
                               {'edit_pk': self.book.pk}).status_code, 403)
        c.post(reverse('book_change_status', args=[self.book.pk]), {'action': 'archived'})
        self.assertEqual(c.post(reverse('api_book_inline_status', args=[self.book.pk]),
                                json.dumps({'status': 'archived'}),
                                content_type='application/json').status_code, 403)
        self.assertEqual(c.post(reverse('api_delete_book', args=[self.book.pk])).status_code, 403)
        self.book.refresh_from_db()
        self.assertFalse(self.book.is_archived)
        self.assertFalse(self.book.is_deleted)

    def test_one_who_cannot_see_the_book_gets_not_found(self):
        stranger = User.objects.create_user('wstranger', password='pw-wstranger-1111')
        UserProfile.objects.update_or_create(user=stranger, defaults={'department': self.kh})
        c = self._as(stranger)
        self.assertEqual(c.get(reverse('book_edit', args=[self.unit_book.pk])).status_code, 404)
        self.assertEqual(c.post(reverse('api_book_inline_status', args=[self.unit_book.pk]),
                                json.dumps({'status': 'archived'}),
                                content_type='application/json').status_code, 404)

    def test_the_owner_still_edits(self):
        c = self._as(self.colleague)
        self.assertEqual(c.get(reverse('book_edit', args=[self.book.pk])).status_code, 302)
        c.post(reverse('book_change_status', args=[self.book.pk]), {'action': 'archived'})
        self.book.refresh_from_db()
        self.assertTrue(self.book.is_archived)

    def test_the_unit_keeps_its_row_action(self):
        resp = self._as(self.unit).post(
            reverse('api_referral_action', args=[self.book.pk, self.referral.pk]),
            json.dumps({'act': 'received'}), content_type='application/json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.referral.refresh_from_db()
        self.assertEqual(self.referral.status, BookReferral.RECEIVED)

    def test_the_page_offers_editing_to_whoever_may_edit(self):
        edit_url = reverse('book_edit', args=[self.book.pk])
        for user, shown in ((self.unit, False), (self.mentioned, False),
                            (self.clerk, True), (self.admin, True)):
            with self.subTest(user=user.username):
                resp = self._as(user).get(reverse('book_detail', args=[self.book.pk]))
                self.assertEqual(resp.status_code, 200)
                self.assertIs(resp.context['can_edit'], shown)
                self.assertEqual(edit_url in resp.content.decode('utf-8'), shown)


class TrashButtonsTests(EditRightsTestCase):
    """لا زرَّ يُعرض ليُرفض: الوحدةُ ترى كتابَ المالك المحذوف في سلّتها ولا تستعيده."""

    def test_restore_shows_to_whoever_may_restore_and_purge_to_the_admin(self):
        Book.all_objects.filter(pk=self.book.pk).update(is_deleted=True, deleted_at=timezone.now())
        restore = reverse('restore_book', args=[self.book.pk])
        purge = reverse('purge_book', args=[self.book.pk])
        for user, can_restore, can_purge in ((self.unit, False, False), (self.clerk, True, False),
                                             (self.admin, True, True)):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                html = self.client.get(reverse('trash_list')).content.decode('utf-8')
                self.assertIn(self.book.our_number_display, html)
                self.assertEqual(restore in html, can_restore)
                self.assertEqual(purge in html, can_purge)
