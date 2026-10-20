"""
طاولةُ البريد — الورقتان المطبوعتان.

**والورقةُ أخطرُ من الشاشة لا أقلّ**: تخرج من الجهاز وتُترك على طاولة. فأشدُّ
ما تحرسه هذه الاختبارات أن يمرّ الكشفُ والدفترُ **بالبوّابتين نفسَيهما**
(النطاق + السرّيّة) لا بأقلَّ منهما.
"""

from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.test.html import parse_html
from django.urls import reverse
from django.utils import timezone

from core.custody_service import record_custody
from core.models import (Book, BookReferral, BookRegistration, CustodyEvent, Department, Entity,
                         UserProfile)
from core.referral_service import distribute
from core.registration_service import register_book_here
from core.roles import CONTROLLER_GROUP_NAME


class DeskTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.dept = Department.objects.create(name='المتابعة', code='ط-ش13')
        cls.unit = Department.objects.create(
            name='شعبة الموازنة', code='ط-ش13/1', parent=cls.dept,
            entity=Entity.objects.create(name='شعبة الموازنة'),
        )
        cls.other = Department.objects.create(name='العقود', code='ط-ش5')

        def member(name, dept, *, head=False, controller=False):
            u = User.objects.create_user(name, password='pw-%s-11111' % name)
            UserProfile.objects.create(user=u, department=dept, is_department_head=head)
            if controller:
                group, _ = Group.objects.get_or_create(name=CONTROLLER_GROUP_NAME)
                u.groups.add(group)
            return u

        cls.officer = member('tofficer', cls.dept, controller=True)
        cls.head = member('thead', cls.dept, head=True)
        cls.plain = member('tplain', cls.dept)
        cls.outsider = member('tout', cls.other)

        cls.book = Book.objects.create(
            kind='incoming_external', title='تخصيصاتُ الحفر', created_by=cls.officer,
            department=cls.dept, our_number='2433',
        )
        cls.secret = Book.objects.create(
            kind='incoming_internal', title='مناقصةٌ سرّيّة', created_by=cls.officer,
            department=cls.dept, our_number='2437', secret_level='secret',
        )
        #: «للتنفيذ» لا يُفرَّق بلا موعد — وموعدٌ بعد أسبوعٍ لا يجعل الصفَّ متأخّراً.
        cls.due = timezone.localdate() + timedelta(days=7)


