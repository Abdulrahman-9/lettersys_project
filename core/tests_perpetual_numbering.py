# -*- coding: utf-8 -*-
"""اختبارات السلسلة اللانهائية + العرض + البحث + كشف التكرار.

القاعدة المُختبَرة هنا (قرار المالك): سلسلةٌ واحدة لا نهائية أساسها أرقام 2026
بلا تصفير سنوي، وبيانات 2025 وما قبلها موسومةٌ بسنة إضافتها، ولا بادئة سجلّ في
الرقم إطلاقاً. نحو الأرقام نفسه مُثبَّت في `core/tests_numbering.py`؛ هذا الملف
يُثبّت **الطبقات فوقه**: العدّاد، وخصائص العرض، والبحث، والفرز، وحارس التكرار.
"""
from datetime import date

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from .models import Book, BookSequence, Entity
from .views.filter_helpers import BookSortEngine
from .views.helpers import apply_search_filters
from .views.books_helpers import find_duplicate_candidates


class BookSequenceFormatTests(TestCase):
    def test_format_number_is_bare(self):
        # لا بادئة سجلّ ولا سنة — الرقم كما يُكتب على الورق
        self.assertEqual(BookSequence.format_number('incoming_internal', 89), '89')
        self.assertEqual(BookSequence.format_number('incoming_external', 5), '5')
        self.assertEqual(BookSequence.format_number('outgoing_internal', 1234), '1234')

    def test_numberless_is_empty_not_a_number(self):
        # «بلا رقم» تعني لا رقم فعلاً — لا '0NNNN'
        self.assertEqual(BookSequence.format_number('incoming_internal', 3, numberless=True), '')

    def test_format_number_ignores_year_arg(self):
        self.assertEqual(BookSequence.format_number('incoming_internal', 89, year=2026), '89')

    def test_consume_next_is_perpetual(self):
        r1 = BookSequence.consume_next('incoming_internal')
        r2 = BookSequence.consume_next('incoming_internal')
        self.assertEqual(r1['number'] + 1, r2['number'])
        self.assertEqual(r2['formatted'], str(r2['number']))

    def test_numberless_does_not_consume_the_counter(self):
        # الفجوة التي كانت: كتابٌ بلا رقم يبتلع رقماً لا يظهر على أي ورقة
        BookSequence.objects.update_or_create(
            kind='incoming_internal', defaults={'next_number': 2433, 'year': 2026})
        out = BookSequence.consume_next('incoming_internal', numberless=True)
        self.assertEqual(out['formatted'], '')
        self.assertEqual(
            BookSequence.objects.get(kind='incoming_internal').next_number, 2433)

    def test_seed_high_then_continue(self):
        # أساس السلسلة من بيانات 2026 (مثل 2433) → يُكمل ولا يتصفّر
        seq, _ = BookSequence.objects.update_or_create(
            kind='outgoing_internal', defaults={'next_number': 455, 'year': 2026})
        r = BookSequence.consume_next('outgoing_internal')
        self.assertEqual(r['number'], 455)
        self.assertEqual(r['formatted'], '455')
        seq.refresh_from_db()
        self.assertEqual(seq.next_number, 456)


