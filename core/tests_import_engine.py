# -*- coding: utf-8 -*-
"""اختبارات core/import_engine.py — محرك استيراد البيانات القديمة.

يغطّي: تحويل التواريخ، خرائط النوع/السرية، منطق الأرشفة الموحَّد،
معالجة تكرار الأرقام، إنشاء الجهات والكتب، dry_run، والوسم/السجل.
"""
from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase

from .models import Book, Entity, BookHistory, Tag
from .import_engine import LegacyImportEngine


def make_engine(user, dry_run=False):
    # field_map فارغ → تُستخدم أسماء حقول LetterSys مباشرةً في السجلات
    return LegacyImportEngine(field_map={}, import_user=user, dry_run=dry_run)


class ParseDateTests(TestCase):
    def test_iso(self):
        self.assertEqual(LegacyImportEngine._parse_date('2024-01-15'), date(2024, 1, 15))

    def test_slash_dmy(self):
        self.assertEqual(LegacyImportEngine._parse_date('15/01/2024'), date(2024, 1, 15))

    def test_datetime_iso(self):
        self.assertEqual(LegacyImportEngine._parse_date('2024-01-15T10:30:00'), date(2024, 1, 15))

    def test_date_passthrough(self):
        self.assertEqual(LegacyImportEngine._parse_date(date(2024, 1, 15)), date(2024, 1, 15))

    def test_empty_and_invalid_return_none(self):
        self.assertIsNone(LegacyImportEngine._parse_date(''))
        self.assertIsNone(LegacyImportEngine._parse_date(None))
        self.assertIsNone(LegacyImportEngine._parse_date('غير صالح'))


class FieldGetTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u', password='p')

    def test_case_insensitive_lookup(self):
        eng = make_engine(self.user)
        self.assertEqual(eng._get({'Our_Number': '123'}, 'our_number', ''), '123')

    def test_field_map_translation(self):
        eng = LegacyImportEngine(field_map={'our_number': 'LetterNo'}, import_user=self.user)
        self.assertEqual(eng._get({'LetterNo': 'A-9'}, 'our_number', ''), 'A-9')

    def test_default_when_missing(self):
        eng = make_engine(self.user)
        self.assertEqual(eng._get({}, 'title', 'افتراضي'), 'افتراضي')


class MappingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u', password='p')
        self.eng = make_engine(self.user)

    def _kind(self, raw):
        r = self.eng._import_one({'title': 'ع', 'our_number': '', 'kind': raw})
        return Book.objects.get(pk=r.book_id).kind

    def test_kind_arabic_and_codes(self):
        self.assertEqual(self._kind('صادر داخلي'), 'outgoing_internal')
        self.assertEqual(self._kind('وارد'), 'incoming_external')
        self.assertEqual(self._kind('3'), 'incoming_internal')

    def test_kind_unknown_defaults_incoming_external(self):
        self.assertEqual(self._kind('شيء غريب'), 'incoming_external')

    def test_secret_map(self):
        r = self.eng._import_one({'title': 'ع', 'our_number': '', 'secret_level': 'سري'})
        self.assertEqual(Book.objects.get(pk=r.book_id).secret_level, 'secret')


class ArchiveLogicTests(TestCase):
    """منطق الأرشفة الموحَّد: is_archived صريح ← وإلا يُستنتج من due_date."""

    def setUp(self):
        self.user = User.objects.create_user('u', password='p')
        self.eng = make_engine(self.user)

    def _archived(self, **extra):
        base = {'title': 'ع', 'our_number': ''}
        base.update(extra)
        r = self.eng._import_one(base)
        return Book.objects.get(pk=r.book_id).is_archived

    def test_explicit_true(self):
        self.assertTrue(self._archived(is_archived='1'))

    def test_explicit_false(self):
        # is_archived=False ذو معنى فقط مع due_date (قاعدة النموذج: لا due_date ⇒ مؤرشف)
        self.assertFalse(self._archived(is_archived='0', due_date='2030-01-01'))

    def test_inferred_archived_when_no_due_date(self):
        self.assertTrue(self._archived())                       # لا is_archived ولا due_date

    def test_inferred_active_when_due_date_present(self):
        self.assertFalse(self._archived(due_date='2030-01-01'))  # due_date ⇒ نشط


class ImportOneTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('u', password='p')

    def test_creates_book_with_core_fields(self):
        eng = make_engine(self.user)
        r = eng._import_one({
            'our_number': '2024-100', 'title': '  كتاب مهم  ',
            'date': '2024-03-01', 'sender_number': 'S-9', 'margin': 'هامش',
        })
        self.assertTrue(r.success)
        b = Book.objects.get(pk=r.book_id)
        self.assertEqual(b.our_number, '2024-100')
        self.assertEqual(b.title, 'كتاب مهم')          # مُشذّب
        self.assertEqual(b.date, date(2024, 3, 1))
        self.assertEqual(b.sender_number, 'S-9')
        self.assertEqual(b.created_by, self.user)

    def test_dry_run_creates_nothing(self):
        eng = make_engine(self.user, dry_run=True)
        r = eng._import_one({'our_number': 'X-1', 'title': 'ع'})
        self.assertTrue(r.success)
        self.assertIsNone(r.book_id)
        self.assertEqual(Book.objects.count(), 0)

    def test_empty_title_fails(self):
        eng = make_engine(self.user)
        r = eng._import_one({'our_number': 'X-2', 'title': '   '})
        self.assertFalse(r.success)
        self.assertEqual(Book.objects.count(), 0)

    def test_duplicate_number_is_skipped_by_default(self):
        # الافتراضي الآن بلا بادئة «قديم» — التعارض يُتخطّى (لا نسخة مكرّرة بعلامة).
        eng = make_engine(self.user)
        eng._import_one({'our_number': '500', 'title': 'الأول'})
        r2 = eng._import_one({'our_number': '500', 'title': 'الثاني'})
        self.assertTrue(r2.success)
        self.assertTrue(r2.skipped)
        self.assertEqual(Book.objects.count(), 1)                  # لم يُنشأ مكرّر

    def test_duplicate_with_custom_prefix_still_disambiguates(self):
        # آلية البادئة تبقى متاحة لمن يمرّرها صراحةً (توافق).
        eng = LegacyImportEngine(field_map={}, import_user=self.user,
                                 dry_run=False, number_prefix='X-')
        eng._import_one({'our_number': '500', 'title': 'الأول'})
        r2 = eng._import_one({'our_number': '500', 'title': 'الثاني'})
        self.assertTrue(r2.success)
        self.assertFalse(r2.skipped)
        self.assertEqual(Book.objects.get(pk=r2.book_id).our_number, 'X-500')

    def test_entities_created_and_cached(self):
        eng = make_engine(self.user)
        eng._import_one({'our_number': 'E-1', 'title': 'ع',
                         'issuing_entity': 'وزارة أ', 'receiving_entity': 'وزارة ب'})
        eng._import_one({'our_number': 'E-2', 'title': 'ع2',
                         'issuing_entity': 'وزارة أ'})   # نفس الجهة → من الكاش
        self.assertEqual(eng.summary.entities_created, 2)
        self.assertEqual(Entity.objects.filter(name__in=['وزارة أ', 'وزارة ب']).count(), 2)
        b1 = Book.objects.get(our_number='E-1')
        self.assertEqual(b1.issuing_entities.first().name, 'وزارة أ')

    def test_legacy_tag_and_history_recorded(self):
        eng = make_engine(self.user)
        r = eng._import_one({'our_number': 'H-1', 'title': 'ع', 'date': '2024-01-01'})
        b = Book.objects.get(pk=r.book_id)
        self.assertTrue(b.tags.filter(slug='legacy-import').exists())
        self.assertTrue(BookHistory.objects.filter(book=b, action='create').exists())
