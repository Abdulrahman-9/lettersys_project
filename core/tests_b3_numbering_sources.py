# -*- coding: utf-8 -*-
"""(ب)3‑2 — أيُّ دفترٍ يُستهلك عدّادُه؟ (2026‑11‑11)

قرارُ المالك 2026‑11‑02: «الإدخالُ في ديوان القسم فقط». الشعبةُ والوحدةُ تحت أبٍ لا تمسكان
سجلّاً (``Department.holds_register``) فتعملان على سجلّ أقرب أبٍ يمسكه — في العرض والحجز والحفظ
والقيد معاً، من مصدرٍ واحد (``BookSequence.resolve_department``). والقراءةُ لا تُنشئ عدّاداً،
والقيدُ عندنا لا يقبل قسماً يختاره الطلب.
"""
import json

from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from core.models import (Book, BookRegistration, BookSequence, Department, Entity, UserCapabilityOverride,
                         UserProfile)
from core.registration_service import ledger_department, register_book_here, register_here_ledger
from core.roles import ENTRY_GROUP_NAME, ensure_role_groups

KIND = 'incoming_external'


class NumberingSourcesCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_role_groups()
        cls.dept = Department.objects.create(name='قسم الترقيم', code='تر1')
        cls.unit = Department.objects.create(name='شعبة الترقيم', code='تر1ش', parent=cls.dept, holds_register=False)
        cls.sub = Department.objects.create(name='وحدة الترقيم', code='تر1شو', parent=cls.unit, holds_register=False)
        cls.other = Department.objects.create(name='قسم آخر للترقيم', code='تر2')
        cls.entry = cls.person('n_entry', cls.dept)
        cls.unit_entry = cls.person('n_unitentry', cls.unit)
        cls.sub_entry = cls.person('n_subentry', cls.sub)
        cls.entity = Entity.objects.create(name='جهة الترقيم')

    @classmethod
    def person(cls, name, dept):
        user = User.objects.create_user(name, password='pw-num-1111')
        UserProfile.objects.update_or_create(user=user, defaults={'department': dept})
        user.groups.add(Group.objects.get(name=ENTRY_GROUP_NAME))
        return user

    def setUp(self):
        cache.clear()


class RegisterHolderTests(NumberingSourcesCase):
    def test_the_holder_is_self_or_the_nearest_parent_that_holds(self):
        self.assertEqual(self.dept.register_holder(), self.dept)
        self.assertEqual(self.unit.register_holder(), self.dept)
        self.assertEqual(self.sub.register_holder(), self.dept)

    def test_no_holder_up_the_tree_is_none_even_in_a_cycle(self):
        Department.objects.filter(pk=self.dept.pk).update(holds_register=False, parent=self.sub)
        unit = Department.objects.get(pk=self.unit.pk)
        self.assertIsNone(unit.register_holder())

    def test_every_counter_path_resolves_to_the_holder(self):
        self.assertEqual(BookSequence.resolve_department(self.sub), self.dept)
        self.assertEqual(BookSequence.resolve_department(self.dept), self.dept)
        self.assertEqual(BookSequence.resolve_department(None),
                         Department.objects.filter(is_active=True, holds_register=True).order_by('id').first())


    def test_the_default_is_the_first_active_holder(self):
        first = Department.objects.filter(is_active=True).order_by('id').first()
        Department.objects.filter(pk=first.pk).update(holds_register=False)
        resolved = BookSequence.resolve_department(None)
        self.assertNotEqual(resolved, first)
        self.assertTrue(resolved.holds_register)


class ReadingDoesNotCreateTests(NumberingSourcesCase):
    def test_get_next_reads_without_creating_a_row(self):
        before = BookSequence.objects.count()
        for dept in (self.dept, self.unit, self.sub):
            with self.subTest(dept=dept.code):
                self.assertEqual(BookSequence.get_next(KIND, department=dept)['number'], 1)
        self.assertEqual(BookSequence.objects.count(), before)

    def test_consuming_from_a_unit_moves_the_holders_counter(self):
        issued = BookSequence.consume_next(KIND, department=self.unit)
        self.assertEqual(issued['number'], 1)
        self.assertTrue(BookSequence.objects.filter(kind=KIND, department=self.dept).exists())
        self.assertFalse(BookSequence.objects.filter(department__in=[self.unit, self.sub]).exists())
        self.assertEqual(BookSequence.get_next(KIND, department=self.sub)['number'], 2)

    def test_the_entry_desk_reads_without_creating(self):
        before = BookSequence.objects.count()
        self.client.force_login(self.unit_entry)
        self.assertEqual(self.client.get('/books/extract/smart-desktop/').status_code, 200)
        self.assertEqual(BookSequence.objects.count(), before)


