# -*- coding: utf-8 -*-
"""الدفعةُ الثالثة من تدقيق نيلسن (2026‑10‑07): حرّاسُ الخادم.

A#11–13 التنبيهات (العنوانُ والرابطُ و«تعليم الكلّ» ورابطٌ داخليٌّ وحدَه) ·
D#9 سجلُّ الحركات يجد الموظّفَ باسمه الكامل · E#15 البادئةُ المهملة لا تُمسح بغياب حقلها ·
D#24 طاولةُ الوارد الفارغة فراغٌ واحد.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import Book, BookHistory, BookSequence, Notification


class NotificationsPageTests(TestCase):

    def setUp(self):
        self.clerk = User.objects.create_user('ntclerk', password='pw-ntclerk-1111')
        self.other = User.objects.create_user('ntother', password='pw-ntother-1111')
        self.client.force_login(self.clerk)

    def test_title_and_internal_link_are_shown(self):
        Notification.objects.create(user=self.clerk, title='أُحيل إليك كتاب', message='التفاصيل',
                                    link_url='/books/7/')
        body = self.client.get(reverse('notifications')).content.decode('utf-8')
        self.assertIn('أُحيل إليك كتاب', body)
        self.assertIn('value="/books/7/"', body)

    def test_an_outside_or_script_link_is_never_rendered(self):
        for bad in ('https://evil.example/x', 'javascript:alert(1)', '//evil.example/x'):
            Notification.objects.create(user=self.clerk, title='ت', message='م', link_url=bad)
        body = self.client.get(reverse('notifications')).content.decode('utf-8')
        self.assertNotIn('evil.example', body)
        self.assertNotIn('javascript:', body)

    def test_mark_read_follows_only_an_internal_next(self):
        n = Notification.objects.create(user=self.clerk, title='ت', message='م')
        resp = self.client.post(reverse('notification_mark_read', args=[n.pk]),
                                {'next': 'https://evil.example/x'})
        self.assertEqual(resp['Location'], reverse('notifications'))
        n2 = Notification.objects.create(user=self.clerk, title='ت', message='م')
        resp = self.client.post(reverse('notification_mark_read', args=[n2.pk]), {'next': '/books/7/'})
        self.assertEqual(resp['Location'], '/books/7/')

    def test_mark_all_read_touches_only_the_readers_own(self):
        Notification.objects.create(user=self.clerk, title='1', message='م')
        Notification.objects.create(user=self.clerk, title='2', message='م')
        theirs = Notification.objects.create(user=self.other, title='3', message='م')
        self.assertEqual(self.client.get(reverse('notification_mark_all_read')).status_code, 405)
        self.client.post(reverse('notification_mark_all_read'))
        self.assertFalse(self.clerk.notifications.filter(is_read=False).exists())
        theirs.refresh_from_db()
        self.assertFalse(theirs.is_read)


class AuditActorByFullNameTests(TestCase):

    def test_the_displayed_full_name_finds_the_rows(self):
        admin = User.objects.create_superuser('aadmin', 'a@x.co', 'pw-aadmin-1111')
        clerk = User.objects.create_user('u1907', password='pw-u1907-1111',
                                         first_name='سارة', last_name='الكاتبة')
        book = Book.objects.create(kind='incoming_internal', title='سجلّ', our_number='8401', created_by=clerk)
        BookHistory.objects.create(book=book, action='edit', by=clerk)
        self.client.force_login(admin)
        resp = self.client.get(reverse('audit_log'), {'actor': 'سارة الكاتبة'})
        self.assertEqual(len(resp.context['rows']), 1)
        resp = self.client.get(reverse('audit_log'), {'actor': 'لا أحد'})
        self.assertEqual(len(resp.context['rows']), 0)


class SequencePrefixKeptTests(TestCase):

    def test_saving_without_the_prefix_field_keeps_the_stored_prefix(self):
        admin = User.objects.create_superuser('padm', 'p@x.co', 'pw-padm-1111')
        self.client.force_login(admin)
        BookSequence.objects.update_or_create(kind='incoming_internal',
                                              defaults={'next_number': 10, 'prefix': 'و/'})
        self.client.post(reverse('sequence_settings'), {'next_number_incoming_internal': 11})
        seq = BookSequence.objects.get(kind='incoming_internal')
        self.assertEqual(seq.prefix, 'و/')
        self.assertEqual(seq.next_number, 11)


class DeskEmptyStateTests(TestCase):

    def test_an_empty_desk_says_so_once(self):
        admin = User.objects.create_superuser('dadm', 'd@x.co', 'pw-dadm-1111')
        self.client.force_login(admin)
        resp = self.client.get(reverse('desk_board'))
        self.assertTrue(resp.context['queues_empty'])
        self.assertContains(resp, 'الطاولةُ نظيفة', count=1)
