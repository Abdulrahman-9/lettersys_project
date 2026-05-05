# -*- coding: utf-8 -*-
"""
core.extraction.matchers.pattern
==================================
Pattern Matching & Data Extraction Service — استخراج البيانات المنظمة من النص
"""

import re
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from dateutil import parser as date_parser
import logging

logger = logging.getLogger('lettersys')


class PatternMatcher:
    """
    استخراج البيانات باستخدام Pattern Matching
    """

    # الأنماط (Patterns) الأساسية
    PATTERNS = {
        'book_number': [
            r'رقم\s*الكتاب\s*[:=]?\s*(\d+)',  # رقم الكتاب: 123
            r'كتاب\s*رقم\s*[:=]?\s*(\d+)',     # كتاب رقم: 123
            r'^\d{3,8}$',                       # مجرد رقم بـ 3-8 أرقام
        ],
        'arabic_date': [
            r'(\d{1,2})\s*(?:من|/)\s*(يناير|فبراير|مارس|أبريل|مايو|يونيو|يوليو|أغسطس|سبتمبر|أكتوبر|نوفمبر|ديسمبر)\s*(?:/|من)?\s*(\d{4})',
            r'(\d{1,2})\s*[-/]\s*(\d{1,2})\s*[-/]\s*(\d{4})',  # DD-MM-YYYY
        ],
        'secret_level': [
            (r'\bسري\s+للغاية\b', 'topsecret'),
            (r'\bسري\b', 'secret'),
            (r'\bاعتيادي\b', 'normal'),
        ],
        'book_kind': [
            (r'\bوارد\b', 'incoming'),
            (r'\bصادر\b', 'outgoing'),
            (r'INCOMING', 'incoming'),
            (r'OUTGOING', 'outgoing'),
        ],
        'entity': [
            r'(?:الجهة|المرسلة|من)\s*[:=]?\s*(.+?)(?:\.|\n|الى|إلى|المستقبلة)',
            r'(?:المرسل|من|جهة)\s*[:=]?\s*(.+?)(?:\.|\n)',
        ]
    }

    # خريطة أشهر عربية
    ARABIC_MONTHS = {
        'يناير': 1, 'فبراير': 2, 'مارس': 3, 'أبريل': 4,
        'مايو': 5, 'يونيو': 6, 'يوليو': 7, 'أغسطس': 8,
        'سبتمبر': 9, 'أكتوبر': 10, 'نوفمبر': 11, 'ديسمبر': 12,
    }

    def extract_book_number(self, text: str) -> Tuple[Optional[str], float]:
        """
        استخراج رقم الكتاب من النص

        Returns:
            (رقم الكتاب، درجة الثقة)
        """
        for pattern in self.PATTERNS['book_number']:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                number = match.group(1) if '(' in pattern else match.group(0)
                confidence = 0.95 if 'رقم الكتاب' in pattern else 0.80
                return (number, confidence)

        return (None, 0.0)

    def extract_date(self, text: str) -> Tuple[Optional[datetime], float]:
        """
        استخراج التاريخ من النص

        Returns:
            (التاريخ، درجة الثقة)
        """
        # البحث عن التاريخ العربي
        for pattern in self.PATTERNS['arabic_date']:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    if len(match.groups()) == 3:
                        day, month_name, year = match.groups()
                        if month_name in self.ARABIC_MONTHS:
                            month = self.ARABIC_MONTHS[month_name]
                            date_obj = datetime(int(year), int(month), int(day))
                            return (date_obj, 0.95)
                    else:
                        day, month, year = match.groups()
                        date_obj = datetime(int(year), int(month), int(day))
                        return (date_obj, 0.92)
                except (ValueError, AttributeError):
                    pass

        # محاولة استخراج أي تاريخ
        try:
            # البحث عن أرقام يمكن أن تكون تاريخ
            date_patterns = [
                r'\d{1,2}[-/]\d{1,2}[-/]\d{4}',
                r'\d{4}[-/]\d{1,2}[-/]\d{1,2}',
            ]

            for pattern in date_patterns:
                match = re.search(pattern, text)
                if match:
                    date_str = match.group(0)
                    date_obj = date_parser.parse(date_str, dayfirst=True)
                    return (date_obj, 0.85)
        except (ValueError, TypeError, OverflowError):
            pass

        return (None, 0.0)

    def extract_secret_level(self, text: str) -> Tuple[Optional[str], float]:
        """
        استخراج مستوى السرية من النص
        """
        for pattern, level in self.PATTERNS['secret_level']:
            if re.search(pattern, text, re.IGNORECASE):
                confidence = 0.95
                return (level, confidence)

        return (None, 0.0)

    def extract_book_kind(self, text: str) -> Tuple[Optional[str], float]:
        """
        استخراج نوع الكتاب (وارد/صادر) من النص
        """
        for pattern, kind in self.PATTERNS['book_kind']:
            if re.search(pattern, text, re.IGNORECASE):
                confidence = 0.92
                return (kind, confidence)

        return (None, 0.0)

    def extract_entities(self, text: str) -> List[Tuple[str, float]]:
        """
        استخراج أسماء الجهات من النص
        """
        entities = []

        for pattern in self.PATTERNS['entity']:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                entity_text = match.strip() if isinstance(match, str) else match[0].strip()
                if len(entity_text) > 2:  # تجنب النصوص القصيرة جداً
                    entities.append((entity_text, 0.75))

        return entities

    def extract_title_keywords(self, text: str, num_words: int = 10) -> str:
        """
        استخراج كلمات العنوان الرئيسية من النص
        """
        # إزالة الكلمات الشائعة
        stop_words = {'من', 'إلى', 'هذا', 'ذلك', 'كل', 'بعض', 'أي', 'التي', 'الذي',
                     'أن', 'إن', 'كان', 'كانت', 'هو', 'هي', 'هم', 'أنت', 'نحن'}

        # تقسيم إلى كلمات
        lines = text.split('\n')
        first_lines = '\n'.join(lines[:3])  # أول 3 أسطر فقط

        words = [w.strip() for w in first_lines.split() if w.strip() and w.strip() not in stop_words]

        # أخذ أول عدد من الكلمات
        title_words = words[:num_words]

        return ' '.join(title_words)

    def extract_all_data(self, text: str) -> Dict:
        """
        استخراج جميع البيانات من النص
        """
        book_number, book_number_conf = self.extract_book_number(text)
        date, date_conf = self.extract_date(text)
        secret_level, secret_conf = self.extract_secret_level(text)
        book_kind, kind_conf = self.extract_book_kind(text)
        entities = self.extract_entities(text)
        title = self.extract_title_keywords(text)

        return {
            'book_number': book_number,
            'book_number_confidence': book_number_conf,
            'date': date.isoformat() if date else None,
            'date_confidence': date_conf,
            'secret_level': secret_level,
            'secret_level_confidence': secret_conf,
            'book_kind': book_kind,
            'book_kind_confidence': kind_conf,
            'entities': entities,
            'title': title,
            'raw_text': text[:500],  # أول 500 حرف
        }


