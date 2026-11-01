# -*- coding: utf-8 -*-
"""تدقيقُ التحكّم بالوصول 2026-11-01 — حرّاسُ ما أُغلق.

١. **إكمالُ العناوين وقاموسُ كلماتها** في نطاق القسم، والسرّيُّ لا يُقترح لمَن لا يفتحه،
   والكاشُ لا يعبر من مستخدمٍ إلى آخر.
٢. **بريدُ الجهة** يُعدَّل من صفحة الجهة وحدَها (``entity_edit``).
٣. **لوحةُ Django** لمدير النظام، وبابُ دخولها يقاسم ``/login/`` عدّادَ محاولاته،
   و``BookHistory`` فيها للقراءة.
٤. **حدُّ المحاولات** لا يقرأ ``X-Forwarded-For`` ما لم يُعلَن البروكسي.
"""
import json

from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.test import TestCase
from django.urls import NoReverseMatch, reverse

from core import roles
from core.models import Book, BookHistory, Department, Entity, UserProfile


def _member(name, dept, group=None, staff=False):
    user = User.objects.create_user(name, password=f'pw-{name}-1101', is_staff=staff)
    UserProfile.objects.update_or_create(user=user, defaults={'department': dept})
    if group:
        user.groups.add(Group.objects.get(name=group))
    return user


class TitleSuggestionScopeTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        roles.ensure_role_groups()
        cls.d_a = Department.objects.create(name='المخازن', code='ت-أ1101')
        cls.d_b = Department.objects.create(name='العقود', code='ت-ب1101')
        cls.clerk_a = _member('clerk_a', cls.d_a, roles.ENTRY_GROUP_NAME)
        cls.owner_b = _member('owner_b', cls.d_b, roles.ENTRY_GROUP_NAME)
        cls.colleague_b = _member('colleague_b', cls.d_b, roles.ENTRY_GROUP_NAME)
        cls.root = User.objects.create_superuser('root1101', 'r@x.com', 'pw-root-1101')
        Book.objects.create(kind='incoming_internal', title='تقرير المخازن السنوي',
                            created_by=cls.clerk_a, department=cls.d_a)
        Book.objects.create(kind='incoming_internal', title='عقد صيانة المولدات',
                            created_by=cls.owner_b, department=cls.d_b)
        Book.objects.create(kind='incoming_internal', title='خطة دمج الشركة',
                            created_by=cls.owner_b, department=cls.d_b, secret_level='topsecret')

    def setUp(self):
        cache.clear()

    def words(self, user):
        self.client.force_login(user)
        return set(self.client.get('/books/api/title-words/').json()['ar'])

    def next_word(self, user, q):
        self.client.force_login(user)
        return self.client.get('/books/api/title-autocomplete/',
                               {'q': q, 'mode': 'next_word'}).json()['next_word']

    def test_words_come_from_own_department_only(self):
        words = self.words(self.clerk_a)
        self.assertIn('المخازن', words)
        self.assertNotIn('المولدات', words)
        self.assertNotIn('الشركة', words)

    def test_secret_title_words_only_for_who_opens_it(self):
        self.assertIn('المولدات', self.words(self.colleague_b))
        self.assertNotIn('الشركة', self.words(self.colleague_b))
        self.assertIn('الشركة', self.words(self.owner_b))

    def test_next_word_does_not_complete_hidden_titles(self):
        self.assertIsNone(self.next_word(self.clerk_a, 'خطة دمج'))
        self.assertIsNone(self.next_word(self.colleague_b, 'خطة دمج'))
        self.assertEqual(self.next_word(self.owner_b, 'خطة دمج'), 'الشركة')

    def test_cache_is_not_served_across_users(self):
        """مديرُ النظام يملأ الكاشَ أوّلاً — ولا يرث الموظّفُ ما رآه المدير."""
        self.assertIn('الشركة', self.words(self.root))
        self.assertNotIn('الشركة', self.words(self.clerk_a))
        self.assertEqual(self.next_word(self.root, 'خطة دمج'), 'الشركة')
        self.assertIsNone(self.next_word(self.clerk_a, 'خطة دمج'))

    def test_arabic_queries_do_not_share_one_cache_key(self):
        """``slugify`` بلا allow_unicode يُفرغ الاستعلامَ العربيّ — فيُعاد جوابُ غيره."""
        self.assertEqual(self.next_word(self.owner_b, 'خطة دمج'), 'الشركة')
        self.assertEqual(self.next_word(self.owner_b, 'عقد صيانة'), 'المولدات')

    def test_unscoped_title_routes_are_gone(self):
        for name in ('entity_stats', 'search_titles'):
            with self.subTest(name=name), self.assertRaises(NoReverseMatch):
                reverse(name)


