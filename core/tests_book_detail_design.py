# -*- coding: utf-8 -*-
"""حرّاسُ ترويسة صفحة التفاصيل — ما نُقل يجب ألّا يعود مكرّراً."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import Book, BookRegistration, Department, Entity


class BookDetailHeaderTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('root', 'r@x.co', 'pw')
        self.client.force_login(self.admin)
        self.book = Book.objects.create(kind='incoming_external', title='كتابُ التصميم',
                                        our_number='7700', created_by=self.admin)

    def test_the_page_carries_the_design_scope(self):
        """كلُّ الهويّة مقصورةٌ على `.bd-page` — بلا الصنف لا لونَ إطلاقاً."""
        res = self.client.get(reverse('book_detail', args=[self.book.pk]))

        self.assertContains(res, 'bd-page')
        self.assertContains(res, 'book_detail_design.css')

    def test_the_number_and_title_are_in_the_header(self):
        res = self.client.get(reverse('book_detail', args=[self.book.pk]))

        self.assertContains(res, 'bd-num')
        self.assertContains(res, 'كتابُ التصميم')

    def test_custody_appears_once_not_twice(self):
        """نُقلت من لوحة دورة الحياة ولم تُنسخ — نسختان على شاشةٍ واحدة أسوأ من غيابها."""
        res = self.client.get(reverse('book_detail', args=[self.book.pk]))
        body = res.content.decode()

        self.assertEqual(body.count('العهدة الآن'), 1)
        self.assertEqual(body.count('bd-custody-lbl'), 1)

    def test_the_registration_strip_shows_only_when_there_are_entries(self):
        """شريطُ القيود لا يُعرض فارغاً — ضجيجٌ في أكثر الصفحات فتحاً."""
        res = self.client.get(reverse('book_detail', args=[self.book.pk]))
        self.assertNotContains(res, 'bd-regs-lbl')

        dept = Department.objects.create(name='قسم القيد', code='ص.ق')
        BookRegistration.objects.create(book=self.book, department=dept,
                                        number='2501', registered_by=self.admin)

        res = self.client.get(reverse('book_detail', args=[self.book.pk]))
        self.assertContains(res, 'bd-regs-lbl')
        self.assertContains(res, '2501')

    def test_the_stylesheet_is_cache_busted(self):
        """فخُّ الـPWA: بلا `?v=` لا يصل النمطُ إلى المتصفّح أبداً."""
        res = self.client.get(reverse('book_detail', args=[self.book.pk]))

        self.assertRegex(res.content.decode(), r'book_detail_design\.css\?v=')
