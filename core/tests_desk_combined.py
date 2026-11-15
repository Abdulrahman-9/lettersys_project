"""الكشفُ الذكيّ (أمرُ المالك 2026-11-12): وحدةٌ واحدة ⟵ بطاقتُها كما كانت؛ عدّةُ وحدات ⟵ **كشفٌ واحد**،
الجهةُ فيه خليّةٌ في كلّ سطر وكلُّ مستلمٍ يوقّع سطرَه — ما يفعله مَن يفرّق البريد على الورق اليوم
اختصاراً للأوراق المطبوعة. و**متعهّدُ البريد الخارجيّ غيرُ التفريق الداخليّ**: كشفُه مستقلٌّ لا يُطوى فيه.
"""
from django.contrib.auth.models import User
from django.urls import reverse

from core.models import Book, BookReferral, Department
from core.tests_desk import DeskTestCase
from core.tests_desk_identity import sheet_of


class CombinedHandoverTests(DeskTestCase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.unit2 = Department.objects.create(name='شعبة التدقيق', code='ط-ش13/2', parent=cls.dept)
        cls.book2 = Book.objects.create(kind='incoming_internal', title='كتابُ التدقيق', created_by=cls.officer,
                                        department=cls.dept, our_number='2440')
        cls.book3 = Book.objects.create(kind='incoming_external', title='كتابٌ ثانٍ للموازنة', created_by=cls.officer,
                                        department=cls.dept, our_number='2441')
        for book, unit in ((cls.book, cls.unit), (cls.book2, cls.unit2), (cls.book3, cls.unit)):
            BookReferral.objects.create(book=book, from_department=cls.dept, to_department=unit, due_date=cls.due)
        cls.outgoing = Book.objects.create(kind='outgoing_external', title='صادرٌ للمتعهّد', created_by=cls.officer,
                                           department=cls.dept, our_number='91')

    def setUp(self):
        self.client.force_login(self.officer)

    def test_one_sheet_is_offered_when_several_units_wait(self):
        prep = self.client.get(reverse('desk_handover'))
        self.assertContains(prep, 'value="all"')
        self.assertContains(prep, 'to=all"')
        self.assertEqual(prep.context['combined_count'], 3)

    def test_the_unit_is_a_cell_and_every_receiver_signs_his_row(self):
        r = self.client.get(reverse('desk_handover'), {'to': 'all'})
        self.assertTrue(r.context['is_combined'])
        targets = [row['target'] for row in r.context['rows']]
        self.assertEqual(len(targets), 3)
        self.assertEqual(targets, sorted(targets))          # سطورُ كلّ وحدةٍ متجاورة
        self.assertEqual(set(targets), {str(self.unit), str(self.unit2)})
        paper = sheet_of(r)
        self.assertIn('<th scope="col">الجهة المستلِمة</th>', paper)
        self.assertEqual(paper.count('class="ho-target"'), 3)
        self.assertEqual(paper.count('class="ho-unit-start"'), 2)
        self.assertIn('ho-sign-note', paper)
        self.assertEqual(paper.count('<span>الاسم</span><i></i>'), 1)      # المُسلِّمُ وحدَه؛ المستلمون في سطورهم
        self.assertNotIn('desk-kind-group', paper)

    def test_a_single_unit_keeps_its_card(self):
        r = self.client.get(reverse('desk_handover'), {'to': self.unit.pk})
        self.assertFalse(r.context['is_combined'])
        self.assertEqual(len(r.context['rows']), 2)
        paper = sheet_of(r)
        self.assertNotIn('ho-target', paper)
        self.assertNotIn('c-target', paper)
        self.assertEqual(paper.count('<span>الاسم</span><i></i>'), 2)

    def test_all_with_one_waiting_unit_is_that_units_sheet(self):
        BookReferral.objects.filter(to_department=self.unit2).delete()
        prep = self.client.get(reverse('desk_handover'))
        self.assertNotContains(prep, 'value="all"')
        r = self.client.get(reverse('desk_handover'), {'to': 'all'})
        self.assertFalse(r.context['is_combined'])
        self.assertEqual(r.context['chosen'], self.unit)

    def test_the_courier_is_never_folded_into_the_internal_sheet(self):
        prep = self.client.get(reverse('desk_handover'))
        self.assertEqual(prep.context['courier_count'], 1)
        self.assertContains(prep, 'value="courier"')
        combined = self.client.get(reverse('desk_handover'), {'to': 'all'})
        self.assertFalse(combined.context['is_courier'])
        self.assertNotIn('صادرٌ للمتعهّد', sheet_of(combined))
        courier = self.client.get(reverse('desk_handover'), {'to': 'courier'})
        self.assertTrue(courier.context['is_courier'])
        self.assertFalse(courier.context['is_combined'])
        self.assertIn('صادرٌ للمتعهّد', sheet_of(courier))

    # مراجعةُ فيبل 11-15: الكشفُ يحمل ما فرّقه قسمي وحدَه، فيطابق عددُ القائمة سطورَ الورقة.

    def test_another_departments_referral_to_the_same_unit_stays_off_my_sheet(self):
        theirs = Book.objects.create(kind='incoming_external', title='إحالةُ قسمٍ آخر', created_by=self.officer,
                                     department=self.other, our_number='77')
        BookReferral.objects.create(book=theirs, from_department=self.other, to_department=self.unit, due_date=self.due)
        admin = User.objects.create_superuser('desk-rows-admin', password='pw-desk-1115')
        self.client.force_login(admin)
        for to in (self.unit.pk, 'all'):
            with self.subTest(to=to):
                r = self.client.get(reverse('desk_handover'), {'department': self.dept.pk, 'to': to})
                self.assertNotIn('إحالةُ قسمٍ آخر', sheet_of(r))
        prep = self.client.get(reverse('desk_handover'), {'department': self.dept.pk})
        combined = self.client.get(reverse('desk_handover'), {'department': self.dept.pk, 'to': 'all'})
        self.assertEqual(prep.context['combined_count'], len(combined.context['rows']))

    def test_no_login_name_for_the_assignee(self):
        BookReferral.objects.filter(book=self.book).update(assignee=self.plain)
        r = self.client.get(reverse('desk_handover'), {'to': self.unit.pk})
        self.assertNotIn(self.plain.username, sheet_of(r))
