"""
الترقيم لكلّ قسم — المرحلة أ/3 (قرار المالك: لكلّ قسمٍ دفتر ختمه).

كان العدّاد واحداً لكلّ نوعٍ على مستوى النظام (`kind` فريد)، وقيدُ التفرّد
`(our_number, kind)` عالميّاً — فقسمان لا يستطيعان إصدار الرقم نفسه ولو كان
لكلٍّ منهما دفترُه الورقيّ المستقلّ.
"""

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase

from core.models import Book, BookSequence, Department


class SequencePerDepartmentTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.d1 = Department.objects.create(name='المتابعة', code='ن-ش13')
        cls.d2 = Department.objects.create(name='العقود', code='ن-ش5')

    def test_each_department_has_its_own_counter(self):
        a = BookSequence.consume_next('incoming_internal', department=self.d1)
        b = BookSequence.consume_next('incoming_internal', department=self.d2)
        self.assertEqual(a['number'], b['number'], 'العدّادان تشاركا الرقم بدل أن يستقلّا')

    def test_counters_advance_independently(self):
        for _ in range(3):
            BookSequence.consume_next('incoming_internal', department=self.d1)
        self.assertEqual(BookSequence.get_next('incoming_internal', self.d1)['number'], 4)
        self.assertEqual(BookSequence.get_next('incoming_internal', self.d2)['number'], 1)

    def test_missing_department_falls_back_to_default(self):
        """المسارات القديمة لا تعرف القسم — تسقط إلى الافتراضيّ لا إلى خطأ."""
        info = BookSequence.get_next('incoming_internal')
        self.assertIsNotNone(info['number'])

    def test_numberless_still_consumes_nothing(self):
        before = BookSequence.get_next('incoming_internal', self.d1)['number']
        BookSequence.consume_next('incoming_internal', numberless=True, department=self.d1)
        self.assertEqual(BookSequence.get_next('incoming_internal', self.d1)['number'], before)


class UniquenessIsScopedToDepartmentTests(TestCase):
    """جوهرُ القرار: الرقم نفسه في قسمين مشروع، وتكراره داخل القسم ممنوع."""

    @classmethod
    def setUpTestData(cls):
        cls.d1 = Department.objects.create(name='المتابعة', code='ق-ش13')
        cls.d2 = Department.objects.create(name='العقود', code='ق-ش5')
        cls.user = User.objects.create_user('clerk', password='pw-clerk-111')

    def _book(self, dept, number='2433'):
        return Book.objects.create(kind='incoming_internal', title='كتاب',
                                   created_by=self.user, department=dept, our_number=number)

    def test_same_number_in_two_departments_is_allowed(self):
        self._book(self.d1)
        self._book(self.d2)   # لا يجوز أن يرمي
        self.assertEqual(Book.objects.filter(our_number='2433').count(), 2)

    def test_duplicate_inside_one_department_is_refused(self):
        self._book(self.d1)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._book(self.d1)

    def test_deleted_book_frees_its_number(self):
        """القيد ما زال يستثني المحذوف: موظّفٌ يصحّح خطأه بإعادة الرقم."""
        first = self._book(self.d1)
        first.is_deleted = True
        first.save(update_fields=['is_deleted'])
        self._book(self.d1)   # لا يجوز أن يرمي
        self.assertEqual(Book.all_objects.filter(our_number='2433').count(), 2)
