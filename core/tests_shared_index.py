# -*- coding: utf-8 -*-
"""دفعةُ السرعة الآمنة (2026‑10‑05): الفهارسُ المشتركة، والإحماء، وقراءةُ Tesseract بلا ضغطٍ زائد.

العقدُ الذي تحرسه هذه الاختبارات: **النتيجةُ نفسُها حرفاً**.
  - الفهرسُ المشترك يُعاد بناؤه متى تغيّر مصدرُه — إشارةٌ عند الإيداع، أو بصمةُ قاعدةٍ
    تلتقط ما لا يُطلق إشارة، أو عمر — ولا يثق ببناءٍ تغيّر مصدرُه أثناءه.
  - القراءةُ السريعة ترى البكسلاتِ نفسَها التي كان pytesseract يمرّرها.
  - تحويلُ صفحة PDF بلا ضغط PNG يُعطي المصفوفةَ نفسَها بكسلاً ببكسل.
(المطابقةُ طرفاً إلى طرف على 19 كتاباً مختوماً في D:/migration/extraction_speed/accept_identical.py.)
"""
import os
import tempfile
import threading
import time
from collections import defaultdict
from unittest import mock

import cv2
import numpy as np
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase, override_settings
from PIL import Image

from core.extraction import shared_index as SI
from core.extraction import warmup as W
from core.extraction.matchers import entity as EM
from core.extraction.matchers import profile as PF
from core.extraction.ocr import providers as PR
from core.models import Book, Entity, LetterheadMemory


class _Builds:
    """دالّةُ بناءٍ تَعُدّ نداءاتها وتُعيد قيمةً جديدةً في كلّ مرّة."""

    def __init__(self, during=None):
        self.n = 0
        self.during = during

    def __call__(self):
        self.n += 1
        if self.during:
            self.during()
        return ['value', self.n]


def _index(build, signature=lambda: ('s',), ttl=300):
    return SI.SharedIndex('test', build, signature, 'NO_SUCH_SETTING_FOR_TESTS', ttl, register=False)


class SharedIndexContractTests(SimpleTestCase):
    """الآليّةُ وحدها، بلا قاعدة: متى يُعاد البناءُ ومتى يُشارَك."""

    def test_reused_while_source_is_unchanged(self):
        build = _Builds()
        idx = _index(build)
        first = idx.get()
        self.assertIs(idx.get(), first)
        self.assertEqual(build.n, 1)

    def test_zero_ttl_means_no_sharing_at_all(self):
        build = _Builds()
        idx = _index(build, ttl=0)
        idx.get(); idx.get()
        self.assertEqual(build.n, 2, 'العمرُ صفرٌ (الاختبارات) يجب أن يعني «ابنِ كما كان» لا «لا ينتهي»')
        self.assertIsNone(idx._state, 'لا يُنشَر شيءٌ بلا مشاركة')

    def test_invalidate_forces_a_rebuild(self):
        build = _Builds()
        idx = _index(build)
        idx.get()
        idx.invalidate()
        self.assertEqual(idx.get(), ['value', 2])

    def test_a_changed_database_signature_forces_a_rebuild(self):
        sig = ['a']
        build = _Builds()
        idx = _index(build, signature=lambda: (sig[0],))
        idx.get()
        sig[0] = 'b'                           # كتابةٌ من عمليّةٍ أخرى بلا إشارة
        self.assertEqual(idx.get(), ['value', 2])

    def test_age_beyond_ttl_forces_a_rebuild(self):
        build = _Builds()
        idx = _index(build, ttl=300)
        idx.get()
        later = time.monotonic() + 301
        with mock.patch.object(SI.time, 'monotonic', return_value=later):
            self.assertEqual(idx.get(), ['value', 2])

    def test_a_build_invalidated_while_running_is_not_trusted(self):
        holder = {}
        build = _Builds(during=lambda: holder['idx'].invalidate() if build.n == 1 else None)
        holder['idx'] = idx = _index(build)
        self.assertEqual(idx.get(), ['value', 1])          # نداءُ البناء نفسُه يُعيد ما بناه
        self.assertEqual(idx.get(), ['value', 2], 'بناءٌ تغيّر مصدرُه أثناءه نُشر كأنّه حديث')

    def test_a_signature_changed_while_building_is_not_trusted(self):
        sig = ['a']
        build = _Builds(during=lambda: sig.__setitem__(0, 'b') if build.n == 1 else None)
        idx = _index(build, signature=lambda: (sig[0],))
        idx.get()
        self.assertEqual(idx.get(), ['value', 2], 'البصمةُ قُرئت بعد البناء لا قبله')

    def test_a_failed_build_publishes_nothing(self):
        calls = {'n': 0}

        def build():
            calls['n'] += 1
            if calls['n'] == 2:
                raise RuntimeError('db not ready')
            return ['value', calls['n']]
        idx = _index(build)
        idx.get()
        idx.invalidate()
        with self.assertRaises(RuntimeError):
            idx.get()
        self.assertEqual(idx.get(), ['value', 3])

    def test_concurrent_readers_wait_for_one_build(self):
        gate = threading.Event()
        build = _Builds(during=lambda: gate.wait(2))
        idx = _index(build)
        got = []
        threads = [threading.Thread(target=lambda: got.append(idx.get())) for _ in range(4)]
        for t in threads:
            t.start()
        time.sleep(0.2)
        gate.set()
        for t in threads:
            t.join(5)
        self.assertEqual(build.n, 1, 'أربعةُ طلباتٍ متزامنة بنت الفهرسَ أكثرَ من مرّة')
        self.assertTrue(all(g is got[0] for g in got))


