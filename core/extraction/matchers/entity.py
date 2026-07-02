# -*- coding: utf-8 -*-
"""
core.extraction.matchers.entity
=================================
Entity Matching & NER Service — مطابقة الجهات والكشف عن الكيانات المسماة
"""

import re
import time

from fuzzywuzzy import fuzz
from typing import Dict, List, Tuple, Optional
from core.models import Entity
import logging

logger = logging.getLogger('lettersys')

_ENTITY_CACHE_TTL = 300  # 5 دقائق
_TFIDF_MIN_SIM = 0.3     # عتبة كوزَيْن دنيا لاعتبار مطابقة TF-IDF
_MEMORY_MIN_SIM = 0.25       # عتبة تشابه ترويسة دنيا لاعتبار مطابقة ذاكرة
_MEMORY_HALFLIFE_DAYS = 180  # نصف-عُمر ترجيح الحداثة: الأحدث أوثق (يعالج انجراف التوجيه)
_AR_TASHKEEL = re.compile(r'[ً-ْٰـ]')


def _normalize_ar(s: str) -> str:
    """تطبيع عربي خفيف يحسّن المطابقة (ألف/ياء/تاء مربوطة + حذف تشكيل/تطويل)."""
    s = _AR_TASHKEEL.sub('', str(s or ''))
    s = re.sub(r'[إأآ]', 'ا', s)
    s = s.replace('ى', 'ي').replace('ة', 'ه')
    return ' '.join(s.lower().split()).strip()


