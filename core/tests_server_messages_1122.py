# -*- coding: utf-8 -*-
"""رسائلُ الخادم بسببها وطريقِ إصلاحها (11-22) — كانت «إجراء غير صالح.» و«تبويب غير معروف.»
و«غير مصرح بالاستعادة.» لا تقول ما الخطأ ولا ما يُفعل ولا لمن يُطلب.
"""
from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.urls import reverse

from core.models import Book, Entity
from core.tests_b4_trash import TrashCase


def _said(response):
    return [str(m) for m in get_messages(response.wsgi_request)]


class StatusAndKindMessagesTests(TrashCase):

    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser('msg_admin', password='pw-msg-1122')
        self.client.force_login(self.admin)

    def test_an_unknown_status_action_names_the_two_it_accepts(self):
        response = self.client.post(reverse('book_change_status', args=[self.book.pk]), {'action': 'bogus'})
        self.assertRedirects(response, reverse('book_detail', args=[self.book.pk]), fetch_redirect_response=False)
        said = ' '.join(_said(response))
        self.assertIn('«أنهِ المتابعة» أو «أعِد فتح المتابعة»', said)
        self.assertIn('أعد تحميل الصفحة', said)

    def test_an_unknown_kind_lists_the_tabs_and_never_echoes_the_request(self):
        entity = Entity.objects.create(name='جهةُ الرسائل')
        response = self.client.post(reverse('entity_set_kind'), {'kind': '<b>x</b>', 'selected': [entity.pk]})
        said = ' '.join(_said(response))
        self.assertIn('لم يُنقل شيء', said)
        self.assertIn('«نقل إلى:»', said)
        self.assertNotIn('<b>x</b>', said)


class RestoreRefusalTests(TrashCase):

    def _refused(self, url):
        response = self.post(self.far_mail, url)
        self.assertRedirects(response, reverse('trash_list'), fetch_redirect_response=False)
        return ' '.join(_said(response))

    def test_a_refused_book_restore_says_whose_key_it_is(self):
        Book.all_objects.filter(pk=self.book.pk).update(is_deleted=True)
        said = self._refused(reverse('restore_book', args=[self.book.pk]))
        self.assertIn('لا تملك استرجاعَ هذا الكتاب', said)
        self.assertIn('رئيس قسم «قسم السلّة»', said)
        self.assertTrue(Book.all_objects.get(pk=self.book.pk).is_deleted)

    def test_a_book_without_a_department_points_to_its_creator(self):
        Book.all_objects.filter(pk=self.book.pk).update(is_deleted=True, department=None)
        said = self._refused(reverse('restore_book', args=[self.book.pk]))
        self.assertIn('الكتابُ بلا قسمٍ مالك', said)
