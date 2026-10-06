"""
لوحةُ دورة الحياة في صفحة التفاصيل.

كلُّ ما بُني في البنود ②③④ كان **غيرَ مرئيّ**: جداولُ تمتلئ ولا شاشةَ تقرؤها.
وهذه اللوحةُ هي المكانُ الذي يرى فيه الكاتبُ ما بناه النظامُ له — «بعهدة مَن»
أوّلاً لأنّها الميزةُ الحاكمة، ثمّ مَن ردّ ومَن تأخّر.
"""

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from core.custody_service import record_custody
from core.linking_service import add_link
from core.models import (Book, BookLink, CustodyEvent, Department, Entity,
                         UserProfile)
from core.referral_service import distribute
from core.registration_service import register_book_here


class LifecyclePanelTestCase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.dept = Department.objects.create(name='المتابعة', code='ل-ش13')
        cls.unit = Department.objects.create(
            name='شعبة الموازنة', code='ل-ش13/1', parent=cls.dept,
            entity=Entity.objects.create(name='شعبة الموازنة'),
        )
        cls.gm = Department.objects.create(name='مكتب المدير العام', code='ل-م')

        cls.clerk = User.objects.create_user('lpclerk', password='pw-lp-11111')
        UserProfile.objects.create(user=cls.clerk, department=cls.dept)

        cls.book = Book.objects.create(
            kind='incoming_external', title='تخصيصاتُ الحفر', created_by=cls.clerk,
            department=cls.dept, our_number='2433',
        )
        cls.bare = Book.objects.create(
            kind='incoming_external', title='كتابٌ منقولٌ من الورق',
            created_by=cls.clerk, department=cls.dept, our_number='825',
        )

    def setUp(self):
        self.client.force_login(self.clerk)

    def _page(self, book):
        resp = self.client.get('/books/%d/' % book.pk)
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode()


class PanelContentTests(LifecyclePanelTestCase):

    def test_it_shows_who_holds_the_book(self):
        record_custody(self.book, CustodyEvent.UNIT_RECEIPT, to_department=self.unit,
                       by=self.clerk, note='بموجب كشف التسليم 14')
        body = self._page(self.book)
        self.assertIn('بعهدة', body)
        self.assertIn('شعبة الموازنة', body)
        self.assertIn('بموجب كشف التسليم 14', body)

    def test_it_shows_the_referral_with_its_directive(self):
        distribute(self.book, [self.unit], by=self.clerk, margin='أعدّوا مذكّرة')
        body = self._page(self.book)
        self.assertIn('أعدّوا مذكّرة', body)

    def test_an_overdue_action_is_marked(self):
        distribute(self.book, [self.unit], by=self.clerk,
                   due_date=timezone.localdate() - timedelta(days=3))
        body = self._page(self.book)
        self.assertIn('متأخّر', body)

    def test_it_shows_the_registers_the_paper_passed_through(self):
        """رحلةُ الورقة كاملةً — ومَن يرى نصفَها لا يرى شيئاً."""
        row = register_book_here(self.book, self.gm, by=self.clerk)
        body = self._page(self.book)
        self.assertIn('مكتب المدير العام', body)
        self.assertIn(row.number, body)

    def test_a_link_label_reads_correctly_from_this_side(self):
        """«جواب على» على كتابٍ *أجابه* غيرُه تُقرأ عكسَ معناها."""
        other = Book.objects.create(
            kind='outgoing_internal', title='الجواب', created_by=self.clerk,
            department=self.dept, our_number='2455',
        )
        add_link(other, self.book, BookLink.REPLY, by=self.clerk)
        self.assertIn('أجابه', self._page(self.book))
        self.assertIn('جواب على', self._page(other))


class EmptyStateTests(LifecyclePanelTestCase):
    """11,183 كتاباً منقولاً من الورق: أربعُ حالاتٍ فارغةٍ عليها ضجيجٌ لا معلومة."""

    def test_a_book_with_no_movement_gets_one_honest_line(self):
        body = self._page(self.bare)
        self.assertIn('لا حركةَ تسييرٍ على هذا الكتاب', body)
        self.assertNotIn('لم يُفرَّق هذا الكتاب على أحد بعد', body)

    def test_the_panel_still_has_its_place(self):
        """لا تُخفى تماماً — كي يبقى مكانُها معروفاً حين يبدأ التسيير."""
        self.assertIn('lifecycleCard', self._page(self.bare))

    def test_one_movement_opens_the_full_panel(self):
        distribute(self.bare, [self.unit], by=self.clerk)
        body = self._page(self.bare)
        self.assertIn('التفريق والردود', body)
        self.assertNotIn('لا حركةَ تسييرٍ على هذا الكتاب', body)


