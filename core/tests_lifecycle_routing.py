"""قراراتُ دورة الكتاب (docs/LIFECYCLE_DECISIONS_2026-09-11.md) — الفرعُ feat/lifecycle-routing.

§5.1 الذكرُ يوجّه تلقائيّاً: كلُّ وحدةٍ مستلِمةٍ داخل قسم المتابعة تنال صفَّ «للعلم» عند
الحفظ؛ خارجَه فقط إن كان لها حساب؛ لا تكرارَ ولا حذف.
"""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import Book, BookReferral, Department, Entity, UserProfile
from core.referral_service import auto_route_from_receivers


class RoutingTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.dept = Department.objects.create(name='المتابعة', code='ر-ش13')
        cls.unit_reports = Department.objects.create(
            name='وحدة التقارير', code='ر-ش13/2', parent=cls.dept,
            entity=Entity.objects.create(name='وحدة التقارير'))
        cls.unit_budget = Department.objects.create(
            name='شعبة الموازنة', code='ر-ش13/1', parent=cls.dept,
            entity=Entity.objects.create(name='شعبة الموازنة'))
        cls.legal = Department.objects.create(
            name='القانوني', code='ر-ش7', entity=Entity.objects.create(name='القسم القانوني'))
        cls.ebs = Entity.objects.create(name='EBS')
        cls.clerk = User.objects.create_user('lclerk', password='pw-lclerk-11')
        UserProfile.objects.create(user=cls.clerk, department=cls.dept)

    def _book(self, **kw):
        b = Book.objects.create(kind='incoming_external', title='ك', created_by=self.clerk,
                                department=self.dept, **kw)
        b.issuing_entities.add(self.ebs)
        return b


class AutoRouteTests(RoutingTestCase):

    def test_every_receiving_unit_inside_the_department_gets_an_info_row(self):
        b = self._book()
        b.receiving_entities.set([self.unit_reports.entity, self.unit_budget.entity, self.ebs])
        rows = auto_route_from_receivers(b, by=self.clerk)
        self.assertEqual({r.to_department_id for r in rows}, {self.unit_reports.id, self.unit_budget.id})
        self.assertTrue(all(r.purpose == BookReferral.INFO and r.due_date is None for r in rows))
        self.assertEqual(b.history.filter(action='referral').count(), 1)

    def test_outside_department_only_when_it_has_an_account(self):
        b = self._book()
        b.receiving_entities.set([self.legal.entity])
        self.assertEqual(auto_route_from_receivers(b, by=self.clerk), [])
        u = User.objects.create_user('llegal', password='pw-llegal-11')
        UserProfile.objects.create(user=u, department=self.legal)
        rows = auto_route_from_receivers(b, by=self.clerk)
        self.assertEqual([r.to_department_id for r in rows], [self.legal.id])

    def test_idempotent_and_never_deletes(self):
        b = self._book()
        b.receiving_entities.set([self.unit_reports.entity])
        auto_route_from_receivers(b, by=self.clerk)
        auto_route_from_receivers(b, by=self.clerk)
        self.assertEqual(BookReferral.objects.filter(book=b).count(), 1)
        b.receiving_entities.clear()
        auto_route_from_receivers(b, by=self.clerk)
        self.assertEqual(BookReferral.objects.filter(book=b).count(), 1, 'التاريخُ لا يُكشط')

    def test_the_owner_department_itself_is_never_a_target(self):
        own = Entity.objects.create(name='قسم المتابعة')
        self.dept.entity = own; self.dept.save()
        b = self._book()
        b.receiving_entities.set([own])
        self.assertEqual(auto_route_from_receivers(b, by=self.clerk), [])

    def test_saving_through_the_api_routes(self):
        self.client.force_login(self.clerk)
        r = self.client.post(reverse('save-book-api'), {
            'kind': 'incoming_external', 'title': 'عبر الواجهة', 'our_number': '9001',
            'date': '2026-09-11', 'sender_number': 'EBS-1', 'sender_date': '2026-09-01',
            'issuing_entity_ids[]': [str(self.ebs.id)],
            'receiving_entity_ids[]': [str(self.unit_reports.entity_id)],
        })
        self.assertEqual(r.status_code, 201, r.content[:300])
        book = Book.objects.get(title='عبر الواجهة')
        self.assertTrue(BookReferral.objects.filter(book=book, to_department=self.unit_reports,
                                                    purpose=BookReferral.INFO).exists())
