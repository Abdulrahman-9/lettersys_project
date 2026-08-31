"""
نقاطُ الكتابة لدورة الحياة — التفريقُ والعهدةُ والقيدُ ونقلاتُ الحالة.

بُنيت الجداولُ الخمسةُ وخدماتُها ولا شاشةَ تكتب فيها. وهذه النقاطُ **أخطرُ سطحٍ
في الدفعة**: منها يتحرّك المستند. فالاختباراتُ تسأل عن ثلاثة:
هل تُحترم البوّابات من هنا كما من الخدمة · وهل يُترجَم الرفضُ رمزاً صادقاً ·
وهل يتسرّب منطقٌ إلى الغلاف فيصير نسخةً ثانيةً للحقيقة.
"""

import json
from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.utils import timezone

from core.custody_service import record_custody
from core.models import (Book, BookReferral, BookSequence, CustodyEvent, Department,
                         Entity, EntityGroup, UserProfile)
from core.referral_service import distribute
from core.roles import CONTROLLER_GROUP_NAME


class LifecycleApiTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.dept = Department.objects.create(name='المتابعة', code='ن-ش13')
        cls.unit = Department.objects.create(
            name='شعبة الموازنة', code='ن-ش13/1', parent=cls.dept,
            entity=Entity.objects.create(name='شعبة الموازنة'))
        cls.other = Department.objects.create(
            name='العقود', code='ن-ش5', entity=Entity.objects.create(name='قسم العقود'))
        cls.ministry = Entity.objects.create(name='وزارة النفط')

        def member(name, dept, *, controller=False):
            u = User.objects.create_user(name, password='pw-%s-11111' % name)
            UserProfile.objects.create(user=u, department=dept)
            if controller:
                u.groups.add(Group.objects.get_or_create(name=CONTROLLER_GROUP_NAME)[0])
            return u

        cls.clerk = member('nlclerk', cls.dept, controller=True)
        cls.staff = member('nlstaff', cls.unit)
        cls.outsider = member('nlout', cls.other)

        cls.book = Book.objects.create(
            kind='incoming_external', title='تخصيصاتُ الحفر', created_by=cls.clerk,
            department=cls.dept, our_number='2433')
        cls.foreign = Book.objects.create(
            kind='incoming_internal', title='كتابُ العقود', created_by=cls.outsider,
            department=cls.other, our_number='991')

    def setUp(self):
        self.client.force_login(self.clerk)

    def _post(self, url, payload=None):
        return self.client.post(url, data=json.dumps(payload or {}),
                                content_type='application/json')


