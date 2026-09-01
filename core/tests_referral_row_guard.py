# -*- coding: utf-8 -*-
"""حارسُ صفّ الإحالة — الأختُ لا تُقفل التزامَ أختها."""

from django.contrib.auth.models import Group, User
from django.core.exceptions import PermissionDenied
from django.test import TestCase

from core.models import Book, BookReferral, Department, Entity, UserProfile
from core.referral_service import mark_done, mark_received
from core.roles import CONTROLLER_GROUP_NAME


class ReferralRowGuardTests(TestCase):
    def setUp(self):
        self.boss = User.objects.create_superuser('root', 'r@x.co', 'pw')

        self.dept_ent = Entity.objects.create(name='قسم الحرس', code='ج.ق')
        self.dept = Department.objects.create(name='قسم الحرس', code='ج.ق',
                                              entity=self.dept_ent)
        self.left = Department.objects.create(name='وحدة يمنى', code='ج.ي',
                                              parent=self.dept)
        self.right = Department.objects.create(name='وحدة يسرى', code='ج.س',
                                               parent=self.dept)

        self.in_left = self._user('left', self.left)
        self.in_right = self._user('right', self.right)

        self.book = Book.objects.create(kind='incoming_external', title='ك',
                                        our_number='8100', department=self.dept,
                                        created_by=self.boss)
        self.referral = BookReferral.objects.create(
            book=self.book, from_department=self.dept, to_department=self.right,
            status=BookReferral.SENT, created_by=self.boss)

    def _user(self, name, department, *, head=False, controller=False):
        user = User.objects.create_user(name, name + '@x.co', 'pw')
        UserProfile.objects.update_or_create(
            user=user, defaults={'department': department, 'is_department_head': head})
        if controller:
            group, _ = Group.objects.get_or_create(name=CONTROLLER_GROUP_NAME)
            user.groups.add(group)
        return user

    def test_a_sister_unit_cannot_close_the_row(self):
        """الثغرةُ الأصليّة: بوّابةُ الكتاب وحدها كانت تكفي.

        يفشل على الكود السابق — الوحدتان أختان فترى كلٌّ منهما الكتاب.
        """
        with self.assertRaises(PermissionDenied):
            mark_done(self.referral, by=self.in_left)

        self.referral.refresh_from_db()
        self.assertEqual(self.referral.status, BookReferral.SENT)

    def test_the_target_unit_closes_its_own_row(self):
        mark_done(self.referral, by=self.in_right)

        self.referral.refresh_from_db()
        self.assertEqual(self.referral.status, BookReferral.DONE)

    def test_the_parent_department_may_close_a_child_row(self):
        """الشجرةُ تسيل نزولاً — رئيسُ الشعبة يُقفل صفَّ وحدته."""
        parent_user = self._user('parent', self.dept)

        mark_received(self.referral, by=parent_user)

        self.referral.refresh_from_db()
        self.assertEqual(self.referral.status, BookReferral.RECEIVED)

    def test_the_assignee_closes_it_wherever_they_sit(self):
        """الالتزامُ باسمِ شخصٍ يتبعه أينما كان قسمُه.

        والسيناريو واقعيٌّ لا مفتعَل: وحدةٌ أختٌ **مذكورةٌ في الكتاب** فتراه
        بأضبارتها، والالتزامُ باسم موظّفٍ فيها. بلا شرطِ المكلَّف يُرفض وهو
        صاحبُ العمل. (المحاولةُ الأولى وضعت مكلَّفاً لا يرى الكتابَ أصلاً —
        فرضيّةٌ لا تقع، وبوّابةُ الكتاب تردّه قبل حارس الصفّ.)
        """
        left_entity = Entity.objects.create(name='وحدة يمنى', code='ج.ي.ج')
        self.left.entity = left_entity
        self.left.save(update_fields=['entity'])
        self.book.receiving_entities.add(left_entity)

        self.referral.assignee = self.in_left
        self.referral.save(update_fields=['assignee'])

        mark_done(self.referral, by=self.in_left)

        self.referral.refresh_from_db()
        self.assertEqual(self.referral.status, BookReferral.DONE)

    def test_the_owning_mail_officer_may_close_it(self):
        """هو مَن يستلم الورقةَ الموقَّعة — منعُه يدفع العملَ خارج النظام."""
        clerk = self._user('clerk', self.dept, controller=True)

        mark_done(self.referral, by=clerk)

        self.referral.refresh_from_db()
        self.assertEqual(self.referral.status, BookReferral.DONE)

    def test_a_mail_officer_of_another_department_may_not(self):
        """صفةُ المختصّ لا تعبر حدودَ قسمها."""
        other = Department.objects.create(name='قسم غريب', code='ج.غ')
        stranger = self._user('stranger', other, controller=True)

        with self.assertRaises(PermissionDenied):
            mark_done(self.referral, by=stranger)

    def test_a_user_without_a_department_is_refused(self):
        loose = User.objects.create_user('loose', 'l@x.co', 'pw')
        UserProfile.objects.update_or_create(user=loose,
                                             defaults={'department': None})

        with self.assertRaises(PermissionDenied):
            mark_done(self.referral, by=loose)

    def test_the_admin_still_passes(self):
        mark_done(self.referral, by=self.boss)

        self.referral.refresh_from_db()
        self.assertEqual(self.referral.status, BookReferral.DONE)


class ReminderDirectionTests(ReferralRowGuardTests):
    """التنبيهُ فعلُ المُرسِل — عكسُ تحريك الحالة تماماً."""

    def test_the_sending_side_may_chase(self):
        from core.referral_service import send_reminder

        sender = self._user('sender', self.dept)

        send_reminder(self.referral, by=sender)

        self.referral.refresh_from_db()
        self.assertIsNotNone(self.referral.last_reminder_at)

    def test_the_target_unit_cannot_chase_itself(self):
        """«التنبيهُ لمن ينتظر الجواب لا لمن عليه» — ومَن عليه هو الوحدة."""
        from core.referral_service import send_reminder

        with self.assertRaises(PermissionDenied):
            send_reminder(self.referral, by=self.in_right)

    def test_a_sister_unit_cannot_chase_either(self):
        from core.referral_service import send_reminder

        with self.assertRaises(PermissionDenied):
            send_reminder(self.referral, by=self.in_left)

    def test_the_desk_may_chase(self):
        """موظّفُ البريد يطارد المتأخّر — وهو الاستعمالُ الذي بُنيت له."""
        from core.referral_service import send_reminder

        clerk = self._user('chaser', self.dept, controller=True)

        send_reminder(self.referral, by=clerk)

        self.referral.refresh_from_db()
        self.assertIsNotNone(self.referral.last_reminder_at)
