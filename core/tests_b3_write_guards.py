# -*- coding: utf-8 -*-
"""(ب)3 — حرّاسُ الكتابة على مفاتيحها (2026‑11‑11).

كلُّ موضعٍ كان يسأل ``can_write`` («أيكتب أصلاً؟») صار يسأل مفتاحَ فعله في مصفوفة الأدوار:
الإدخالُ والتعديلُ وحجزُ الرقم وإضافةُ الجهة والعهدةُ والربط. والحاملون الافتراضيّون للخمسة
متطابقون، فاختبارٌ بالأدوار وحدها لا يميّز مفتاحاً من مفتاح — لذا يُبنى هنا كلُّ فاعلٍ من
«مدخل» يُسحب منه مفتاحٌ واحد باستثناءٍ شخصيّ، فتُقتل طفرةُ تبديل المفاتيح.
"""
import io
import json

from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from core import scoping as s
from core.custody_service import record_custody
from core.linking_service import add_link, remove_link
from core.models import (Attachment, Book, BookLink, CustodyEvent, DataExtractionResult, Department, Entity,
                         RoleCapabilityOverride,
                         UserCapabilityOverride, UserProfile)
from core.registration_service import register_book_here, register_here_ledger
from core.roles import ENTRY_GROUP_NAME, ensure_role_groups
from core.testing import as_custodian
from core.views.book_state import more_actions, primary_action

DESK = '/books/extract/smart-desktop/'