class DistributeApiTests(LifecycleApiTestCase):

    def test_distributes_to_chosen_departments(self):
        resp = self._post('/books/api/book/%d/distribute/' % self.book.pk,
                          {'targets': ['dep:%d' % self.unit.pk],
                           'margin': 'أعدّوا مذكّرة'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['count'], 1)
        self.assertEqual(self.book.referrals.first().margin, 'أعدّوا مذكّرة')

    def test_distributes_to_an_external_entity(self):
        self._post('/books/api/book/%d/distribute/' % self.book.pk,
                   {'targets': ['ent:%d' % self.ministry.pk]})
        self.assertEqual(self.book.referrals.first().to_entity, self.ministry)

    def test_a_group_wins_over_manual_targets(self):
        """هدفان متضاربان يُنتجان تفريقاً مزدوجاً — والعنقودُ هو المُعلَن."""
        group = EntityGroup.objects.create(name='قسمٌ واحد')
        group.members.add(self.other.entity)
        self._post('/books/api/book/%d/distribute/' % self.book.pk,
                   {'group': group.pk, 'targets': ['dep:%d' % self.unit.pk]})
        self.assertEqual([r.to_department for r in self.book.referrals.all()], [self.other])

    def test_no_target_is_refused_with_a_message(self):
        resp = self._post('/books/api/book/%d/distribute/' % self.book.pk, {'targets': []})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('لم تختر', resp.json()['message'])

    def test_a_foreign_book_is_not_found(self):
        """خارجُ النطاق «غير موجود» لا «ممنوع» — فلا يُسرَّب وجودُه."""
        resp = self._post('/books/api/book/%d/distribute/' % self.foreign.pk,
                          {'targets': ['dep:%d' % self.unit.pk]})
        self.assertEqual(resp.status_code, 404)

    def test_a_repeat_over_an_open_commitment_is_refused(self):
        distribute(self.book, [self.unit], by=self.clerk)
        resp = self._post('/books/api/book/%d/distribute/' % self.book.pk,
                          {'targets': ['dep:%d' % self.unit.pk]})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('مُفرَّق', resp.json()['message'])

    def test_an_assignee_outside_my_tree_is_dropped_not_fatal(self):
        """إسنادُ عملٍ لموظّفٍ لا أراه لا معنى له — ويُهمَل بلا إسقاط العمليّة."""
        resp = self._post('/books/api/book/%d/distribute/' % self.book.pk,
                          {'targets': ['dep:%d' % self.unit.pk],
                           'assignee': self.outsider.pk})
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(self.book.referrals.first().assignee_id)

    def test_an_assignee_inside_my_tree_is_kept(self):
        self._post('/books/api/book/%d/distribute/' % self.book.pk,
                   {'targets': ['dep:%d' % self.unit.pk], 'assignee': self.staff.pk})
        self.assertEqual(self.book.referrals.first().assignee, self.staff)

    def test_a_due_date_is_parsed(self):
        due = (timezone.localdate() + timedelta(days=7)).isoformat()
        self._post('/books/api/book/%d/distribute/' % self.book.pk,
                   {'targets': ['dep:%d' % self.unit.pk], 'due_date': due})
        self.assertEqual(self.book.referrals.first().due_date.isoformat(), due)

    def test_a_broken_date_is_ignored_not_fatal(self):
        resp = self._post('/books/api/book/%d/distribute/' % self.book.pk,
                          {'targets': ['dep:%d' % self.unit.pk], 'due_date': 'أمس'})
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(self.book.referrals.first().due_date)

    def test_garbage_target_tokens_are_skipped(self):
        resp = self._post('/books/api/book/%d/distribute/' % self.book.pk,
                          {'targets': ['dep:abc', 'nope', 'dep:99999']})
        self.assertEqual(resp.status_code, 400)

    def test_get_is_refused(self):
        self.assertEqual(
            self.client.get('/books/api/book/%d/distribute/' % self.book.pk).status_code, 405)


class ReferralActionApiTests(LifecycleApiTestCase):

    def setUp(self):
        super().setUp()
        self.row = distribute(self.book, [self.unit], by=self.clerk)[0]

    def _act(self, act, note=''):
        return self._post('/books/api/book/%d/referral/%d/act/' % (self.book.pk, self.row.pk),
                          {'act': act, 'note': note})

    def test_received_then_done(self):
        self.assertEqual(self._act('received').status_code, 200)
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, BookReferral.RECEIVED)
        self.assertEqual(self._act('done', 'رُفعت المذكّرة').status_code, 200)
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, BookReferral.DONE)

    def test_returned_records_the_reason(self):
        from core.models import BookHistory

        self._act('returned', 'ليس من اختصاصنا')
        self.assertTrue(BookHistory.objects.filter(
            book=self.book, action='referral-returned',
            notes__contains='ليس من اختصاصنا').exists())

    def test_a_reminder_stamps_the_row(self):
        self.assertEqual(self._act('remind').status_code, 200)
        self.row.refresh_from_db()
        self.assertIsNotNone(self.row.last_reminder_at)

    def test_reminding_a_closed_commitment_is_refused(self):
        self._act('done')
        resp = self._act('remind')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('مُغلق', resp.json()['message'])

    def test_an_unknown_act_is_refused(self):
        self.assertEqual(self._act('احذف كل شيء').status_code, 400)

    def test_a_referral_of_another_book_is_not_found(self):
        other = Book.objects.create(kind='incoming_internal', title='آخر',
                                    created_by=self.clerk, department=self.dept,
                                    our_number='2434')
        resp = self._post('/books/api/book/%d/referral/%d/act/' % (other.pk, self.row.pk),
                          {'act': 'done'})
        self.assertEqual(resp.status_code, 404)

    def test_a_stranger_cannot_act_on_it(self):
        self.client.force_login(self.outsider)
        self.assertEqual(self._act('done').status_code, 404)

    def test_the_assigned_unit_may_act_on_it(self):
        """الوحدةُ المُحال إليها طرفٌ في الإحالة — فتُقدّم حالتَها بنفسها."""
        self.client.force_login(self.staff)
        self.assertEqual(self._act('received').status_code, 200)


class CustodyApiTests(LifecycleApiTestCase):

    def test_records_custody_to_a_department(self):
        resp = self._post('/books/api/book/%d/custody/' % self.book.pk,
                          {'event': CustodyEvent.UNIT_RECEIPT,
                           'to_department': self.unit.pk,
                           'note': 'بموجب كشف التسليم 14'})
        self.assertEqual(resp.status_code, 200)
        self.book.refresh_from_db()
        self.assertEqual(self.book.current_custody.holder_name, 'شعبة الموازنة')

    def test_a_free_text_holder_needs_no_account(self):
        self._post('/books/api/book/%d/custody/' % self.book.pk,
                   {'event': CustodyEvent.COURIER_PICKUP, 'to_name': 'أبو أحمد'})
        self.book.refresh_from_db()
        self.assertEqual(self.book.current_custody.holder_name, 'أبو أحمد')

    def test_custody_to_nobody_is_refused(self):
        resp = self._post('/books/api/book/%d/custody/' % self.book.pk,
                          {'event': CustodyEvent.INTAKE})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('حامل', resp.json()['message'])

    def test_an_unknown_event_is_refused(self):
        resp = self._post('/books/api/book/%d/custody/' % self.book.pk,
                          {'event': 'ضياع', 'to_department': self.unit.pk})
        self.assertEqual(resp.status_code, 400)

    def test_a_signed_at_in_the_past_is_honoured(self):
        stamp = (timezone.now() - timedelta(days=1)).strftime('%Y-%m-%dT%H:%M')
        self._post('/books/api/book/%d/custody/' % self.book.pk,
                   {'event': CustodyEvent.INTAKE, 'to_department': self.dept.pk,
                    'signed_at': stamp})
        moment = self.book.custody_events.first()
        self.assertLess(moment.signed_at, timezone.now() - timedelta(hours=12))

    def test_unit_receipt_through_the_api_advances_its_referral(self):
        row = distribute(self.book, [self.unit], by=self.clerk)[0]
        self._post('/books/api/book/%d/custody/' % self.book.pk,
                   {'event': CustodyEvent.UNIT_RECEIPT, 'referral': row.pk,
                    'to_department': self.unit.pk})
        row.refresh_from_db()
        self.assertEqual(row.status, BookReferral.RECEIVED)

    def test_a_stranger_gets_not_found(self):
        self.client.force_login(self.outsider)
        resp = self._post('/books/api/book/%d/custody/' % self.book.pk,
                          {'event': CustodyEvent.INTAKE, 'to_department': self.other.pk})
        self.assertEqual(resp.status_code, 404)


