# -*- coding: utf-8 -*-
"""صفحةُ التقارير على **المصدر الوحيد للرؤية** وبحجبِ محتوى السرّيّ.

كانت التقاريرُ تحمل نسختَها الخاصّة من قاعدة الرؤية («المشرف الكلّ، وغيرُه
كتبَه فقط»)، فيرى موظّفُ القسم في لوحته رقمَ قسمه وفي التقارير كتبَه هو. وبعد
توسيع النطاق إلى القسم صار لزاماً أن يُحجب محتوى السرّيّ فيها — في الجدول
والتصدير وفلتر الجهة — كما يُحجب في القائمة.

(مراجعةُ فيبل 2026‑09‑27 · P0‑1/P0‑2/P0‑3.)
"""
import csv
import io
import re
from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Book, BookHistory, Department, Entity, UserProfile
from core.roles import CONTROLLER_GROUP_NAME
from core.scoping import ACCESS_STUB, STUB_TITLE, restricted_flag_sql, secret_access


def _tbody(resp):
    """جسمُ جدول النتائج وحدَه — قائمةُ الجهات في النموذج تحمل كلَّ الأسماء عمداً،
    وجدولُ «بحسب القسم» يسبقه حين تجتمع أقسامٌ عدّة."""
    html = resp.content.decode('utf-8')
    m = re.search(r'id="reportTable".*?<tbody>(.*?)</tbody>', html, re.S)
    assert m, 'لا جدولَ نتائج في الصفحة'
    return m.group(1)


def _csv_rows(resp):
    body = b''.join(resp.streaming_content).decode('utf-8').lstrip('\ufeff')
    return list(csv.reader(io.StringIO(body)))


class ReportsScopeTestCase(TestCase):
    """قسمٌ «ق» بشعبةٍ «ش» وقسمٌ آخر «خ»؛ وسرّيٌّ في «ق» وسرّيٌّ في «ش»."""

    @classmethod
    def setUpTestData(cls):
        cls.today = timezone.localdate()
        cls.q = Department.objects.create(name='قسمُ التقرير', code='ر.ق')
        cls.sh = Department.objects.create(name='شعبةُ التقرير', code='ر.ش', parent=cls.q)
        cls.kh = Department.objects.create(name='قسمٌ آخر', code='ر.خ')

        def member(name, dept, *, head=False, controller=False):
            u = User.objects.create_user(name, password=f'pw-{name}-1111')
            UserProfile.objects.update_or_create(
                user=u, defaults={'department': dept, 'is_department_head': head})
            if controller:
                group, _ = Group.objects.get_or_create(name=CONTROLLER_GROUP_NAME)
                u.groups.add(group)
            return u

        cls.clerk = member('rclerk', cls.q)
        cls.head = member('rhead', cls.q, head=True)
        cls.officer = member('rofficer', cls.q, controller=True)
        cls.author = member('rauthor', cls.q)
        cls.unit = member('runit', cls.sh)
        cls.stranger = member('rstranger', cls.kh)
        cls.admin = User.objects.create_superuser('radmin', 'ra@x.co', 'pw-radmin-1111')

        cls.ent_plain = Entity.objects.create(name='جهةٌ علنيّةٌ للتقرير')
        cls.ent_secret = Entity.objects.create(name='جهةُ المناقصة المحجوبة')
        cls.ent_secret_sh = Entity.objects.create(name='جهةُ الشعبة المحجوبة')

        def book(title, by, dept, num, *, due=3, **kw):
            b = Book.objects.create(
                kind=kw.pop('kind', 'incoming_internal'), title=title, created_by=by,
                department=dept, our_number=num, date=cls.today,
                due_date=cls.today + timedelta(days=due) if due is not None else None,
                is_archived=due is None, **kw)
            return b

        cls.colleague = book('كتابُ الزميل', cls.author, cls.q, '3101')
        cls.colleague.issuing_entities.add(cls.ent_plain)
        cls.own = book('كتابُ الكاتب', cls.clerk, cls.q, '3102', due=-2)
        cls.outgoing = book('صادرُ القسم', cls.author, cls.q, '3103',
                            kind='outgoing_internal', due=0)
        cls.foreign = book('كتابُ القسم الآخر', cls.stranger, cls.kh, '3104')
        cls.secret_q = book('مناقصةٌ سرّيّةٌ للحفر', cls.author, cls.q, '3105',
                            secret_level='secret', sender_number='ش/9 771',
                            sender_date=cls.today - timedelta(days=4),
                            margin='هامشٌ حسّاسٌ جدّاً')
        cls.secret_q.issuing_entities.add(cls.ent_secret)
        cls.secret_sh = book('تقريرُ الشعبة السرّيّ', cls.unit, cls.sh, '3106',
                             secret_level='secret', sender_number='5512',
                             margin='هامشُ الشعبة الخاصّ')
        cls.secret_sh.issuing_entities.add(cls.ent_secret_sh)

    def _reports(self, user, **params):
        self.client.force_login(user)
        return self.client.get(reverse('reports'), params)

    def _export(self, user, **params):
        self.client.force_login(user)
        return self.client.get(reverse('reports_export'), params)


