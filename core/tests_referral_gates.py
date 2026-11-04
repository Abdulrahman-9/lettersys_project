# -*- coding: utf-8 -*-
"""الإحالاتُ على المحلِّل: مَن يُحيل، ومَن يستلم وينجز، وإلى أين، والسرّيُّ المُحال."""
from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core import referral_service as rs
from core import scoping as s
from core.models import (Book, BookReferral, Department, Entity, RoleCapabilityOverride, UserCapabilityOverride,
                         UserProfile)
from core.roles import ARCHIVIST_GROUP_NAME, CONTROLLER_GROUP_NAME, ENTRY_GROUP_NAME, EXECUTOR_GROUP_NAME


class ReferralCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dept = Department.objects.create(name='قسم إحالة', code='ر1')
        cls.section = Department.objects.create(name='شعبة إحالة', code='ر1ش', parent=cls.dept, holds_register=False)
        cls.unit = Department.objects.create(name='وحدة إحالة', code='ر1و', parent=cls.section, holds_register=False)
        cls.sibling = Department.objects.create(name='وحدة أخت', code='ر1خ', parent=cls.section, holds_register=False)
        cls.far = Department.objects.create(name='قسم بعيد', code='ر2')
        cls.head = cls.person('r_head', cls.dept, head=True)
        cls.mail = cls.person('r_mail', cls.dept, CONTROLLER_GROUP_NAME)
        cls.entry = cls.person('r_entry', cls.dept, ENTRY_GROUP_NAME)
        cls.arch = cls.person('r_arch', cls.dept, ARCHIVIST_GROUP_NAME)
        cls.reader = cls.person('r_reader', cls.dept)
        cls.section_head = cls.person('r_shead', cls.section, head=True)
        cls.unit_head = cls.person('r_uhead', cls.unit, head=True)
        cls.executor = cls.person('r_exec', cls.unit, EXECUTOR_GROUP_NAME)
        cls.sib_exec = cls.person('r_sib', cls.sibling, EXECUTOR_GROUP_NAME)
        cls.unit_reader = cls.person('r_ureader', cls.unit)
        cls.far_head = cls.person('r_far', cls.far, head=True)
        cls.admin = User.objects.create_superuser('r_root', password='x')
        cls.book = cls.make_book('5001')
        cls.secret = cls.make_book('5002', secret_level='secret')
        cls.far_book = Book.objects.create(kind='incoming_internal', title='بعيد', our_number='5003',
                                           created_by=cls.far_head, department=cls.far)
        cls.due = timezone.localdate() + timedelta(days=3)

    @classmethod
    def person(cls, name, dept, group=None, head=False):
        user = User.objects.create_user(name, password='x')
        UserProfile.objects.update_or_create(user=user, defaults={'department': dept, 'is_department_head': head})
        if group:
            user.groups.add(Group.objects.get_or_create(name=group)[0])
        return user

    @classmethod
    def make_book(cls, number, **kw):
        return Book.objects.create(kind='incoming_internal', title='كتاب', our_number=number, created_by=cls.head,
                                   department=cls.dept, **kw)

    def refer(self, book=None, to=None, **kw):
        return BookReferral.objects.create(book=book or self.book, from_department=self.dept, to_department=to or self.unit,
                                           purpose=BookReferral.ACTION, due_date=self.due, created_by=self.head, **kw)

    def fresh(self, user):
        return User.objects.get(pk=user.pk)

    def send(self, by, to=None, book=None):
        return rs.distribute(book or self.book, [to or self.unit], by=self.fresh(by), purpose=BookReferral.INFO)


