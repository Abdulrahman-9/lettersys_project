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
        kw.setdefault('title', 'ك')
        from datetime import date as _d
        kw.setdefault('date', _d(2026, 9, 11))
        b = Book.objects.create(kind='incoming_external', created_by=self.clerk,
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


class ActivateFollowupTests(RoutingTestCase):
    """§5.2 «فعِّل متابعة»: صفُّ «للعلم» يصير «للإجراء» بموعد؛ بلا موعدٍ يُرفض؛ المُقفلُ يُرفض؛
    غيرُ مالكِ المحتوى يُرفض. الصفُّ نفسُه لا صفٌّ جديد."""

    def _info_row(self):
        b = self._book()
        b.receiving_entities.set([self.unit_reports.entity])
        return b, auto_route_from_receivers(b, by=self.clerk)[0]

    def test_turns_the_same_row_into_action_with_a_due_date(self):
        from datetime import date
        from core.referral_service import activate_followup
        b, row = self._info_row()
        out = activate_followup(row, due_date=date(2026, 9, 30), by=self.clerk, margin='الردّ خلال أسبوع')
        self.assertEqual(out.pk, row.pk)
        self.assertEqual(out.purpose, BookReferral.ACTION)
        self.assertEqual(str(out.due_date), '2026-09-30')
        self.assertEqual(out.margin, 'الردّ خلال أسبوع')
        self.assertEqual(BookReferral.objects.filter(book=b).count(), 1)

    def test_rejects_missing_date_closed_row_and_non_owner(self):
        from datetime import date
        from django.core.exceptions import PermissionDenied, ValidationError
        from core.referral_service import activate_followup, mark_done
        b, row = self._info_row()
        with self.assertRaises(ValidationError):
            activate_followup(row, due_date=None, by=self.clerk)
        outsider = User.objects.create_user('lout', password='pw-lout-11')
        UserProfile.objects.create(user=outsider, department=self.legal)
        with self.assertRaises(PermissionDenied):
            activate_followup(row, due_date=date(2026, 9, 30), by=outsider)
        mark_done(row, by=self.clerk)
        with self.assertRaises(ValidationError):
            activate_followup(row, due_date=date(2026, 9, 30), by=self.clerk)

    def test_the_api_exposes_act_activate_and_the_page_shows_the_button(self):
        import json
        b, row = self._info_row()
        self.client.force_login(self.clerk)
        page = self.client.get(reverse('book_detail', args=[b.pk]))
        self.assertContains(page, f'data-followup-activate="{row.pk}"')
        self.assertContains(page, 'id="followupModal"')
        r = self.client.post(reverse('api_referral_action', args=[b.pk, row.pk]),
                             data=json.dumps({'act': 'activate', 'due_date': '2026-10-01'}),
                             content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content[:200])
        row.refresh_from_db()
        self.assertEqual(row.purpose, BookReferral.ACTION)
        page = self.client.get(reverse('book_detail', args=[b.pk]))
        self.assertNotContains(page, f'data-followup-activate="{row.pk}"')


class ReplyClosesReferralTests(RoutingTestCase):
    """§5.5 الجوابُ يُقفل الإحالة — من حواريّة الربط، وللجهة الخارجيّة بوارِدها."""

    def _distributed_to(self, target):
        from core.referral_service import distribute
        b = self._book()
        rows = distribute(b, [target], by=self.clerk, purpose=BookReferral.ACTION)
        return b, rows[0]

    def test_linking_as_reply_from_the_picker_closes_the_unit_commitment(self):
        import json
        b, row = self._distributed_to(self.unit_reports)
        reply = Book.objects.create(kind='outgoing_internal', title='جواب', created_by=self.clerk,
                                    department=self.unit_reports, our_number='7')
        self.client.force_login(self.clerk)
        r = self.client.post(reverse('api_add_link', args=[reply.pk]),
                             data=json.dumps({'to_book': b.pk, 'relation': 'reply'}),
                             content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content[:200])
        row.refresh_from_db()
        self.assertEqual(row.status, BookReferral.DONE)
        self.assertIsNotNone(row.closed_by_link_id)

    def test_an_external_entity_is_closed_by_its_incoming_reply(self):
        from core.registration_service import register_reply
        b, row = self._distributed_to(self.ebs)
        reply = Book.objects.create(kind='incoming_external', title='ردُّ EBS', created_by=self.clerk,
                                    department=self.dept, our_number='8')
        reply.issuing_entities.add(self.ebs)
        _link, closed = register_reply(b, reply, by=self.clerk)
        self.assertIsNotNone(closed, 'إحالةُ الجهة الخارجيّة لم تُقفل بوارِدها')
        self.assertEqual(closed.pk, row.pk)

    def test_a_reply_from_someone_else_closes_nothing(self):
        from core.registration_service import register_reply
        b, row = self._distributed_to(self.ebs)
        other = Entity.objects.create(name='جهةٌ أخرى')
        reply = Book.objects.create(kind='incoming_external', title='ردٌّ غريب', created_by=self.clerk,
                                    department=self.dept, our_number='9')
        reply.issuing_entities.add(other)
        _link, closed = register_reply(b, reply, by=self.clerk)
        self.assertIsNone(closed)
        row.refresh_from_db(); self.assertEqual(row.status, BookReferral.SENT)

    def test_linking_as_something_else_keeps_the_commitment_open(self):
        import json
        b, row = self._distributed_to(self.unit_reports)
        other = Book.objects.create(kind='outgoing_internal', title='إلحاق', created_by=self.clerk,
                                    department=self.unit_reports, our_number='10')
        self.client.force_login(self.clerk)
        r = self.client.post(reverse('api_add_link', args=[other.pk]),
                             data=json.dumps({'to_book': b.pk, 'relation': 'followup'}),
                             content_type='application/json')
        self.assertIn(r.status_code, (200, 400))
        row.refresh_from_db(); self.assertEqual(row.status, BookReferral.SENT)


class TwoMarginsNamedTests(RoutingTestCase):
    """§2 هامشان لشخصين: هامشُ المدير العام على الكتاب يُقرأ داخل حواريّة التفريق، وهامشُ
    مدير القسم يُكتب فيها — لا يُنسَخ أحدُهما إلى الآخر."""

    def test_the_dialog_shows_the_gm_margin_and_names_the_head_margin(self):
        b = self._book(margin='قسم المتابعة — إجراء اللازم')
        self.client.force_login(self.clerk)
        r = self.client.get(reverse('book_detail', args=[b.pk]))
        self.assertContains(r, 'id="distGmMargin"')
        self.assertContains(r, 'هامشُ المدير العام على الكتاب')
        self.assertContains(r, 'هامشُ مدير القسم')
        self.assertNotContains(r, 'ملاحظات وهوامش')


class GmOfficeNumberTests(RoutingTestCase):
    """§3 الصادرُ الخارجيّ: رقمُ مكتب المدير العام قيدٌ في دفتره، يدويٌّ، لا يستهلك سلسلة؛
    يُصحَّح ويُزال؛ ويعود في بيانات التعديل."""

    def test_saving_an_outgoing_external_book_records_the_gm_office_number(self):
        from core.models import BookRegistration, BookSequence
        from core.registration_service import GM_OFFICE_NAME
        before = BookSequence.objects.count()
        self.client.force_login(self.clerk)
        r = self.client.post(reverse('save-book-api'), {
            'kind': 'outgoing_external', 'title': 'إلى EBS', 'our_number': '3201',
            'date': '2026-09-11', 'gm_office_number': 'ش13/27189',
            'receiving_entity_ids[]': [str(self.ebs.id)],
        })
        self.assertEqual(r.status_code, 201, r.content[:300])
        book = Book.objects.get(title='إلى EBS')
        reg = BookRegistration.objects.get(book=book, department__name=GM_OFFICE_NAME)
        self.assertEqual(reg.number, 'ش13/27189')
        self.assertEqual(BookSequence.objects.count(), before, 'قيدُ المكتب استهلك سلسلة')
        self.assertEqual(book.our_number, '3201', 'رقمُنا يبقى رقمَ سجلّنا')
        data = self.client.get(reverse('api_book_detail_json', args=[book.pk])).json()
        self.assertEqual(data.get('gm_office_number'), 'ش13/27189')

    def test_correct_and_remove(self):
        from core.models import BookRegistration
        from core.registration_service import GM_OFFICE_NAME, record_gm_office_number
        b = Book.objects.create(kind='outgoing_external', title='ص', created_by=self.clerk,
                                department=self.dept, our_number='3202')
        record_gm_office_number(b, '109', by=self.clerk)
        record_gm_office_number(b, '110', by=self.clerk)
        self.assertEqual(BookRegistration.objects.get(book=b, department__name=GM_OFFICE_NAME).number, '110')
        record_gm_office_number(b, '', by=self.clerk)
        self.assertFalse(BookRegistration.objects.filter(book=b, department__name=GM_OFFICE_NAME).exists())

    def test_the_input_page_has_the_field_hidden_by_default(self):
        self.client.force_login(self.clerk)
        r = self.client.get(reverse('extraction-smart-desktop'))
        self.assertContains(r, 'id="gmOfficeNumberGroup"')
        self.assertContains(r, 'id="gmOfficeNumber"')


class DossierRollupTests(RoutingTestCase):
    """§4.3 التجمّعُ صعوداً: أضبارةُ القسم تضمّ ما ذُكرت فيه وحداتُه؛ الوحدةُ لا ترى أختَها."""

    def setUp(self):
        self.dept.entity = Entity.objects.create(name='قسم المتابعة (توأم)'); self.dept.save()
        self.b_reports = self._book(title='للتقارير'); self.b_reports.receiving_entities.add(self.unit_reports.entity)
        self.b_budget = self._book(title='للموازنة'); self.b_budget.receiving_entities.add(self.unit_budget.entity)
        self.client.force_login(self.clerk)

    def test_the_department_dossier_includes_its_units(self):
        r = self.client.get(reverse('dossier_detail', args=[self.dept.entity_id]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'واردة (2)')   # كتابا الوحدتين معاً
        r2 = self.client.get(reverse('dossier_detail', args=[self.dept.entity_id]) + '?document_type=متفرقة')
        self.assertContains(r2, 'للتقارير'); self.assertContains(r2, 'للموازنة')

    def test_a_unit_dossier_shows_only_its_own_mentions(self):
        r = self.client.get(reverse('dossier_detail', args=[self.unit_reports.entity_id]))
        self.assertContains(r, 'واردة (1)')
        self.assertNotContains(r, 'واردة (2)')

    def test_an_entity_without_a_twin_is_itself_only(self):
        from core.views.dossiers import dossier_entity_ids
        self.assertEqual(dossier_entity_ids(self.ebs.pk), [self.ebs.pk])


class DossierYearFoldersTests(RoutingTestCase):
    """§4.5 الملفّاتُ بالنوع ثمّ بالسنة: داخل ملفّ النوع تظهر السنواتُ حين تتعدّد، و?year يضيّق."""

    def setUp(self):
        from datetime import date
        self.dept.entity = Entity.objects.create(name='قسم المتابعة (توأم)'); self.dept.save()
        for y, t in ((2024, 'ألفٌ قديم'), (2025, 'باءٌ وسط'), (2026, 'جيمٌ جديد')):
            b = self._book(title=t, date=date(y, 3, 1), document_type='كتاب')
            b.receiving_entities.add(self.unit_reports.entity)
        self.client.force_login(self.clerk)

    def test_type_folder_shows_year_subfolders_then_rows(self):
        url = reverse('dossier_detail', args=[self.unit_reports.entity_id])
        r = self.client.get(url + '?document_type=كتاب')
        self.assertContains(r, 'folder-grid-years')
        for y in ('2024', '2025', '2026'):
            self.assertContains(r, f'year={y}')
        r = self.client.get(url + '?document_type=كتاب&year=2025')
        self.assertNotContains(r, 'folder-grid-years')
        self.assertContains(r, 'باءٌ وسط'); self.assertNotContains(r, 'ألفٌ قديم'); self.assertNotContains(r, 'جيمٌ جديد')
        self.assertContains(r, 'sf-crumb')

    def test_a_single_year_skips_the_year_level(self):
        url = reverse('dossier_detail', args=[self.unit_budget.entity_id])
        from datetime import date
        b = self._book(title='وحيد', date=date(2026, 1, 1), document_type='كتاب')
        b.receiving_entities.add(self.unit_budget.entity)
        r = self.client.get(url + '?document_type=كتاب')
        self.assertNotContains(r, 'folder-grid-years'); self.assertContains(r, 'وحيد')
