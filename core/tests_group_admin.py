# -*- coding: utf-8 -*-
"""حرّاسُ إدارة العناقيد يدويّاً — إنشاءٌ وتعديلُ أعضاءٍ وحذف."""

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from core.admin_service import delete_group, save_group
from core.models import Book, Entity, EntityGroup


class GroupMembershipTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('root', 'r@x.co', 'pw')
        self.client.force_login(self.admin)
        self.a = Entity.objects.create(name='جهة أ')
        self.b = Entity.objects.create(name='جهة ب')
        self.group = save_group(by=self.admin, name='عنقود',
                                member_ids=[self.a.pk, self.b.pk])

    def _post(self, **extra):
        data = {'action': 'save_group', 'tab': 'groups', 'id': self.group.pk,
                'name': self.group.name, 'auto_rule': ''}
        data.update(extra)
        return self.client.post(reverse('admin_panel'), data)

    def test_toggling_active_does_not_wipe_members(self):
        """زرُّ التعطيل لا حقلَ أعضاءَ فيه — فلا يمسّ العضويّة.

        يفشل على الكود السابق: القائمةُ المتعدّدة لا ترسل شيئاً حين لا يُحدَّد
        أحد، فكان `[]` يصل `members.set([])` فيمحو العنقودَ **صامتاً**.
        """
        self._post(is_active='0')

        self.assertEqual(self.group.members.count(), 2)

    def test_explicit_empty_selection_does_clear_members(self):
        """أمّا الإرسالُ الصريحُ فارغاً فيُفرغ — والعلامةُ تفصل الحالتين."""
        self._post(members_submitted='1')

        self.assertEqual(self.group.members.count(), 0)

    def test_members_can_be_edited(self):
        self._post(members_submitted='1', members=[self.a.pk])

        self.assertEqual(list(self.group.members.values_list('pk', flat=True)),
                         [self.a.pk])

    def test_members_can_be_added(self):
        c = Entity.objects.create(name='جهة ج')

        self._post(members_submitted='1',
                   members=[self.a.pk, self.b.pk, c.pk])

        self.assertEqual(self.group.members.count(), 3)


class GroupDeleteTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('root', 'r@x.co', 'pw')
        self.group = save_group(by=self.admin, name='عنقود')

    def test_an_unused_group_is_deleted(self):
        delete_group(by=self.admin, group=self.group)

        self.assertFalse(EntityGroup.objects.filter(pk=self.group.pk).exists())

    def test_a_group_with_history_is_refused(self):
        """`sent_to_group` بـSET_NULL — فالحذفُ يمحو «عُمِّم على» من كتابٍ مضى."""
        Book.objects.create(kind='outgoing_internal', title='تعميم',
                            created_by=self.admin, sent_to_group=self.group)

        with self.assertRaises(ValidationError):
            delete_group(by=self.admin, group=self.group)

        self.assertTrue(EntityGroup.objects.filter(pk=self.group.pk).exists())

    def test_ordinary_user_cannot_delete(self):
        plain = User.objects.create_user('plain', 'p@x.co', 'pw')

        with self.assertRaises(Exception):
            delete_group(by=plain, group=self.group)


class GroupEditFormTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('root', 'r@x.co', 'pw')
        self.client.force_login(self.admin)
        self.member = Entity.objects.create(name='عضو')
        self.group = save_group(by=self.admin, name='عنقود',
                                member_ids=[self.member.pk])

    def test_edit_link_prefills_the_form(self):
        res = self.client.get(reverse('admin_panel'),
                              {'tab': 'groups', 'edit': self.group.pk})

        self.assertEqual(res.context['editing'], self.group)
        self.assertEqual(res.context['member_ids'], {self.member.pk})

    def test_no_edit_param_means_a_blank_form(self):
        res = self.client.get(reverse('admin_panel'), {'tab': 'groups'})

        self.assertIsNone(res.context['editing'])

    def test_every_active_entity_is_offered(self):
        """عنقودٌ لا يجد عضوَه في القائمة عيبٌ صامت — فلا سقفَ على الجهات."""
        for i in range(30):
            Entity.objects.create(name='جهة %d' % i)

        res = self.client.get(reverse('admin_panel'), {'tab': 'groups'})

        self.assertEqual(len(res.context['entities']),
                         Entity.objects.filter(is_active=True).count())
