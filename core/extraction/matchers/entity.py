# -*- coding: utf-8 -*-
"""
core.extraction.matchers.entity
=================================
Entity Matching & NER Service — مطابقة الجهات والكشف عن الكيانات المسماة
"""

from fuzzywuzzy import fuzz, process
from typing import Dict, List, Tuple, Optional
from core.models import Entity
import logging

logger = logging.getLogger('lettersys')


class EntityMatcher:
    """
    محرك مطابقة الجهات الذكي
    """

    def __init__(self, threshold=70):
        """
        Args:
            threshold: درجة التشابه الأدنى (0-100)
        """
        self.threshold = threshold
        self.entities_cache = None

    def get_entities_list(self) -> List[Dict]:
        """الحصول على قائمة الجهات من قاعدة البيانات"""
        if self.entities_cache is None:
            try:
                entities = Entity.objects.filter(is_active=True).values('id', 'name', 'code', 'etype')
                self.entities_cache = list(entities)
            except Exception as e:
                logger.error(f"خطأ في جلب الجهات: {str(e)}")
                self.entities_cache = []

        return self.entities_cache

    def match_entity(self, entity_text: str, entity_type: Optional[str] = None) -> List[Dict]:
        """
        مطابقة جهة من النص مع قائمة الجهات

        Args:
            entity_text: نص الجهة المستخرج
            entity_type: نوع الجهة (issuer, receiver, both)

        Returns:
            قائمة الجهات المقترحة مع درجات التشابه
        """
        entities = self.get_entities_list()

        if not entities:
            return []

        # فلترة حسب النوع إن وجد
        if entity_type and entity_type != 'both':
            entities = [e for e in entities if e['etype'] in [entity_type, 'both']]

        # البحث عن أفضل مطابقة
        matches = []

        for entity in entities:
            # مطابقة الاسم
            name_score = fuzz.token_set_ratio(entity_text.lower(), entity['name'].lower())

            # مطابقة الرمز إن وجد
            code_score = 0
            if entity['code']:
                code_score = fuzz.ratio(entity_text.lower(), entity['code'].lower())

            # أخذ أعلى درجة
            score = max(name_score, code_score)

            if score >= self.threshold:
                matches.append({
                    'entity_id': entity['id'],
                    'entity_name': entity['name'],
                    'entity_code': entity['code'],
                    'entity_type': entity['etype'],
                    'score': score,
                    'match_type': 'name' if name_score >= code_score else 'code'
                })

        # ترتيب حسب الدرجة (الأعلى أولاً)
        matches.sort(key=lambda x: x['score'], reverse=True)

        return matches

    def match_issuing_entity(self, entity_text: str) -> List[Dict]:
        """مطابقة جهة مرسلة"""
        return self.match_entity(entity_text, entity_type='issuer')

    def match_receiving_entity(self, entity_text: str) -> List[Dict]:
        """مطابقة جهة مستقبلة"""
        return self.match_entity(entity_text, entity_type='receiver')

    def get_best_match(self, entity_text: str, entity_type: Optional[str] = None) -> Optional[Dict]:
        """الحصول على أفضل مطابقة فقط"""
        matches = self.match_entity(entity_text, entity_type)
        return matches[0] if matches else None

    def batch_match_entities(self, entities_list: List[str]) -> List[List[Dict]]:
        """
        مطابقة عدة جهات دفعة واحدة
        """
        return [self.match_entity(entity) for entity in entities_list]

    def clear_cache(self):
        """تطهير الذاكرة المؤقتة"""
        self.entities_cache = None


