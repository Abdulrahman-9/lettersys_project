# -*- coding: utf-8 -*-
"""اختبار «طبقة النصّ أولاً» — كشف طبقة نصّ PDF الغنيّة (مستند رقمي) مقابل الممسوح.

للمستندات الرقمية نستخدم النصّ المضمّن مباشرةً (أدقّ/أسرع/أخفّ من إعادة OCR)؛
وللصور الممسوحة بلا نصّ نسقط إلى OCR. العتبة تحرس من طبقة نصّ ضئيلة (ختم/أثر)."""
import os
import tempfile

import fitz
from django.test import TestCase

from core.extraction.pipeline import AIExtractionService


def _make_pdf(text):
    """يُنشئ PDF مؤقّتاً بنصٍّ مضمّن (أو بلا نصّ إن text=None). يُدرِج سطراً سطراً كي
    لا يُقصّ السطر الطويل عند حافّة الصفحة (insert_text لا يلفّ النص)."""
    doc = fitz.open()
    page = doc.new_page()
    if text:
        y = 72
        for line in text.split('\n'):
            page.insert_text((72, y), line, fontsize=11)
            y += 18
    fd, path = tempfile.mkstemp(suffix='.pdf')
    os.close(fd)
    doc.save(path)
    doc.close()
    return path


class TextLayerDetectionTests(TestCase):
    def setUp(self):
        self.svc = AIExtractionService()
        self._paths = []

    def tearDown(self):
        for p in self._paths:
            try:
                os.remove(p)
            except OSError:
                pass

    def _pdf(self, text):
        p = _make_pdf(text)
        self._paths.append(p)
        return p

    def test_rich_text_layer_returned(self):
        # نصّ غنيّ (> العتبة) موزّع على أسطر، بلغة حقيقية → يُعاد ليُستخدَم بدل OCR
        rich = '\n'.join('the subject of this letter %02d alpha beta' % i for i in range(8))
        out = self.svc._extract_pdf_text_layer(self._pdf(rich))
        self.assertIsNotNone(out)
        self.assertIn('alpha', out)

    def test_garbage_scanner_layer_rejected(self):
        # طبقة برنامج مسحٍ خردة (عربية قُرئت بمحرّك لاتيني: «.hiill;Jljo») — طويلة
        # لكنها بلا كلمات لغةٍ حقيقية → تُرفض ويسقط المستند إلى OCR المُدرَّب
        garbage = '\n'.join('hiill Jljo lrj asi %02d jJslt irSL Datc llc' % i for i in range(8))
        self.assertIsNone(self.svc._extract_pdf_text_layer(self._pdf(garbage)))

    def test_sparse_text_layer_falls_back(self):
        # نصّ ضئيل (ختم/أثر) دون العتبة → None → يلزم OCR
        self.assertIsNone(self.svc._extract_pdf_text_layer(self._pdf('hi there')))

    def test_image_only_pdf_falls_back(self):
        # PDF بلا طبقة نصّ (صورة ممسوحة) → None
        self.assertIsNone(self.svc._extract_pdf_text_layer(self._pdf(None)))

    def test_non_pdf_returns_none(self):
        fd, path = tempfile.mkstemp(suffix='.png')
        os.close(fd)
        self._paths.append(path)
        self.assertIsNone(self.svc._extract_pdf_text_layer(path))


class TextLayerReadabilityTests(TestCase):
    """بوّابة المقروئية مباشرةً — تحمي المطابقة العربية من طبقات المسح الخردة."""

    def test_real_arabic_accepted(self):
        from core.extraction.pipeline import _text_layer_is_readable
        self.assertTrue(_text_layer_is_readable(
            'وزارة النفط\nالعدد: 1234\nالموضوع: طلب تزويد\nالسيد المدير المحترم'))

    def test_real_english_accepted(self):
        from core.extraction.pipeline import _text_layer_is_readable
        self.assertTrue(_text_layer_is_readable(
            'Date: June 20, 2026\nSubject: Coordination of the pipeline works'))

    def test_latin_garbage_rejected(self):
        from core.extraction.pipeline import _text_layer_is_readable
        self.assertFalse(_text_layer_is_readable('.hiill;Jljo lrj asi jJslt irSL l)atc'))

    def test_mixed_legacy_garbage_rejected(self):
        # ملفات قديمة: خردة عربية-كلاتيني + إنكليزية حقيقية قليلة في الترويسة
        # («Ministry of Oil») — العدّ المطلق ينخدع، الكثافة (≈2%) تفضحها
        from core.extraction.pipeline import _text_layer_is_readable
        junk = 'LiiI 6Jtj Lij isi ljlt Jr Li isJi crIe uJt qj gAB dLl rL Jt ' * 12
        self.assertFalse(_text_layer_is_readable(
            junk + 'Republic of Iraq Ministry of Oil ' + junk))

    def test_presentation_forms_rejected(self):
        # أشكال العرض (ترتيب بصري مُشكَّل) تكسر المطابقة حتى لو بدت عربيةً
        from core.extraction.pipeline import _text_layer_is_readable
        shaped = 'ﻢﻜﻴﻠﻋ ﻡﻼﺴﻟﺍ ﻂﻔﻨﻟﺍ ﺓﺭﺍﺯﻭ ' * 6
        self.assertFalse(_text_layer_is_readable(shaped))