class BackgroundRebuildTests(SimpleTestCase):

    def test_rebuilder_builds_what_was_requested_then_exits(self):
        build = _Builds()
        idx = _index(build)
        with mock.patch.object(SI, '_DEBOUNCE_SEC', 0):
            SI._REBUILDER.request(idx)
            deadline = time.monotonic() + 5
            while SI._REBUILDER._thread is not None and time.monotonic() < deadline:
                time.sleep(0.02)
        self.assertEqual(build.n, 1)
        self.assertIsNotNone(idx._state, 'البناءُ الخلفيّ لم يُنشر')
        self.assertIsNone(SI._REBUILDER._thread, 'الخيطُ بقي «جارياً» فسيُسكت كلَّ طلبٍ بعده')

    @override_settings(EXTRACTION_BACKGROUND_INDEXING=False, LETTERHEAD_MEMORY_INDEX_TTL=300,
                       SENDER_PROFILES_INDEX_TTL=900)
    def test_background_rebuild_is_off_when_disabled(self):
        with mock.patch.object(SI._REBUILDER, 'request') as req:
            SI.refresh_extraction_indexes_soon()
        req.assert_not_called()

    @override_settings(EXTRACTION_BACKGROUND_INDEXING=True, LETTERHEAD_MEMORY_INDEX_TTL=300,
                       SENDER_PROFILES_INDEX_TTL=900)
    def test_background_rebuild_requests_every_shared_index(self):
        with mock.patch.object(SI._REBUILDER, 'request') as req:
            SI.refresh_extraction_indexes_soon()
        self.assertEqual({c.args[0] for c in req.call_args_list}, {EM.MEMORY_INDEX, PF.PROFILES_INDEX})


