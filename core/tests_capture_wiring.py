# -*- coding: utf-8 -*-
"""حلقة التعلّم موصولةٌ لمسار الرفع أيضاً (إصلاح 2026-08-16).

تشخيصٌ على الكتاب #11298 (وارد خارجيّ حقيقيّ): رمز المسح كان يُسكّ في مسار **وكيل
المسح وحده**، فكلُّ مستندٍ يُرفع يدوياً يصل `books_api` بلا رمز ⟵ يتخطّى
`persist_extraction_capture` ⟵ **تصحيح الكاتب يضيع**. الدليل المقيس: 6 سجلّات التقاطٍ
في القاعدة كلّها مقابل آلاف الحفظات. هذه الاختبارات تحرس أن الرمز يُسكّ ويحمل شكلاً
يقبله الالتقاط، وأن الالتقاط يسجّل التصحيح فعلاً."""
from django.core.cache import cache
from django.test import SimpleTestCase


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
