# -*- coding: utf-8 -*-
"""حلقة التعلّم موصولةٌ لمسار الرفع أيضاً (إصلاح 2026-08-16).

تشخيصٌ على الكتاب #11298 (وارد خارجيّ حقيقيّ): رمز المسح كان يُسكّ في مسار **وكيل
المسح وحده**، فكلُّ مستندٍ يُرفع يدوياً يصل `books_api` بلا رمز ⟵ يتخطّى
`persist_extraction_capture` ⟵ **تصحيح الكاتب يضيع**. الدليل المقيس: 6 سجلّات التقاطٍ
في القاعدة كلّها مقابل آلاف الحفظات. هذه الاختبارات تحرس أن الرمز يُسكّ ويحمل شكلاً
يقبله الالتقاط، وأن الالتقاط يسجّل التصحيح فعلاً."""
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase

from core.extraction.capture import persist_extraction_capture
from core.models import Attachment, Book


class _FakeResult:
    """أدنى نتيجةٍ يقبلها `result_to_scan_data` (بلا أنبوبٍ ولا OCR)."""

    def __init__(self):
        from core.extraction.pipeline import AIExtractionResult
        r = AIExtractionResult()
        r.raw_text = 'العدد : 7369\nالتاريخ : 2026/8/13'
        r.cleaned_text = r.raw_text
        r.sender_number = '7369'
        r.title = 'قائمة الجهات الموردة'
        r.ocr_engine = 'tesseract'
        self.r = r


class MintScanTokenTests(SimpleTestCase):
    def test_token_minted_and_payload_is_capture_shaped(self):
        from core.extraction.api.endpoints import _mint_scan_token
        token = _mint_scan_token(_FakeResult().r)
        self.assertTrue(token, 'يجب سكّ رمزٍ لكل استخراج (وإلا ضاعت حلقة التعلّم)')
        data = cache.get(f'scan_token:{token}')
        self.assertIsNotNone(data, 'الاقتراح يجب أن يُخزَّن تحت المفتاح الذي يقرؤه الحفظ')
        # الشكل الذي يقرؤه `persist_extraction_capture`
        for key in ('raw_text', 'cleaned_text', 'title', 'sender_number', 'ocr_engine'):
            self.assertIn(key, data, f'الالتقاط يقرأ {key} — غيابه يُفرغ الحلقة')
        self.assertEqual(data['sender_number'], '7369')

    def test_mint_never_breaks_extraction(self):
        """الحلقة تحسينٌ لا شرط: نتيجةٌ معطوبة ⟵ رمزٌ فارغ لا استثناء."""
        from core.extraction.api.endpoints import _mint_scan_token
        self.assertEqual(_mint_scan_token(object()), '')


class SenderNumberBoxCaptureTests(TestCase):
    """الصندوق يُحفَظ حتى حين **يمتنع** القارئ — وهناك تسكن عيّنات التدريب المفيدة.

    قِيس 2026-08-18: صفٌّ واحدٌ من 12 في القاعدة يحمل صندوقاً، لأنّ الصندوق كان
    مشروطاً بقراءةٍ تجتاز CONF_GATE=0.90 — أي جمعُ أمثلةٍ من الصفحات التي نجحنا فيها
    أصلاً. الكاشف يجد الموضع على ~90% بصرف النظر عن قدرة القارئ، فصار يُحفَظ موسوماً
    بمصدره ومقاسه المرجعيّ."""

    def _capture(self, suggested, kind='incoming_internal'):
        user = User.objects.create_user('boxcap', password='x')
        book = Book.objects.create(title='ت', kind=kind, created_by=user)
        att = Attachment.objects.create(book=book, file='attachments/a.pdf')
        return persist_extraction_capture(
            book=book, attachment=att, suggested=suggested,
            final={'sender_number': '1754'}, user=user)

    def test_detector_box_persisted_with_source_and_dims(self):
        res = self._capture({
            'raw_text': 'نصّ', 'sender_number': '',
            'sender_number_bbox': [0.7, 0.1, 0.8, 0.13],
            'sender_number_bbox_source': 'detector',
            'sender_number_bbox_dims': [2480, 3508],
        })
        self.assertIsNotNone(res)
        ad = res.additional_data
        self.assertEqual(ad['sender_number_bbox'], [0.7, 0.1, 0.8, 0.13])
        self.assertEqual(ad['sender_number_bbox_source'], 'detector',
                         'المصدر يميّز صندوقَ قراءةٍ واثقة عن صندوقِ كاشفٍ امتنع عنده القارئ')
        self.assertEqual(ad['sender_number_bbox_dims'], [2480, 3508],
                         'بلا المقاس المرجعيّ لا تُعاد البكسلات — وذاك فخّ 1600/2600/3500')

    def test_outgoing_still_skips_the_whole_number_block(self):
        """الصادر لا عددَ لنا فيه ⟵ لا صندوق ولا قيمة (وإلّا فُبركت عيّنةٌ سالبة)."""
        res = self._capture({
            'raw_text': 'نصّ',
            'sender_number_bbox': [0.7, 0.1, 0.8, 0.13],
            'sender_number_bbox_source': 'detector',
        }, kind='outgoing_external')
        self.assertIsNotNone(res)
        self.assertNotIn('sender_number_bbox', res.additional_data)