@override_settings(LETTERHEAD_MEMORY_INDEX_TTL=300, SENDER_PROFILES_INDEX_TTL=900)
class SharedIndexDatabaseTests(TestCase):
    """مع القاعدة: البصمةُ تلتقط ما لا يُطلق إشارة، والإشاراتُ تُبطل عند الإيداع، والنتائجُ طازجة."""

    def setUp(self):
        for idx in (EM.MEMORY_INDEX, PF.PROFILES_INDEX):
            idx._state = None
        self.addCleanup(lambda: [setattr(i, '_state', None) for i in (EM.MEMORY_INDEX, PF.PROFILES_INDEX)])
        self.user = User.objects.create_user('shared-idx', password='pw-shared-1')
        self.alpha = Entity.objects.create(name='شركة الألفا للنفط', code='ALF')
        self.beta = Entity.objects.create(name='هيئة البيتا للغاز', code='BTA')

    def _book(self, **kw):
        kw.setdefault('kind', 'incoming_external')
        kw.setdefault('title', 'كتاب')
        return Book.objects.create(created_by=self.user, **kw)

    def test_signature_is_stable_without_changes(self):
        self.assertEqual(SI.db_signature(), SI.db_signature())

    def test_signature_sees_every_kind_of_source_change(self):
        """ومنها ما لا يُطلق إشارةً أصلاً (`queryset.update`) أو يجري في عمليّةٍ أخرى."""
        book = self._book(sender_number='MF-2026-101')
        row = LetterheadMemory.objects.create(letterhead='شركة الألفا', issuing_entity=self.alpha, book=book)
        changes = (
            ('memory row repointed in bulk', lambda: LetterheadMemory.objects.filter(pk=row.pk)
             .update(issuing_entity=self.beta)),
            ('bulk soft delete', lambda: Book.all_objects.filter(pk=book.pk).update(is_deleted=True)),
            ('sender number edited in bulk', lambda: Book.all_objects.filter(pk=book.pk)
             .update(sender_number='MF-2026-1011')),
            ('entity renamed in bulk', lambda: Entity.objects.filter(pk=self.beta.pk)
             .update(name='هيئة البيتا للغاز والنفط')),
            ('issuing link added', lambda: book.issuing_entities.add(self.alpha)),
            ('memory row added', lambda: LetterheadMemory.objects.create(letterhead='x', book=book)),
        )
        for label, change in changes:
            before = SI.db_signature()
            change()
            self.assertNotEqual(SI.db_signature(), before, label)

    def test_signals_invalidate_only_when_the_transaction_commits(self):
        gen = EM.MEMORY_INDEX._generation
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            LetterheadMemory.objects.create(letterhead='شركة الألفا', issuing_entity=self.alpha)
        self.assertEqual(EM.MEMORY_INDEX._generation, gen, 'أُبطل قبل الإيداع — قد يُبنى من حالٍ لم تُودَع')
        for cb in callbacks:
            cb()
        self.assertGreater(EM.MEMORY_INDEX._generation, gen)

    def test_saves_that_touch_unread_fields_do_not_invalidate(self):
        book = self._book(sender_number='MF-2026-101')
        gen = PF.PROFILES_INDEX._generation
        with self.captureOnCommitCallbacks(execute=True):
            book.margin = 'هامش'
            book.save(update_fields=['margin', 'updated_at'])
        self.assertEqual(PF.PROFILES_INDEX._generation, gen, 'هامشٌ أبطل فهرسَ البصمات بلا داع')
        with self.captureOnCommitCallbacks(execute=True):
            book.sender_number = 'MF-2026-102'
            book.save(update_fields=['sender_number'])
        self.assertGreater(PF.PROFILES_INDEX._generation, gen)

    def test_memory_matches_stay_fresh_while_shared(self):
        text = 'شركة الألفا للنفط\nالعدد ١٢٣\nالموضوع اجتماع'
        book = self._book()
        with self.captureOnCommitCallbacks(execute=True):
            row = LetterheadMemory.objects.create(letterhead=text, issuing_entity=self.alpha, book=book)
        first = EM.EntityMatcher().match_from_memory(text, 'issuer')
        self.assertEqual(first[0]['entity_id'], self.alpha.id)
        with self.captureOnCommitCallbacks(execute=True):    # تصحيحُ الكاتب (حفظٌ بإشارة)
            row.issuing_entity = self.beta
            row.save(update_fields=['issuing_entity'])
        self.assertEqual(EM.EntityMatcher().match_from_memory(text, 'issuer')[0]['entity_id'], self.beta.id)
        LetterheadMemory.objects.filter(pk=row.pk).update(issuing_entity=self.alpha)   # بلا إشارة
        self.assertEqual(EM.EntityMatcher().match_from_memory(text, 'issuer')[0]['entity_id'], self.alpha.id,
                         'الفهرسُ المشترك أعاد جهةً قديمة بعد تحديثٍ جماعيّ')

    def test_number_profiles_stay_fresh_while_shared(self):
        for i, num in enumerate(('MF-2026-101', 'MF-2026-150')):
            with self.captureOnCommitCallbacks(execute=True):
                self._book(sender_number=num, title=f'ك{i}').issuing_entities.add(self.alpha)
        text = 'Reference Number: MF-2026-195\nSubject: Meeting'
        self.assertEqual(PF.SenderNumberProfiles().find(text, self.alpha.id).value, 'MF-2026-195')
        self.assertIsNone(PF.SenderNumberProfiles().find('Ref: NK-20260237', self.beta.id))
        for i, num in enumerate(('NK-20260230', 'NK-20260231')):
            with self.captureOnCommitCallbacks(execute=True):
                self._book(sender_number=num, title=f'ن{i}').issuing_entities.add(self.beta)
        self.assertEqual(PF.SenderNumberProfiles().find('Ref: NK-20260237', self.beta.id).value, 'NK-20260237')

    def test_published_profiles_cannot_grow_keys_by_reading(self):
        with self.captureOnCommitCallbacks(execute=True):
            self._book(sender_number='MF-2026-101').issuing_entities.add(self.alpha)
        prof = PF.SenderNumberProfiles()
        prof._ensure_index()
        bucket = prof._profiles[self.alpha.id]['prefixes']
        self.assertNotIsInstance(bucket, defaultdict,
                                 'الفهرسُ المنشور ما يزال defaultdict — فهرسةٌ بقوسين تكتب فيه')
        with self.assertRaises(KeyError):
            bucket['L9-D9']


class WarmupTests(SimpleTestCase):

    def setUp(self):
        W._started = False
        self.addCleanup(setattr, W, '_started', False)

    @override_settings(EXTRACTION_WARMUP=False)
    def test_off_means_no_thread(self):
        self.assertIsNone(W.start_extraction_warmup())

    @override_settings(EXTRACTION_WARMUP=True)
    def test_starts_once_per_process(self):
        with mock.patch.object(W, '_warm') as warm:
            thread = W.start_extraction_warmup()
            thread.join(5)
            self.assertIsNone(W.start_extraction_warmup(), 'wsgi وasgi معاً بدآ إحماءَين')
        warm.assert_called_once()


