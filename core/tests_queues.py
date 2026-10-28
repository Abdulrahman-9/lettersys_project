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

    def test_received_action_has_its_own_work_queue(self):
        referral = self._referral(
            status=BookReferral.RECEIVED, due_date=self.today + timedelta(days=2),
        )
        self.client.force_login(self.clerk)

        res = self.client.get(reverse('desk_board'))
        queue = next(q for q in res.context['queues'] if q['key'] == 'received_action')

        self.assertEqual(queue['total'], 1)
        self.assertEqual(queue['rows'][0]['referral'], referral)
        self.assertEqual(queue['rows'][0]['status_label'], 'مستلَم')
        self.assertEqual(queue['rows'][0]['purpose_label'], 'للتنفيذ')

    def test_desk_classification_shows_one_queue_in_a_structured_table(self):
        self._referral(due_date=self.today - timedelta(days=1))
        self._referral(due_date=self.today)
        self.client.force_login(self.clerk)
        response = self.client.get(reverse('desk_board'), {'queue': 'overdue'})
        self.assertEqual(response.context['selected_queue']['key'], 'overdue')
        self.assertContains(response, 'class="desk-queue-table"', count=1)
        self.assertContains(response, 'class="desk-queue-panel ', count=1)
        self.assertNotContains(response, 'class="qb-grid"')
        self.assertNotContains(response, 'id="recent-books"')
        self.assertContains(response, 'الجهة المحال إليها')
        self.assertContains(response, 'موعد الإنجاز')

    def test_recent_actions_identify_the_recipient_and_distinguish_arrival_from_custody(self):
        self._referral(due_date=self.today)
        self.client.force_login(self.clerk)
        response = self.client.get(reverse('desk_board'))
        self.assertContains(response, 'class="desk-referral-actions"')
        self.assertContains(response, '<legend>وحدة التقارير</legend>')
        self.assertContains(response, 'data-desk-target="وحدة التقارير"')
        self.assertContains(response, 'تأكيد وصول الإحالة')
        self.assertContains(response, 'لا يوثّق توقيعاً ورقياً')

    def test_unknown_desk_classification_is_not_silently_ignored(self):
        self.client.force_login(self.clerk)
        self.assertEqual(self.client.get(reverse('desk_board'), {'queue': 'unknown'}).status_code, 404)

    def test_dashboard_queue_links_select_the_corresponding_desk_tab(self):
        from core.dashboard_sections import _to

        self.assertEqual(
            _to('desk_board', anchor='overdue'),
            reverse('desk_board') + '?queue=overdue#q-overdue',
        )

    def test_desk_expand_preserves_selected_classification(self):
        from core.views.queues import ROW_LIMIT

        for _ in range(ROW_LIMIT + 1):
            self._referral(due_date=self.today)
        self.client.force_login(self.clerk)
        response = self.client.get(reverse('desk_board'), {'queue': 'today'})
        self.assertContains(response, '?queue=today&amp;expand=today#q-today')
        expanded = self.client.get(reverse('desk_board'), {'queue': 'today', 'expand': 'today'})
        self.assertEqual(len(expanded.context['selected_queue']['rows']), ROW_LIMIT + 1)

    def test_info_referrals_do_not_count_as_due_today_or_overdue(self):
        self._referral(
            purpose=BookReferral.INFO,
            due_date=self.today,
        )
        self._referral(
            purpose=BookReferral.INFO,
            due_date=self.today - timedelta(days=1),
        )
        self.client.force_login(self.clerk)

        totals = {q['key']: q['total'] for q in self.client.get(reverse('desk_board')).context['queues']}

        self.assertEqual(totals['today'], 0)
        self.assertEqual(totals['overdue'], 0)
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

    def test_recent_books_show_live_department_books_only(self):
        live = self._book(title='حيّ')
        self._referral(book=live, due_date=self.today + timedelta(days=1))
        Book.objects.create(
            kind='incoming_external', title='إرث', our_number='9002',
            department=self.dept, created_by=self.clerk, source_ref='IIMAIL_2025#1',
        )
        Book.objects.create(
            kind='incoming_external', title='تدريب', our_number='T131',
            department=self.dept, created_by=self.clerk, is_training=True,
        )
        self.client.force_login(self.clerk)

        recent = self.client.get(reverse('desk_board')).context['recent_books']

        titles = [b.title for b in recent]
        self.assertIn('حيّ', titles)
        self.assertNotIn('إرث', titles)
        self.assertNotIn('تدريب', titles)
        row = next(b for b in recent if b.title == 'حيّ')
        self.assertEqual(row.desk_referrals[0].target_name, 'وحدة التقارير')

    def test_cancel_referral_from_desk_keeps_history_and_closes_row(self):
        referral = self._referral(due_date=self.today + timedelta(days=1))
        self.client.force_login(self.clerk)

        response = self.client.post(
            reverse('desk_cancel_referral', args=[referral.book_id, referral.pk]),
            {'note': 'توجيهٌ بديل'},
            follow=True,
        )
        referral.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(referral.status, BookReferral.CANCELLED)
        self.assertFalse(BookReferral.objects.filter(
            pk=referral.pk, status__in=BookReferral.OPEN_STATUSES,
        ).exists())

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


class QueueExpandTests(TestCase):
    """مواصفةُ الواجهات، الدفعتان 1–2: «و{n} غيرها» بابٌ لا طريقٌ مسدود — ``?expand=<key>``
    يرفع القطعَ عن طابورٍ واحد، والبطاقةُ تحمل مرساةً ``id="q-<key>"`` تشير إليها عدّاداتُ الداشبورد."""

    def setUp(self):
        from core.models import Department, UserProfile
        self.dept = Department.objects.create(name='قسمُ التوسيع', code='ق-ع')
        self.me = User.objects.create_user('qexp', password='pw-qexp-11')
        UserProfile.objects.create(user=self.me, department=self.dept)
        today = timezone.localdate()
        for i in range(15):
            b = Book.objects.create(kind='incoming_internal', title=f'ك{i}', created_by=self.me,
                                    department=self.dept)
            BookReferral.objects.create(book=b, from_department=self.dept, to_department=self.dept,
                                        assignee=self.me, purpose=BookReferral.ACTION,
                                        due_date=today - timedelta(days=1), created_by=self.me)
        self.client.force_login(self.me)

    def test_the_card_is_cut_and_links_to_its_expansion(self):
        r = self.client.get(reverse('my_today'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'id="q-overdue"')
        self.assertContains(r, '?expand=overdue#q-overdue')
        self.assertContains(r, 'و3 غيرها')

    def test_expand_lifts_the_cut_for_that_queue_only(self):
        r = self.client.get(reverse('my_today') + '?expand=overdue')
        self.assertNotContains(r, '?expand=overdue#q-overdue')   # لم يعد مقطوعاً
        self.assertContains(r, 'is-expanded', count=1)            # طابورٌ واحدٌ فقط
        self.assertContains(r, '?expand=action#q-action')         # الآخرُ ما زال مقطوعاً
        self.assertContains(r, 'اطوِ')