class BookNumberDisplayTests(TestCase):
    """خصائص العرض — كلّها واجهةٌ رفيعة فوق `core/numbering.py`."""

    def setUp(self):
        self.user = User.objects.create_user('u', password='p')

    def _book(self, our_number, kind='incoming_internal', **kw):
        return Book.objects.create(our_number=our_number, title='ع', kind=kind,
                                   created_by=self.user, **kw)

    def test_series_number_shows_bare_without_tag(self):
        b = self._book('2433')
        self.assertEqual(b.our_number_sequence, '2433')
        self.assertEqual(b.our_number_year, '')          # السلسلة الجارية بلا وسم
        self.assertFalse(b.our_number_is_numberless)

    def test_tagged_number_shows_bare_with_year_tag(self):
        # المخزَّن '20250825' يُعرض «825» ووسمه «2025» منفصلاً
        b = self._book('20250825')
        self.assertEqual(b.our_number_sequence, '825')
        self.assertEqual(b.our_number_year, '2025')

    def test_old_ledger_years_are_tagged_too(self):
        b = self._book('20070825')
        self.assertEqual(b.our_number_sequence, '825')
        self.assertEqual(b.our_number_year, '2007')

    def test_base_year_prefix_is_not_a_tag(self):
        # الفخّ: '20260825' رقم سلسلةٍ لا وسم — سنة الأساس ليست وسماً
        b = self._book('20260825')
        self.assertEqual(b.our_number_year, '')
        self.assertEqual(b.our_number_sequence, '20260825')

    def test_short_number_is_never_read_as_a_year(self):
        # '2025' وحده تسلسلٌ لا سنة (اشتراط الطول ≥ 8 للوسم)
        b = self._book('2025')
        self.assertEqual(b.our_number_year, '')
        self.assertEqual(b.our_number_sequence, '2025')

    def test_numberless_is_empty_field(self):
        b = self._book('')
        self.assertTrue(b.our_number_is_numberless)
        self.assertEqual(b.our_number_sequence, '')
        self.assertIn('بلا رقم', b.our_number_explained)

    def test_training_number_is_outside_the_series(self):
        b = self._book('T57')
        self.assertTrue(b.our_number_is_training)
        self.assertEqual(b.our_number_sequence, 'T57')
        self.assertIn('تدريب', b.our_number_explained)

    def test_register_label_comes_from_kind_not_from_the_number(self):
        b = self._book('825', kind='incoming_external')
        self.assertEqual(b.our_number_register_label, 'وارد خارجي')

    def test_explained_distinguishes_our_number_from_theirs(self):
        b = self._book('825')
        self.assertIn('رقمنا', b.our_number_explained)

    def test_explained_for_manual_kind_names_the_source(self):
        b = self._book('27189', kind='outgoing_external')
        self.assertIn('المدير العام', b.our_number_explained)


class SearchFormatTests(TestCase):
    """كتابة الرقم المجرّد تجده في كل صيغه المخزَّنة — ولا تجد ما يشبهه."""

    def setUp(self):
        self.user = User.objects.create_user('u', password='p')
        mk = lambda o, k='incoming_internal': Book.objects.create(
            our_number=o, title='ع', kind=k, created_by=self.user)
        self.cur = mk('825')             # السلسلة الجارية
        self.y25 = mk('20250825')        # موسوم 2025 — نفس الرقم
        self.y07 = mk('20070825')        # موسوم 2007 — نفس الرقم
        self.near1 = mk('8250')          # ليس 825
        self.near2 = mk('1825')          # ليس 825
        self.other = mk('826')

    def _search(self, text):
        return set(apply_search_filters(Book.objects.all(), text)
                   .values_list('our_number', flat=True))

    def test_bare_number_finds_every_stored_shape(self):
        res = self._search('825')
        self.assertIn('825', res)
        self.assertIn('20250825', res)
        self.assertIn('20070825', res)

    def test_bare_number_does_not_match_lookalikes(self):
        res = self._search('825')
        self.assertNotIn('8250', res)
        self.assertNotIn('1825', res)
        self.assertNotIn('826', res)

    def test_year_alone_finds_that_ledger(self):
        res = self._search('2025')
        self.assertIn('20250825', res)
        self.assertNotIn('20070825', res)

    def test_base_year_is_not_a_ledger_tag(self):
        # لا كتب موسومة بـ2026 — سنة الأساس بلا وسم
        self.assertNotIn('20250825', self._search('2026'))

    def test_training_number_findable_by_its_sequence(self):
        Book.objects.create(our_number='T57', title='تدريب',
                            kind='incoming_internal', created_by=self.user)
        self.assertIn('T57', self._search('57'))