class LedgerLiveOnlyTests(DeskTestCase):
    """§7.2 صراحةً على الدفتر: كان الحرزُ عرَضيّاً (المنقولُ بلا ``department``)."""

    def test_a_legacy_book_stays_out_of_the_ledger_even_with_a_department(self):
        Book.objects.create(
            kind='incoming_external', title='منقولٌ من الورق', created_by=self.officer,
            department=self.dept, our_number='7001', source_ref='IIMAIL_2025#1',
        )
        Book.objects.create(
            kind='incoming_external', title='كتابُ تدريب', created_by=self.officer,
            department=self.dept, our_number='7002', is_training=True,
        )
        self.client.force_login(self.officer)
        resp = self.client.get('/books/desk/ledger/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'تخصيصاتُ الحفر')
        self.assertNotContains(resp, 'منقولٌ من الورق')
        self.assertNotContains(resp, 'كتابُ تدريب')


class DeskAccessTests(DeskTestCase):
    """بوّابةُ سطحٍ يخرج من الجهاز — لا بوّابةُ سرّيّة."""

    def test_the_mail_officer_may_open_it(self):
        self.client.force_login(self.officer)
        self.assertEqual(self.client.get('/books/desk/ledger/').status_code, 200)

    def test_the_department_head_may_open_it(self):
        self.client.force_login(self.head)
        self.assertEqual(self.client.get('/books/desk/handover/').status_code, 200)

    def test_a_plain_member_may_not(self):
        self.client.force_login(self.plain)
        self.assertEqual(self.client.get('/books/desk/ledger/').status_code, 403)

    def test_anonymous_is_sent_to_login(self):
        resp = self.client.get('/books/desk/ledger/')
        self.assertIn(resp.status_code, (302, 301))


class HandoverSheetTests(DeskTestCase):

    def setUp(self):
        self.client.force_login(self.officer)
        distribute(self.book, [self.unit], by=self.officer, margin='للمداولة',
                   due_date=self.due)

    def test_the_unit_appears_with_its_pending_count(self):
        body = self.client.get('/books/desk/handover/').content.decode()
        self.assertIn('شعبة الموازنة', body)

    def test_the_sheet_lists_the_unsigned_book(self):
        body = self.client.get('/books/desk/handover/', {'to': self.unit.pk}).content.decode()
        self.assertIn('تخصيصاتُ الحفر', body)
        self.assertIn('2433', body)
        self.assertIn('للمداولة', body)

    def test_a_signed_book_leaves_the_sheet(self):
        """جوهرُ الكشف: ما وُقّع عليه لا يُطلب توقيعُه ثانية."""
        record_custody(self.book, CustodyEvent.UNIT_RECEIPT, to_department=self.unit,
                       by=self.officer)
        body = self.client.get('/books/desk/handover/', {'to': self.unit.pk}).content.decode()
        self.assertNotIn('تخصيصاتُ الحفر', body)

    def test_it_carries_a_signature_column(self):
        body = self.client.get('/books/desk/handover/', {'to': self.unit.pk}).content.decode()
        self.assertIn('توقيع المستلم', body)
        self.assertIn('sign-cell', body)

    def test_an_unknown_unit_shows_nothing(self):
        body = self.client.get('/books/desk/handover/', {'to': 99999}).content.decode()
        self.assertNotIn('تخصيصاتُ الحفر', body)

    def test_a_secret_book_is_listed_without_its_subject(self):
        """الكشفُ يخرج من الجهاز — فالحجبُ فيه أوجبُ منه على الشاشة."""
        distribute(self.secret, [self.unit], by=self.officer, due_date=self.due)
        self.client.force_login(self.head)   # رئيسُ القسم يرى السرّيّ
        body = self.client.get('/books/desk/handover/', {'to': self.unit.pk}).content.decode()
        self.assertIn('مناقصةٌ سرّيّة', body)

        # ومن لا يملك محتواه لا يراه في الورقة — ولو كان مخوَّلاً بالطاولة
        Book.objects.filter(pk=self.secret.pk).update(department=self.other)
        body = self.client.get('/books/desk/handover/', {'to': self.unit.pk}).content.decode()
        self.assertNotIn('مناقصةٌ سرّيّة', body)


class LedgerTests(DeskTestCase):

    def setUp(self):
        self.client.force_login(self.officer)

    def test_it_lists_books_we_own(self):
        body = self.client.get('/books/desk/ledger/').content.decode()
        self.assertIn('تخصيصاتُ الحفر', body)
        self.assertIn('2433', body)

    def test_it_lists_books_registered_here_with_our_number(self):
        """الرقمُ رقمُ **دفترنا** لا رقمُ صاحبه — جوهرُ القيود المتعدّدة."""
        foreign = Book.objects.create(
            kind='incoming_internal', title='كتابُ العقود', created_by=self.outsider,
            department=self.other, our_number='991',
        )
        distribute(foreign, [self.dept], by=self.outsider, due_date=self.due)
        row = register_book_here(foreign, self.dept, by=self.officer)

        body = self.client.get('/books/desk/ledger/').content.decode()
        self.assertIn('كتابُ العقود', body)
        self.assertIn(row.number, body)

    def test_it_carries_the_clerk_five_columns(self):
        for column in ('الرقم', 'التاريخ', 'الموضوع', 'إلى مَن وُزِّع', 'مَن استلم'):
            with self.subTest(column=column):
                body = self.client.get('/books/desk/ledger/').content.decode()
                self.assertIn(column, body)

    def test_distribution_and_receipt_show_in_their_columns(self):
        distribute(self.book, [self.unit], by=self.officer, due_date=self.due)
        record_custody(self.book, CustodyEvent.UNIT_RECEIPT, to_department=self.unit,
                       by=self.officer)
        body = self.client.get('/books/desk/ledger/').content.decode()
        self.assertIn('شعبة الموازنة', body)

    def test_another_department_book_never_appears(self):
        Book.objects.create(
            kind='incoming_internal', title='لا شأنَ لنا به', created_by=self.outsider,
            department=self.other, our_number='992',
        )
        body = self.client.get('/books/desk/ledger/').content.decode()
        self.assertNotIn('لا شأنَ لنا به', body)

    def test_the_date_range_narrows_it(self):
        body = self.client.get('/books/desk/ledger/',
                               {'date_from': '1990-01-01', 'date_to': '1990-12-31'}).content.decode()
        self.assertNotIn('تخصيصاتُ الحفر', body)

    def test_a_broken_date_is_reported_without_crashing(self):
        resp = self.client.get('/books/desk/ledger/', {'date_from': 'ليس تاريخاً'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'aria-invalid="true"')
        self.assertEqual(resp.context['rows'], [])


class SheetsCarryTheCompanyNameTests(DeskTestCase):
    """ق‑7: الورقتان الموقَّعتان تطبعان «شركة نفط الوسط» (من الإعدادات، لا «نفط ميسان»)."""

    def test_both_sheets_name_the_company_from_settings(self):
        self.client.force_login(self.officer)
        for name in ('desk_handover', 'desk_ledger'):
            r = self.client.get(reverse(name))
            self.assertEqual(r.status_code, 200, name)
            self.assertContains(r, 'شركة نفط الوسط')
            self.assertNotContains(r, 'نفط ميسان')


class DeskWorkspacePresentationTests(DeskTestCase):
    def setUp(self):
        self.client.force_login(self.officer)

    def test_all_pages_share_navigation_and_identify_the_current_page(self):
        for page in ('desk_board', 'desk_ledger', 'desk_handover'):
            with self.subTest(page=page):
                response = self.client.get(reverse(page))
                self.assertContains(response, 'aria-label="صفحات طاولة البريد"')
                self.assertContains(response, 'aria-current="page"', count=2 if page == 'desk_board' else 1)
                self.assertContains(response, '<h1', count=1)
                self.assertContains(response, 'css/desk.css?v=20261020-mail-desk2')
                for destination in ('desk_board', 'desk_ledger', 'desk_handover'):
                    self.assertContains(response, reverse(destination))

    def test_sheet_navigation_preserves_the_selected_department(self):
        admin = User.objects.create_superuser('desk-preview-admin', password='test-only')
        self.client.force_login(admin)
        response = self.client.get(reverse('desk_ledger'), {'department': self.dept.pk})
        self.assertContains(
            response,
            'href="%s?department=%s"' % (reverse('desk_handover'), self.dept.pk),
        )

    def test_handover_selection_uses_explicit_submission(self):
        response = self.client.get(reverse('desk_handover'))
        self.assertContains(response, 'تجهيز الكشف')
        self.assertNotContains(response, 'onchange=')
        self.assertContains(response, '<button type="submit"')

    def test_paper_tables_keep_their_columns_and_keyboard_scroll_region(self):
        distribute(self.book, [self.unit], by=self.officer, due_date=self.due)
        for page, params, columns in (
            ('desk_ledger', {}, 6),
            ('desk_handover', {'to': self.unit.pk}, 5),
        ):
            with self.subTest(page=page):
                response = self.client.get(reverse(page), params)
                self.assertContains(response, 'class="desk-sheet-scroll" role="region"')
                self.assertContains(response, 'tabindex="0"')
                self.assertContains(response, '<th scope="col"', count=columns)

    def test_paper_pages_have_well_formed_html_including_empty_states(self):
        distribute(self.book, [self.unit], by=self.officer, due_date=self.due)
        for page, params in (
            ('desk_ledger', {}),
            ('desk_ledger', {'kind': 'invalid'}),
            ('desk_handover', {}),
            ('desk_handover', {'to': self.unit.pk}),
            ('desk_handover', {'to': self.unit.pk, 'kind': 'invalid'}),
        ):
            with self.subTest(page=page, params=params):
                response = self.client.get(reverse(page), params)
                self.assertEqual(response.status_code, 200)
                parse_html(response.content.decode())


class DeskFilteringTests(DeskTestCase):
    def setUp(self):
        self.client.force_login(self.officer)
        self.today = timezone.localdate()
        for number in ('3921', '3930', '3931'):
            book = Book.objects.create(
                kind='incoming_external', title='قيد %s' % number, our_number=number,
                department=self.dept, created_by=self.officer, date=self.today,
            )
            distribute(book, [self.unit], by=self.officer, due_date=self.due)
        distribute(self.secret, [self.unit], by=self.officer, due_date=self.due)

    def _responses(self, filters):
        for page in ('desk_ledger', 'desk_handover'):
            params = dict(filters)
            if page == 'desk_handover':
                params['to'] = self.unit.pk
            yield page, self.client.get(reverse(page), params)

    def test_number_range_is_inclusive_on_both_sheets(self):
        for page, response in self._responses({
            'number_from': '3921', 'number_to': '3930',
        }):
            with self.subTest(page=page):
                self.assertEqual({r['number'] for r in response.context['rows']}, {'3921', '3930'})
                self.assertContains(response, 'نطاق النتائج المطبوعة')
                self.assertContains(response, 'من رقم قيد القسم: 3921')

    def test_open_ended_and_arabic_digit_range(self):
        for page, response in self._responses({'number_from': '٣٩٣٠'}):
            with self.subTest(page=page):
                self.assertEqual({r['number'] for r in response.context['rows']}, {'3930', '3931'})

    def test_kind_and_date_are_combined_with_the_number_range(self):
        for page, response in self._responses({
            'kind': 'incoming_external', 'number_from': '3921',
            'date_from': self.today.isoformat(), 'date_to': self.today.isoformat(),
        }):
            with self.subTest(page=page):
                self.assertEqual(len(response.context['rows']), 3)
        for page, response in self._responses({'kind': 'incoming_internal'}):
            with self.subTest(page=page):
                self.assertEqual({r['number'] for r in response.context['rows']}, {'2437'})

    def test_invalid_filters_show_errors_and_never_print_an_unfiltered_sheet(self):
        for filters in (
            {'number_from': '3930', 'number_to': '3921'},
            {'number_from': '-1'},
            {'number_to': 'abc'},
            {'number_from': '0'},
            {'kind': 'unknown'},
            {'date_from': '2026-10-20', 'date_to': '2026-10-19'},
            {'date_from': 'invalid'},
            {'number_from': '20250825', 'number_to': '3930'},
        ):
            for page, response in self._responses(filters):
                with self.subTest(page=page, filters=filters):
                    self.assertEqual(response.status_code, 200)
                    self.assertTrue(response.context['desk_filters'].errors)
                    self.assertEqual(response.context['rows'], [])
                    self.assertContains(response, 'aria-invalid="true"')
                    self.assertNotContains(response, 'onclick="window.print()"')

    def test_target_links_and_reset_preserve_department_and_unit_context(self):
        response = self.client.get(reverse('desk_handover'), {
            'kind': 'incoming_external', 'number_from': '3921',
        })
        self.assertContains(response, 'kind=incoming_external&amp;number_from=3921&amp;to=')
        chosen = self.client.get(reverse('desk_handover'), {
            'to': self.unit.pk, 'number_from': '3921',
        })
        self.assertEqual(chosen.context['reset_filter_url'], '?to=%s' % self.unit.pk)
        self.assertEqual(
            chosen.context['desk_ledger_url'],
            reverse('desk_ledger') + '?number_from=3921',
        )

    def test_a_foreign_number_does_not_count_as_our_number(self):
        from core.models import BookReferral

        foreign = Book.objects.create(
            kind='incoming_external', title='رقم القسم الآخر', our_number='3925',
            department=self.other, created_by=self.outsider,
        )
        BookReferral.objects.create(
            book=foreign, from_department=self.dept, to_department=self.unit,
            created_by=self.officer, purpose=BookReferral.ACTION, due_date=self.due,
        )
        for page, response in self._responses({'number_from': '3925', 'number_to': '3925'}):
            with self.subTest(page=page):
                self.assertEqual(response.context['rows'], [])

    def test_local_registration_number_is_used_for_filtering_and_printing(self):
        from core.models import BookReferral

        foreign = Book.objects.create(
            kind='incoming_external', title='قيدنا المحلي', our_number='9991',
            department=self.other, created_by=self.outsider,
        )
        distribute(foreign, [self.dept], by=self.outsider, due_date=self.due)
        registration = register_book_here(foreign, self.dept, by=self.officer)
        registration.number = '3925'
        registration.save(update_fields=['number'])
        BookReferral.objects.create(
            book=foreign, from_department=self.dept, to_department=self.unit,
            created_by=self.officer, purpose=BookReferral.ACTION, due_date=self.due,
        )
        for page, response in self._responses({'number_from': '3925', 'number_to': '3925'}):
            with self.subTest(page=page):
                self.assertEqual([r['number'] for r in response.context['rows']], ['3925'])
                self.assertContains(response, 'قيدنا المحلي')
                self.assertNotContains(response, '9991')

    def test_tagged_numbers_do_not_leak_into_the_current_series(self):
        book = Book.objects.create(
            kind='incoming_external', title='رقم موسوم', our_number='20253925',
            department=self.dept, created_by=self.officer,
        )
        distribute(book, [self.unit], by=self.officer, due_date=self.due)
        for page, response in self._responses({'number_from': '3921', 'number_to': '3930'}):
            with self.subTest(page=page):
                self.assertNotContains(response, 'رقم موسوم')
        for page, response in self._responses({'number_from': '20253925', 'number_to': '20253925'}):
            with self.subTest(page=page):
                self.assertEqual([r['number'] for r in response.context['rows']], ['3925'])
                self.assertContains(response, 'سجل 2025')


class MailDeskTests(DeskTestCase):
    """طاولةُ البريد: العنوانُ يتبع النوع، والصادرُ الخارجيُّ يُسلَّم لمتعهّد البريد."""

    def setUp(self):
        self.client.force_login(self.officer)
        self.outgoing = Book.objects.create(
            kind='outgoing_external', title='كتابٌ صادرٌ للوزارة', created_by=self.officer,
            department=self.dept, our_number='455',
        )
        self.outgoing.receiving_entities.add(Entity.objects.create(name='وزارة النفط'))

    def test_titles_follow_the_selected_mail_kind(self):
        cases = {'': 'دفتر البريد', 'incoming': 'دفتر الوارد', 'outgoing': 'دفتر الصادر',
                 'outgoing_external': 'دفتر الصادر الخارجي'}
        for kind, title in cases.items():
            with self.subTest(kind=kind):
                resp = self.client.get('/books/desk/ledger/', {'kind': kind})
                self.assertContains(resp, '<h2 class="rep-title" id="ledger-heading">%s</h2>' % title,
                                    html=True)
        resp = self.client.get('/books/desk/handover/', {'kind': 'incoming'})
        self.assertContains(resp, 'كشف تسليم الوارد')

    def test_direction_groups_filter_the_ledger(self):
        incoming = self.client.get('/books/desk/ledger/', {'kind': 'incoming'})
        outgoing = self.client.get('/books/desk/ledger/', {'kind': 'outgoing'})
        everything = self.client.get('/books/desk/ledger/')
        self.assertContains(incoming, 'تخصيصاتُ الحفر')
        self.assertNotContains(incoming, 'كتابٌ صادرٌ للوزارة')
        self.assertContains(outgoing, 'كتابٌ صادرٌ للوزارة')
        self.assertNotContains(outgoing, 'تخصيصاتُ الحفر')
        self.assertContains(outgoing, 'وزارة النفط')
        self.assertContains(everything, 'class="desk-kind-group"')
        body = everything.content.decode()
        self.assertLess(body.index('تخصيصاتُ الحفر'), body.index('كتابٌ صادرٌ للوزارة'))
        self.assertNotContains(
            self.client.get('/books/desk/ledger/', {'kind': 'incoming_external'}), 'desk-kind-group')

    def test_ledger_print_carries_the_attest_and_signature_boxes(self):
        resp = self.client.get('/books/desk/ledger/')
        self.assertContains(resp, 'class="ho-attest"')
        self.assertContains(resp, '<h2>المستلِم</h2>', html=True)

    def test_courier_sheet_lists_undelivered_outgoing_external_until_pickup(self):
        prep = self.client.get('/books/desk/handover/')
        self.assertEqual(prep.context['courier_count'], 1)
        self.assertContains(prep, 'to=courier')

        sheet = self.client.get('/books/desk/handover/', {'to': 'courier'})
        self.assertTrue(sheet.context['is_courier'])
        self.assertEqual([r['title'] for r in sheet.context['rows']], ['كتابٌ صادرٌ للوزارة'])
        self.assertContains(sheet, 'كشف تسليم الصادر الخارجي إلى متعهّد البريد')
        self.assertContains(sheet, 'وزارة النفط')
        self.assertContains(sheet, 'الرجوع لاختيار الجهة المستلِمة')

        record_custody(self.outgoing, CustodyEvent.COURIER_PICKUP, to_name='أبو علي',
                       by=self.officer)
        after = self.client.get('/books/desk/handover/', {'to': 'courier'})
        self.assertEqual(after.context['courier_count'], 0)
        self.assertFalse(after.context['is_courier'])
        ledger = self.client.get('/books/desk/ledger/', {'kind': 'outgoing'})
        self.assertContains(ledger, 'أبو علي')

    def test_ledger_filters_by_party_distributed_to_sent_to_or_received_from(self):
        BookReferral.objects.create(book=self.book, from_department=self.dept,
                                    to_department=self.unit, due_date=self.due)
        from_unit = Book.objects.create(
            kind='incoming_internal', title='مذكّرةٌ من الشعبة', created_by=self.officer,
            department=self.dept, our_number='2440',
        )
        from_unit.issuing_entities.add(self.unit.entity)
        ministry = Entity.objects.get(name='وزارة النفط')

        ledger = self.client.get('/books/desk/ledger/')
        choices = dict(ledger.context['desk_filters'].fields['party'].choices[1:])
        self.assertIn(('u:%d' % self.unit.pk, str(self.unit)), choices['وحدات وأقسام داخلية'])
        entity_values = [value for value, _ in choices['جهات المراسلة']]
        self.assertIn('e:%d' % ministry.pk, entity_values)
        self.assertNotIn('e:%d' % self.unit.entity_id, entity_values)

        by_unit = self.client.get('/books/desk/ledger/', {'party': 'u:%d' % self.unit.pk})
        self.assertContains(by_unit, 'تخصيصاتُ الحفر')
        self.assertContains(by_unit, 'مذكّرةٌ من الشعبة')
        self.assertNotContains(by_unit, 'كتابٌ صادرٌ للوزارة')
        self.assertContains(by_unit, 'الجهة: %s' % self.unit)

        by_ministry = self.client.get('/books/desk/ledger/', {'party': 'e:%d' % ministry.pk})
        self.assertContains(by_ministry, 'كتابٌ صادرٌ للوزارة')
        self.assertNotContains(by_ministry, 'تخصيصاتُ الحفر')

        forged = self.client.get('/books/desk/ledger/', {'party': 'e:999999'})
        self.assertTrue(forged.context['desk_filters'].errors)
        self.assertEqual(forged.context['rows'], [])

        handover = self.client.get('/books/desk/handover/')
        self.assertNotIn('party', handover.context['desk_filters'].fields)

    def test_party_filter_never_reveals_a_secret_books_correspondents(self):
        secret = Book.objects.create(
            kind='incoming_external', title='سرٌّ وارد', created_by=self.outsider,
            department=self.other, our_number='5001', secret_level='secret',
        )
        hidden = Entity.objects.create(name='جهةٌ لا تُكشف')
        secret.issuing_entities.add(hidden)
        BookReferral.objects.create(book=secret, from_department=self.other,
                                    to_department=self.dept, due_date=self.due)
        BookRegistration.objects.create(book=secret, department=self.dept, number='2450',
                                        registered_by=self.officer)
        ledger = self.client.get('/books/desk/ledger/')
        self.assertContains(ledger, '2450')
        self.assertNotContains(ledger, 'جهةٌ لا تُكشف')
        probed = self.client.get('/books/desk/ledger/', {'party': 'e:%d' % hidden.pk})
        self.assertEqual(probed.context['rows'], [])

        public = Book.objects.create(
            kind='incoming_external', title='كتابٌ علنيّ من الجهة نفسها', created_by=self.officer,
            department=self.dept, our_number='2452',
        )
        public.issuing_entities.add(hidden)
        listed = self.client.get('/books/desk/ledger/', {'party': 'e:%d' % hidden.pk})
        self.assertEqual([row['book_id'] for row in listed.context['rows']], [public.pk])

    def test_a_registered_copy_of_foreign_outgoing_is_not_our_courier_duty(self):
        foreign = Book.objects.create(
            kind='outgoing_external', title='صادرُ قسمٍ آخر', created_by=self.outsider,
            department=self.other, our_number='77',
        )
        BookReferral.objects.create(book=foreign, from_department=self.other,
                                    to_department=self.dept, due_date=self.due)
        BookRegistration.objects.create(book=foreign, department=self.dept, number='2451',
                                        registered_by=self.officer)
        prep = self.client.get('/books/desk/handover/')
        self.assertEqual(prep.context['courier_count'], 1)

    def test_print_lives_outside_the_filter_form_with_a_stale_guard(self):
        html = self.client.get('/books/desk/ledger/').content.decode()
        form = html.split('data-desk-filter-form>', 1)[1].split('</form>', 1)[0]
        self.assertIn('تطبيق التصفية', form)
        self.assertNotIn('window.print', form)
        self.assertIn('data-desk-output', html)
        self.assertIn('js/desk_actions.js', html)

    def test_back_link_sits_in_the_header_not_in_the_toolbar(self):
        for url in ('/books/desk/ledger/', '/books/desk/handover/'):
            with self.subTest(url=url):
                html = self.client.get(url).content.decode()
                header = html.split('<header class="desk-header">', 1)[1].split('</header>', 1)[0]
                self.assertIn('class="desk-back"', header)
                self.assertIn('الرجوع إلى طاولة البريد', header)
                self.assertEqual(html.count('class="desk-back"'), 1)
                self.assertNotIn('class="btn back" href="/books/desk/"', html)

    def test_searchable_selects_load_local_assets_only(self):
        html = self.client.get('/books/desk/ledger/').content.decode()
        self.assertIn('vendor/tom-select/tom-select.complete.min.js', html)
        self.assertIn('data-desk-search', html)
        self.assertNotIn('cdn', html.lower())