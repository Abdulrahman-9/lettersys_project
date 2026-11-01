# -*- coding: utf-8 -*-
"""كتبُ الدفتر القديم بلا قسم (دمجُ 2026‑10‑27: 2,622 كتاباً) — الأمرُ الذي يُصلح
ما دخل، والمحرّكُ الذي يمنع تكراره (قرارُ المالك 2026‑11‑01: سجلٌّ واحدٌ لقسم المتابعة)."""
import csv
import io
import tempfile
from collections import defaultdict
from pathlib import Path

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from core.legacy_restore import LegacyRestoreEngine
from core.models import Book, BookSequence, Department


class AssignRegisterDepartmentTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.register = Department.objects.create(name='قسمُ سجلّ الاختبار', code='ش13-ت')
        cls.other = Department.objects.create(name='قسمٌ آخر للاختبار', code='ش5-ت')
        cls.user = User.objects.create_user('legacy-owner', password='legacy-owner-pass-1234')

        def book(source_ref, department=None, kind='incoming_internal'):
            return Book.objects.create(kind=kind, title='كتاب', date=timezone.localdate(),
                                       created_by=cls.user, department=department,
                                       source_ref=source_ref)

        cls.incoming = book('IIMAIL_2026#1')
        cls.outgoing = book('IOMAIL_2026#2', kind='outgoing_internal')
        cls.app_orphan = book('')                       # من التطبيق — لا يُلمَس
        cls.assigned = book('IIMAIL_2026#3', cls.other)  # له قسم — لا يُلمَس

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.report = self.tmp / 'report.csv'

    def _run(self, *args):
        out = io.StringIO()
        call_command('assign_register_department', '--department', self.register.code,
                     '--report', str(self.report), *args, stdout=out)
        return out.getvalue()

    def _departments(self):
        return {b.pk: b.department_id for b in Book.all_objects.filter(
            pk__in=(self.incoming.pk, self.outgoing.pk, self.app_orphan.pk, self.assigned.pk))}

    def test_the_preview_changes_nothing(self):
        before = self._departments()
        out = self._run()
        self.assertIn('كتبٌ قديمةٌ بلا قسم: 2', out)
        self.assertIn('معاينة', out)
        self.assertEqual(self._departments(), before)
        self.assertFalse(self.report.exists())

    def test_yes_files_only_the_legacy_orphans(self):
        self._run('--yes')
        after = self._departments()
        self.assertEqual((after[self.incoming.pk], after[self.outgoing.pk]),
                         (self.register.pk, self.register.pk))
        self.assertIsNone(after[self.app_orphan.pk])
        self.assertEqual(after[self.assigned.pk], self.other.pk)
        with self.report.open(encoding='utf-8') as fh:
            self.assertEqual(len(list(csv.DictReader(fh))), 2)

    def test_a_source_prefix_narrows_it(self):
        self._run('--yes', '--source', 'IOMAIL_2026')
        after = self._departments()
        self.assertEqual(after[self.outgoing.pk], self.register.pk)
        self.assertIsNone(after[self.incoming.pk])

    def test_undo_returns_what_the_report_filed(self):
        self._run('--yes')
        Book.all_objects.filter(pk=self.outgoing.pk).update(department=self.other)  # غيّره أحدٌ بعدها
        out = io.StringIO()
        call_command('assign_register_department', '--undo', str(self.report), '--yes', stdout=out)
        after = self._departments()
        self.assertIsNone(after[self.incoming.pk])
        self.assertEqual(after[self.outgoing.pk], self.other.pk)   # لا يُرجَع ما تغيّر بعده
        self.assertEqual(after[self.assigned.pk], self.other.pk)


class RestoreEngineFilesInTheRegisterTests(TestCase):
    """المحرّكُ كان يُنشئ الكتابَ بلا قسم إلّا الصادرَ الخارجيّ."""

    def setUp(self):
        self.register = BookSequence.resolve_department() or Department.objects.create(
            name='قسمُ سجلّ المحرّك', code='ش13-م')
        self.user = User.objects.create_user('legacy-engine', password='legacy-engine-pass-1234')
        self.engine = LegacyRestoreEngine('server', 'db', 'user', 'password')

    def _upsert(self, source_ref, by_sref=None, mode='skip_existing'):
        row = {'IINUM': '55', 'IISUB': 'موضوعٌ قديم', 'IIWID': '12'}
        self.engine._upsert_row(row, 'II', 'incoming_internal', False, 2026, self.user,
                                False, mode, source_ref, by_sref or {}, defaultdict(int))

    def test_a_new_legacy_book_lands_in_the_register_department(self):
        self._upsert('IIMAIL_2026#900')
        self.assertEqual(Book.objects.get(source_ref='IIMAIL_2026#900').department, self.register)

    def test_a_rerun_fills_a_missing_department(self):
        orphan = Book.objects.create(kind='incoming_internal', title='يتيم', date=timezone.localdate(),
                                     created_by=self.user, source_ref='IIMAIL_2026#901')
        self._upsert('IIMAIL_2026#901', by_sref={'IIMAIL_2026#901': orphan.pk})
        orphan.refresh_from_db()
        self.assertEqual(orphan.department, self.register)
