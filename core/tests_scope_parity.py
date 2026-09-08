# -*- coding: utf-8 -*-
"""تطابقُ نصفَي قاعدة الرؤية — `can_view_book` مقابل `scope_books_for`.

**العيبُ الذي يحرسه هذا الملفّ وقع ثلاث مرّات**: يتّسع أحدُ النصفين ويُنسى
قرينُه، فيظهر الكتابُ في القائمة ويُرفض عند فتحه — أو الأسوأ، يُفتح ولا يظهر.
الحارسُ بنيويّ: مصفوفةُ حالاتٍ تُقارَن فيها الدالّتان صفّاً صفّاً، فأيُّ شقٍّ
جديدٍ يُضاف إلى أحدهما دون الآخر يسقط هنا.
"""

from django.contrib.auth.models import User
from django.test import TestCase

from core.models import Book, BookReferral, Department, Entity, UserProfile
from core.scoping import can_view_book, scope_books_for


class ScopeParityTests(TestCase):
    def setUp(self):
        self.boss = User.objects.create_superuser('root', 'r@x.co', 'pw')
        self.outsider = User.objects.create_user('out', 'o@x.co', 'pw')

        self.dept_ent = Entity.objects.create(name='قسم التطابق', code='ط.ق')
        self.dept = Department.objects.create(name='قسم التطابق', code='ط.ق',
                                              entity=self.dept_ent)
        self.unit_ent = Entity.objects.create(name='وحدة التطابق', code='ط.و')
        self.unit = Department.objects.create(name='وحدة التطابق', code='ط.و',
                                              entity=self.unit_ent,
                                              parent=self.dept)
        self.far = Department.objects.create(name='قسم بعيد', code='ط.ب')
        # مالكٌ محايدٌ لا مستخدمَ فيه: كتبُ التفريق والذكر يجب ألّا تُرى
        # بالملكيّة وإلّا لم يُقَس الشقُّ المقصود.
        self.neutral = Department.objects.create(name='قسم محايد', code='ط.ح')

        self.head = self._user('head', self.dept)
        self.worker = self._user('worker', self.unit)
        self.stranger = self._user('stranger', self.far)

        self.books = {
            'مملوكٌ للقسم': self._book('9001', department=self.dept),
            'مملوكٌ للوحدة': self._book('9002', department=self.unit),
            'مملوكٌ لقسمٍ بعيد': self._book('9003', department=self.far),
            'أنشأه الغريب': self._book('9004', department=self.far,
                                        created_by=self.outsider),
        }

        # مُفرَّقٌ إلى الوحدة (الشقُّ الثالث)
        referred = self._book('9005', department=self.neutral)
        BookReferral.objects.create(book=referred, from_department=self.neutral,
                                    to_department=self.unit,
                                    status=BookReferral.SENT, created_by=self.boss)
        self.books['مُفرَّقٌ إلى الوحدة'] = referred

        # ذُكرت فيه الوحدةُ وارداً (الشقُّ الرابع — الأضبارة)
        mentioned = self._book('9006', department=self.neutral)
        mentioned.receiving_entities.add(self.unit_ent)
        self.books['ذُكرت فيه الوحدة'] = mentioned

        # وذُكر فيه القسمُ صادراً
        issued = self._book('9007', department=self.neutral)
        issued.issuing_entities.add(self.dept_ent)
        self.books['ذُكر فيه القسم صادراً'] = issued

    def _user(self, name, department):
        user = User.objects.create_user(name, name + '@x.co', 'pw')
        UserProfile.objects.update_or_create(user=user,
                                             defaults={'department': department})
        return user

    def _book(self, number, *, department, created_by=None):
        return Book.objects.create(kind='incoming_external', title='ك ' + number,
                                   our_number=number, department=department,
                                   created_by=created_by or self.boss)

    def test_the_two_halves_agree_on_every_case(self):
        """المصفوفةُ كلُّها: صفٌّ لكلّ (مستخدم × كتاب)."""
        actors = {'رئيسُ القسم': self.head, 'موظّفُ الوحدة': self.worker,
                  'غريبٌ بقسم': self.stranger, 'بلا قسم': self.outsider,
                  'مديرُ النظام': self.boss}

        for who, user in actors.items():
            visible = set(scope_books_for(user, Book.objects.all())
                          .values_list('pk', flat=True))
            for label, book in self.books.items():
                self.assertEqual(
                    can_view_book(book, user), book.pk in visible,
                    msg='انفرجَ النصفان: %s ⟵ %s' % (who, label))

    def test_the_dossier_clause_is_actually_exercised(self):
        """الحارسُ لا يقيس شيئاً إن لم تُفعِّل الحالاتُ الشقَّ الرابع.

        بلا هذا التأكيد يبقى الملفُّ أخضرَ ولو حُذف شقُّ الذكر من الاثنين معاً.
        """
        mentioned = self.books['ذُكرت فيه الوحدة']

        self.assertTrue(can_view_book(mentioned, self.worker))
        self.assertFalse(can_view_book(mentioned, self.stranger))

    def test_the_tree_flows_down_not_up(self):
        """رئيسُ القسم يرى كتابَ وحدته، والوحدةُ لا ترى كتابَ الأمّ."""
        self.assertTrue(can_view_book(self.books['مملوكٌ للوحدة'], self.head))
        self.assertFalse(can_view_book(self.books['مملوكٌ للقسم'], self.worker))