class ScopeTests(ReportsScopeTestCase):

    def test_the_head_sees_his_colleagues_book_and_not_another_department(self):
        """الرئيسُ يرى كتابَ موظّفٍ في قسمه (لا كتبَه هو وحدَها) ولا يرى القسمَ الآخر.
        (والتقاريرُ للرئيس والمدير وحدَهما — ``tests_reports_gate``.)"""
        resp = self._reports(self.head, bucket='all')
        self.assertEqual(resp.status_code, 200)
        body = _tbody(resp)
        self.assertIn('كتابُ الزميل', body)
        self.assertNotIn('كتابُ القسم الآخر', body)

    def test_the_head_sees_the_units_books(self):
        """الشجرةُ تسيل نزولاً: رئيسُ «ق» يرى صفَّ «ش» (محجوبَ المحتوى)."""
        pks = [b.pk for b in self._reports(self.head, bucket='all').context['books']]
        self.assertIn(self.secret_sh.pk, pks)

    def test_active_incoming_is_the_dashboards_number(self):
        """الرقمُ الذي تفتحه اللوحة هو الرقمُ الذي تعدّه التقارير — لا رقمٌ ثالث."""
        for user in (self.head, self.admin):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                dash = self.client.get(reverse('dashboard')).context['incoming_pending']
                total = self._reports(user, bucket='active', kind='incoming').context['total']
                self.assertEqual(total, dash)
                self.assertGreater(total, 0)


class SecretMaskingTests(ReportsScopeTestCase):

    #: (القارئ، الكتابُ المحجوبُ عنه، جهتُه) — الرئيسُ على سرّيّ شعبته (الحقُّ
    #: بالدور على قسمه لا على شجرته — ``secret_access``). والكاتبُ لا تقاريرَ له
    #: أصلاً منذ بوّابة الدور؛ حجبُه يحرسه ``test_the_restricted_flag_is_secret_access``.
    def _cases(self):
        return ((self.head, self.secret_sh, self.ent_secret_sh),)

    def test_the_restricted_flag_is_secret_access(self):
        """علَمُ SQL توأمُ ``secret_access`` فاعلاً فاعلاً — لا ينحرفان."""
        for user in (self.clerk, self.head, self.officer, self.author, self.unit,
                     self.stranger, self.admin):
            for b in (self.secret_q, self.secret_sh, self.colleague):
                with self.subTest(user=user.username, book=b.our_number):
                    flag = (Book.objects.filter(pk=b.pk)
                            .annotate(r=restricted_flag_sql(user)).get().r)
                    self.assertEqual(flag, secret_access(user, b) == ACCESS_STUB)

    def test_html_shows_the_stub_and_no_content(self):
        for user, secret, ent in self._cases():
            with self.subTest(user=user.username):
                resp = self._reports(user, bucket='all')
                row = next(b for b in resp.context['books'] if b.pk == secret.pk)
                self.assertEqual(row.shown_title, STUB_TITLE)
                body = _tbody(resp)
                self.assertIn(STUB_TITLE, body)
                self.assertNotIn(secret.title, body)
                self.assertNotIn(ent.name, body)
                self.assertNotIn(secret.sender_number, body)
                self.assertNotIn(secret.margin, body)

    def test_the_owner_of_the_content_still_sees_it(self):
        """حارسُ عدم الانحدار: رئيسُ «ق» يملك سرّيَّ قسمه، والمديرُ كلَّه."""
        for user, secret in ((self.head, self.secret_q), (self.admin, self.secret_sh)):
            with self.subTest(user=user.username):
                body = _tbody(self._reports(user, bucket='all'))
                self.assertIn(secret.title, body)
                self.assertIn(secret.margin, body)

    def test_csv_shows_the_stub_and_no_content(self):
        for user, secret, ent in self._cases():
            with self.subTest(user=user.username):
                rows = _csv_rows(self._export(user, bucket='all'))
                row = next(r for r in rows if r[0] == secret.our_number_display)
                self.assertEqual(row[2], STUB_TITLE)
                text = '\n'.join(','.join(r) for r in rows)
                self.assertNotIn(secret.title, text)
                self.assertNotIn(ent.name, text)
                self.assertNotIn(secret.sender_number, text)
                self.assertNotIn(secret.margin, text)

    def test_the_entity_filter_does_not_match_a_masked_book(self):
        """السرّيُّ لا يُطابَق بجهةٍ لمن لا يملك محتواه — وإلّا كشف الفلترُ جهتَه."""
        for user, secret, ent in self._cases():
            with self.subTest(user=user.username):
                resp = self._reports(user, bucket='all', entity=ent.pk)
                self.assertNotIn(secret.pk, [b.pk for b in resp.context['books']])
                rows = _csv_rows(self._export(user, bucket='all', entity=ent.pk))
                self.assertEqual(rows[1:], [])

    def test_the_entity_filter_matches_for_the_owner_of_the_content(self):
        resp = self._reports(self.head, bucket='all', entity=self.ent_secret.pk)
        self.assertEqual([b.pk for b in resp.context['books']], [self.secret_q.pk])


class BookReportTests(ReportsScopeTestCase):

    def test_a_stranger_gets_404_not_403(self):
        """«غيرُ موجود» لا «ممنوع» — فرقُ الرمزين يُسرّب وجودَ الكتاب."""
        self.client.force_login(self.stranger)
        resp = self.client.get(reverse('book_report', args=[self.colleague.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_a_bulk_archive_is_counted(self):
        """«أُرشفت (bulk)» مشكولةٌ ولا «إنهاء» فيها — كانت لا تُحتسب."""
        BookHistory.objects.create(book=self.colleague, action='status',
                                   by=self.author, notes='أُرشفت (bulk)')
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('book_report', args=[self.colleague.pk]))
        self.assertEqual(resp.context['followup']['archives'], 1)