class RowButtonsFollowTheGuardsTests(TestCase):
    """أزرارُ الصفّ لمن يقبلها الخادم — تقريرُ فيبل لتفاصيل الكتاب، P0 البند 3.

    كانت «استلم/أُنجز/تنبيه/أُعيد» تُعرض لكلّ ناظرٍ ثمّ يرفضها ``_guard_target``
    أو ``_guard_chaser``. والحالةُ اليوميّة: كتابُ قسمي فُرِّق إلى قسمٍ آخر —
    فموظّفُ قسمي بلا دورٍ **يُنبّه** ولا يُقفل التزامَ غيره، وموظّفُ القسم
    المستقبِل **يُقفل** التزامَه ولا يُنبّه نفسَه، وطاولةُ قسمي تملك الاثنين.
    """

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth.models import Group

        from core.roles import CONTROLLER_GROUP_NAME

        cls.dept = Department.objects.create(name='المتابعة', code='ز-ش13')
        cls.contracts = Department.objects.create(name='العقود', code='ز-ش5')

        def member(name, dept, desk=False):
            u = User.objects.create_user(name, password='pw-%s-11111' % name)
            UserProfile.objects.create(user=u, department=dept)
            if desk:
                u.groups.add(Group.objects.get_or_create(name=CONTROLLER_GROUP_NAME)[0])
            return u

        cls.clerk = member('rbclerk', cls.dept)                 # بلا دور
        cls.desk = member('rbdesk', cls.dept, desk=True)        # مختصُّ بريد القسم
        cls.target = member('rbtarget', cls.contracts)          # القسمُ المستقبِل
        cls.book = Book.objects.create(
            kind='incoming_external', title='كتابٌ إلى العقود', created_by=cls.clerk,
            department=cls.dept, our_number='2450',
        )
        cls.row = distribute(cls.book, [cls.contracts], by=cls.clerk)[0]

    def _page(self, user):
        self.client.force_login(user)
        resp = self.client.get('/books/%d/' % self.book.pk)
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode()

    def _button(self, act):
        import re
        return re.compile(r'data-referral-act="%s"\s+data-referral-id="%d"' % (act, self.row.pk))

    def test_a_plain_member_of_the_owner_chases_but_does_not_close(self):
        body = self._page(self.clerk)
        self.assertRegex(body, self._button('remind'))
        for act in ('received', 'done', 'returned'):
            self.assertNotRegex(body, self._button(act))

    def test_the_receiving_department_closes_but_does_not_chase_itself(self):
        body = self._page(self.target)
        for act in ('received', 'done', 'returned'):
            self.assertRegex(body, self._button(act))
        self.assertNotRegex(body, self._button('remind'))

    def test_the_owning_desk_has_both(self):
        body = self._page(self.desk)
        for act in ('received', 'done', 'returned', 'remind'):
            self.assertRegex(body, self._button(act))

    def test_flags_agree_with_the_guards(self):
        """التطابقُ البنيويّ: العلمُ = «الحارسُ لا يرفع» لكلّ ناظرٍ على صفٍّ مفتوح."""
        from django.core.exceptions import PermissionDenied

        from core.referral_service import _guard_chaser, _guard_target, reply_matrix

        def allowed(guard, row, user):
            try:
                guard(row, user)
            except PermissionDenied:
                return False
            return True

        for user in (self.clerk, self.desk, self.target):
            items = reply_matrix(self.book, user)
            self.assertEqual(len(items), 1)
            with self.subTest(user=user.username):
                self.assertEqual(items[0]['can_act'], allowed(_guard_target, self.row, user))
                self.assertEqual(items[0]['can_chase'], allowed(_guard_chaser, self.row, user))


class HeaderRefreshesInPlaceTests(LifecyclePanelTestCase):
    """P0 البند 11: الترويسةُ تتحدّث بعد «عهدة» و«قيِّده عندنا».

    `refreshInPlace` يستبدل **المناطقَ الموسومة** وحدَها (`[data-lifecycle-refresh]`
    بمعرّف) — وبطاقةُ العهدة وشريطُ القيود في الترويسة كانا بلا وسم، فيبقى
    «لم تُسجَّل عهدة» بعد تسجيلها. والشريطُ كان يغيب كلُّه حين لا قيد، فلا
    يجد السكربتُ عنصراً يملؤه بعد أوّل قيد.
    """

    REGIONS = ('bookCustodyCard', 'bookRegsBar')

    def test_both_header_regions_are_tagged_even_when_empty(self):
        body = self._page(self.bare)
        for region in self.REGIONS:
            self.assertIn('id="%s" data-lifecycle-refresh' % region, body)

    def test_the_fresh_page_carries_the_new_holder_and_register(self):
        """ما يجلبه السكربتُ بعد الفعل يحمل الحقيقةَ الجديدة في المعرّف نفسِه."""
        import re

        record_custody(self.bare, CustodyEvent.UNIT_RECEIPT, to_department=self.unit,
                       by=self.clerk)
        register_book_here(self.bare, self.gm, by=self.clerk)
        body = self._page(self.bare)
        custody = re.search(r'id="bookCustodyCard" data-lifecycle-refresh>(.*?)</div>\s*</div>\s*</div>',
                            body, re.S)
        self.assertIsNotNone(custody)
        self.assertIn('شعبة الموازنة', custody.group(1))
        regs = body[body.index('id="bookRegsBar"'):]
        self.assertIn('مكتب المدير العام', regs[:1500])