class SearchRankingTests(TestCase):
    """الترتيب حين يتكرّر الرقم بين السلسلة الجارية والموسوم بسنته."""

    def setUp(self):
        self.user = User.objects.create_user('u', password='p')
        self.tagged = Book.objects.create(
            our_number='20250089', title='موسوم', date=date(2025, 3, 1),
            kind='incoming_internal', created_by=self.user)
        self.current = Book.objects.create(
            our_number='89', title='جارٍ', date=date(2026, 6, 1),
            kind='incoming_internal', created_by=self.user)

    def _ordered(self, text):
        return list(apply_search_filters(Book.objects.all(), text)
                    .values_list('our_number', flat=True))

    def test_current_series_ranks_above_tagged(self):
        res = self._ordered('89')
        self.assertEqual(res[0], '89')
        self.assertIn('20250089', res)

    def test_exact_full_number_ranks_first(self):
        res = self._ordered('20250089')
        self.assertEqual(res[0], '20250089')

    def test_our_number_ranks_above_sender_number(self):
        # السيناريو الحقيقي: البحث «512» — قيدنا يعلو رقم الجهة حتى لو كان أقدم
        Book.objects.create(
            our_number='512', title='قيدنا 512', date=date(2026, 1, 1),
            kind='incoming_internal', created_by=self.user)
        Book.objects.create(
            our_number='1717', sender_number='512', title='رقمهم أ',
            date=date(2026, 3, 29), kind='incoming_internal', created_by=self.user)
        Book.objects.create(
            our_number='1082', sender_number='512', title='رقمهم ب',
            date=date(2026, 2, 22), kind='incoming_internal', created_by=self.user)
        self.assertEqual(self._ordered('512')[0], '512')


class NumericSortTests(TestCase):
    """الفرز بالرقم رقميّ لا نصّيّ — وإلا جاء '10' قبل '9'."""

    def setUp(self):
        self.user = User.objects.create_user('u', password='p')
        for n in ('9', '10', '100', '20250009', '20259999'):
            Book.objects.create(our_number=n, title='ع', kind='incoming_internal',
                                date=date(2026, 1, 1), created_by=self.user)

    def _sorted(self, field):
        return list(BookSortEngine.apply_sort(Book.objects.all(), field)
                    .values_list('our_number', flat=True))

    def test_ascending_is_numeric_and_tagged_comes_first(self):
        # الموسوم بسنته أقدم زمنياً فيتقدّم، ثم السلسلة الجارية رقمياً
        self.assertEqual(self._sorted('our_number'),
                         ['20250009', '20259999', '9', '10', '100'])

    def test_descending_is_the_exact_mirror(self):
        self.assertEqual(self._sorted('-our_number'),
                         ['100', '10', '9', '20259999', '20250009'])


class DuplicateDetectionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u', password='p')
        self.ent = Entity.objects.create(name='وزارة الصحة', etype='issuer')
        self.book = Book.objects.create(
            our_number='1001', title='طلب إجازة', kind='incoming_external',
            sender_number='ص-500', sender_date=date(2026, 5, 1), created_by=self.user)
        self.book.issuing_entities.add(self.ent)

    def _find(self, **over):
        kw = dict(kind='incoming_external', title='طلب إجازة',
                  cmp_date=date(2026, 5, 1), party_number='ص-500',
                  party_entities=[self.ent])
        kw.update(over)
        return find_duplicate_candidates(**kw)

    def test_full_match_is_4of4(self):
        res = self._find()
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]['match_count'], 4)

    def test_three_of_four_when_number_differs(self):
        res = self._find(party_number='ص-999')
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]['match_count'], 3)

    def test_two_of_four_not_reported(self):
        res = self._find(title='عنوان آخر تماماً', cmp_date=date(2020, 1, 1))
        self.assertEqual(res, [])

    def test_excludes_self(self):
        res = self._find(exclude_id=self.book.id)
        self.assertEqual(res, [])

    def test_empty_number_not_counted_as_match(self):
        self.book.sender_number = ''
        self.book.save(update_fields=['sender_number'])
        res = self._find(party_number='')
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]['match_count'], 3)


