# -*- coding: utf-8 -*-
"""حرّاسُ «مَن قام بهذا العمل» — ودمجِ وظيفتَي البريد والأرشفة.

**الغرضُ الذي أعلنه المالك**: يُعطي فريقَ البريد والأرشفة أكثرَ من حساب
ليقتسموا العمل، ويعرف **مَن فعل ماذا من صفحة تفاصيل الكتاب**. والنسبةُ كانت
محفوظةً في القاعدة (`by_snapshot` · `recorded_by` · `created_by`) ولا تُعرض
في سطرٍ واحد — فحرّاسُ هذا الملفّ يمنعون عودتَها إلى الصمت.

و«مسؤول إدارة البريد والأرشفة» **اجتماعُ عضويّتين لا مجموعةٌ ثالثة** — كي
يبقى بابُ الفصل مفتوحاً حين يقتسمون العمل لاحقاً.
"""

from django.contrib.auth.models import Group, User
from django.test import TestCase

from core.dashboard_sections import sections_for
from core.models import (Book, BookHistory, BookReferral, CustodyEvent,
                         Department, UserProfile)
from core.roles import (ARCHIVIST_GROUP_NAME, CONTROLLER_GROUP_NAME,
                        get_user_role)
from core.scoping import is_archivist, is_mail_officer


def _member(name, department, *, head=False, controller=False,
            archivist=False, admin=False):
    if admin:
        user = User.objects.create_superuser(name, name + '@x.co', 'pw')
    else:
        user = User.objects.create_user(name, name + '@x.co', 'pw')
    UserProfile.objects.update_or_create(
        user=user, defaults={'department': department, 'is_department_head': head})
    for wanted, group_name in ((controller, CONTROLLER_GROUP_NAME),
                               (archivist, ARCHIVIST_GROUP_NAME)):
        if wanted:
            user.groups.add(Group.objects.get_or_create(name=group_name)[0])
    return user


class MailGateIsMembershipTests(TestCase):
    """بوّابةُ البريد عضويّةٌ لا تسمية — شرطُ دمج الوظيفتين لا زينتُه."""

    @classmethod
    def setUpTestData(cls):
        cls.dept = Department.objects.create(name='قسم الدمج', code='د.م')
        cls.plain = _member('plain', cls.dept)
        cls.officer = _member('officer', cls.dept, controller=True)
        cls.head = _member('head', cls.dept, head=True)
        cls.head_officer = _member('headofficer', cls.dept, head=True, controller=True)
        cls.combined = _member('combined', cls.dept, controller=True, archivist=True)
        cls.root = _member('root', cls.dept, admin=True)

    def test_a_department_head_who_is_also_the_mail_officer_keeps_the_mail_desk(self):
        """كان يفقدها: السلسلةُ تُعيد `dept_head` فتُلغي خانتَه المؤشَّرة."""
        self.assertEqual(get_user_role(self.head_officer), 'dept_head')
        self.assertTrue(is_mail_officer(self.head_officer))

    def test_the_head_officer_sees_the_mail_section_on_his_dashboard(self):
        keys = {s['key'] for s in sections_for(self.head_officer)}

        self.assertIn('mail', keys)

    def test_the_mail_gate_answers_membership_not_the_label(self):
        """حارسٌ بنيويّ: البوّابةُ = العضويّة، فاعلاً فاعلاً."""
        for user in (self.plain, self.officer, self.head, self.head_officer,
                     self.combined, self.root):
            member = user.groups.filter(name=CONTROLLER_GROUP_NAME).exists()

            self.assertEqual(is_mail_officer(user), member, user.username)

    def test_a_department_head_without_the_group_still_has_no_mail(self):
        """التوسيعُ لا يتسرّب: الرئاسةُ وحدَها لا تفتح البريد."""
        self.assertFalse(is_mail_officer(self.head))

    def test_the_combined_officer_holds_both_doors(self):
        """«مسؤول إدارة البريد والأرشفة» = اجتماعُ عضويّتين."""
        self.assertTrue(is_mail_officer(self.combined))
        self.assertTrue(is_archivist(self.combined))

    def test_an_anonymous_visitor_is_no_officer(self):
        from django.contrib.auth.models import AnonymousUser

        self.assertFalse(is_mail_officer(AnonymousUser()))


