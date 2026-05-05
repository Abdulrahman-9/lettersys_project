# -*- coding: utf-8 -*-
"""
core.extraction.ocr.service
============================
OCR Service using EasyOCR — Arabic text extraction.

استخراج النص من الصور بدعم العربية
"""

import time
import logging
from typing import List, Dict, Tuple
import cv2
import numpy as np
from pathlib import Path

logger = logging.getLogger('lettersys')

# ─────────────────────────────────────────────────────────────────────────────
# Module-level singleton: النموذج يُحمَّل مرة واحدة طوال عمر العملية.
# OCRService.__init__ لا يحمّل النموذج بعد الآن — يستخدم هذا المرجع مباشرة.
# ─────────────────────────────────────────────────────────────────────────────
_OCR_READER = None
_OCR_LANGUAGES = ['ar', 'en']


def _get_reader(languages=None, gpu=False):
    """إرجاع نموذج EasyOCR — يُنشأ مرة واحدة فقط (module-level singleton)."""
    global _OCR_READER
    if _OCR_READER is None:
        try:
            import easyocr
        except ImportError as exc:
            logger.error("تعذر تحميل مكتبة EasyOCR: %s", exc)
            raise RuntimeError("EasyOCR غير متوفر حالياً") from exc
        langs = languages or _OCR_LANGUAGES
        logger.info("تحميل نموذج EasyOCR للغات: %s", langs)
        _OCR_READER = easyocr.Reader(langs, gpu=gpu)
        logger.info("تم تحميل نموذج EasyOCR بنجاح")
    return _OCR_READER