class EntityEmailWriteTests(TestCase):

    def test_regular_user_cannot_rewrite_entity_contact(self):
        roles.ensure_role_groups()
        dept = Department.objects.create(name='أ', code='ب-أ1101')
        clerk = _member('mailclerk', dept, roles.ENTRY_GROUP_NAME)
        entity = Entity.objects.create(name='جهةٌ خارجيّة', email='desk@entity.example')
        self.client.force_login(clerk)
        r = self.client.post(f'/books/api/email/entity/{entity.pk}/update/',
                             data=json.dumps({'email': 'other@example.com',
                                              'email_cc': 'cc@example.com'}),
                             content_type='application/json')
        self.assertEqual(r.status_code, 404)
        entity.refresh_from_db()
        self.assertEqual((entity.email, entity.email_cc), ('desk@entity.example', ''))


class OutOfScopeIsNotFoundTests(TestCase):
    """كتابُ قسمٍ آخر «غير موجود» عند الحذف والاستعادة — لا «ممنوع» يُثبت وجودَه."""

    @classmethod
    def setUpTestData(cls):
        roles.ensure_role_groups()
        d_a = Department.objects.create(name='أ', code='ن-أ1101')
        d_b = Department.objects.create(name='ب', code='ن-ب1101')
        cls.clerk_a = _member('nf_clerk_a', d_a, roles.ENTRY_GROUP_NAME)
        owner_b = _member('nf_owner_b', d_b, roles.ENTRY_GROUP_NAME)
        cls.live_b = Book.objects.create(kind='incoming_internal', title='حيّ', created_by=owner_b,
                                         department=d_b)
        cls.trashed_b = Book.objects.create(kind='incoming_internal', title='محذوف',
                                            created_by=owner_b, department=d_b, is_deleted=True)

    def test_delete_and_undo_answer_like_a_missing_book(self):
        self.client.force_login(self.clerk_a)
        for url in (reverse('api_delete_book', args=[self.live_b.pk]),
                    reverse('api_undo_delete_book', args=[self.trashed_b.pk]),
                    reverse('api_delete_book', args=[999999]),
                    reverse('api_undo_delete_book', args=[999999])):
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url).status_code, 404)
        self.assertFalse(Book.all_objects.get(pk=self.live_b.pk).is_deleted)
        self.assertTrue(Book.all_objects.get(pk=self.trashed_b.pk).is_deleted)


class DjangoAdminGateTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        roles.ensure_role_groups()
        dept = Department.objects.create(name='أ', code='ل-أ1101')
        # staff ومجموعةُ «مشرف المتابعة» تمنحه view/change_book — وهذا ما كان يفتح اللوحة
        cls.staff = _member('staff1101', dept, roles.CONTROLLER_GROUP_NAME, staff=True)
        cls.root = User.objects.create_superuser('root_adm1101', 'r@x.com', 'pw-root-1101')
        cls.book = Book.objects.create(kind='incoming_internal', title='كتاب', created_by=cls.root,
                                       department=dept)
        cls.history = BookHistory.objects.create(book=cls.book, action='create', by=cls.root)

    def setUp(self):
        cache.clear()

    def test_staff_with_model_perms_is_turned_away(self):
        self.client.force_login(self.staff)
        r = self.client.get('/admin/core/book/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/admin/login/', r['Location'])

    def test_superuser_still_opens_admin(self):
        self.client.force_login(self.root)
        self.assertEqual(self.client.get('/admin/core/book/').status_code, 200)

    def test_book_history_cannot_be_edited_or_deleted(self):
        self.client.force_login(self.root)
        base = f'/admin/core/bookhistory/{self.history.pk}'
        self.assertEqual(self.client.get(f'{base}/delete/').status_code, 403)
        r = self.client.post(f'{base}/change/', {'action': 'edit', 'notes': 'x'})
        self.assertEqual(r.status_code, 403)
        self.assertTrue(BookHistory.objects.filter(pk=self.history.pk, action='create').exists())

    def test_admin_login_is_rate_limited(self):
        codes = [self.client.post('/admin/login/', {'username': 'root_adm1101',
                                                    'password': 'wrong'}).status_code
                 for _ in range(11)]
        self.assertEqual(codes[-1], 429)
        # الحدُّ على الإرسال وحدَه: الصفحةُ نفسُها تُعرض
        self.assertEqual(self.client.get('/admin/login/').status_code, 200)

    def test_admin_login_shares_the_app_login_bucket(self):
        for _ in range(10):
            self.client.post('/login/', {'username': 'root_adm1101', 'password': 'wrong'})
        r = self.client.post('/admin/login/', {'username': 'root_adm1101', 'password': 'wrong'})
        self.assertEqual(r.status_code, 429)


class LoginLimitForwardedForTests(TestCase):

    def setUp(self):
        cache.clear()

    def test_rotating_forwarded_for_does_not_reset_the_limit(self):
        codes = [self.client.post('/login/', {'username': 'nobody', 'password': 'wrong'},
                                  HTTP_X_FORWARDED_FOR=f'10.0.0.{i}').status_code
                 for i in range(11)]
        self.assertEqual(codes[-1], 429)