class DateParser:
    """
    محلل التواريخ المتقدم
    دعم صيغ متعددة للتواريخ
    """

    MONTH_MAP = {
        'يناير': 1, 'كانون الثاني': 1,
        'فبراير': 2, 'شباط': 2,
        'مارس': 3, 'آذار': 3,
        'أبريل': 4, 'نيسان': 4,
        'مايو': 5, 'أيار': 5,
        'يونيو': 6, 'حزيران': 6,
        'يوليو': 7, 'تموز': 7,
        'أغسطس': 8, 'آب': 8,
        'سبتمبر': 9, 'أيلول': 9,
        'أكتوبر': 10, 'تشرين الأول': 10,
        'نوفمبر': 11, 'تشرين الثاني': 11,
        'ديسمبر': 12, 'كانون الأول': 12,
    }

    @staticmethod
    def parse(date_string: str) -> Optional[datetime]:
        """
        تحليل تاريخ من صيغ متعددة
        """
        if not date_string or not isinstance(date_string, str):
            return None

        date_string = date_string.strip()

        try:
            # محاولة التحليل الأساسي
            return date_parser.parse(date_string, dayfirst=True)
        except (ValueError, TypeError, OverflowError):
            pass

        try:
            # محاولة مع الأشهر العربية
            for month_name, month_num in DateParser.MONTH_MAP.items():
                if month_name in date_string:
                    date_string = date_string.replace(month_name, str(month_num))
                    return date_parser.parse(date_string, dayfirst=True)
        except (ValueError, TypeError, OverflowError):
            pass

        return None

    @staticmethod
    def format_date(date_obj: datetime) -> str:
        """تنسيق التاريخ"""
        return date_obj.strftime('%Y-%m-%d')


# ===================================================
# Helper Functions
# ===================================================

def extract_structured_data(text: str) -> Dict:
    """
    دالة مساعدة لاستخراج البيانات المنظمة
    """
    matcher = PatternMatcher()
    return matcher.extract_all_data(text)


def parse_date_flexible(date_string: str) -> Optional[datetime]:
    """
    دالة مساعدة لتحليل التاريخ المرن
    """
    return DateParser.parse(date_string)