class OCRService:
    """
    خدمة الاستخراج الضوئي
    """

    def __init__(self, languages=None, gpu=False):
        self.languages = languages or _OCR_LANGUAGES
        self.gpu = gpu
        # لا تحمّل النموذج هنا — يُحمَّل عند الاستخدام الفعلي الأول

    def extract_text(self, image_path_or_bytes, detail=False, min_confidence=0.1) -> Dict:
        """
        استخراج النص من صورة مع تحسينات للعربية

        Args:
            image_path_or_bytes: مسار الصورة أو bytes
            detail: هل نريد تفاصيل (score، مواقع، إلخ)
            min_confidence: الحد الأدنى للثقة (تجاهل النصوص الضعيفة)

        Returns:
            قاموس بالنتائج
        """
        start_time = time.time()

        try:
            # تحضير الصورة
            if isinstance(image_path_or_bytes, (str, Path)):
                image = cv2.imread(str(image_path_or_bytes))
            else:
                nparr = np.frombuffer(
                    image_path_or_bytes.read() if hasattr(image_path_or_bytes, 'read') else image_path_or_bytes,
                    np.uint8
                )
                image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            if image is None:
                return {
                    'status': 'error',
                    'error': 'فشل تحميل الصورة',
                    'raw_text': '',
                    'high_confidence_text': '',
                    'confidence': 0.0,
                    'processing_time': time.time() - start_time
                }

            # استخدام الـ singleton — لا تحميل جديد هنا
            reader = _get_reader(self.languages, self.gpu)

            logger.info("[OCR] Starting text extraction, image shape: %s, min_confidence: %s", image.shape, min_confidence)
            results = reader.readtext(image, detail=1)

            logger.info("[OCR] Raw results count: %d", len(results))
            if results:
                high_conf = [r for r in results if r[2] >= min_confidence]
                logger.info("[OCR] High-confidence results: %d / %d", len(high_conf), len(results))
            else:
                logger.warning("[OCR] No text detected in image!")

            extracted_data = self._process_results(results, detail, min_confidence)
            extracted_data['processing_time'] = time.time() - start_time
            extracted_data['status'] = 'success'

            logger.info(
                "[OCR] Extracted %d lines (high-conf: %d), avg confidence: %.2f",
                extracted_data['num_lines'],
                extracted_data['num_high_conf_lines'],
                extracted_data['avg_confidence'],
            )

            return extracted_data

        except Exception as e:
            logger.error("خطأ في OCR: %s", e)
            return {
                'status': 'error',
                'error': str(e),
                'raw_text': '',
                'high_confidence_text': '',
                'confidence': 0.0,
                'processing_time': time.time() - start_time
            }

    def _process_results(self, results, detail=False, min_confidence=0.1) -> Dict:
        """
        معالجة نتائج EasyOCR مع تنقية وتنظيف النص العربي

        Args:
            results: نتائج EasyOCR الخام
            detail: إذا كنا نريد تفاصيل
            min_confidence: الحد الأدنى للثقة
        """
        texts = []
        confidences = []
        details_list = []
        high_conf_texts = []  # نصوص بثقة عالية فقط

        for (bbox, text, confidence) in results:
            # تنظيف النص
            cleaned = self._clean_arabic_text(text)
            if not cleaned:
                continue  # تجاهل النصوص الفارغة

            # تصفية النصوص الضعيفة
            if confidence < min_confidence:
                logger.debug(f"[OCR] Skipping low-confidence text: '{cleaned}' ({confidence:.2f})")
                continue

            texts.append(cleaned)
            confidences.append(confidence)

            # احتفظ بالنصوص ذات الثقة العالية (> 0.7)
            if confidence > 0.7:
                high_conf_texts.append(cleaned)

            if detail:
                details_list.append({
                    'text': cleaned,
                    'confidence': float(confidence),
                    'bbox': [[int(p[0]), int(p[1])] for p in bbox]
                })

        # حساب الثقة الإجمالية
        avg_confidence = np.mean(confidences) if confidences else 0.0

        # جمع النصوص
        raw_text = '\n'.join(texts)
        high_conf_text = '\n'.join(high_conf_texts)

        return {
            'raw_text': raw_text,
            'high_confidence_text': high_conf_text,  # نص عالي الجودة فقط
            'texts': texts,
            'confidences': confidences,
            'avg_confidence': float(avg_confidence),
            'max_confidence': float(max(confidences)) if confidences else 0.0,
            'min_confidence': float(min(confidences)) if confidences else 0.0,
            'num_lines': len(texts),
            'num_high_conf_lines': len(high_conf_texts),  # عدد الأسطر عالية الجودة
            'num_characters': sum(len(t) for t in texts),
            'details': details_list if detail else None
        }

    def extract_text_region(self, image_path_or_bytes, bbox: List) -> Dict:
        """
        استخراج النص من منطقة معينة في الصورة

        Args:
            image_path_or_bytes: الصورة
            bbox: [x1, y1, x2, y2]

        Returns:
            قاموس بالنص المستخرج من المنطقة
        """
        try:
            if isinstance(image_path_or_bytes, (str, Path)):
                image = cv2.imread(str(image_path_or_bytes))
            else:
                nparr = np.frombuffer(
                    image_path_or_bytes.read() if hasattr(image_path_or_bytes, 'read') else image_path_or_bytes,
                    np.uint8
                )
                image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            x1, y1, x2, y2 = bbox
            region = image[int(y1):int(y2), int(x1):int(x2)]

            if region.size == 0:
                return {'error': 'المنطقة المحددة فارغة', 'text': ''}

            return self.extract_text(region)

        except Exception as e:
            logger.error(f"خطأ في استخراج المنطقة: {str(e)}")
            return {'error': str(e), 'text': ''}

    def detect_language(self, text: str) -> str:
        """
        الكشف عن لغة النص
        """
        arabic_count = sum(1 for c in text if '\u0600' <= c <= '\u06FF')
        english_count = sum(1 for c in text if 'a' <= c.lower() <= 'z')

        if arabic_count > english_count:
            return 'ar'
        elif english_count > arabic_count:
            return 'en'
        else:
            return 'mixed'

    def _clean_arabic_text(self, text: str) -> str:
        """
        تنظيف النص العربي من الضوضاء والأخطاء الشائعة

        يقوم بـ:
        - توحيد الألف (ا، أ، إ)
        - تحويل ى إلى ي
        - إزالة التشكيل
        - إزالة الأحرف الغريبة
        - توحيد المسافات
        """
        if not text:
            return ""

        # كشف اللغة أولاً
        language = self.detect_language(text)

        # إزالة المسافات الزائدة أولاً
        text = ' '.join(text.split())

        # تنظيف حسب اللغة
        if language == 'ar' or language == 'mixed':
            text = self._clean_arabic_specific(text)

        if language == 'en' or language == 'mixed':
            text = self._clean_english_specific(text)

        # تنظيف عام
        text = self._clean_general(text)

        return text.strip()

    def _clean_arabic_specific(self, text: str) -> str:
        """
        تنظيف خاص بالعربية
        """
        # توحيد الأحرف العربية
        replacements = {
            'إ': 'ا',  # همزة على أ → ا
            'أ': 'ا',  # همزة تحت ا → ا
            'آ': 'ا',  # ألف مع مد → ا
            'ى': 'ي',  # ألف مقصورة → ياء
            'ۀ': 'ة',  # تاء معكوفة → ة
            'ۃ': 'ة',  # تاء معكوفة أخرى → ة
            'ۂ': 'ة',  # تاء معكوفة ثالثة → ة
            '\u064c': '',    # ضمة (U+064C)
            '\u0650': '',    # كسرة (U+0650)
            '\u064e': '',    # فتحة (U+064E)
            '\u064b': '',    # فتحتان (تنوين) (U+064B)
            '\u064d': '',    # كسرتان (تنوين) (U+064D)
            '\u0652': '',    # سكون (U+0652)
            '\u0651': '',    # شدة (U+0651)
            '\u0640': '',    # علامة تطويل (U+0640)
            '\u0654': '',    # همزة على الألف (U+0654)
            '\u0655': '',    # همزة تحت الألف (U+0655)
        }

        for old, new in replacements.items():
            text = text.replace(old, new)

        return text

    def _clean_english_specific(self, text: str) -> str:
        """
        تنظيف خاص بالإنجليزية
        """
        # إصلاح الأحرف الشائعة المخطئة في OCR
        ocr_corrections = {
            '0': 'O',  # صفر → حرف O (في الكلمات)
            '1': 'I',  # واحد → حرف I (في الكلمات)
            '5': 'S',  # خمسة → حرف S (في بعض الحالات)
        }

        # تطبيق التصحيحات بحذر (فقط في الكلمات)
        words = text.split()
        corrected_words = []

        for word in words:
            # إذا كانت الكلمة تحتوي على أحرف إنجليزية وأرقام معاً
            has_letters = any(c.isalpha() for c in word)
            has_digits = any(c.isdigit() for c in word)

            if has_letters and has_digits:
                # حاول تصحيح الأرقام في الكلمات
                for digit, letter in ocr_corrections.items():
                    if digit in word and any(c.isalpha() for c in word):
                        # استبدل فقط إذا كانت محاطة بأحرف
                        word = word.replace(digit, letter)

            corrected_words.append(word)

        text = ' '.join(corrected_words)

        # إزالة المسافات قبل علامات الترقيم
        text = text.replace(' .', '.')
        text = text.replace(' ,', ',')
        text = text.replace(' :', ':')
        text = text.replace(' ;', ';')
        text = text.replace(' !', '!')
        text = text.replace(' ?', '?')

        # إضافة مسافة بعد علامات الترقيم إذا لم تكن موجودة
        import re
        text = re.sub(r'([.،,!?;:])([A-Za-z])', r'\1 \2', text)

        return text

    def _clean_general(self, text: str) -> str:
        """
        تنظيف عام لكل اللغات
        """
        # إزالة أي أحرف تحكم أو غير مرئية
        text = ''.join(c for c in text if ord(c) >= 32 or c == '\n')

        # إزالة المسافات المتكررة
        text = ' '.join(text.split())

        # إزالة الأسطر الفارغة
        text = '\n'.join(line.strip() for line in text.split('\n') if line.strip())

        return text

    def clean_text(self, text: str) -> str:
        """
        تنظيف وتصحيح النص المستخرج
        """
        # إزالة المسافات الزائدة
        text = ' '.join(text.split())

        # إزالة الأحرف الغريبة
        allowed_chars = set('0123456789 ')
        allowed_chars.update(chr(i) for i in range(0x0600, 0x06FF))
        allowed_chars.update('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ')
        allowed_chars.update('.,;:!?-/()[]{}')

        text = ''.join(c for c in text if c in allowed_chars)

        return text.strip()


