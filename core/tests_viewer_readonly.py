# -*- coding: utf-8 -*-
"""«قارئ فقط» يقرأ ويعلّق ولا يكتب — قرارُ المالك 2026-11-01.

كان الدورُ تسميةَ عرضٍ (``roles.get_user_role``) لا تمنع شيئاً: القارئُ حذف كتابَ قسمه.
المسندُ اليوم مفاتيحُ مصفوفة الأدوار ((ب)3–(ب)5 حذفت ``scoping.can_write``؛ كان عضويّةً أو رئاسةَ قسم، أو
مديرُ النظام) مطويٌّ في ``can_edit_book``، ومعه ``can_act_on_book`` لأفعال الصفّ،
وحارسا ``writer_required``/``writer_required_api`` لنقاط الإنشاء بلا كتاب.

١. **العقد**: مَن يكتب ومَن لا — دوراً دوراً، والقائمةُ الصريحة تطابق مجموعات الأدوار.
٢. **القراءةُ لم تتغيّر**: القارئُ وزميلُه المُدخِل يريان ويفتحان الشيءَ نفسَه.
٣. **كلُّ نقطة كتابة ترفضه** ولا يتغيّر في القاعدة صفّ.
٤. **التعليقُ له**: يضيف ويعدّل تعليقَه ويحذفه.
"""
import json

from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.test import TestCase

from core import roles
from core.models import (Book, BookComment, BookEmailLog, BookHistory, BookLink,
                         BookNumberReservation, BookReferral, BookRegistration,
                         CustodyEvent, Department, EmailThread, Entity, UserProfile)
from core.scoping import (can_edit_book, can_enter_book, can_link_book, can_register_book,
                          can_open_content, can_view_book, scope_books_for)


def _member(name, dept, group=None, *, head=False, staff=False, active=True):
    user = User.objects.create_user(name, password=f'pw-{name}-1101', is_staff=staff,
                                    is_active=active)
    UserProfile.objects.update_or_create(user=user, defaults={'department': dept,
                                                              'is_department_head': head})
    if group:
        user.groups.add(Group.objects.get(name=group))
    return user


class CanWriteContractTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        roles.ensure_role_groups()
        Group.objects.get_or_create(name=roles.ARCHIVE_ALL_GROUP_NAME)
        cls.dept = Department.objects.create(name='العقد', code='ع-1101')

    def test_who_writes(self):
        root = User.objects.create_superuser('cw_root', 'r@x.com', 'pw-root-1101')
        cases = {
            'superuser': (root, True),
            'head_without_groups': (_member('cw_head', self.dept, head=True), True),
            'entry': (_member('cw_entry', self.dept, roles.ENTRY_GROUP_NAME), True),
            'controller': (_member('cw_ctl', self.dept, roles.CONTROLLER_GROUP_NAME), True),
            'archivist': (_member('cw_arc', self.dept, roles.ARCHIVIST_GROUP_NAME), True),
            'company_archivist': (_member('cw_all', self.dept, roles.ARCHIVE_ALL_GROUP_NAME), True),
            'viewer': (_member('cw_viewer', self.dept), False),
            'staff_alone': (_member('cw_staff', self.dept, staff=True), False),
            'inactive_entry': (_member('cw_off', self.dept, roles.ENTRY_GROUP_NAME,
                                       active=False), False),
        }
        for label, (user, expected) in cases.items():
            with self.subTest(label):
                # (ب)3–(ب)5: حُذف ``can_write``؛ «يكتب» = يملك مفتاحَ الإدخال في مصفوفة الأدوار
                self.assertIs(can_enter_book(user), expected)