def letterhead_region(text: str) -> str:
    """أعلى ~40% من أسطر المستند (ترويسة + مُخاطَب، دون ضوضاء المتن) — مصدر مطابقة
    الجهة الأدقّ (مقيس: يفوق الموضع البكسلي والنصّ الكامل)."""
    lines = [ln for ln in (text or '').split('\n') if ln.strip()]
    if not lines:
        return ''
    return ' '.join(lines[: max(8, int(0.4 * len(lines)))])


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
        self._cache_loaded_at: float = 0.0
        self._tfidf = None                  # (vectorizer, matrix) لفهرس أسماء الجهات
        self._tfidf_built_at: float = -1.0
        self._memory_index = None           # (vec, matrix, rows, count) لفهرس ذاكرة الترويسة
        self._memory_built_at: float = 0.0

    def get_entities_list(self) -> List[Dict]:
        """الحصول على قائمة الجهات من قاعدة البيانات مع TTL 5 دقائق."""
        now = time.monotonic()
        if self.entities_cache is None or (now - self._cache_loaded_at) > _ENTITY_CACHE_TTL:
            try:
                entities = Entity.objects.filter(is_active=True).values('id', 'name', 'code', 'etype')
                self.entities_cache = list(entities)
                self._cache_loaded_at = now
                logger.debug('[EntityMatcher] cache refreshed — %d entities', len(self.entities_cache))
            except Exception as e:
                logger.error('خطأ في جلب الجهات: %s', e)
                if self.entities_cache is None:
                    self.entities_cache = []

        return self.entities_cache

    def match_entity(self, entity_text: str, entity_type: Optional[str] = None) -> List[Dict]:
        """
        مطابقة جهة من النص — TF-IDF حرفي (أدقّ، يفوق fuzzy بفارق كبير على بياناتنا)
        مع تراجع تلقائي إلى fuzzy عند تعذّر sklearn.

        Args:
            entity_text: نص الجهة المستخرج
            entity_type: نوع الجهة (issuer, receiver, both)

        Returns:
            قائمة الجهات المقترحة مرتّبة تنازلياً بدرجة التشابه (0-100)
        """
        entities = self.get_entities_list()
        if not entities or not (entity_text or '').strip():
            return []
        try:
            result = self._match_tfidf(entity_text, entities, entity_type)
            if result is not None:
                return result
        except Exception as e:
            logger.warning('[EntityMatcher] TF-IDF تعذّر، تراجع إلى fuzzy: %s', e)
        return self._match_fuzzy(entity_text, entities, entity_type)

    def _ensure_tfidf(self, entities):
        """يبني فهرس TF-IDF (char_wb 3-5) ويُعيد بناءه عند تغيّر الكاش."""
        if self._tfidf is not None and self._tfidf_built_at == self._cache_loaded_at:
            return self._tfidf
        from sklearn.feature_extraction.text import TfidfVectorizer
        names = [_normalize_ar(e['name']) for e in entities]
        vec = TfidfVectorizer(analyzer='char_wb', ngram_range=(3, 5))
        matrix = vec.fit_transform(names)
        self._tfidf = (vec, matrix)
        self._tfidf_built_at = self._cache_loaded_at
        return self._tfidf

    def _match_tfidf(self, entity_text, entities, entity_type) -> List[Dict]:
        from sklearn.metrics.pairwise import cosine_similarity
        vec, matrix = self._ensure_tfidf(entities)
        sims = cosine_similarity(vec.transform([_normalize_ar(entity_text)]), matrix).ravel()
        matches = []
        for idx, sim in enumerate(sims):
            if sim < _TFIDF_MIN_SIM:
                continue
            e = entities[idx]
            if entity_type and entity_type != 'both' and e['etype'] not in (entity_type, 'both'):
                continue
            matches.append({
                'entity_id': e['id'],
                'entity_name': e['name'],
                'entity_code': e['code'],
                'entity_type': e['etype'],
                'score': round(float(sim) * 100, 1),
                'match_type': 'tfidf',
            })
        matches.sort(key=lambda x: x['score'], reverse=True)
        return matches

    def _match_fuzzy(self, entity_text, entities, entity_type) -> List[Dict]:
        """مسار احتياطي (fuzzywuzzy) عند غياب sklearn."""
        if entity_type and entity_type != 'both':
            entities = [e for e in entities if e['etype'] in [entity_type, 'both']]
        matches = []
        for entity in entities:
            name_score = fuzz.token_set_ratio(entity_text.lower(), entity['name'].lower())
            code_score = fuzz.ratio(entity_text.lower(), entity['code'].lower()) if entity['code'] else 0
            score = max(name_score, code_score)
            if score >= self.threshold:
                matches.append({
                    'entity_id': entity['id'],
                    'entity_name': entity['name'],
                    'entity_code': entity['code'],
                    'entity_type': entity['etype'],
                    'score': score,
                    'match_type': 'name' if name_score >= code_score else 'code',
                })
        matches.sort(key=lambda x: x['score'], reverse=True)
        return matches

    def match_from_letterhead(self, text: str, entity_type: str = 'issuer',
                              top_k: int = 3) -> List[Dict]:
        """اقتراح أفضل-k جهة بمطابقة ترويسة المستند (أعلى ~40% أسطر) بأسماء الجهات.

        يعالج الحالة الغالبة التي تفشل فيها أنماط «من/الجهة»: اسمُ الجهة المُرسِلة
        حاضرٌ في ترويستها لا في جملة «من X». مقيسٌ على بيانات حقيقية:
        hit@3 ≈ 22% مقابل ≈4% للأنماط وحدها. اقتراحٌ للمراجعة لا للقبول الصامت
        (الثقة تُحدَّد في الأنبوب) — لأن ~63% من الجهات وحداتٌ داخلية غير مطبوعة أصلاً.
        """
        entities = self.get_entities_list()
        text = (text or '').strip()
        if not entities or not text:
            return []
        head = letterhead_region(text)      # أوّل 40% أسطر (ترويسة + مُخاطَب)
        if not head:
            return []
        words = _normalize_ar(head).split()[:80]
        windows = [
            ' '.join(words[i:i + n])
            for n in range(2, 7)
            for i in range(len(words) - n + 1)
        ]
        if not windows:
            return []
        try:
            vec, matrix = self._ensure_tfidf(entities)
            sims = (vec.transform(windows) @ matrix.T).toarray()
            per_entity = sims.max(axis=0)          # أعلى تشابه لكلّ جهة عبر النوافذ
        except Exception as e:
            logger.warning('[EntityMatcher] مطابقة الترويسة تعذّرت: %s', e)
            return []
        matches = []
        for idx in per_entity.argsort()[::-1]:
            sim = float(per_entity[idx])
            if sim < _TFIDF_MIN_SIM:
                break                              # مرتّبة تنازلياً — لا فائدة بعدها
            e = entities[idx]
            if entity_type and entity_type != 'both' and e['etype'] not in (entity_type, 'both'):
                continue
            matches.append({
                'entity_id': e['id'],
                'entity_name': e['name'],
                'entity_code': e['code'],
                'entity_type': e['etype'],
                'score': round(sim * 100, 1),
                'match_type': 'letterhead',
            })
            if len(matches) >= top_k:
                break
        return matches

    def _ensure_memory_index(self):
        """يبني فهرس TF-IDF على ترويسات الذاكرة، ويُعيد بناءه عند تغيّر العدد أو مرور TTL."""
        from core.models import LetterheadMemory
        now = time.monotonic()
        count = LetterheadMemory.objects.count()
        if (self._memory_index is not None and self._memory_index[3] == count
                and (now - self._memory_built_at) <= _ENTITY_CACHE_TTL):
            return self._memory_index
        rows = list(LetterheadMemory.objects.values_list(
            'letterhead',
            'issuing_entity_id', 'issuing_entity__name', 'issuing_entity__code',
            'receiving_entity_id', 'receiving_entity__name', 'receiving_entity__code',
            'book__date', 'created_at'))       # 7,8: إشارتا الحداثة للترجيح
        if not rows:
            self._memory_index = (None, None, [], count)
            self._memory_built_at = now
            return self._memory_index
        from sklearn.feature_extraction.text import TfidfVectorizer
        vec = TfidfVectorizer(analyzer='char_wb', ngram_range=(3, 5))
        matrix = vec.fit_transform([_normalize_ar(r[0]) for r in rows])
        self._memory_index = (vec, matrix, rows, count)
        self._memory_built_at = now
        return self._memory_index

    def match_from_memory(self, text: str, entity_type: str = 'issuer',
                          top_k: int = 3) -> List[Dict]:
        """يقترح الجهة بمطابقة ترويسة مستندٍ جديد بترويسات سابقة مؤكَّدة (تعلّمٌ من الداتا بيس).

        يكسر سقف «الوحدات الداخلية غير المطبوعة»: مستندات نفس المُرسِل تُسنَد دوماً
        لنفس الجهة، فالتشابه يكشفها. مقيسٌ بترك-واحد: hit@3 ≈ 85% مقابل ≈16% لمطابقة
        الاسم. يكبر مع كلّ كتاب يُحفَظ (حلقة الالتقاط) — بلا حدّ ولا إعادة تدريب."""
        text = (text or '').strip()
        if not text:
            return []
        try:
            vec, matrix, rows, _ = self._ensure_memory_index()
        except Exception as e:
            logger.warning('[EntityMatcher] فهرس الذاكرة تعذّر: %s', e)
            return []
        if vec is None:
            return []
        head = letterhead_region(text)
        if not head:
            return []
        sims = (vec.transform([_normalize_ar(head)]) @ matrix.T).toarray().ravel()
        cols = (1, 2, 3) if entity_type == 'issuer' else (4, 5, 6)   # (id, name, code)
        from datetime import date
        today = date.today()

        def _recency_weight(row):
            """الأحدث أوثق (يعالج انجراف التوجيه): وزنٌ يتناقص بنصف-عُمر حسب تاريخ
            الكتاب (أو تاريخ إنشاء الصفّ احتياطاً). يؤثّر في الترتيب لا في الثقة."""
            rdate = row[7] or (row[8].date() if row[8] else None)
            if rdate is None:
                return 0.1
            age = (today - rdate).days
            return 2.0 ** (-max(age, 0) / _MEMORY_HALFLIFE_DAYS)

        votes = {}   # eid -> [weighted_acc, max_sim, name, code] — الترتيب بالمُرجَّح، الثقة = max_sim
        for i, sim in enumerate(sims):
            s = float(sim)
            if s < _MEMORY_MIN_SIM:
                continue
            row = rows[i]
            eid = row[cols[0]]
            if eid is None:
                continue
            weighted = s * _recency_weight(row)
            v = votes.get(eid)
            if v is None:
                votes[eid] = [weighted, s, row[cols[1]], row[cols[2]]]
            else:
                v[0] += weighted
                if s > v[1]:
                    v[1] = s
        ranked = sorted(votes.items(), key=lambda kv: kv[1][0], reverse=True)[:top_k]
        return [{
            'entity_id': eid,
            'entity_name': v[2],
            'entity_code': v[3],
            'entity_type': entity_type,
            'score': round(v[1] * 100, 1),      # ثقة = أعلى تشابه (لا تُظلَم الجهات القديمة)
            'match_type': 'memory',
        } for eid, v in ranked]

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
        """تطهير الذاكرة المؤقتة (يُعيد التحميل عند الطلب التالي)"""
        self.entities_cache = None
        self._cache_loaded_at = 0.0
        self._tfidf = None
        self._tfidf_built_at = -1.0
        self._memory_index = None
        self._memory_built_at = 0.0


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
