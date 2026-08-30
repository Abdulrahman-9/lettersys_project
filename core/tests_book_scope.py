"""
بوابة رؤية الكتب — سجلّ العيوب ح5، ثمّ عقدُ المرحلة أ.

القاعدة في `core/scoping.py` وحده (كانت منسوخة في 27 موضعاً). وهذه الاختبارات
تحرس **السلوك**: من يرى ماذا بعد وصول بُعد القسم وطبقة السرّيّة.
"""

from django.contrib.auth.models import User
from django.test import TestCase

from core.models import Book, Department, UserProfile
from core.scoping import can_view_book, is_privileged, scope_books_for


def _book(title, owner, dept, secret='normal'):
    return Book.objects.create(kind='incoming_internal', title=title, created_by=owner,
                               department=dept, secret_level=secret)


class ScopeContractTests(TestCase):
    """قسمان، وموظّفان، ورئيسُ قسمٍ، ومديرُ نظام."""

    @classmethod
    def setUpTestData(cls):
        cls.d1 = Department.objects.create(name='المتابعة', code='ش13-t')
        cls.d2 = Department.objects.create(name='العقود', code='ش5-t')

        def member(name, dept, head=False, staff=False):
            u = User.objects.create_user(name, password=f'pw-{name}-1111', is_staff=staff)
            UserProfile.objects.create(user=u, department=dept, is_department_head=head)
            return u

        cls.emp1  = member('emp1', cls.d1)
        cls.emp1b = member('emp1b', cls.d1, staff=True)   # staff لا يوسّع الرؤية
        cls.head1 = member('head1', cls.d1, head=True)
        cls.emp2  = member('emp2', cls.d2)
        cls.root  = User.objects.create_superuser('root', 'r@x.com', 'pw-root-1111')
        cls.orphan = User.objects.create_user('orphan', password='pw-orphan-11')  # بلا ملفّ

        cls.b1      = _book('كتاب المتابعة', cls.emp1, cls.d1)
        cls.b1_sec  = _book('سرّيّ المتابعة', cls.head1, cls.d1, secret='secret')
        cls.b1_mine = _book('سرّيٌّ أنشأتُه', cls.emp1, cls.d1, secret='secret')
        cls.b2      = _book('كتاب العقود', cls.emp2, cls.d2)

    def titles(self, user):
        return set(scope_books_for(user).values_list('title', flat=True))

    # ── القسم ──
    def test_employee_sees_department_books_not_only_own(self):
        """الكتاب ملكُ القسم لا مُدخِله — تغييرٌ مقصود عن «كتبي أنا»."""
        self.assertIn('كتاب المتابعة', self.titles(self.emp1))
        self.assertNotIn('كتاب العقود', self.titles(self.emp1))

    def test_other_department_is_invisible(self):
        self.assertNotIn('كتاب المتابعة', self.titles(self.emp2))

    def test_superuser_sees_everything(self):
        self.assertEqual(len(self.titles(self.root)), 4)

    # ── طبقة السرّيّة ──
    def test_secret_row_is_visible_but_content_is_not(self):
        """العقدُ الجديد: الصفُّ يُرى كما في الدفتر الورقيّ، والمحتوى يُحجب.

        (كان هذا الاختبار يحرس القاعدةَ المشحونة خطأً: إخفاءَ الصفّ كلِّه.)
        """
        from core.scoping import can_open_content

        self.assertIn('سرّيّ المتابعة', self.titles(self.emp1))
        self.assertFalse(can_open_content(self.b1_sec, self.emp1))

    def test_secret_visible_to_its_creator(self):
        self.assertIn('سرّيٌّ أنشأتُه', self.titles(self.emp1))

    def test_secret_visible_to_department_head(self):
        self.assertIn('سرّيّ المتابعة', self.titles(self.head1))
        self.assertIn('سرّيٌّ أنشأتُه', self.titles(self.head1))

    def test_head_of_other_department_sees_nothing_of_ours(self):
        head2 = User.objects.create_user('head2', password='pw-head2-11')
        UserProfile.objects.create(user=head2, department=self.d2, is_department_head=True)
        self.assertNotIn('سرّيّ المتابعة', self.titles(head2))

    # ── is_staff لم تعد تُوسّع ──
    def test_staff_flag_no_longer_widens_visibility(self):
        """حاملُ is_staff يرى ما يراه أيّ موظّفٍ في قسمه: العلنيّ فقط.

        (لا نقارنه بـ``emp1`` لأنّ الأخير أنشأ كتاباً سرّيّاً فيراه بحقّ الملكيّة.)
        """
        self.assertFalse(is_privileged(self.emp1b))
        # يرى صفوفَ قسمه كلَّها (والسرّيُّ محجوبُ المحتوى لا الصفّ)، ولا يرى قسماً آخر.
        self.assertEqual(self.titles(self.emp1b), self.titles(self.emp1))
        self.assertNotIn('كتاب العقود', self.titles(self.emp1b))

    # ── التوافق ──
    def test_user_without_profile_falls_back_to_own_books(self):
        """سلوكُ ما قبل الأقسام — كي لا ينكسر تنصيبٌ لم تُبذَر أقسامُه."""
        own = _book('كتابٌ يتيم', self.orphan, None)
        self.assertEqual(self.titles(self.orphan), {'كتابٌ يتيم'})
        self.assertTrue(can_view_book(own, self.orphan))

    def test_soft_deleted_stays_hidden(self):
        self.b1.is_deleted = True
        self.b1.save(update_fields=['is_deleted'])
        self.assertNotIn('كتاب المتابعة', self.titles(self.emp1))

    # ── تطابق الدالّتين ──
    def test_predicate_matches_queryset(self):
        for user in (self.emp1, self.emp1b, self.head1, self.emp2, self.root):
            visible = self.titles(user)
            for book in Book.objects.all():
                self.assertEqual(
                    can_view_book(book, user), book.title in visible,
                    f'اختلفت الدالّتان على {book.title} للمستخدم {user.username}',
                )


class ForeignBookIsUnreachableTests(TestCase):
    """المسارات التي كانت تكرّر القاعدة يدويّاً — كلّها تُغلق."""

    def setUp(self):
        d1 = Department.objects.create(name='أ', code='ق-أ')
        d2 = Department.objects.create(name='ب', code='ق-ب')
        self.alice = User.objects.create_user('a2', password='pw-a2-11111')
        UserProfile.objects.create(user=self.alice, department=d1)
        bob = User.objects.create_user('b2', password='pw-b2-11111')
        UserProfile.objects.create(user=bob, department=d2)
        self.book_b = _book('كتاب بوب', bob, d2)
        self.client.force_login(self.alice)

    def _denied(self, resp):
        self.assertIn(resp.status_code, (302, 403, 404),
                      f'مسارٌ سمح بكتاب قسمٍ آخر: {resp.status_code}')

    def test_detail_page(self):
        self._denied(self.client.get(f'/books/{self.book_b.pk}/'))

    def test_edit_page(self):
        self._denied(self.client.get(f'/books/{self.book_b.pk}/edit/'))

    def test_report_page(self):
        self._denied(self.client.get(f'/books/{self.book_b.pk}/report/'))

    def test_delete_api(self):
        self._denied(self.client.post(f'/books/api/book/{self.book_b.pk}/delete/'))

    def test_list_excludes_other_departments(self):
        resp = self.client.get('/books/unified/')
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'كتاب بوب')