class RegisterHereApiTests(LifecycleApiTestCase):

    def test_registers_with_a_number_from_my_counter(self):
        expected = BookSequence.get_next('incoming_external',
                                         department=self.dept)['formatted']
        resp = self._post('/books/api/book/%d/register-here/' % self.book.pk)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['number'], expected)

    def test_registering_twice_is_refused(self):
        self._post('/books/api/book/%d/register-here/' % self.book.pk)
        resp = self._post('/books/api/book/%d/register-here/' % self.book.pk)
        self.assertEqual(resp.status_code, 400)
        self.assertIn('سلفاً', resp.json()['message'])

    def test_numberless_consumes_no_counter(self):
        before = BookSequence.get_next('incoming_external', department=self.dept)['number']
        self._post('/books/api/book/%d/register-here/' % self.book.pk, {'numberless': True})
        after = BookSequence.get_next('incoming_external', department=self.dept)['number']
        self.assertEqual(before, after)


class TargetsApiTests(LifecycleApiTestCase):

    def test_it_lists_departments_groups_people_and_events(self):
        data = self.client.get('/books/api/lifecycle/targets/').json()
        for key in ('departments', 'groups', 'people', 'events'):
            self.assertIn(key, data)

    def test_all_departments_are_offered_not_only_my_tree(self):
        """التفريق يتجاوز حدودَ القسم بطبيعته — «إحالةٌ لقسمٍ آخر بالشركة»."""
        names = [d['name'] for d in self.client.get('/books/api/lifecycle/targets/').json()['departments']]
        self.assertIn('العقود', names)

    def test_my_department_is_marked(self):
        rows = {d['name']: d['is_mine']
                for d in self.client.get('/books/api/lifecycle/targets/').json()['departments']}
        self.assertTrue(rows['شعبة الموازنة'])
        self.assertFalse(rows['العقود'])

    def test_people_are_limited_to_my_tree(self):
        """المكلَّفُ من شجرتي — وإسنادُ عملٍ لموظّفٍ لا أراه لا معنى له."""
        names = [p['name'] for p in self.client.get('/books/api/lifecycle/targets/').json()['people']]
        self.assertIn('nlstaff', names)
        self.assertNotIn('nlout', names)

    def test_anonymous_is_sent_to_login(self):
        self.client.logout()
        self.assertIn(self.client.get('/books/api/lifecycle/targets/').status_code, (301, 302))


class DialogsRenderTests(LifecycleApiTestCase):
    """الحواريّاتُ تُصيَّر في الصفحة — وإلّا فالأزرارُ تفتح فراغاً."""

    def test_the_panel_carries_the_book_id(self):
        body = self.client.get('/books/%d/' % self.book.pk).content.decode()
        self.assertIn('data-book-id="%d"' % self.book.pk, body)

    def test_the_dialogs_are_present_even_with_no_history(self):
        body = self.client.get('/books/%d/' % self.book.pk).content.decode()
        self.assertIn('distributeModal', body)
        self.assertIn('custodyModal', body)
        self.assertIn('registerHereBtn', body)

    def test_open_referrals_get_action_buttons(self):
        distribute(self.book, [self.unit], by=self.clerk)
        body = self.client.get('/books/%d/' % self.book.pk).content.decode()
        self.assertIn('data-referral-act="received"', body)
        self.assertIn('data-referral-act="remind"', body)

    def test_a_closed_referral_has_no_action_buttons(self):
        row = distribute(self.book, [self.unit], by=self.clerk)[0]
        from core.referral_service import mark_done
        mark_done(row, by=self.clerk)
        body = self.client.get('/books/%d/' % self.book.pk).content.decode()
        self.assertNotIn('data-referral-id="%d"' % row.pk, body)

    def test_the_script_is_loaded_with_a_cache_key(self):
        """فخُّ الـPWA: بلا ?v= لا يصل التعديلُ إلى المتصفّح أبداً."""
        body = self.client.get('/books/%d/' % self.book.pk).content.decode()
        self.assertIn('book_lifecycle.js', body)
        self.assertIn('?v=', body.split('book_lifecycle.js')[1][:40])