class FastTesseractInputTests(SimpleTestCase):
    """البكسلاتُ التي يراها tesseract.exe لا تتغيّر — يتغيّر الضغطُ والزمنُ فقط."""

    def _gray(self):
        rng = np.random.default_rng(7)
        return Image.fromarray(rng.integers(0, 256, size=(60, 90), dtype=np.uint8), mode='L')

    def test_gray_image_reaches_tesseract_as_a_png_with_identical_pixels(self):
        img = self._gray()
        seen = {}

        def fake_itd(image, **kw):
            seen['arg'] = image
            with Image.open(image) as got:
                seen['pixels'] = np.array(got)
                seen['info'] = dict(got.info)
                seen['format'] = got.format
            return {'text': []}
        fake = mock.Mock(image_to_data=fake_itd)
        PR.tesseract_image_to_data(fake, img, lang='ara')
        self.assertIsInstance(seen['arg'], str)
        self.assertEqual(seen['format'], 'PNG')
        np.testing.assert_array_equal(seen['pixels'], np.array(img))
        self.assertFalse({'dpi', 'gamma', 'srgb', 'icc_profile'} & set(seen['info']))
        self.assertFalse(os.path.exists(seen['arg']), 'الملفُّ المؤقّت لم يُحذف')

    def test_other_modes_go_to_pytesseract_untouched(self):
        rgba = Image.new('RGBA', (8, 8), (0, 0, 0, 0))
        fake = mock.Mock()
        PR.tesseract_image_to_data(fake, rgba, lang='ara')
        self.assertIs(fake.image_to_data.call_args.args[0], rgba)

    def test_only_plain_gray_png_files_are_read_as_is(self):
        tmp = tempfile.mkdtemp()
        gray = os.path.join(tmp, 'g.png'); cv2.imwrite(gray, np.full((20, 30), 200, np.uint8))
        dpi = os.path.join(tmp, 'd.png'); Image.new('L', (8, 8), 255).save(dpi, dpi=(300, 300))
        rgb = os.path.join(tmp, 'c.png'); cv2.imwrite(rgb, np.zeros((8, 8, 3), np.uint8))
        jpg = os.path.join(tmp, 'j.jpg'); cv2.imwrite(jpg, np.full((8, 8), 200, np.uint8))
        self.assertTrue(PR.TesseractOCRProvider._png_read_as_is(gray))
        self.assertFalse(PR.TesseractOCRProvider._png_read_as_is(dpi), 'pHYs تُسقطها إعادةُ الكتابة')
        self.assertFalse(PR.TesseractOCRProvider._png_read_as_is(rgb))
        self.assertFalse(PR.TesseractOCRProvider._png_read_as_is(jpg), 'JPEG كان يُعاد ضغطُه فيتغيّر')
        for path in (gray, dpi, rgb, jpg):
            os.remove(path)                    # لا مقبضَ مفتوحاً بعد الفحص (ويندوز)

    def test_provider_hands_the_pipeline_png_to_tesseract_directly(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, 'page.png')
        cv2.imwrite(path, np.full((40, 60), 255, np.uint8))
        prov = PR.TesseractOCRProvider()
        args = []

        def fake_itd(image, **kw):
            args.append(image)
            return {'text': ['كلمة'], 'conf': ['95'], 'block_num': [1], 'par_num': [1], 'line_num': [1]}
        prov._pytesseract = mock.Mock(image_to_data=fake_itd, Output=mock.Mock(DICT='dict'))
        out = prov.extract(path)
        self.assertEqual(args, [path])
        self.assertEqual(out['raw_text'], 'كلمة')
        os.remove(path)


class PdfRenderWithoutPngRoundTripTests(SimpleTestCase):

    def test_page_array_matches_the_old_png_round_trip(self):
        import fitz
        from core.extraction.ocr.image import ImageProcessor
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, 'p.pdf')
        doc = fitz.open()
        page = doc.new_page(width=200, height=280)
        page.draw_rect(fitz.Rect(20, 30, 120, 90), color=(0.8, 0.1, 0.2), fill=(0.1, 0.5, 0.9))
        page.insert_text((30, 150), 'Ref 2026/101', fontsize=14, color=(0.2, 0.3, 0.1))
        doc.save(path); doc.close()

        zoom = 300 / 72
        with fitz.open(path) as d:
            pix = d[0].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            old = cv2.imdecode(np.frombuffer(pix.tobytes('png'), np.uint8), cv2.IMREAD_COLOR)
        new = ImageProcessor(path, preprocess_pdf=False, max_ocr_dim=3500).get_image()
        self.assertEqual(new.dtype, np.uint8)
        np.testing.assert_array_equal(new, old)
        os.remove(path)