class B3Case(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_role_groups()
        cls.dept = Department.objects.create(name='قسم ب3', code='ب3')
        cls.unit = Department.objects.create(name='وحدة ب3', code='ب3و', parent=cls.dept, holds_register=False)
        cls.other = Department.objects.create(name='قسم آخر ب3', code='ب3آ')
        cls.entry = cls.person('b3_entry', cls.dept, writer=True)
        cls.reader = cls.person('b3_reader', cls.dept)
        cls.unit_head = cls.person('b3_unithead', cls.unit, head=True)
        cls.unit_entry = cls.person('b3_unitentry', cls.unit, writer=True)
        # «مدخل» يُسحب منه مفتاحٌ واحد — كلٌّ يقتل طفرةَ تبديل مفتاحه.
        cls.no_custody = cls.person('b3_nocustody', cls.dept, writer=True, deny=('custody.link',))
        cls.no_enter = cls.person('b3_noenter', cls.dept, writer=True, deny=('book.enter',))
        cls.no_edit = cls.person('b3_noedit', cls.dept, writer=True, deny=('book.edit',))
        cls.no_desk = cls.person('b3_nodesk', cls.dept, writer=True, deny=('book.enter', 'book.edit'))
        cls.no_reserve = cls.person('b3_noreserve', cls.dept, writer=True, deny=('number.reserve',))
        cls.no_entity = cls.person('b3_noentity', cls.dept, writer=True, deny=('entity.add',))
        cls.book = Book.objects.create(kind='incoming_internal', title='كتاب ب3', created_by=cls.entry,
                                       department=cls.dept)
        cls.book2 = Book.objects.create(kind='incoming_internal', title='كتاب ب3 ثانٍ', created_by=cls.entry,
                                        department=cls.dept)
        # المُنشئُ يفتح ما أنشأه — فالسرّيُّ والبعيدُ لغير المدخل الذي يُختبر عليهما.
        cls.owner = cls.person('b3_owner', cls.dept, writer=True)
        cls.far_owner = cls.person('b3_farowner', cls.other, writer=True)
        cls.secret = Book.objects.create(kind='incoming_internal', title='سرّيّ ب3', created_by=cls.owner,
                                         department=cls.dept, secret_level='secret')
        cls.far = Book.objects.create(kind='incoming_internal', title='بعيد ب3', created_by=cls.far_owner,
                                      department=cls.other)
        cls.unit_book = Book.objects.create(kind='incoming_internal', title='كتاب الوحدة', created_by=cls.unit_entry,
                                            department=cls.unit)

    @classmethod
    def person(cls, name, dept, *, writer=False, head=False, deny=()):
        user = User.objects.create_user(name, password='pw-b3-1111')
        UserProfile.objects.update_or_create(user=user, defaults={'department': dept, 'is_department_head': head})
        if writer:
            user.groups.add(Group.objects.get(name=ENTRY_GROUP_NAME))
        for key in deny:
            UserCapabilityOverride.objects.create(user=user, capability=key, allowed=False)
        return user

    def fresh(self, user):
        """كائنٌ جديد كما في كلّ طلب — مخبأُ الصلاحيّات على الكائن لا يعبر الاختبارات."""
        return User.objects.get(pk=user.pk)

    def setUp(self):
        cache.clear()


class EachGuardReadsItsOwnKeyTests(B3Case):
    def test_a_writer_holds_all_five(self):
        u = self.fresh(self.entry)
        self.assertTrue(s.can_enter_book(u))
        self.assertTrue(s.can_use_entry_desk(u))
        self.assertTrue(s.can_reserve_number(u))
        self.assertTrue(s.can_add_entity(u))
        self.assertTrue(s.can_edit_book(self.book, u))
        self.assertTrue(s.can_link_book(self.book, u))
        self.assertTrue(s.can_register_book(self.book, u))

    def test_one_key_withdrawn_closes_its_door_only(self):
        u = self.fresh(self.no_custody)
        self.assertFalse(s.can_link_book(self.book, u))
        self.assertTrue(s.can_register_book(self.book, u))
        self.assertTrue(s.can_edit_book(self.book, u))

        u = self.fresh(self.no_enter)
        self.assertFalse(s.can_register_book(self.book, u))
        self.assertFalse(s.can_enter_book(u))
        self.assertTrue(s.can_link_book(self.book, u))
        self.assertTrue(s.can_use_entry_desk(u))   # التعديلُ يفتح الصفحةَ في وضعه

        u = self.fresh(self.no_edit)
        self.assertFalse(s.can_edit_book(self.book, u))
        self.assertTrue(s.can_enter_book(u))
        self.assertTrue(s.can_use_entry_desk(u))
        self.assertTrue(s.can_link_book(self.book, u))

        self.assertFalse(s.can_use_entry_desk(self.fresh(self.no_desk)))
        self.assertFalse(s.can_reserve_number(self.fresh(self.no_reserve)))
        self.assertTrue(s.can_enter_book(self.fresh(self.no_reserve)))
        self.assertFalse(s.can_add_entity(self.fresh(self.no_entity)))
        self.assertTrue(s.can_enter_book(self.fresh(self.no_entity)))

    def test_trash_and_restore_read_their_own_keys_since_b4(self):
        """(ب)4: الحذفُ والاسترجاعُ مفتاحان لا «التعديل» — المدخلُ يعدّل ولا يحذف."""
        for user in (self.entry, self.no_edit, self.reader):
            with self.subTest(user=user.username):
                self.assertFalse(s.can_trash_book(self.book, self.fresh(user)))
                self.assertFalse(s.can_restore_book(self.book, self.fresh(user)))
        self.assertTrue(s.can_edit_book(self.book, self.fresh(self.entry)))
        as_custodian(self.entry)
        self.assertTrue(s.can_trash_book(self.book, self.fresh(self.entry)))
        self.assertTrue(s.can_restore_book(self.book, self.fresh(self.entry)))

    def test_content_is_a_condition_no_key_widens(self):
        """المدخلُ لا يفتح السرّيَّ ولا كتابَ قسمٍ آخر — فلا عهدةَ ولا قيدَ عليهما وإن ملك المفتاح."""
        u = self.fresh(self.entry)
        for book in (self.secret, self.far):
            with self.subTest(book=book.title):
                self.assertFalse(s.can_open_content(book, u))
                self.assertFalse(s.can_link_book(book, u))
                self.assertFalse(s.can_register_book(book, u))
                self.assertFalse(s.can_edit_book(book, u))

    def test_a_frozen_role_row_is_ignored_and_a_person_exception_counts(self):
        RoleCapabilityOverride.objects.create(role=s.ROLE_READER, capability='book.enter', allowed=True)
        self.assertFalse(s.can_enter_book(self.fresh(self.reader)))
        UserCapabilityOverride.objects.create(user=self.reader, capability='book.enter', allowed=True)
        self.assertTrue(s.can_enter_book(self.fresh(self.reader)))

    def test_the_unit_head_no_longer_writes_but_mail_waits_for_b5(self):
        """أمرُ المالك «يُضيَّق can_write عن رئيس أيّ مستوى» — والبريدُ وحده على can_write حتى (ب)5."""
        u = self.fresh(self.unit_head)
        self.assertEqual(s.role_of(u), s.ROLE_UNIT)
        self.assertFalse(s.can_enter_book(u))
        self.assertFalse(s.can_use_entry_desk(u))
        self.assertFalse(s.can_edit_book(self.unit_book, u))
        self.assertFalse(s.can_link_book(self.unit_book, u))
        self.assertTrue(s.can_open_content(self.unit_book, u))
        self.assertTrue(s.can_write(u))


class ServicesRefuseWithoutTheKeyTests(B3Case):
    def test_link_needs_custody_link(self):
        with self.assertRaises(PermissionDenied):
            add_link(self.book, self.book2, BookLink.REPLY, by=self.fresh(self.no_custody))
        self.assertIsNotNone(add_link(self.book, self.book2, BookLink.REPLY, by=self.fresh(self.no_enter)))

    def test_custody_needs_custody_link(self):
        with self.assertRaises(PermissionDenied):
            record_custody(self.book, CustodyEvent.INTAKE, to_name='حامل', by=self.fresh(self.no_custody))

    def test_unlinking_needs_custody_link(self):
        link = add_link(self.book, self.book2, BookLink.REPLY, by=self.fresh(self.entry))
        with self.assertRaises(PermissionDenied):
            remove_link(link, by=self.fresh(self.no_custody))
        self.assertTrue(BookLink.objects.filter(pk=link.pk).exists())

    def test_registering_here_needs_enter(self):
        with self.assertRaises(PermissionDenied):
            register_book_here(self.book, self.dept, by=self.fresh(self.no_enter))

    def test_the_register_button_follows_enter(self):
        """«قيّده عندنا» يُعرض من الخدمة نفسِها — ``None`` لمن سيُرفض."""
        self.assertIsNotNone(register_here_ledger(self.book, self.fresh(self.entry)))
        self.assertIsNone(register_here_ledger(self.book, self.fresh(self.no_enter)))
        self.assertIsNotNone(register_here_ledger(self.book, self.fresh(self.no_custody)))


class EntryDeskPageTests(B3Case):
    def get(self, user, query=''):
        self.client.force_login(user)
        return self.client.get(DESK + query)

    def test_two_modes_two_keys(self):
        edit = f'?edit_pk={self.book.pk}'
        self.assertEqual(self.get(self.entry).status_code, 200)
        self.assertEqual(self.get(self.no_enter).status_code, 403)        # إدخالٌ جديد بلا «الإدخال»
        self.assertEqual(self.get(self.no_enter, edit).status_code, 200)  # وتعديلٌ بـ«التعديل»
        self.assertEqual(self.get(self.no_edit).status_code, 200)
        self.assertEqual(self.get(self.no_edit, edit).status_code, 403)
        self.assertEqual(self.get(self.no_desk).status_code, 403)
        self.assertEqual(self.get(self.reader).status_code, 403)
        self.assertEqual(self.get(self.unit_head).status_code, 403)

    def test_the_reserve_ring_follows_its_key(self):
        self.assertIn('id="reservationRing"', self.get(self.entry).content.decode())
        body = self.get(self.no_reserve).content.decode()
        self.assertNotIn('id="reservationRing"', body)
        self.assertIn('id="bookNumber"', body)


class ApiGatesTests(B3Case):
    def post_json(self, user, url, payload):
        self.client.force_login(user)
        return self.client.post(url, data=json.dumps(payload), content_type='application/json')

    def assert_forbidden(self, response):
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json().get('error_code'), 'FORBIDDEN')

    def test_reserve_is_refused_before_any_lookup(self):
        url = '/books/api/reservation/reactivate/'
        self.assert_forbidden(self.post_json(self.no_reserve, url, {'reservation_id': 987654}))
        self.assertNotEqual(self.post_json(self.entry, url, {'reservation_id': 987654}).status_code, 403)
        self.assert_forbidden(self.post_json(self.no_reserve, '/books/api/reservation/reserve/',
                                             {'kind': 'incoming_internal'}))

    def test_add_entity_needs_its_key(self):
        before = Entity.objects.count()
        self.assert_forbidden(self.post_json(self.no_entity, '/books/api/entity/add/', {'name': 'جهة ب3'}))
        self.assertEqual(Entity.objects.count(), before)
        self.assertNotEqual(self.post_json(self.no_enter, '/books/api/entity/add/',
                                           {'name': 'جهة ب3'}).status_code, 403)

    def test_save_needs_enter_not_the_desk(self):
        before = Book.all_objects.count()
        self.client.force_login(self.no_enter)
        self.assert_forbidden(self.client.post('/books/api/book/save/', {'kind': 'incoming_internal',
                                                                         'title': 'جديد ب3'}))
        self.assertEqual(Book.all_objects.count(), before)

    def test_extraction_tools_follow_the_desk(self):
        self.client.force_login(self.no_desk)
        self.assert_forbidden(self.client.post('/books/api/extract/smart/', {}))
        self.assert_forbidden(self.client.get('/books/api/extract/smart/progress/b3-none/'))
        self.client.force_login(self.no_enter)
        self.assertNotEqual(self.client.post('/books/api/extract/smart/', {}).status_code, 403)


