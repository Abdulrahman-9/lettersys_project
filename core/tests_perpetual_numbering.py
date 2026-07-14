# -*- coding: utf-8 -*-
"""اختبارات الترقيم الدائم + كشف التكرار.

يغطّي:
  • BookSequence: format_number بلا سنة + consume_next لا يتصفّر.
  • Book._parse_year_prefix والخصائص: تمييز التاريخي/الدائم + فخّ reg=2 (20200).
  • apply_search_filters: إيجاد التسلسل في الصيغتين.
  • find_duplicate_candidates + حارس الحفظ (4/4 منع، 3/4 تنبيه).
"""
from datetime import date

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from .models import Book, BookSequence, Entity
from .views.helpers import apply_search_filters
from .views.books_helpers import find_duplicate_candidates


class BookSequenceFormatTests(TestCase):
    def test_format_number_drops_year(self):
        # الصيغة الدائمة: {R}{NNNN} بلا سنة
        self.assertEqual(BookSequence.format_number('incoming_internal', 89), '10089')
        self.assertEqual(BookSequence.format_number('incoming_external', 5), '20005')
        self.assertEqual(BookSequence.format_number('outgoing_external', 1234), '41234')

    def test_format_number_numberless(self):
        self.assertEqual(BookSequence.format_number('incoming_internal', 3, numberless=True), '00003')

    def test_format_number_ignores_year_arg(self):
        # المعامل year مُهمَل (توافق رجعي) — لا يظهر في الناتج
        self.assertEqual(BookSequence.format_number('incoming_internal', 89, year=2026), '10089')

    def test_consume_next_is_perpetual(self):
        r1 = BookSequence.consume_next('incoming_internal')
        r2 = BookSequence.consume_next('incoming_internal')
        self.assertEqual(r1['number'] + 1, r2['number'])
        self.assertEqual(r2['formatted'], f"1{r2['number']:04d}")

    def test_seed_high_then_continue(self):
        # يحاكي بذرة تسلسل عالية (كتب 2026 مُرحَّلة) → يُكمل لا يتصفّر
        seq, _ = BookSequence.objects.update_or_create(
            kind='outgoing_internal', defaults={'next_number': 2470, 'year': 2026})
        r = BookSequence.consume_next('outgoing_internal')
        self.assertEqual(r['number'], 2470)
        self.assertEqual(r['formatted'], '32470')
        seq.refresh_from_db()
        self.assertEqual(seq.next_number, 2471)


class BookNumberParseTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u', password='p')

    def _book(self, our_number, kind='incoming_internal', **kw):
        return Book.objects.create(our_number=our_number, title='ع', kind=kind,
                                   created_by=self.user, **kw)

    def test_historical_9char(self):
        b = self._book('202610089')
        self.assertEqual(b.our_number_year, '2026')
        self.assertEqual(b.our_number_register_label, 'وارد داخلي')
        self.assertEqual(b.our_number_sequence, '89')

    def test_historical_8char_no_register(self):
        b = self._book('20260089')
        self.assertEqual(b.our_number_year, '2026')
        self.assertEqual(b.our_number_sequence, '89')

    def test_perpetual_basic(self):
        b = self._book('10089')
        self.assertEqual(b.our_number_year, '')                 # بلا سنة
        self.assertEqual(b.our_number_register_label, 'وارد داخلي')
        self.assertEqual(b.our_number_sequence, '89')

    def test_perpetual_reg2_year_lookalike(self):
        # الفخّ الحرج: 20200 (سجل 2، تسلسل 200) يجب ألّا يُقرأ كسنة 2020
        b = self._book('20200', kind='incoming_external')
        self.assertEqual(b.our_number_year, '')
        self.assertEqual(b.our_number_register_label, 'وارد خارجي')
        self.assertEqual(b.our_number_sequence, '200')

    def test_perpetual_numberless(self):
        b = self._book('00003')
        self.assertTrue(b.our_number_is_numberless)
        self.assertEqual(b.our_number_year, '')

    def test_perpetual_large_sequence(self):
        b = self._book('112345')   # سجل 1، تسلسل 12345
        self.assertEqual(b.our_number_year, '')
        self.assertEqual(b.our_number_sequence, '12345')


class SearchFormatTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u', password='p')
        mk = lambda o, k='incoming_internal': Book.objects.create(
            our_number=o, title='ع', kind=k, created_by=self.user)
        self.hist = mk('202610089')      # تاريخي: تسلسل 89
        self.perp = mk('10090')          # دائم: تسلسل 90
        self.perp89 = mk('10089')        # دائم: تسلسل 89 (نفس تسلسل التاريخي)
        self.ext = mk('20200', 'incoming_external')  # دائم reg2 تسلسل 200

    def _search(self, text):
        return set(apply_search_filters(Book.objects.all(), text).values_list('our_number', flat=True))

    def test_search_sequence_finds_both_formats(self):
        res = self._search('89')
        self.assertIn('202610089', res)   # تاريخي
        self.assertIn('10089', res)       # دائم
        self.assertNotIn('10090', res)

    def test_search_perpetual_only_sequence(self):
        res = self._search('90')
        self.assertIn('10090', res)
        self.assertNotIn('10089', res)

    def test_search_reg2_perpetual(self):
        res = self._search('200')
        self.assertIn('20200', res)

    def test_search_year_finds_historical(self):
        res = self._search('2026')
        self.assertIn('202610089', res)


