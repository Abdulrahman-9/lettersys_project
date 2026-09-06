# -*- coding: utf-8 -*-
"""حلقةُ تعلّم الجهات — ذاكرةُ الترويسة تتعلّم من التصحيح ولا تتعلّم من ملءٍ لم يُلمَس.

**العطبان المقيسان (2026-09-01)**:
١. `_persist_letterhead_memory` كان يعود مبكراً إن وُجد صفٌّ للكتاب — فتصحيحُ
   الكاتب بعد أوّل حفظٍ لا يبلغ الذاكرةَ أبداً، وتبقى تُعلّم الخطأَ الأوّل.
٢. لم يكن يسأل من أين جاءت الجهة: الواجهةُ تحوّل top‑1 الذاكرةِ إلى وسمٍ تلقائيّاً،
   فحفظٌ بلا لمسٍ يعيد مخرجَ الذاكرة إليها صفّاً يصوّت لنفسه (33 صفّاً من كتب
   التطبيق على القاعدة الحيّة يوم القياس). الوسمُ `autofilled` يُسكِت الجانب.
"""
from django.contrib.auth.models import User
from django.test import TestCase

from core.extraction.capture import persist_extraction_capture, refresh_letterhead_memory
from core.models import Attachment, Book, Entity, LetterheadMemory

HEAD = 'جمهورية العراق\nشركة نفط الوسط\nقسم المتابعة\nالعدد: ش13/44\nم/ طلب'


class LetterheadMemoryLearningTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('kaatib_lm', password='x')
        self.e1 = Entity.objects.create(name='قسم المتابعة', code='ش13', etype='issuer', is_active=True)
        self.e2 = Entity.objects.create(name='قسم التخطيط', code='ش14', etype='issuer', is_active=True)
        self.r1 = Entity.objects.create(name='هيئة العمليات', code='R1', etype='receiver', is_active=True)
        self.book = Book.objects.create(title='ت', kind='incoming_internal', created_by=self.user)
        self.att = Attachment.objects.create(book=self.book, file='attachments/lm.pdf')

    def _save(self, **final_extra):
        return persist_extraction_capture(
            book=self.book, attachment=self.att,
            suggested={'raw_text': HEAD, 'title': 'ت'},
            final={'title': 'ت', **final_extra}, user=self.user)

    def test_autofilled_issuing_is_not_learned(self):
        """الجانبُ المملوءُ آليّاً بلا لمسٍ لا يدخل الذاكرة — وإلّا صوّتت لنفسها."""
        self.book.issuing_entities.add(self.e1)
        self.book.receiving_entities.add(self.r1)
        self._save(issuing_entity_provenance='autofilled', receiving_entity_provenance='typed')
        row = LetterheadMemory.objects.get(book=self.book)
        self.assertIsNone(row.issuing_entity_id)
        self.assertEqual(row.receiving_entity_id, self.r1.id)

    def test_correction_after_first_save_updates_the_memory(self):
        """التصحيحُ يبلغ الذاكرةَ — كان يُهمَل بعودةٍ مبكرة."""
        self.book.issuing_entities.add(self.e1)
        self._save(issuing_entity_provenance='typed')
        self.assertEqual(LetterheadMemory.objects.get(book=self.book).issuing_entity_id, self.e1.id)
        # مسارُ التعديل: لا مسحَ جديد ولا التقاطَ ثانياً (OCRResult واحدٌ لكلّ مرفق)
        self.book.issuing_entities.set([self.e2])
        refresh_letterhead_memory(self.book, issuing_prov='typed')
        self.assertEqual(LetterheadMemory.objects.filter(book=self.book).count(), 1)
        self.assertEqual(LetterheadMemory.objects.get(book=self.book).issuing_entity_id, self.e2.id)

    def test_edit_path_does_not_learn_an_autofilled_side(self):
        self.book.issuing_entities.add(self.e1)
        self._save(issuing_entity_provenance='typed')
        self.book.issuing_entities.set([self.e2])
        refresh_letterhead_memory(self.book, issuing_prov='autofilled')
        self.assertEqual(LetterheadMemory.objects.get(book=self.book).issuing_entity_id, self.e1.id)

    def test_legacy_ui_without_provenance_still_learns(self):
        """واجهةٌ قديمةٌ لا ترسل الوسم ⟵ السلوكُ السابقُ حرفيّاً (لا انكسار)."""
        self.book.issuing_entities.add(self.e1)
        self._save()
        self.assertEqual(LetterheadMemory.objects.get(book=self.book).issuing_entity_id, self.e1.id)

    def test_provenance_lands_in_capture_record(self):
        self.book.issuing_entities.add(self.e1)
        res = self._save(issuing_entity_provenance='confirmed', receiving_entity_provenance='')
        self.assertEqual(res.additional_data['issuing_entity_provenance'], 'confirmed')
        self.assertEqual(res.additional_data['receiving_entity_provenance'], '')


class ResolveEntityCandidatesContractTests(TestCase):
    """الدالّةُ المقيسة هي الدالّةُ التي يبلغ الكاتبَ مخرجُها — لا نسخةٌ موازية."""

    def test_register_code_leads_for_issuer_and_exclusion_is_plumbed(self):
        from core.extraction.pipeline import AIExtractionService
        e = Entity.objects.create(name='قسم المتابعة', code='ش13', etype='issuer', is_active=True)
        svc = AIExtractionService()
        ranked = svc.resolve_entity_candidates('issuer', HEAD, 'incoming_internal', '', 'ش13', [],
                                               exclude_book_id=999999)
        self.assertTrue(ranked and ranked[0]['entity_id'] == e.id)
        self.assertEqual(ranked[0]['match_type'], 'register_code')

    def test_pipeline_closure_delegates_to_the_method(self):
        import os
        from django.conf import settings
        src = open(os.path.join(settings.BASE_DIR, 'core', 'extraction', 'pipeline.py'),
                   encoding='utf-8').read()
        self.assertIn('return self.resolve_entity_candidates(', src)


class DominantDestinationFallbackTests(TestCase):
    """صمتُ المستلمة يُسدّ بالوجهة السائدة لنوع الكتاب بثقةٍ منخفضة — لا للمُصدِرة."""

    def test_silent_receiver_gets_the_dominant_destination(self):
        from core.extraction import pipeline as P
        from core.extraction.pipeline import AIExtractionService
        P._DOMINANT_CACHE.clear()
        r = Entity.objects.create(name='هيئة العمليات', code='OPS', etype='receiver', is_active=True)
        u = User.objects.create_user('kaatib_dom', password='x')
        for _ in range(2):
            b = Book.objects.create(title='ت', kind='incoming_internal', created_by=u)
            b.receiving_entities.add(r)
        svc = AIExtractionService()
        got = svc.resolve_entity_candidates('receiver', 'نصٌّ بلا أيّ إشارة', 'incoming_internal', '', '', [])
        self.assertTrue(got and got[-1]['match_type'] == 'kind_prior' and got[-1]['entity_id'] == r.id)
        self.assertLessEqual(got[-1]['score'], 30.0)
        self.assertFalse(any(x.get('match_type') == 'kind_prior'
                             for x in svc.resolve_entity_candidates('issuer', 'نصٌّ', 'incoming_internal', '', '', [])))
        P._DOMINANT_CACHE.clear()