class ActorNameTests(TestCase):
    """اسمُ الفاعل — **اللقطةُ أوّلاً** لأنّها الاسمُ وقتَ الفعل."""

    def setUp(self):
        self.dept = Department.objects.create(name='قسم النسبة', code='ن.س')
        self.user = _member('ahmad', self.dept)
        self.book = Book.objects.create(
            kind='incoming_external', title='كتابُ النسبة', our_number='9700',
            department=self.dept, created_by=self.user)

    def _row(self, **extra):
        return BookHistory.objects.create(book=self.book, action='custody', **extra)

    def test_the_snapshot_wins_over_the_live_user(self):
        """يُعاد تسميةُ الموظّف — ويبقى الاسمُ الذي وقّع به."""
        row = self._row(by=self.user, by_snapshot='أحمد كما كان')
        self.user.first_name = 'اسمٌ جديد'
        self.user.save()

        self.assertEqual(row.actor_name, 'أحمد كما كان')

    def test_the_actor_name_survives_the_deletion_of_the_user(self):
        """`by` هي SET_NULL — ولولا اللقطةُ لصار القيدُ بلا فاعل.

        والفاعلُ هنا **ليس** مُنشئَ الكتاب: `Book.created_by` هي PROTECT
        فلا يُحذف مُنشئٌ أصلاً — والحالُ الواقعيّة موظّفٌ ساهم ثمّ ترك العمل.
        """
        leaver = _member('leaver', self.dept)
        row = self._row(by=leaver, by_snapshot='أحمد الكاتب')
        leaver.delete()
        row.refresh_from_db()

        self.assertIsNone(row.by_id)
        self.assertEqual(row.actor_name, 'أحمد الكاتب')

    def test_a_row_without_a_snapshot_falls_back_to_the_live_user(self):
        row = self._row(by=self.user, by_snapshot='')

        self.assertEqual(row.actor_name, 'ahmad')

    def test_a_row_with_no_actor_at_all_reads_as_the_system(self):
        """أوامرُ الجدولة والمستوردُ تكتب بلا فاعلٍ بشريّ — و«—» تترك القارئَ يخمّن."""
        self.assertEqual(self._row().actor_name, 'النظام')

    def test_bulk_written_rows_carry_the_actor_snapshot(self):
        """`bulk_create` يتجاوز `save()` — واللقطةُ تُمرَّر صراحةً أو تضيع."""
        from datetime import timedelta

        from django.utils import timezone

        # الفعلُ الجماعيُّ لا يؤهّل إلّا المتابَع: كتابٌ بلا موعدٍ علَمُه
        # مرفوعٌ سلفاً بقاعدة `Book.save()` الذهبيّة فلا صفَّ يُكتب له.
        self.book.due_date = timezone.localdate() + timedelta(days=5)
        self.book.is_archived = False
        self.book.save()
        self.client.force_login(self.user)

        self.client.post('/books/api/books/bulk-status/',
                         data='{"book_ids": [%d], "status": "archived"}' % self.book.pk,
                         content_type='application/json')

        row = BookHistory.objects.filter(book=self.book, action='status').first()
        self.assertIsNotNone(row, 'لم يُكتب قيدٌ جماعيّ')
        self.assertTrue(row.by_snapshot, 'كُتب بلا لقطةِ اسم')


