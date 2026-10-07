# -*- coding: utf-8 -*-
"""«ملفّ الكتاب» — حرّاسُ الصفحة المعتمَدة (2026‑10‑06) وقراراتِ المالك Q2–Q5.

الرقمُ هويّةٌ واحدة في الدائرة · «بعهدة» مرّةً في الترويسة · فعلٌ أساسيٌّ واحدٌ أو
لا شيء · حبّةُ الموعد لا تقول «مؤرشف» لكتابٍ بلا متابعة · «مَن يفتحه» للسرّيّ ·
والمناطقُ التي يُعيد السكربتُ رسمَها موسومةٌ وتحمل الحقيقةَ الجديدة بعد الفعل.
"""
import re
from datetime import date, timedelta

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.custody_service import record_custody
from core.models import Book, BookRegistration, CustodyEvent, Department, Entity, UserProfile
from core.roles import CONTROLLER_GROUP_NAME


class BookDetailPageTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.today = timezone.localdate()
        cls.dept = Department.objects.create(name='قسمُ الملفّ', code='م.ق')
        cls.admin = User.objects.create_superuser('mroot', 'm@x.co', 'pw-mroot-1111')
        cls.clerk = User.objects.create_user('mclerk', password='pw-mclerk-1111',
                                             first_name='كاتبةُ', last_name='الملفّ')
        UserProfile.objects.update_or_create(user=cls.clerk, defaults={'department': cls.dept})
        cls.sender = Entity.objects.create(name='جهةُ الملفّ المُرسِلة')
        cls.book = Book.objects.create(
            kind='incoming_external', title='كتابُ التصميم', our_number='7700',
            created_by=cls.clerk, department=cls.dept, date=date(2026, 9, 27),
            sender_number='م/417', sender_date=date(2026, 9, 20), document_type='طلب بيانات',
            due_date=cls.today + timedelta(days=5), is_archived=False)
        cls.book.issuing_entities.add(cls.sender)
        cls.undated = Book.objects.create(kind='incoming_internal', title='بلا موعد',
                                          our_number='7701', created_by=cls.clerk,
                                          department=cls.dept)   # is_archived=True افتراضاً

    def _page(self, book=None, user=None):
        self.client.force_login(user or self.clerk)
        resp = self.client.get(reverse('book_detail', args=[(book or self.book).pk]))
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode('utf-8')


class IdentityTests(BookDetailPageTestCase):

    def test_the_page_carries_its_scope_and_a_cache_busted_sheet(self):
        body = self._page()
        self.assertIn('class="bx"', body)
        self.assertRegex(body, r'book_detail_v2\.css\?v=\d{8}')
        self.assertNotIn('app-sidebar-context-panel', body)   # اللوحتان المكرّرتان حُذفتا

    def test_the_number_is_one_identity_in_the_dark_circle(self):
        """Q2: الدائرةُ وحدها — لا شارةَ رقمٍ ثانية؛ والدائرةُ نفسُها تنسخه."""
        body = self._page()
        self.assertEqual(body.count('id="bookNumberText"'), 1)
        self.assertRegex(body, r'class="bx-circle" data-copy-target="bookNumberText"')
        self.assertNotIn('badge bg-info', body)

    def test_the_citation_line_reads_like_the_correspondence(self):
        body = self._page()
        cite = re.search(r'id="bookCitationText">(.*?)</span>\s*<button', body, re.S).group(1)
        text = re.sub(r'<[^>]+>', '', cite)
        self.assertEqual(text, 'من جهةُ الملفّ المُرسِلة — كتابهم م/417 في 20/09/2026'
                               ' · قُيِّد عندنا 7700 في 27/09/2026')

    def test_the_missing_facts_are_shown(self):
        """تقريرُ فيبل P1: تاريخُ الجهة ونوعُ المستند كانا غائبَين عن الصفحة كلِّها."""
        body = self._page()
        self.assertIn('طلب بيانات', body)
        self.assertIn('20/09/2026', body)


