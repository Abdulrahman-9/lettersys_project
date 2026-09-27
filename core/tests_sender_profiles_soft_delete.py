"""الفئة (ب) في كنس 7.4‑هـ: الضمُّ لا يمرّ بمدير.

بصمةُ أرقام الجهة (`SenderNumberProfiles`) تُبنى من الجدول الوسيط ومن ذاكرة الترويسة،
وكلاهما يصل إلى `Book` **بضمٍّ** لا بمدير ⟵ شرطُ `book__is_deleted=False` هناك حاملٌ
للحمل. هذان الاختباران يحمرّان إن «أكمل» أحدٌ الكنسَ بحذفه.
"""

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from core.extraction.matchers.profile import SenderNumberProfiles, induce_template
from core.models import Book, Entity, LetterheadMemory


class SenderProfilesIgnoreDeletedBooksTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('prof', password='pw-prof-11')
        cls.entity = Entity.objects.create(name='وزارةُ العقد')
        live = Book.objects.create(kind='incoming_external', title='حيّ', created_by=cls.user,
                                   sender_number='12345')
        gone = Book.objects.create(kind='incoming_external', title='محذوف', created_by=cls.user,
                                   sender_number='ABC-777', is_deleted=True,
                                   deleted_at=timezone.now())
        live.issuing_entities.add(cls.entity)
        gone.issuing_entities.add(cls.entity)
        LetterheadMemory.objects.create(letterhead='الرقم: XYZ-12345 / التاريخ',
                                        issuing_entity=cls.entity, book=live)
        LetterheadMemory.objects.create(letterhead='الرقم: QQQ-ABC-777 / التاريخ',
                                        issuing_entity=cls.entity, book=gone)

    def _profile(self):
        prof = SenderNumberProfiles()
        prof._ensure_index()
        return prof._profiles[self.entity.pk]

    def test_through_join_excludes_deleted_book_numbers(self):
        p = self._profile()
        self.assertIn(induce_template('12345'), p['templates'])
        self.assertNotIn(induce_template('ABC-777'), p['templates'],
                         'رقمُ كتابٍ محذوفٍ دخل بصمةَ الجهة — الضمُّ صار بلا شرط')

    def test_letterhead_memory_join_excludes_deleted_books(self):
        p = self._profile()
        ctx = {pre for tmpl in p['ctx_prefixes'] for pre in p['ctx_prefixes'][tmpl]}
        self.assertIn('XYZ', ctx)
        self.assertNotIn('QQQ', ctx, 'ذاكرةُ الترويسة تعلّمت من كتابٍ محذوف')