class TrashDoorsFollowTheirWrappersTests(B3Case):
    """الأبوابُ التي انتقلت إلى الغلافين البينيّين — تتبع «التعديل» حتى يبدّل (ب)4 مفتاحَيهما."""

    def post_json(self, user, url, payload):
        self.client.force_login(user)
        return self.client.post(url, data=json.dumps(payload), content_type='application/json')

    def setUp(self):
        super().setUp()
        as_custodian(self.entry)   # (ب)4: الحذفُ والاسترجاعُ مفتاحان — المدخلُ يُمنحهما هنا والمسحوبُ منه التعديلُ لا

    def fresh_book(self, **extra):
        return Book.objects.create(kind='incoming_internal', title='سلّة ب3', created_by=self.owner,
                                   department=self.dept, **extra)

    def test_bulk_status_needs_edit(self):
        from django.utils import timezone

        book = self.fresh_book(due_date=timezone.localdate(), is_archived=False)   # بلا موعدٍ يُؤرشف تلقائيّاً
        payload = {'book_ids': [book.pk], 'action': 'archived'}
        self.post_json(self.no_edit, '/books/api/books/bulk-status/', payload)
        self.assertFalse(Book.all_objects.get(pk=book.pk).is_archived)
        self.post_json(self.entry, '/books/api/books/bulk-status/', payload)
        self.assertTrue(Book.all_objects.get(pk=book.pk).is_archived)

    def test_bulk_delete_needs_trash(self):
        book = self.fresh_book()
        self.post_json(self.no_edit, '/books/api/books/bulk-delete/', {'book_ids': [book.pk]})
        self.assertFalse(Book.all_objects.get(pk=book.pk).is_deleted)
        self.post_json(self.entry, '/books/api/books/bulk-delete/', {'book_ids': [book.pk]})
        self.assertTrue(Book.all_objects.get(pk=book.pk).is_deleted)

    def test_restoring_a_book_needs_restore(self):
        book = self.fresh_book(is_deleted=True)
        url = f'/books/trash/book/{book.pk}/restore/'
        self.client.force_login(self.no_edit)
        self.client.post(url)
        self.assertTrue(Book.all_objects.get(pk=book.pk).is_deleted)
        self.client.force_login(self.entry)
        self.client.post(url)
        self.assertFalse(Book.all_objects.get(pk=book.pk).is_deleted)

    def test_restoring_an_attachment_needs_restore(self):
        att = Attachment.objects.create(book=self.book, file='b3/none.pdf', is_deleted=True)
        url = f'/books/trash/attachment/{att.pk}/restore/'
        self.client.force_login(self.no_edit)
        self.client.post(url)
        self.assertTrue(Attachment.all_objects.get(pk=att.pk).is_deleted)
        self.client.force_login(self.entry)
        self.client.post(url)
        self.assertFalse(Attachment.all_objects.get(pk=att.pk).is_deleted)