class WhoSendsTests(ReferralCase):
    def test_head_and_mail_and_unit_manager_send(self):
        self.assertTrue(self.send(self.head))
        self.assertTrue(self.send(self.mail, to=self.sibling))

    def test_section_manager_sends_to_his_units(self):
        book = Book.objects.create(kind='incoming_internal', title='للشعبة', our_number='5004',
                                   created_by=self.section_head, department=self.section)
        self.assertTrue(self.send(self.section_head, book=book))

    def test_entry_archivist_reader_executor_do_not_send(self):
        for user in (self.entry, self.arch, self.reader, self.executor):
            with self.subTest(user=user.username), self.assertRaises(PermissionDenied):
                self.send(user)

    def test_automatic_routing_at_entry_stays_for_everyone(self):
        """استثناءٌ مقصود: الإحالةُ الآليّة عند الإدخال لا تمرّ بحرّاس التفريق اليدويّ."""
        entity = Entity.objects.create(name='توأم الوحدة')
        Department.objects.filter(pk=self.unit.pk).update(entity=entity)
        self.book.receiving_entities.add(entity)
        created = rs.auto_route_from_receivers(self.book, by=self.fresh(self.entry))
        self.assertEqual([r.to_department_id for r in created], [self.unit.pk])

    def test_a_personal_exception_lets_one_person_send(self):
        UserCapabilityOverride.objects.create(user=self.entry, capability='referral.send', allowed=True)
        self.assertTrue(self.send(self.entry))
        other = self.person('r_entry2', self.dept, ENTRY_GROUP_NAME)
        with self.assertRaises(PermissionDenied):
            self.send(other)

    def test_a_role_override_lets_the_role_send(self):
        RoleCapabilityOverride.objects.create(role='entry', capability='referral.send', allowed=True)
        self.assertTrue(self.send(self.entry))

    def test_a_blocked_exception_stops_the_head(self):
        UserCapabilityOverride.objects.create(user=self.mail, capability='referral.send', allowed=False)
        with self.assertRaises(PermissionDenied):
            self.send(self.mail)

    def test_a_grant_does_not_reach_a_book_outside_scope(self):
        UserCapabilityOverride.objects.create(user=self.entry, capability='referral.send', allowed=True)
        with self.assertRaises(PermissionDenied):
            self.send(self.entry, book=self.far_book)
        self.assertFalse(BookReferral.objects.filter(book=self.far_book).exists())

    def test_a_grant_does_not_open_a_secret_book(self):
        UserCapabilityOverride.objects.create(user=self.unit_reader, capability='referral.send', allowed=True)
        with self.assertRaises(PermissionDenied):
            self.send(self.unit_reader, book=self.secret)


class WhereToTests(ReferralCase):
    def test_a_section_cannot_refer_outside_its_tree(self):
        book = Book.objects.create(kind='incoming_internal', title='للشعبة', our_number='5005',
                                   created_by=self.section_head, department=self.section)
        for target in (self.far, self.dept):
            with self.subTest(target=target.code), self.assertRaises(PermissionDenied):
                self.send(self.section_head, to=target, book=book)
        with self.assertRaises(PermissionDenied):
            rs.distribute(book, [Entity.objects.create(name='جهة خارجيّة للإحالة')], by=self.fresh(self.section_head),
                          purpose=BookReferral.INFO)

    def test_a_register_department_refers_anywhere(self):
        self.assertTrue(self.send(self.head, to=self.far))
        self.assertTrue(rs.distribute(self.book, [Entity.objects.create(name='جهة خارجيّة أخرى')], by=self.fresh(self.head),
                                      purpose=BookReferral.INFO))

    def test_a_bad_target_writes_nothing(self):
        book = Book.objects.create(kind='incoming_internal', title='للشعبة', our_number='5006',
                                   created_by=self.section_head, department=self.section)
        with self.assertRaises(PermissionDenied):
            rs.distribute(book, [self.unit, self.far], by=self.fresh(self.section_head), purpose=BookReferral.INFO)
        self.assertFalse(BookReferral.objects.filter(book=book).exists())

    def test_the_system_admin_refers_anywhere(self):
        self.assertTrue(self.send(self.admin, to=self.far))


class WhoReceivesTests(ReferralCase):
    def test_the_executor_of_the_unit_receives_and_finishes(self):
        referral = self.refer()
        rs.mark_received(referral, by=self.fresh(self.executor))
        rs.mark_done(referral, by=self.fresh(self.executor), note='أُنجز')
        referral.refresh_from_db()
        self.assertEqual(referral.status, BookReferral.DONE)

    def test_the_unit_and_section_managers_and_the_desk_can_too(self):
        for user in (self.unit_head, self.section_head, self.head, self.mail):
            with self.subTest(user=user.username):
                referral = self.refer()
                rs.mark_received(referral, by=self.fresh(user))

    def test_a_sister_unit_cannot(self):
        with self.assertRaises(PermissionDenied):
            rs.mark_received(self.refer(), by=self.fresh(self.sib_exec))

    def test_a_reader_in_the_unit_cannot(self):
        with self.assertRaises(PermissionDenied):
            rs.mark_received(self.refer(), by=self.fresh(self.unit_reader))

    def test_entry_and_archivist_cannot_even_when_named(self):
        for user in (self.entry, self.arch):
            with self.subTest(user=user.username), self.assertRaises(PermissionDenied):
                rs.mark_done(self.refer(assignee=user), by=self.fresh(user))

    def test_an_exception_can_take_it_away(self):
        UserCapabilityOverride.objects.create(user=self.executor, capability='referral.receive', allowed=False)
        with self.assertRaises(PermissionDenied):
            rs.mark_received(self.refer(), by=self.fresh(self.executor))

    def test_an_exception_gives_it_but_only_within_the_side(self):
        UserCapabilityOverride.objects.create(user=self.unit_reader, capability='referral.receive', allowed=True)
        rs.mark_received(self.refer(), by=self.fresh(self.unit_reader))
        with self.assertRaises(PermissionDenied):
            rs.mark_received(self.refer(to=self.sibling), by=self.fresh(self.unit_reader))