class NERService:
    """
    خدمة الكشف عن الكيانات المسماة
    Named Entity Recognition
    """

    # الكيانات المدعومة
    ENTITY_TYPES = {
        'ORG': 'منظمة/جهة',      # Organization
        'PERSON': 'شخص',           # Person
        'DATE': 'تاريخ',            # Date
        'LOC': 'موقع/مدينة',       # Location
        'FACILITY': 'منشأة',        # Facility
    }

    @staticmethod
    def extract_entities(text: str) -> Dict[str, List[str]]:
        """
        استخراج الكيانات من النص (Simple Pattern-based approach)
        """
        entities = {
            'organizations': [],
            'persons': [],
            'locations': [],
        }

        # أنماط لاستخراج الجهات
        org_patterns = [
            r'(?:وزارة|مؤسسة|جامعة|شركة|مصرف|مركز|معهد|قسم|إدارة)\s+([^\n.,]{5,50})',
            r'([\u0600-\u06FF\s]{5,50})\s+(?:العامة|الرسمية|الحكومية)',
        ]

        # أنماط لاستخراج الأشخاص
        person_patterns = [
            r'الأستاذ\s+([^\n.,]+)',
            r'السيد\s+([^\n.,]+)',
            r'الدكتور\s+([^\n.,]+)',
        ]

        # أنماط لاستخراج المواقع
        location_patterns = [
            r'(?:في|من|إلى)\s+([^\n.,]{3,30})',
        ]

        import re

        # استخراج الجهات
        for pattern in org_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            entities['organizations'].extend([m.strip() for m in matches if m.strip()])

        # استخراج الأشخاص
        for pattern in person_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            entities['persons'].extend([m.strip() for m in matches if m.strip()])

        # استخراج المواقع
        for pattern in location_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            entities['locations'].extend([m.strip() for m in matches if m.strip()])

        # إزالة التكرارات
        for key in entities:
            entities[key] = list(set(entities[key]))

        return entities

    @staticmethod
    def extract_organizations(text: str) -> List[str]:
        """استخراج الجهات فقط"""
        return NERService.extract_entities(text)['organizations']

    @staticmethod
    def extract_persons(text: str) -> List[str]:
        """استخراج الأشخاص فقط"""
        return NERService.extract_entities(text)['persons']

    @staticmethod
    def extract_locations(text: str) -> List[str]:
        """استخراج المواقع فقط"""
        return NERService.extract_entities(text)['locations']


class EnhancedEntityMatcher(EntityMatcher):
    """
    محرك مطابقة الجهات المحسّن
    يجمع بين Pattern Matching و NER
    """

    def __init__(self, threshold=70):
        super().__init__(threshold)
        self.ner_service = NERService()

    def smart_match(self, text: str, entity_type: Optional[str] = None) -> List[Dict]:
        """
        مطابقة ذكية تجمع النصوص المستخرجة من النص
        """
        # استخراج الكيانات
        organizations = self.ner_service.extract_organizations(text)

        if not organizations:
            # إذا لم نجد منظمات، استخدم النص كاملاً
            organizations = [text]

        all_matches = []

        for org in organizations:
            matches = self.match_entity(org, entity_type)
            if matches:
                all_matches.extend(matches)

        # إزالة التكرارات والترتيب
        seen_ids = set()
        unique_matches = []

        for match in all_matches:
            if match['entity_id'] not in seen_ids:
                seen_ids.add(match['entity_id'])
                unique_matches.append(match)

        unique_matches.sort(key=lambda x: x['score'], reverse=True)

        return unique_matches

    def smart_match_issuing_entity(self, text: str) -> List[Dict]:
        """مطابقة ذكية لجهة مرسلة"""
        return self.smart_match(text, entity_type='issuer')

    def smart_match_receiving_entity(self, text: str) -> List[Dict]:
        """مطابقة ذكية لجهة مستقبلة"""
        return self.smart_match(text, entity_type='receiver')


# ===================================================
# Helper Functions
# ===================================================

def match_entity(entity_text: str, threshold=70) -> Optional[Dict]:
    """
    دالة مساعدة سريعة لمطابقة جهة
    """
    matcher = EntityMatcher(threshold)
    best_match = matcher.get_best_match(entity_text)
    return best_match


def extract_ner_entities(text: str) -> Dict:
    """
    دالة مساعدة لاستخراج الكيانات المسماة
    """
    return NERService.extract_entities(text)


def smart_entity_match(text: str) -> List[Dict]:
    """
    دالة مساعدة للمطابقة الذكية
    """
    matcher = EnhancedEntityMatcher()
    return matcher.smart_match(text)
