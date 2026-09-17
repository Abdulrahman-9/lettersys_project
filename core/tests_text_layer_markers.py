"""حرّاسُ مذكّرة فيبل 8 (2026-09-17): علاماتُ الموضوع الضعيفة، وطبقةُ نصٍّ بلا عربيّة لكتابٍ عربيّ النوع."""
import os
import tempfile
from types import SimpleNamespace

from django.test import SimpleTestCase

from core.extraction.matchers.pattern import PatternMatcher
from core.extraction.pipeline import AIExtractionService, _route_title_emission


class WeakSubjectMarkerTests(SimpleTestCase):
    def _title(self, text):
        pm = PatternMatcher()
        return pm.extract_title_keywords(text, num_words=12), pm.last_title_source

    def test_sub_slash_is_a_weak_marker(self):
        t, src = self._title('To / All Operating Contractors\nSub/ Administrative Order for the analysis team\n'
                             'Greeting,\nAttached herewith is a copy')
        self.assertIn('Administrative', t)
        self.assertEqual(src, 'marker_weak')

    def test_meem_at_end_of_english_line_is_a_weak_marker(self):
        t, src = self._title('الى/ قسم شؤون التراخيص البترولية\n'
                             'The Reason for Contract Execution Delay Provision Stage /م\nتحية طيبة')
        self.assertIn('Reason', t)
        self.assertEqual(src, 'marker_weak')

    def test_weak_marker_is_routed_to_a_suggestion_not_the_field(self):
        r = SimpleNamespace(title='Administrative Order', title_confidence=0.5, title_suggestion=None)
        _route_title_emission(r, 'marker_weak')
        self.assertEqual(r.title, '')
        self.assertEqual(r.title_suggestion['source'], 'marker_weak')


class TextLayerArabicKindGuardTests(SimpleTestCase):
    ENGLISH = ('This letter concerns the diesel supply to be provided by the company. To support proper '
               'planning the contractor has prepared the September delivery schedule. We would appreciate '
               'your support in sharing this schedule with your team while the contractor will communicate '
               'the same information to the relevant stakeholders. ') * 2

    def _pdf(self, text):
        import fitz
        fd, path = tempfile.mkstemp(suffix='.pdf')
        os.close(fd)
        doc = fitz.open()
        doc.new_page().insert_textbox(fitz.Rect(40, 40, 560, 800), text, fontsize=10)
        doc.save(path)
        doc.close()
        self.addCleanup(os.remove, path)
        return path

    def test_latin_only_layer_is_rejected_for_arabic_by_construction_kinds(self):
        path = self._pdf(self.ENGLISH)
        for kind in ('incoming_internal', 'outgoing_internal', 'outgoing_external'):
            self.assertIsNone(AIExtractionService._extract_pdf_text_layer(object(), path, book_kind=kind), kind)

    def test_same_layer_is_still_taken_for_incoming_external(self):
        path = self._pdf(self.ENGLISH)
        self.assertTrue(AIExtractionService._extract_pdf_text_layer(object(), path, book_kind='incoming_external'))