class ViewerReadsLikeAColleagueTests(TestCase):
    """القارئُ والمُدخِلُ في القسم نفسِه يريان ويفتحان الشيءَ نفسَه — والكتابةُ وحدَها تفترق."""

    @classmethod
    def setUpTestData(cls):
        roles.ensure_role_groups()
        d = Department.objects.create(name='المتابعة', code='م-1101')
        other = Department.objects.create(name='العقود', code='ق-1101')
        cls.viewer = _member('rv_viewer', d)
        cls.entry = _member('rv_entry', d, roles.ENTRY_GROUP_NAME)
        owner = _member('rv_owner', d, roles.ENTRY_GROUP_NAME)
        stranger = _member('rv_stranger', other, roles.ENTRY_GROUP_NAME)
        cls.books = [
            Book.objects.create(kind='incoming_internal', title='عاديّ', created_by=owner,
                                department=d),
            Book.objects.create(kind='incoming_internal', title='سرّيّ', created_by=owner,
                                department=d, secret_level='secret'),
            Book.objects.create(kind='incoming_internal', title='قسمٌ آخر',
                                created_by=stranger, department=other),
        ]

    def test_same_reads_no_writes(self):
        self.assertEqual(set(scope_books_for(self.viewer)), set(scope_books_for(self.entry)))
        for book in self.books:
            with self.subTest(book.title):
                self.assertEqual(can_view_book(book, self.viewer), can_view_book(book, self.entry))
                self.assertEqual(can_open_content(book, self.viewer),
                                 can_open_content(book, self.entry))
                self.assertFalse(can_edit_book(book, self.viewer))
                self.assertFalse(can_link_book(book, self.viewer))
                self.assertFalse(can_register_book(book, self.viewer))
        self.assertTrue(can_edit_book(self.books[0], self.entry))
        self.assertTrue(can_link_book(self.books[0], self.entry))
        self.assertTrue(can_register_book(self.books[0], self.entry))


class ViewerWriteEndpointsTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        roles.ensure_role_groups()
        cls.dept = Department.objects.create(name='الوحدة', code='و-1101', entity=None)
        cls.target = Department.objects.create(name='الهدف', code='هـ-1101')
        cls.viewer = _member('wv_viewer', cls.dept)
        owner = _member('wv_owner', cls.dept, roles.ENTRY_GROUP_NAME)
        cls.entity = Entity.objects.create(name='جهة القارئ')
        cls.book = Book.objects.create(kind='incoming_internal', title='كتاب القسم',
                                       created_by=owner, department=cls.dept)
        cls.other_book = Book.objects.create(kind='incoming_internal', title='كتابٌ ثانٍ',
                                             created_by=owner, department=cls.dept)
        cls.thread = EmailThread.objects.create(book=cls.book, created_by=owner, subject='خيط')

    def setUp(self):
        cache.clear()
        self.client.force_login(self.viewer)

    def snapshot(self):
        book = Book.all_objects.get(pk=self.book.pk)
        return {
            'books': Book.all_objects.count(),
            'entities': Entity.objects.count(),
            'reservations': BookNumberReservation.objects.count(),
            'referrals': BookReferral.objects.count(),
            'custody': CustodyEvent.objects.count(),
            'links': BookLink.objects.count(),
            'registrations': BookRegistration.objects.count(),
            'emails': BookEmailLog.objects.count(),
            'history': BookHistory.objects.count(),
            'book': (book.title, book.is_deleted, book.margin, book.secret_level),
            'thread': EmailThread.objects.get(pk=self.thread.pk).status,
        }

    def post_json(self, url, payload):
        return self.client.post(url, data=json.dumps(payload), content_type='application/json')

    def test_user_level_gates_answer_read_only(self):
        """نقاطٌ بلا كتابٍ بعينه: 403 قبل أيّ بحث — بمفتاحها ``FORBIDDEN`` منذ (ب)3، والبريدُ ``READ_ONLY`` حتى (ب)5."""
        before = self.snapshot()
        b = self.book.pk
        calls = {
            'save_book': lambda: self.client.post('/books/api/book/save/', {
                'kind': 'incoming_internal', 'title': 'جديد', 'issuing_entity': 'جهةٌ جديدة'}),
            'add_entity': lambda: self.post_json('/books/api/entity/add/', {'name': 'جهةٌ جديدة'}),
            'reserve': lambda: self.post_json('/books/api/reservation/reserve/',
                                              {'kind': 'incoming_internal'}),
            'reactivate': lambda: self.post_json('/books/api/reservation/reactivate/',
                                                 {'reservation_id': 1}),
            'subject_box_confirm': lambda: self.post_json('/books/api/extract/subject-box/confirm/', {}),
            'smart_stream': lambda: self.client.post('/books/api/extract/smart/stream/', {}),
            'smart_direct': lambda: self.client.post('/books/api/extract/smart/', {}),
            'scan_upload': lambda: self.client.post('/books/api/scan/process-upload/', {}),
            'scan_agent_start': lambda: self.client.post('/books/api/scan/agent-start/', {}),
            'mail_compose': lambda: self.post_json('/books/mail/api/compose/',
                                                   {'to': 'a@b.example', 'subject': 's',
                                                    'body': 'b', 'book_id': b}),
            'mail_bulk': lambda: self.post_json('/books/mail/api/bulk-send/',
                                                {'book_ids': [b], 'subject': 's'}),
            'thread_status': lambda: self.post_json(
                f'/books/mail/api/thread/{self.thread.pk}/status/', {'status': 'closed'}),
            'email_send': lambda: self.post_json('/books/api/email/send/',
                                                 {'book_id': b, 'to': 'a@b.example'}),
            'book_email_send': lambda: self.post_json(f'/books/api/email/book/{b}/send/', {}),
        }
        for label, call in calls.items():
            with self.subTest(label):
                r = call()
                self.assertEqual(r.status_code, 403)
                self.assertEqual(r.json().get('error_code'), 'FORBIDDEN')   # كلُّها على مفاتيحها منذ (ب)5
        self.assertEqual(self.snapshot(), before)

    def test_entry_pages_are_closed(self):
        for url in ('/books/extract/smart-desktop/', '/books/mail/compose/',
                    f'/books/mail/compose/{self.book.pk}/'):
            with self.subTest(url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_book_writes_are_refused_without_effect(self):
        """على كتاب قسمه — يراه فلا يُكتم وجودُه: 403، ولا أثر."""
        before = self.snapshot()
        b, link_target = self.book.pk, self.other_book.pk
        calls = {
            'delete': lambda: self.client.post(f'/books/api/book/{b}/delete/'),
            'inline_status': lambda: self.post_json(f'/books/api/book/{b}/status-inline/',
                                                    {'status': 'done'}),
            'update': lambda: self.client.post('/books/api/book/update/',
                                               {'edit_pk': b, 'title': 'مُعدَّل'}),
            'notes': lambda: self.post_json(f'/books/api/book-notes/{b}/', {'margin': 'هامشٌ جديد'}),
            'distribute': lambda: self.post_json(f'/books/api/book/{b}/distribute/',
                                                 {'targets': [f'dep:{self.target.pk}']}),
            'custody': lambda: self.post_json(f'/books/api/book/{b}/custody/',
                                              {'to_department': self.dept.pk}),
            'register_here': lambda: self.post_json(f'/books/api/book/{b}/register-here/', {}),
            'link': lambda: self.post_json(f'/books/api/book/{b}/links/add/',
                                           {'to_book': link_target, 'relation': BookLink.REFERS}),
        }
        for label, call in calls.items():
            with self.subTest(label):
                self.assertEqual(call().status_code, 403)
        # الجماعيُّ يُجيب بعددٍ لا برمز — يكفيه أن لا يتغيّر شيء
        self.post_json('/books/api/books/bulk-delete/', {'ids': [b]})
        self.post_json('/books/api/books/bulk-status/', {'ids': [b], 'status': 'done'})
        self.client.post(f'/books/{b}/status/', {'status': 'done'})
        self.assertEqual(self.snapshot(), before)

    def test_viewer_comments(self):
        r = self.post_json(f'/books/api/book-comments/{self.book.pk}/add/', {'content': 'ملاحظة القارئ'})
        self.assertEqual(r.status_code, 200, r.content)
        comment = BookComment.objects.get(book=self.book, created_by=self.viewer)
        r = self.post_json(f'/books/api/book-comments/{comment.pk}/edit/', {'content': 'مُعدَّلة'})
        self.assertEqual(r.status_code, 200, r.content)
        comment.refresh_from_db()
        self.assertEqual(comment.content, 'مُعدَّلة')
        r = self.client.post(f'/books/api/book-comments/{comment.pk}/delete/')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(BookComment.objects.filter(pk=comment.pk).exists())

    def test_viewer_still_reads(self):
        self.assertEqual(self.client.get(f'/books/{self.book.pk}/').status_code, 200)
        self.assertEqual(self.client.get(f'/books/api/book/{self.book.pk}/preview/').status_code, 200)