class StateTests(BookDetailPageTestCase):

    def test_at_most_one_primary_action(self):
        for book in (self.book, self.undated):
            with self.subTest(book=book.our_number):
                self.assertLessEqual(self._page(book).count('bx-btn--primary'), 1)

    def test_a_book_without_a_due_date_is_not_called_archived(self):
        """كانت حبّةُ «مؤرشف» على كلّ كتابٍ بلا موعد. (نافذةُ المعاينة العامّة في
        ``base.html`` تحمل مفرداتِ القائمة — دفعتُها لا هذه — فالفحصُ على محتوى الصفحة.)"""
        body = self._page(self.undated)
        page = body[body.index('class="bx"'):body.index('</main>')]
        self.assertIn('بلا موعد متابعة', page)
        self.assertNotIn('مؤرشف', page)

    def test_custody_appears_once_in_the_header(self):
        record_custody(self.book, CustodyEvent.UNIT_RECEIPT, to_department=self.dept, by=self.clerk)
        body = self._page()
        self.assertEqual(body.count('id="bookCustodyCard"'), 1)
        self.assertEqual(body.count('بعهدة <b>'), 1)

    def test_the_fresh_page_carries_the_next_step_in_the_swapped_regions(self):
        """بعد «عهدة» يجلب السكربتُ الصفحةَ ويستبدل المناطق: «أنهِ المتابعة» في
        ``bookActions`` و«بالعهدة» منجزةٌ في ``bookSteps``."""
        from core.referral_service import distribute
        unit = Department.objects.create(name='شعبةُ الملفّ', code='م.ش', parent=self.dept)
        distribute(self.book, [unit], by=self.clerk, due_date=self.today + timedelta(days=7))
        record_custody(self.book, CustodyEvent.UNIT_RECEIPT, to_department=unit, by=self.clerk)
        body = self._page()
        for region in ('followupStateText', 'bookCustodyCard', 'bookSteps', 'bookActions',
                       'bookRegsBar', 'lifecycleRegion', 'followupHistoryCard'):
            self.assertIn('id="%s" data-lifecycle-refresh' % region, body)
        actions = body[body.index('id="bookActions"'):]
        self.assertIn('أنهِ المتابعة', actions[:actions.index('</form>')])
        steps = body[body.index('id="bookSteps"'):body.index('id="bookActions"')]
        self.assertRegex(steps, r'bx-step done[^>]*>\s*<i class="n"[^>]*><i class="bi bi-check"></i></i>\s*'
                                r'<span><b>بالعهدة</b>')

    def test_the_registration_cell_is_always_there_and_names_the_ledger(self):
        body = self._page()
        regs = body[body.index('id="bookRegsBar"'):]
        self.assertIn('في دفتر قسمه وحده', regs[:400])
        other = Department.objects.create(name='مكتبُ المدير للملفّ', code='م.م')
        BookRegistration.objects.create(book=self.book, department=other, number='2501',
                                        registered_by=self.admin)
        regs = self._page()
        regs = regs[regs.index('id="bookRegsBar"'):]
        self.assertIn('مكتبُ المدير للملفّ', regs[:400])
        self.assertIn('2501', regs[:400])


class SecretOpenersLineTests(BookDetailPageTestCase):
    """Q5: «مَن يفتحه» للسرّيّ وحدَه — بالأسماء ومن توأم ``secret_access``."""

    def test_the_line_names_who_opens_a_secret_and_is_absent_otherwise(self):
        officer = User.objects.create_user('mofficer', password='pw-mofficer-1111',
                                           first_name='مختصُّ', last_name='البريد')
        UserProfile.objects.update_or_create(user=officer, defaults={'department': self.dept})
        officer.groups.add(Group.objects.get_or_create(name=CONTROLLER_GROUP_NAME)[0])
        secret = Book.objects.create(kind='incoming_internal', title='سرّيُّ الملفّ',
                                     our_number='7702', created_by=self.clerk,
                                     department=self.dept, secret_level='secret')
        body = self._page(secret)
        line = re.search(r'class="bx-openers">(.*?)</small>', body, re.S).group(1)
        self.assertIn('مديرُ النظام', line)
        self.assertIn('كاتبةُ الملفّ', line)
        self.assertIn('مختصُّ البريد', line)
        self.assertNotIn('bx-openers', self._page())