class DuplicateGuardApiTests(TestCase):
    """حارس التكرار في save_book_api: 4/4 منع (تجاوز للمشرف فقط)، 3/4 تنبيه يتجاوزه الجميع."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user('owner', password='pass1234')
        self.admin = User.objects.create_superuser('boss', password='pass1234', email='b@t.com')
        self.moi = Entity.objects.create(name='وزارة الداخلية', etype='issuer', is_active=True)
        self.existing = Book.objects.create(
            our_number='2001', title='طلب تعيين', date=date(2026, 5, 1),
            sender_date=date(2026, 4, 20), sender_number='ص-77',
            kind='incoming_external', created_by=self.user)
        self.existing.issuing_entities.add(self.moi)

    def _payload(self, **over):
        p = {
            'book_number': '2500',            # رقم مختلف كي لا يتعارض DUPLICATE_NUMBER
            'title': 'طلب تعيين',
            'date': '2026-05-02',
            'sender_date': '2026-04-20',
            'sender_number': 'ص-77',
            'kind': 'incoming_external',
            'document_type': 'كتاب',
            'issuing_entity_id': str(self.moi.id),
        }
        p.update(over)
        return p

    def test_full_duplicate_blocked_for_regular_user(self):
        self.client.login(username='owner', password='pass1234')
        r = self.client.post(reverse('save-book-api'), self._payload())
        self.assertEqual(r.status_code, 409)
        data = r.json()
        self.assertEqual(data['error_code'], 'DUPLICATE_BOOK')
        self.assertFalse(data['can_override'])
        self.assertFalse(Book.objects.filter(our_number='2500').exists())

    def test_regular_user_cannot_override_full_duplicate(self):
        self.client.login(username='owner', password='pass1234')
        r = self.client.post(reverse('save-book-api'),
                             self._payload(confirm_duplicate='true'))
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()['error_code'], 'DUPLICATE_BOOK')

    def test_admin_overrides_full_duplicate(self):
        self.client.login(username='boss', password='pass1234')
        r = self.client.post(reverse('save-book-api'),
                             self._payload(confirm_duplicate='true'))
        self.assertEqual(r.status_code, 201)

    def test_similar_warns_then_confirm_saves(self):
        self.client.login(username='owner', password='pass1234')
        r = self.client.post(reverse('save-book-api'),
                             self._payload(sender_number='ص-999'))
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()['error_code'], 'SIMILAR_BOOK')
        r2 = self.client.post(reverse('save-book-api'),
                              self._payload(sender_number='ص-999', confirm_duplicate='true'))
        self.assertEqual(r2.status_code, 201)


class SearchListOrderingApiTests(TestCase):
    """تكامل: قائمة الكتب تحترم أولوية الصلة عند البحث (قيدنا قبل رقم الجهة)،
    ولا يطمسها فرز -date الافتراضي."""

    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_superuser('boss', password='pass1234', email='b@t.com')
        self.client.login(username='boss', password='pass1234')
        Book.objects.create(our_number='512', title='قيدنا 512', date=date(2026, 1, 1),
                            kind='incoming_internal', created_by=self.admin)
        Book.objects.create(our_number='1717', sender_number='512', title='رقمهم أ',
                            date=date(2026, 3, 29), kind='incoming_internal', created_by=self.admin)
        Book.objects.create(our_number='1082', sender_number='512', title='رقمهم ب',
                            date=date(2026, 2, 22), kind='incoming_internal', created_by=self.admin)

    def test_search_prioritizes_our_number_over_sender(self):
        r = self.client.get(reverse('api_unified_data'), {'q': '512', 'tab': 'all'})
        self.assertEqual(r.status_code, 200)
        books = r.json()['books']
        self.assertTrue(books)
        self.assertEqual(books[0]['our_number'], '512')
