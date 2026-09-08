# -*- coding: utf-8 -*-
"""حرّاسُ ورشة العناقيد في صفحة الجهات."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.admin_service import save_group
from core.models import Book, Entity, EntityGroup


class GroupsWorkshopTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('root', 'r@x.co', 'pw')
        self.client.force_login(self.admin)
        self.member = Entity.objects.create(name='عضوُ العنقود', code='و.ع')
        self.group = save_group(by=self.admin, name='عنقودُ العرض',
                                member_ids=[self.member.pk])

    def test_the_page_has_two_modes(self):
        entities = self.client.get(reverse('entity_list'))
        groups = self.client.get(reverse('entity_list'), {'view': 'groups'})

        self.assertEqual(entities.context['view_mode'], 'entities')
        self.assertEqual(groups.context['view_mode'], 'groups')

    def test_groups_are_listed_with_their_members(self):
        res = self.client.get(reverse('entity_list'), {'view': 'groups'})

        self.assertContains(res, 'عنقودُ العرض')
        self.assertContains(res, 'عضوُ العنقود')

    def test_editing_prefills_from_the_link(self):
        """التعديلُ برابطٍ لا بـJS — يُنسخ ويُشارَك ويعمل بلا سكربت."""
        res = self.client.get(reverse('entity_list'),
                              {'view': 'groups', 'edit': self.group.pk})

        self.assertEqual(res.context['editing_group'], self.group)
        self.assertEqual(res.context['editing_member_ids'], {self.member.pk})

    def test_the_entities_mode_does_not_pay_for_group_queries(self):
        """وضعُ الجهات لا يُحمَّل بيانات العناقيد — الصفحةُ الأكثرُ فتحاً."""
        res = self.client.get(reverse('entity_list'))

        self.assertEqual(list(res.context['groups']), [])
        self.assertEqual(list(res.context['group_entities']), [])

    def test_creating_from_the_page_returns_to_the_page(self):
        """الحفظُ يُرسَل إلى مسار الكتابة الواحد ويعود إلى الورشة لا إلى اللوحة."""
        res = self.client.post(reverse('admin_panel'), {
            'action': 'save_group', 'tab': 'groups',
            'return_to': 'groups_workshop',
            'name': 'عنقودٌ جديد', 'auto_rule': '',
            'members_submitted': '1', 'members': [self.member.pk],
        })

        self.assertEqual(res['Location'], '/books/entities/?view=groups')
        self.assertTrue(EntityGroup.objects.filter(name='عنقودٌ جديد').exists())

    def test_an_unknown_return_target_falls_back_to_the_panel(self):
        """`return_to` قائمةٌ بيضاء لا عنوانٌ حرّ — العنوانُ الحرّ تحويلٌ مفتوح."""
        res = self.client.post(reverse('admin_panel'), {
            'action': 'save_group', 'tab': 'groups',
            'return_to': 'https://evil.example/x',
            'name': 'عنقودٌ آخر', 'auto_rule': '', 'members_submitted': '1',
        })

        self.assertEqual(res['Location'], '/books/admin/?tab=groups')

    def test_a_used_group_shows_as_undeletable(self):
        Book.objects.create(kind='outgoing_internal', title='تعميم',
                            created_by=self.admin, sent_to_group=self.group)

        res = self.client.get(reverse('entity_list'), {'view': 'groups'})

        self.assertContains(res, 'لا يُحذف')
        self.assertNotContains(res, 'delete_group')

    def test_an_unused_group_offers_delete(self):
        res = self.client.get(reverse('entity_list'), {'view': 'groups'})

        self.assertContains(res, 'delete_group')

    def test_an_empty_group_says_so_plainly(self):
        """عنقودٌ بلا أعضاءٍ لا يصل أحداً — والصفحةُ تقولها لا تسكت."""
        save_group(by=self.admin, name='عنقودٌ فارغ', member_ids=[])

        res = self.client.get(reverse('entity_list'), {'view': 'groups'})

        self.assertContains(res, 'لا أعضاء بعد')

    def test_the_admin_panel_links_here_instead_of_duplicating(self):
        res = self.client.get(reverse('admin_panel'), {'tab': 'groups'})

        self.assertContains(res, 'view=groups')
        self.assertNotContains(res, 'grp-members')