class SavingEntersTheHoldersRegisterTests(NumberingSourcesCase):
    def payload(self, title):
        # الترقيمُ التلقائيّ كما ترسله صفحةُ الإدخال: الخادمُ يستهلك العدّادَ ويتجاهل النصّ.
        return {'title': title, 'date': '2026-11-11', 'kind': KIND, 'document_type': 'كتاب',
                'issuing_entity_id': str(self.entity.id), 'auto_number': 'true', 'our_number': 'تلقائي'}

    def test_a_unit_clerk_enters_into_the_holders_register(self):
        self.client.force_login(self.unit_entry)
        response = self.client.post(reverse('save-book-api'), self.payload('كتابٌ من الشعبة'))
        self.assertEqual(response.status_code, 201, response.content[:300])
        book = Book.objects.get(title='كتابٌ من الشعبة')
        self.assertEqual(book.department, self.dept)
        self.assertFalse(BookSequence.objects.filter(department__in=[self.unit, self.sub]).exists())

        self.client.force_login(self.entry)
        self.client.post(reverse('save-book-api'), self.payload('كتابٌ من الديوان'))
        diwan = Book.objects.get(title='كتابٌ من الديوان')
        self.assertEqual(diwan.department, self.dept)
        self.assertEqual(int(diwan.our_number), int(book.our_number) + 1)   # عدّادٌ واحدٌ للدفتر