class SecretReferralTests(ReferralCase):
    """قرارُ المالك: السرّيُّ المُحال تسجّل الوحدةُ استلامَه وإنجازَه ولا تفتحه."""

    def test_the_unit_records_without_opening(self):
        referral = self.refer(book=self.secret)
        user = self.fresh(self.executor)
        self.assertFalse(s.can_open_content(self.secret, user))
        rs.mark_received(referral, by=user)
        rs.mark_done(referral, by=self.fresh(self.executor))
        referral.refresh_from_db()
        self.assertEqual(referral.status, BookReferral.DONE)
        self.assertFalse(s.can_open_content(self.secret, self.fresh(self.executor)))

    def test_the_unit_cannot_chase_or_activate_on_it(self):
        referral = self.refer(book=self.secret)
        for call in (lambda u: rs.send_reminder(referral, by=u),
                     lambda u: rs.activate_followup(referral, due_date=self.due, by=u)):
            with self.assertRaises(PermissionDenied):
                call(self.fresh(self.unit_head))


class ChaseTests(ReferralCase):
    def test_the_sender_side_chases(self):
        referral = self.refer()
        rs.send_reminder(referral, by=self.fresh(self.mail))

    def test_the_executor_cannot_chase(self):
        with self.assertRaises(PermissionDenied):
            rs.send_reminder(self.refer(), by=self.fresh(self.executor))

    def test_entry_cannot_chase_or_cancel(self):
        referral = self.refer()
        with self.assertRaises(PermissionDenied):
            rs.send_reminder(referral, by=self.fresh(self.entry))
        with self.assertRaises(PermissionDenied):
            rs.cancel_referral(referral, by=self.fresh(self.entry))

    def test_activation_needs_the_send_capability(self):
        referral = self.refer()
        with self.assertRaises(PermissionDenied):
            rs.activate_followup(referral, due_date=self.due, by=self.fresh(self.entry))
        rs.activate_followup(referral, due_date=self.due, by=self.fresh(self.mail))


class ButtonsFollowGuardsTests(ReferralCase):
    def flags(self, user):
        row = rs.reply_matrix(self.book, self.fresh(user))[0]
        return row['can_act'], row['can_chase']

    def test_the_row_buttons_match_what_the_server_accepts(self):
        self.refer()
        self.assertEqual(self.flags(self.executor), (True, False))
        self.assertEqual(self.flags(self.mail), (True, True))
        self.assertEqual(self.flags(self.entry), (False, False))

    def test_the_page_offers_distribution_to_senders_only(self):
        self.client.force_login(self.mail)
        self.assertTrue(self.client.get(reverse('book_detail', args=[self.book.pk])).context['can_distribute'])
        self.client.force_login(self.entry)
        self.assertFalse(self.client.get(reverse('book_detail', args=[self.book.pk])).context['can_distribute'])


class SectionSeesItsUnitsTests(ReferralCase):
    """قرارُ المالك للمستوى 5: مسؤولُ الشعبة يرى ما أُحيل إلى وحداته، والسرّيُّ مغلق."""

    def test_list_and_gate_agree(self):
        self.refer()
        user = self.fresh(self.section_head)
        self.assertTrue(s.can_view_book(self.book, user))
        self.assertIn(self.book, s.scope_books_for(user, Book.objects.all()))

    def test_a_sister_unit_does_not_see_it(self):
        self.refer()
        user = self.fresh(self.sib_exec)
        self.assertFalse(s.can_view_book(self.book, user))
        self.assertNotIn(self.book, s.scope_books_for(user, Book.objects.all()))

    def test_the_secret_stays_closed_for_the_section(self):
        self.refer(book=self.secret)
        user = self.fresh(self.section_head)
        self.assertTrue(s.can_view_book(self.secret, user))
        self.assertFalse(s.can_open_content(self.secret, user))