class SearchRankingTests(TestCase):
    """الترتيب تحت الترقيم الدائم: المطابقة التامّة أولاً، ثم الأحدث (الدائم فوق التاريخي)."""

    def setUp(self):
        self.user = User.objects.create_user('u', password='p')
        # تسلسل 89 يتكرّر: تاريخي 2025 + دائم حالي 2026
        self.hist2025 = Book.objects.create(
            our_number='202510089', title='تاريخي', date=date(2025, 3, 1),
            kind='incoming_internal', created_by=self.user)
        self.perp = Book.objects.create(
            our_number='10089', title='حالي', date=date(2026, 6, 1),
            kind='incoming_internal', created_by=self.user)

    def _ordered(self, text):
        return list(apply_search_filters(Book.objects.all(), text)
                    .values_list('our_number', flat=True))

    def test_current_perpetual_ranks_above_historical(self):
        # البحث بالتسلسل «89» يُظهر الدائم الحالي (2026) قبل التاريخي (2025)
        res = self._ordered('89')
        self.assertEqual(res[0], '10089')
        self.assertIn('202510089', res)

    def test_exact_full_number_ranks_first(self):
        # كتابة رقم القيد الكامل يتصدّر حتى لو طابق «89» عدّة كتب
        res = self._ordered('202510089')
        self.assertEqual(res[0], '202510089')

    def test_our_number_ranks_above_sender_number(self):
        # السيناريو الحقيقي: البحث «512» — قيدنا (10512) يجب أن يعلو رقم الجهة (512)
        # حتى لو كانت كتب رقم-الجهة أحدث تاريخاً.
        ours = Book.objects.create(
            our_number='10512', title='قيدنا 512', date=date(2026, 1, 1),
            kind='incoming_internal', created_by=self.user)
        Book.objects.create(
            our_number='11717', sender_number='512', title='رقمهم أ',
            date=date(2026, 3, 29), kind='incoming_internal', created_by=self.user)
        Book.objects.create(
            our_number='11082', sender_number='512', title='رقمهم ب',
            date=date(2026, 2, 22), kind='incoming_internal', created_by=self.user)
        res = self._ordered('512')
        self.assertEqual(res[0], '10512')   # قيدنا أولاً رغم أنّ رقم-الجهة أحدث


class DuplicateDetectionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u', password='p')
        self.ent = Entity.objects.create(name='وزارة الصحة', etype='issuer')
        self.book = Book.objects.create(
            our_number='10001', title='طلب إجازة', kind='incoming_external',
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
        res = self._find(party_number='ص-999')   # الرقم مختلف → 3/4
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]['match_count'], 3)

    def test_two_of_four_not_reported(self):
        # عنوان وتاريخ مختلفان → 2/4 فقط (الجهة+الرقم) → لا يُبلَّغ
        res = self._find(title='عنوان آخر تماماً', cmp_date=date(2020, 1, 1))
        self.assertEqual(res, [])

    def test_excludes_self(self):
        res = self._find(exclude_id=self.book.id)
        self.assertEqual(res, [])

    def test_empty_number_not_counted_as_match(self):
        # رقم فارغ في الطرفين لا يُحتسب مطابقةً (يبقى 3/4 من العنوان+التاريخ+الجهة)
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
            our_number='20001', title='طلب تعيين', date=date(2026, 5, 1),
            sender_date=date(2026, 4, 20), sender_number='ص-77',
            kind='incoming_external', created_by=self.user)
        self.existing.issuing_entities.add(self.moi)

    def _payload(self, **over):
        p = {
            'book_number': '20500',           # رقم مختلف كي لا يتعارض DUPLICATE_NUMBER
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
        # لم يُنشأ كتاب جديد
        self.assertFalse(Book.objects.filter(our_number='20500').exists())

    def test_regular_user_cannot_override_full_duplicate(self):
        # حتى مع علَم التأكيد: غير المشرف لا يتجاوز 4/4 (يُفحَص في الخادم)
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
        # قيدنا = 512 (تاريخ أقدم)
        Book.objects.create(our_number='10512', title='قيدنا 512', date=date(2026, 1, 1),
                            kind='incoming_internal', created_by=self.admin)
        # رقم الجهة = 512 (تواريخ أحدث — كانت تتصدّر خطأً بفرز -date)
        Book.objects.create(our_number='11717', sender_number='512', title='رقمهم أ',
                            date=date(2026, 3, 29), kind='incoming_internal', created_by=self.admin)
        Book.objects.create(our_number='11082', sender_number='512', title='رقمهم ب',
                            date=date(2026, 2, 22), kind='incoming_internal', created_by=self.admin)

    def test_search_prioritizes_our_number_over_sender(self):
        r = self.client.get(reverse('api_unified_data'), {'q': '512', 'tab': 'all'})
        self.assertEqual(r.status_code, 200)
        books = r.json()['books']
        self.assertTrue(books)
        self.assertEqual(books[0]['our_number'], '10512')   # قيدنا أولاً
