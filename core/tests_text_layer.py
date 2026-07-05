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
        # نصّ غنيّ (> العتبة) موزّع على أسطر → يُعاد كما هو ليُستخدَم بدل OCR
        rich = '\n'.join('line %02d alpha beta gamma delta' % i for i in range(8))  # 48 كلمة
        out = self.svc._extract_pdf_text_layer(self._pdf(rich))
        self.assertIsNotNone(out)
        self.assertIn('gamma', out)

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