class RegisterHereLedgerTests(NumberingSourcesCase):
    def setUp(self):
        super().setUp()
        self.book = Book.objects.create(kind='outgoing_internal', title='صادرٌ للقيد', created_by=self.entry,
                                        department=self.dept)

    def test_the_ledger_is_the_holders_for_a_unit_clerk(self):
        self.assertEqual(ledger_department(self.unit_entry), self.dept)
        self.assertEqual(ledger_department(self.sub_entry), self.dept)
        # كتابٌ تفتحه الوحدةُ الفرعيّة (كتابُ القسم الأب لا تفتحه — ذلك نطاقٌ لا دفتر)
        sub_book = Book.objects.create(kind='outgoing_internal', title='صادرُ الوحدة', created_by=self.sub_entry,
                                       department=self.sub)
        self.assertEqual(register_here_ledger(sub_book, self.sub_entry), self.dept)

    def test_the_service_records_the_holder_even_when_handed_a_unit(self):
        row = register_book_here(self.book, self.unit, by=self.entry)
        self.assertEqual(row.department, self.dept)

    def test_the_request_cannot_choose_whose_counter_is_consumed(self):
        self.client.force_login(self.entry)
        response = self.client.post(reverse('api_register_here', args=[self.book.pk]),
                                    data=json.dumps({'department': self.other.pk}),
                                    content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertEqual(BookRegistration.objects.get(book=self.book).department, self.dept)
        self.assertFalse(BookSequence.objects.filter(department=self.other).exists())

    def test_without_enter_the_ledger_is_none(self):
        UserCapabilityOverride.objects.create(user=self.unit_entry, capability='book.enter', allowed=False)
        self.assertIsNone(register_here_ledger(self.book, User.objects.get(pk=self.unit_entry.pk)))


class EdgesOfTheSingleSourceTests(NumberingSourcesCase):
    """حدودٌ سمّاها فيبل: كلُّ مسارٍ يسأل المصدرَ نفسَه، وما لا ماسكَ له يُرفض باسمه."""

    def setUp(self):
        super().setUp()
        self.book = Book.objects.create(kind='outgoing_internal', title='صادرٌ للحدود', created_by=self.entry,
                                        department=self.dept)

    def payload(self, title, **extra):
        return {'title': title, 'date': '2026-11-11', 'kind': KIND, 'document_type': 'كتاب',
                'issuing_entity_id': str(self.entity.id), 'auto_number': 'true', 'our_number': 'تلقائي',
                **extra}

    def post_json(self, url, payload):
        return self.client.post(url, data=json.dumps(payload), content_type='application/json')

    def test_no_button_once_the_holder_has_registered_it(self):
        """كتابٌ يفتحه كاتبُ الشعبة، قيّده الديوانُ في دفتره: لا زرَّ للشعبة (كان يُسأل دفترُها هي فيظهر
        الزرُّ ثمّ يرفضه قيدُ التفرّد)."""
        book = Book.objects.create(kind='outgoing_internal', title='صادرُ الشعبة', created_by=self.unit_entry,
                                   department=self.unit)
        clerk = User.objects.get(pk=self.unit_entry.pk)
        self.assertEqual(register_here_ledger(book, clerk), self.dept)
        register_book_here(book, self.dept, by=self.entry)
        self.assertIsNone(register_here_ledger(book, clerk))

    def test_a_user_without_a_department_cannot_name_one(self):
        nobody = User.objects.create_user('n_nodept', password='pw-num-1111')
        nobody.groups.add(Group.objects.get(name=ENTRY_GROUP_NAME))
        book = Book.objects.create(kind='outgoing_internal', title='بلا قسم', created_by=nobody)
        self.client.force_login(nobody)
        response = self.post_json(reverse('api_register_here', args=[book.pk]), {'department': self.other.pk})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(BookRegistration.objects.filter(book=book).exists())
        self.assertFalse(BookSequence.objects.filter(department=self.other).exists())

    def test_a_unit_reservation_is_the_holders_and_the_save_spends_it(self):
        self.client.force_login(self.unit_entry)
        response = self.post_json('/books/api/reservation/reserve/', {'kind': KIND})
        self.assertEqual(response.status_code, 200, response.content[:300])
        reservation = response.json()['reservation']
        self.assertEqual(reservation['department_id'], self.dept.pk)
        response = self.client.post(reverse('save-book-api'),
                                    self.payload('محجوزٌ من الشعبة', reservation_id=str(reservation['id']),
                                                 our_number=reservation['formatted'], auto_number='false'))
        self.assertEqual(response.status_code, 201, response.content[:300])
        book = Book.objects.get(title='محجوزٌ من الشعبة')
        self.assertEqual((book.department, book.our_number), (self.dept, reservation['formatted']))

    def test_a_unit_manual_number_already_in_the_holders_register_is_a_409(self):
        Book.objects.create(kind=KIND, title='قائمٌ في الدفتر', created_by=self.entry, department=self.dept,
                            our_number='77')
        self.client.force_login(self.unit_entry)
        response = self.client.post(reverse('save-book-api'),
                                    self.payload('مكرّرٌ من الشعبة', our_number='77', auto_number='false'))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['error_code'], 'DUPLICATE_NUMBER')

    def test_a_tree_without_a_holder_is_refused_not_defaulted(self):
        counters = list(BookSequence.objects.values_list('pk', 'next_number'))   # بذرةُ 0064 للافتراضيّ
        Department.objects.filter(pk=self.dept.pk).update(holds_register=False)
        unit_entry = User.objects.get(pk=self.unit_entry.pk)
        self.assertIsNone(ledger_department(unit_entry))
        with self.assertRaises(ValidationError):
            BookSequence.resolve_department(Department.objects.get(pk=self.unit.pk))
        before = Book.all_objects.count()
        self.client.force_login(unit_entry)
        response = self.client.post(reverse('save-book-api'), self.payload('بلا ماسك'))
        self.assertEqual((response.status_code, response.json()['error_code']), (400, 'NO_REGISTER'))
        self.assertEqual(Book.all_objects.count(), before)
        for url in ('/books/api/reservation/status/?kind=' + KIND, '/books/api/next-number/?kind=' + KIND):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).json()['error_code'], 'NO_REGISTER')
        self.assertEqual(self.post_json('/books/api/reservation/reserve/', {'kind': KIND}).status_code, 400)
        self.assertEqual(self.client.get('/books/extract/smart-desktop/').status_code, 200)
        self.assertEqual(list(BookSequence.objects.values_list('pk', 'next_number')), counters)   # ولا عدّادُ الافتراضيّ

    def test_the_unit_clerk_sees_but_does_not_own_what_he_enters(self):
        """«الإدخالُ في الديوان فقط»: الشذوذُ يُصحَّح بنقل الحساب (تقريرُ الأدوار) لا بتوسيع الملكيّة."""
        from core.scoping import _owns_book, can_view_book

        book = Book.objects.create(kind=KIND, title='أدخله كاتبُ الشعبة', created_by=self.unit_entry,
                                   department=self.dept)
        clerk = User.objects.get(pk=self.unit_entry.pk)
        self.assertFalse(_owns_book(book, clerk))
        self.assertTrue(can_view_book(book, clerk))