class ArabicOCROptimizer:
    """
    محسّن OCR خاص للعربية
    """

    def __init__(self, ocr_service: OCRService):
        self.ocr = ocr_service

    def extract_with_confidence_filtering(self, image_path_or_bytes, min_confidence=0.5) -> Dict:
        """
        استخراج النص مع فلترة حسب الثقة
        """
        result = self.ocr.extract_text(image_path_or_bytes, detail=True)

        if result['status'] != 'success':
            return result

        # فلترة النصوص حسب الثقة
        filtered_details = [
            d for d in result['details']
            if d['confidence'] >= min_confidence
        ]

        filtered_text = ' '.join([d['text'] for d in filtered_details])
        filtered_confidences = [d['confidence'] for d in filtered_details]

        result['filtered_text'] = filtered_text
        result['filtered_avg_confidence'] = (
            np.mean(filtered_confidences) if filtered_confidences else 0.0
        )
        result['num_filtered_lines'] = len(filtered_details)

        return result

    def extract_structure_aware(self, image_path_or_bytes) -> Dict:
        """
        استخراج النص مع الحفاظ على البنية
        """
        result = self.ocr.extract_text(image_path_or_bytes, detail=True)

        if result['status'] != 'success':
            return result

        # ترتيب النصوص حسب الموقع (من الأعلى للأسفل)
        details = result['details']
        details.sort(key=lambda x: x['bbox'][0][1])  # ترتيب حسب y

        # تجميع السطور
        lines = []
        current_line = []
        current_y = None
        line_height_threshold = 20

        for detail in details:
            bbox = detail['bbox']
            y = bbox[0][1]

            if current_y is None:
                current_y = y

            if abs(y - current_y) <= line_height_threshold:
                current_line.append(detail['text'])
            else:
                if current_line:
                    lines.append(' '.join(current_line))
                current_line = [detail['text']]
                current_y = y

        if current_line:
            lines.append(' '.join(current_line))

        result['structured_text'] = '\n'.join(lines)
        result['num_structured_lines'] = len(lines)

        return result


# ===================================================
# Helper Functions
# ===================================================

def extract_text_simple(image_path_or_bytes) -> str:
    """دالة مساعدة بسيطة لاستخراج النص — تعيد استخدام الـ singleton"""
    service = OCRService()
    result = service.extract_text(image_path_or_bytes)
    return result.get('raw_text', '')


def extract_text_with_details(image_path_or_bytes) -> Dict:
    """دالة مساعدة لاستخراج النص مع التفاصيل — تعيد استخدام الـ singleton"""
    service = OCRService()
    return service.extract_text(image_path_or_bytes, detail=True)
