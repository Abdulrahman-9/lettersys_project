# -*- coding: utf-8 -*-
"""حرّاسُ منتقي الربط — النقطتان كانتا مبنيّتين بلا واجهةٍ تُحرّكهما."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import Book, BookLink, Department, Entity, UserProfile


class LinkPickerUITests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('root', 'r@x.co', 'pw')
        self.client.force_login(self.admin)
        self.book = Book.objects.create(kind='incoming_external', title='الأصل',
                                        our_number='9100', created_by=self.admin)
        self.other = Book.objects.create(kind='outgoing_internal', title='الجواب',
                                         our_number='9101', created_by=self.admin)

    def test_the_dialog_is_rendered_on_the_detail_page(self):
        """كان الضلعُ يُعرَض ولا يُضاف — لا حواريّةَ ولا زرّ."""
        res = self.client.get(reverse('book_detail', args=[self.book.pk]))

        self.assertContains(res, 'linkPickerModal')
        self.assertContains(res, 'link_picker.js')

    def test_the_relation_choices_come_from_the_model(self):
        """الصفاتُ من النموذج لا من قائمةٍ مكتوبةٍ في القالب — مصدرٌ واحد."""
        res = self.client.get(reverse('book_detail', args=[self.book.pk]))

        self.assertEqual(list(res.context['relation_choices']),
                         list(BookLink.RELATION_CHOICES))
        for _, label in BookLink.RELATION_CHOICES:
            self.assertContains(res, label)

    def test_the_picker_excludes_the_current_book(self):
        """الكتابُ لا يُربط بنفسه."""
        # البحثُ برقمٍ كاملٍ لا بجزءٍ منه: قواعدُ العدد في `numbering.py`
        # تُطابق العددَ لا السلسلةَ الجزئيّة — وهذا مقصودٌ لا نقص.
        res = self.client.get(reverse('api_link_picker'),
                              {'q': 'الجواب', 'exclude': self.book.pk})
        ids = [r['id'] for r in res.json()['results']]

        self.assertNotIn(self.book.pk, ids)
        self.assertIn(self.other.pk, ids)

    def test_an_empty_query_returns_nothing_not_everything(self):
        """بحثٌ فارغٌ يعيد الكلّ = تسريبٌ بطيء."""
        res = self.client.get(reverse('api_link_picker'), {'q': ''})

        self.assertEqual(res.json()['results'], [])

    def test_a_secret_title_is_masked_in_the_results(self):
        secret = Book.objects.create(kind='incoming_external', title='سرٌّ مكشوف',
                                     our_number='9102', secret_level='secret',
                                     created_by=self.admin)
        plain = User.objects.create_user('plain', 'p@x.co', 'pw')
        UserProfile.objects.update_or_create(
            user=plain, defaults={'department': Department.objects.create(
                name='قسم بعيد', code='ر.ب')})
        self.client.force_login(plain)

        res = self.client.get(reverse('api_link_picker'), {'q': '9102'})
        titles = [r['title'] for r in res.json()['results']]

        self.assertNotIn('سرٌّ مكشوف', titles)

    def test_adding_a_link_through_the_endpoint(self):
        res = self.client.post(
            reverse('api_add_link', args=[self.book.pk]),
            data='{"to_book": %d, "relation": "reply"}' % self.other.pk,
            content_type='application/json')

        self.assertEqual(res.status_code, 200)
        self.assertTrue(BookLink.objects.filter(from_book=self.book,
                                                to_book=self.other).exists())

    def test_an_unknown_relation_is_refused(self):
        res = self.client.post(
            reverse('api_add_link', args=[self.book.pk]),
            data='{"to_book": %d, "relation": "ملفّق"}' % self.other.pk,
            content_type='application/json')

        self.assertEqual(res.status_code, 400)
        self.assertFalse(BookLink.objects.exists())
