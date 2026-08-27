"""
بوابة رؤية الكتب — اختبارات انحدار لسجلّ العيوب ح5.

القاعدة كانت منسوخة يدويّاً في 27 موضعاً؛ صارت في `core/scoping.py` وحده.
هذه الاختبارات تحرس **السلوك** لا الشكل: مستخدمٌ لا يصل كتاب غيره عبر أيّ مسار.
"""

from django.contrib.auth.models import User
from django.test import TestCase

from core.models import Book
from core.scoping import can_view_book, is_privileged, scope_books_for


class ScopingUnitTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user('a1', password='pw-a1-11111')
        cls.bob   = User.objects.create_user('b1', password='pw-b1-11111')
        cls.staff = User.objects.create_user('s1', password='pw-s1-11111', is_staff=True)
        cls.root  = User.objects.create_superuser('r1', 'r@x.com', 'pw-r1-11111')
        cls.book_a = Book.objects.create(kind='incoming_internal', title='أ', created_by=cls.alice)
        cls.book_b = Book.objects.create(kind='incoming_internal', title='ب', created_by=cls.bob)

    def test_privilege_predicate(self):
        self.assertFalse(is_privileged(self.alice))
        self.assertTrue(is_privileged(self.staff))
        self.assertTrue(is_privileged(self.root))

    def test_can_view_book_matrix(self):
        self.assertTrue(can_view_book(self.book_a, self.alice))
        self.assertFalse(can_view_book(self.book_b, self.alice))
        self.assertTrue(can_view_book(self.book_b, self.staff))
        self.assertTrue(can_view_book(self.book_b, self.root))

    def test_scope_queryset(self):
        self.assertEqual(list(scope_books_for(self.alice).values_list('title', flat=True)), ['أ'])
        self.assertEqual(scope_books_for(self.staff).count(), 2)

    def test_scope_respects_soft_delete_by_default(self):
        """النطاق يبني على المدير الافتراضي — فلا يُعيد المحذوف."""
        self.book_a.is_deleted = True
        self.book_a.save(update_fields=['is_deleted'])
        self.assertEqual(scope_books_for(self.alice).count(), 0)
        self.assertEqual(scope_books_for(self.staff).count(), 1)


class ForeignBookIsUnreachableTests(TestCase):
    """المسارات التي كانت تكرّر القاعدة يدويّاً — كلّها تُغلق الآن."""

    def setUp(self):
        self.alice = User.objects.create_user('a2', password='pw-a2-11111')
        self.bob   = User.objects.create_user('b2', password='pw-b2-11111')
        self.book_b = Book.objects.create(kind='incoming_internal', title='كتاب بوب', created_by=self.bob)
        self.client.force_login(self.alice)

    def _denied(self, resp):
        self.assertIn(resp.status_code, (302, 403, 404),
                      f'مسارٌ سمح بكتاب غيره: {resp.status_code}')

    def test_detail_page(self):
        self._denied(self.client.get(f'/books/{self.book_b.pk}/'))

    def test_edit_page(self):
        self._denied(self.client.get(f'/books/{self.book_b.pk}/edit/'))

    def test_report_page(self):
        self._denied(self.client.get(f'/books/{self.book_b.pk}/report/'))

    def test_delete_api(self):
        self._denied(self.client.post(f'/books/api/book/{self.book_b.pk}/delete/'))

    def test_list_excludes_foreign_books(self):
        resp = self.client.get('/books/unified/')
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'كتاب بوب')