class BookDetailShowsWhoDidWhatTests(TestCase):
    """صفحةُ التفاصيل تقول **مَن** — وهي الغرضُ من تعدّد الحسابات."""

    def setUp(self):
        self.dept = Department.objects.create(name='قسم العرض', code='ع.ر')
        self.unit = Department.objects.create(name='وحدةُ التنفيذ', code='ع.و',
                                              parent=self.dept)
        self.clerk = _member('clerk', self.dept, controller=True)
        self.worker = _member('worker', self.dept)
        self.book = Book.objects.create(
            kind='incoming_external', title='كتابٌ يُتابَع', our_number='9701',
            department=self.dept, created_by=self.clerk)
        BookHistory.objects.create(book=self.book, action='referral',
                                   by=self.clerk, by_snapshot='كاتبُ البريد')
        self.client.force_login(self.worker)

    def _get(self):
        return self.client.get('/books/%d/' % self.book.pk)

    def test_the_history_row_names_the_actor(self):
        self.assertContains(self._get(), 'كاتبُ البريد')

    def test_the_history_row_speaks_arabic_not_the_raw_key(self):
        res = self._get()

        self.assertContains(res, 'تفريق/إحالة')
        self.assertNotContains(res, '>referral<')

    def test_every_content_opener_sees_the_actor_not_only_the_head(self):
        """سجلُّ **أفعالٍ على الورقة** لا سجلُّ قراءة — وعلى الورق علنيّ.

        وقصرُه على رئيس القسم يُبطل غرضَ المالك من تعدّد الحسابات: الزملاءُ
        يقتسمون العمل ولا يرون مَن فعل.
        """
        self.assertFalse(self.worker.profile.is_department_head)
        self.assertContains(self._get(), 'كاتبُ البريد')

    def test_the_custody_row_names_who_recorded_it(self):
        from core.custody_service import record_custody

        record_custody(self.book, CustodyEvent.UNIT_RECEIPT,
                       to_department=self.unit, by=self.clerk)

        # **الاسمُ لا الكلمةُ وحدَها**: زرُّ «قيّده عندنا» في الصفحة نفسِها
        # يحوي «قيّده»، فمطابقتُها وحدَها حارسٌ يمرّ على كودٍ لا يعرض شيئاً.
        self.assertContains(self._get(), 'قيّده clerk')

    def test_the_referral_row_names_who_distributed_it(self):
        BookReferral.objects.create(
            book=self.book, from_department=self.dept, to_department=self.unit,
            status=BookReferral.SENT, created_by=self.clerk)

        self.assertContains(self._get(), 'فرّقه')


class HistoryQueryTests(TestCase):
    """الحدُّ في الاستعلام لا في القالب — و`select_related` لا استعلامٌ لكلّ صفّ."""

    def setUp(self):
        self.dept = Department.objects.create(name='قسم الاستعلام', code='س.ج')
        self.user = _member('u', self.dept)
        self.book = Book.objects.create(
            kind='incoming_external', title='كتابٌ طويلُ السجلّ', our_number='9702',
            department=self.dept, created_by=self.user)
        BookHistory.objects.bulk_create([
            BookHistory(book=self.book, action='custody', by=self.user,
                        by_snapshot='فلان', notes='قيد %d' % i)
            for i in range(60)
        ])
        self.client.force_login(self.user)

    def test_the_history_is_capped_in_the_query_and_the_total_is_honest(self):
        """كتابٌ له 800 قيدٍ كان يدفع ثمنَ 800 صفٍّ ليُعرض خمسون."""
        from core.views.books_detail import HISTORY_PAGE

        ctx = self.client.get('/books/%d/' % self.book.pk).context

        self.assertEqual(len(ctx['history']), HISTORY_PAGE)
        self.assertGreaterEqual(ctx['history_total'], 60)

    def test_the_actor_is_joined_not_fetched_per_row(self):
        ctx = self.client.get('/books/%d/' % self.book.pk).context

        self.assertIn('by', ctx['history'][0]._state.fields_cache)

    def test_the_page_says_it_is_showing_only_part(self):
        res = self.client.get('/books/%d/' % self.book.pk)

        self.assertContains(res, 'يُعرض آخر')