class ScanPayloadDurabilityTests(TestCase):
    """ذهبُ التدريب لا يعبر كاشاً متطايراً.

    الجذر المقيس (2026-08-18): الحمولة كانت في الكاش وحده، وبلا `REDIS_CACHE_URL`
    يكون `LocMemCache` — **نسخةٌ لكلّ عمليّة**. فرمزٌ يُسكّ في عاملٍ لا يراه عاملٌ آخر
    يستقبل الحفظ، وكلّ إعادة تشغيلٍ تمحو المعلّق. وهذا الحقل تحديداً لا تُعوَّض خسارتُه:
    نصٌّ خاطئ يُعاد حسابه غداً، وقيمةٌ كتبها الكاتب بيده تضيع أبداً."""

    def test_mint_writes_a_durable_row_beside_the_cache(self):
        from core.extraction.api.endpoints import _mint_scan_token
        from core.models import ScanPayload
        token = _mint_scan_token(_FakeResult().r)
        self.assertTrue(token)
        row = ScanPayload.objects.filter(token=token).first()
        self.assertIsNotNone(row, 'لا نسخة دائمة — الحمولة في الكاش وحده')
        self.assertTrue(row.data.get('raw_text'), 'الحمولة الدائمة فارغة')

    def test_durable_row_survives_a_cold_cache(self):
        """محاكاةُ إعادة تشغيلٍ أو عاملٍ آخر: يُمسح الكاش ويبقى الصفّ."""
        from core.extraction.api.endpoints import _mint_scan_token
        from core.models import ScanPayload
        token = _mint_scan_token(_FakeResult().r)
        cache.clear()
        self.assertIsNone(cache.get('scan_token:%s' % token))
        self.assertTrue(ScanPayload.objects.get(token=token).data.get('raw_text'))


class SenderDateCaptureTests(TestCase):
    """التقاطُ تاريخ الجهة — الحقل كان مستثنى فضاع كلُّ تصحيحٍ للتاريخ.

    الاستثناء كان بحجّة «فرق صيغة ISO/Date يعطي إيجابيّاتٍ كاذبة»، وتلك علّةُ
    **مقارنةٍ** لا سببٌ لإهدار الذهب: تُقارَن كائناتُ تاريخٍ لا نصوص، والمقارنةُ
    على `iso` لا على السلسلة الخام، وامتناعُ المحلّل لا يولّد إشارةَ تصحيح.
    """

    def _capture(self, sug, final, kind='incoming_internal'):
        user = User.objects.create_user('dcap-%s' % kind, password='x')
        book = Book.objects.create(title='ت', kind=kind, created_by=user)
        att = Attachment.objects.create(book=book, file='attachments/a.pdf')
        base = {'raw_text': 'نصّ'}
        base.update(sug)
        return persist_extraction_capture(book=book, attachment=att, suggested=base,
                                          final=final, user=user), book

    def _sug(self, iso='2025-03-06', raw='2025/3/6', parse='ok'):
        return {'sender_date_suggestion': {
            'raw': raw, 'iso': iso, 'parse': parse, 'confidence': 0.99,
            'bbox': [0.6, 0.12, 0.9, 0.16], 'source': 'crnn_d2', 'geometry': 'x1'}}

    def test_gold_keys_persisted_with_geometry_and_provenance(self):
        res, _ = self._capture(self._sug(), {'sender_date': '2025-03-06',
                                             'date': '2025-03-09',
                                             'sender_date_provenance': 'confirmed'})
        ad = res.additional_data
        self.assertEqual(ad['sender_date_suggested_iso'], '2025-03-06')
        self.assertEqual(ad['sender_date_final'], '2025-03-06')
        self.assertEqual(ad['sender_date_entry'], '2025-03-09',
                         'تاريخُ القيد يُرشّح الذهب لاحقاً (فارقٌ صفر = ختمُنا مُحتمَل)')
        self.assertEqual(ad['sender_date_geometry'], 'x1',
                         'بلا وسم الهندسة يختلط توزيعان في مجموعةٍ واحدة')
        self.assertEqual(ad['sender_date_provenance'], 'confirmed')

    def test_iso_with_time_component_is_not_a_false_correction(self):
        """الفخّ الذي عطّل الحقل: نصّان مختلفان وتاريخٌ واحد."""
        res, _ = self._capture(self._sug(iso='2025-03-06'),
                               {'sender_date': '2025-03-06T00:00:00'})
        self.assertEqual(res.feedbacks.filter(field_name='sender_date').count(), 0)

    def test_real_correction_creates_feedback(self):
        res, _ = self._capture(self._sug(iso='2025-03-06'),
                               {'sender_date': '2025-03-16'})
        fb = res.feedbacks.get(field_name='sender_date')
        self.assertEqual((fb.original_value, fb.corrected_value),
                         ('2025-03-06', '2025-03-16'))

    def test_abstained_parse_never_claims_a_correction(self):
        """لا يصحّ ادّعاءُ «تصحيحِ» اقتراحٍ لم يُنطق — والزوجُ يبقى ذهباً."""
        res, _ = self._capture(self._sug(iso='', parse='ambiguous'),
                               {'sender_date': '2025-03-16'})
        self.assertEqual(res.feedbacks.filter(field_name='sender_date').count(), 0)
        self.assertEqual(res.additional_data['sender_date_parse'], 'ambiguous')

    def test_outgoing_captures_no_date_block(self):
        res, _ = self._capture(self._sug(), {'sender_date': '2025-03-06'},
                               kind='outgoing_external')
        self.assertNotIn('sender_date_suggested_iso', res.additional_data)
        self.assertEqual(res.feedbacks.filter(field_name='sender_date').count(), 0)