class NoButtonShownToBeRefusedTests(B3Case):
    def page(self, user, url):
        self.client.force_login(user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_entry_links_follow_enter(self):
        self.assertIn(f'href="{DESK}"', self.page(self.entry, reverse('dashboard')))
        for user in (self.reader, self.no_enter):
            with self.subTest(user=user.username):
                self.assertNotIn(f'href="{DESK}"', self.page(user, reverse('dashboard')))

    def test_custody_and_link_buttons_follow_custody_link(self):
        detail = reverse('book_detail', args=[self.unit_book.pk])
        writer = self.page(self.unit_entry, detail)
        self.assertIn('data-bs-target="#custodyModal"', writer)
        self.assertIn('data-bs-target="#linkPickerModal"', writer)
        # مسؤولُ الوحدة يُحيل ويفتح ولا يملك العهدةَ والربط: يرى «فرِّق…» ولا يرى ما يُرفض
        head = self.page(self.unit_head, detail)
        self.assertIn('data-bs-target="#distributeModal"', head)
        self.assertNotIn('data-bs-target="#custodyModal"', head)
        self.assertNotIn('data-bs-target="#linkPickerModal"', head)

    def test_the_route_header_hides_custody_too(self):
        """بعد أوّل عهدةٍ تنتقل الأزرارُ إلى رأس «التفريق والردود» — والشرطُ نفسُه هناك."""
        book = Book.objects.create(kind='incoming_internal', title='كتاب الوحدة بعهدة', created_by=self.unit_entry,
                                   department=self.unit)
        record_custody(book, CustodyEvent.INTAKE, to_name='حامل', by=self.fresh(self.unit_entry))
        detail = reverse('book_detail', args=[book.pk])
        self.assertIn('data-bs-target="#custodyModal"', self.page(self.unit_entry, detail))
        head = self.page(self.unit_head, detail)
        self.assertIn('data-bs-target="#distributeModal"', head)
        self.assertNotIn('data-bs-target="#custodyModal"', head)

    def test_results_and_scan_pages_hide_the_desk_link(self):
        result = DataExtractionResult.objects.create(book=self.book, title='نتيجة ب3', status='extracted')
        url = reverse('extraction-results-ui', args=[result.pk])
        self.assertIn(f'href="{DESK}?kind=', self.page(self.entry, url))
        self.assertNotIn(f'href="{DESK}?kind=', self.page(self.reader, url))
        staff = self.person('b3_staff', self.dept)
        staff.is_staff = True
        staff.save(update_fields=['is_staff'])
        self.assertNotIn(f'href="{DESK}"', self.page(staff, reverse('scan_settings')))

    def test_a_reader_gets_no_empty_menu(self):
        body = self.page(self.reader, reverse('book_detail', args=[self.book.pk]))
        self.assertNotIn('aria-label="أفعالٌ أخرى"', body)
        self.assertNotIn('data-bs-target="#linkPickerModal"', body)
        self.assertIn('aria-label="أفعالٌ أخرى"', self.page(self.entry, reverse('book_detail', args=[self.book.pk])))


class BookStateFlagsTests(B3Case):
    def test_custody_is_primary_by_its_own_key(self):
        self.assertEqual(primary_action(self.book, referrals=[], can_distribute=False, can_link=True,
                                        can_edit=False)['key'], 'custody')
        self.assertIsNone(primary_action(self.book, referrals=['r'], can_distribute=True, can_link=False,
                                         can_edit=False))

    def test_more_actions_lists_only_what_is_held(self):
        none = dict(can_distribute=False, can_link=False, can_register=False, can_enter=False)
        self.assertEqual(more_actions(self.book, primary=None, **none), [])
        self.assertEqual(more_actions(self.book, primary=None, **{**none, 'can_enter': True}), ['similar'])
        self.assertEqual(more_actions(self.book, primary={'key': 'custody'}, **{**none, 'can_link': True}), [])
        self.assertEqual(more_actions(self.book, primary=None,
                                      **{**none, 'can_link': True, 'can_register': True}), ['custody', 'register'])


class RoleReportWarnsTests(B3Case):
    def test_a_unit_head_in_a_writer_group_is_named(self):
        self.unit_head.groups.add(Group.objects.get(name=ENTRY_GROUP_NAME))
        out = io.StringIO()
        call_command('role_conversion_report', stdout=out)
        line = next(x for x in out.getvalue().splitlines() if x.startswith('b3_unithead'))
        self.assertIn('رئيس وحدة في مجموعة كتابة', line)
        entry_line = next(x for x in out.getvalue().splitlines() if x.startswith('b3_unitentry'))
        self.assertNotIn('رئيس وحدة في مجموعة كتابة', entry_line)
