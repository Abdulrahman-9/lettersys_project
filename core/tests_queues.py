# -*- coding: utf-8 -*-
"""حرّاسُ طابورَي العمل — طاولةُ الوارد و«ما يخصّني اليوم»."""

from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Book, BookReferral, Department, Entity, UserProfile
from core.roles import CONTROLLER_GROUP_NAME


class QueueScreenTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()

        # هجرةُ بُعد القسم تُنشئ قسماً افتراضيّاً — نبني فوقه لا بجانبه.
        self.ent = Entity.objects.create(name='قسم الاختبار', code='خ.ت')
        self.dept, _ = Department.objects.get_or_create(
            code='خ.ت', defaults={'name': 'قسم الاختبار', 'entity': self.ent})
        self.unit_ent = Entity.objects.create(name='وحدة التقارير', code='خ.و')
        self.unit, _ = Department.objects.get_or_create(
            code='خ.و', defaults={'name': 'وحدة التقارير', 'entity': self.unit_ent,
                                  'parent': self.dept})

        # «مختصُّ البريد» دورٌ بمجموعةٍ في جانغو لا صفةٌ في الملفّ (core/roles.py).
        controllers, _ = Group.objects.get_or_create(name=CONTROLLER_GROUP_NAME)
        self.clerk = User.objects.create_user('clerk', 'c@x.co', 'pw')
        self.clerk.groups.add(controllers)
        UserProfile.objects.update_or_create(
            user=self.clerk, defaults={'department': self.dept})

        self.worker = User.objects.create_user('worker', 'w@x.co', 'pw')
        UserProfile.objects.update_or_create(
            user=self.worker, defaults={'department': self.unit})

    #: قيدُ التفرّد (قسم · رقم · نوع) حقيقيّ — العدّادُ هنا يحترمه.
    _seq = 2500

    def _book(self, title='كتاب', secret='normal'):
        QueueScreenTests._seq += 1
        return Book.objects.create(kind='incoming_external', title=title,
                                   our_number=str(self._seq), secret_level=secret,
                                   department=self.dept, created_by=self.clerk)

    def _referral(self, **kw):
        data = dict(book=self._book(), from_department=self.dept,
                    to_department=self.unit, status=BookReferral.SENT,
                    purpose=BookReferral.ACTION, created_by=self.clerk)
        data.update(kw)
        return BookReferral.objects.create(**data)

    # ── طاولةُ الوارد ──────────────────────────────────────────
    def test_desk_board_is_closed_to_ordinary_staff(self):
        """الطاولةُ تعرض خريطةَ عملِ القسم — ليست لكلّ موظّف."""
        self.client.force_login(self.worker)

        self.assertEqual(self.client.get(reverse('desk_board')).status_code, 403)

    def test_desk_board_sorts_referrals_into_queues(self):
        self._referral(due_date=self.today - timedelta(days=3))
        self._referral(due_date=self.today)
        self.client.force_login(self.clerk)

        res = self.client.get(reverse('desk_board'))
        totals = {q['key']: q['total'] for q in res.context['queues']}

        self.assertEqual(res.status_code, 200)
        self.assertEqual(totals['overdue'], 1)
        self.assertEqual(totals['today'], 1)
        self.assertEqual(totals['unreceived'], 2)

    def test_done_referrals_leave_every_queue(self):
        """المنجَزُ يخرج من الطابور — وإلّا صار الطابورُ أرشيفاً لا عملاً."""
        ref = self._referral(due_date=self.today - timedelta(days=1))
        ref.status = BookReferral.DONE
        ref.save(update_fields=['status'])
        self.client.force_login(self.clerk)

        res = self.client.get(reverse('desk_board'))

        self.assertEqual(sum(q['total'] for q in res.context['queues']), 0)

    def test_count_precedes_the_row_cap(self):
        """العدّادُ يقول الحقيقةَ الكاملة ولو قُطعت الصفوف."""
        from core.views.queues import ROW_LIMIT
        for _ in range(ROW_LIMIT + 3):
            self._referral(due_date=self.today)
        self.client.force_login(self.clerk)

        queue = next(q for q in self.client.get(reverse('desk_board'))
                     .context['queues'] if q['key'] == 'today')

        self.assertEqual(queue['total'], ROW_LIMIT + 3)
        self.assertEqual(len(queue['rows']), ROW_LIMIT)
        self.assertEqual(queue['more'], 3)

    def test_secret_title_is_masked_in_the_queue(self):
        """الطابورُ يعرض عناوينَ كتبٍ لم يفتحها القارئ — فالحجبُ هنا لا في القالب.

        رئيسُ القسم الأمّ يرى صفَّ الوحدة بحكم الشجرة، **ولا** يرى سرَّها:
        `secret_access` تشترط القسمَ نفسَه لا الشجرة. (السيناريو الأوّل كان
        يخدع نفسه — جعل القارئَ مختصَّ بريدِ قسمِ الكتاب وهو صاحبُ حقٍّ فيه.)
        """
        book = Book.objects.create(kind='incoming_external', title='سرٌّ مكشوف',
                                   our_number='9001', secret_level='secret',
                                   department=self.unit, created_by=self.clerk)
        self._referral(book=book, due_date=self.today)

        head = User.objects.create_user('head', 'h@x.co', 'pw')
        UserProfile.objects.update_or_create(
            user=head, defaults={'department': self.dept, 'is_department_head': True})
        self.client.force_login(head)

        res = self.client.get(reverse('desk_board'))
        titles = [r['title'] for q in res.context['queues'] for r in q['rows']]

        self.assertTrue(titles, 'الصفُّ لم يصل الطابورَ أصلاً — الاختبارُ لا يقيس شيئاً')
        self.assertNotIn('سرٌّ مكشوف', titles)

    # ── ما يخصّني اليوم ────────────────────────────────────────
    def test_my_today_is_open_to_every_role(self):
        self.client.force_login(self.worker)

        self.assertEqual(self.client.get(reverse('my_today')).status_code, 200)

    def test_my_today_shows_only_my_assignments(self):
        self._referral(assignee=self.worker, due_date=self.today)
        self._referral(assignee=self.clerk, due_date=self.today)
        self.client.force_login(self.worker)

        res = self.client.get(reverse('my_today'))

        self.assertEqual(res.context['assigned_total'], 1)
        queue = next(q for q in res.context['queues'] if q['key'] == 'today')
        self.assertEqual(queue['total'], 1)

    def test_my_today_is_empty_without_assignments(self):
        """الحالةُ الفارغةُ مصمَّمة — لا صفحةٌ مكسورة."""
        self.client.force_login(self.worker)

        res = self.client.get(reverse('my_today'))

        self.assertEqual(res.context['assigned_total'], 0)
        self.assertContains(res, 'لا التزامَ مفتوحاً')
