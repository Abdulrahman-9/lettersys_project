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


def _is_plausible_date(d) -> bool:
    """رفض التواريخ غير المعقولة (قبل 1900 أو في مستقبل بعيد) — غالباً أثر ضوضاء OCR."""
    return 1900 <= d.year <= datetime.now().year + 1


# تحويل الأرقام العربية-الهندية إلى غربية (للترويسة العراقية ٠-٩)
_AR_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')

# علامات اتجاه/عرض-صفري خفيّة يُدخلها OCR وتُفسِد مطابقة النصّ (مثل «مواظبة‎»)
_INVISIBLE_MARKS = {ord(c): None for c in '‎‏​‌‍﻿'}

# رقم صادر الجهة المُرسِلة: يُلتقط بعد «العدد/الرقم/ref/rf/ro/id». ثلاث صيغ:
#   1) كودٌ مركّب بحروف: NK-20260237 ، KHL/25/32 ، emdoc-2025-043
#   2) كودٌ مركّب بأرقام: 25/32 ، 2025-043
#   3) رقمٌ مجرّد (بعد علامة صريحة فقط): 20260237
# يوضَع كما هو في الحقل ليقبله المستخدم أو يعدّله (يحذف البادئة إن شاء).
_SENDER_NUM_CODE = (r'([A-Za-z؀-ۿ]{1,7} ?[/\-] ?[0-9][0-9/\-]{1,18}'
                    r'|[0-9]{1,6} ?[/\-] ?[ء-ي]{1,4}'                  # رقم ثم حرف سجلّ عربي: 241/و ، 12/ص
                    r'|[0-9]{2,6} ?[/\-] ?[0-9][0-9/\-]{1,18}'
                    r'|[0-9]{4,12})')
# «reference» (والاختصارات) + حشو اختياري «number/no» — يلتقط «Reference Number: MF-2026-195».
# «(?<![ء-ي])» = تسمية الحقل القائمة بذاتها: ترفض «بالعدد/والعدد» الظرفية (إحالات
# المتن: «كتابنا بالعدد 51/55 في…») — قِيس على المخزَّن: 41/45 إيجابية كاذبة كانت
# إحالات؛ يكملها حصرُ البحث بمنطقة الرأس في extract_sender_number.
_SENDER_NUM_RE = re.compile(
    r'(?:(?<![ء-ي])(?:العدد|الرقم)|(?:reference|ref|rf|ro|ri|id)\b(?:\s+(?:number|no)\.?)?)\s*[:.#=\-]?\s*'
    + _SENDER_NUM_CODE,
    re.I)
_SENDER_NUM_BAD = ('fax', 'tel', 'phone', 'هاتف', 'فاكس', 'ص.ب', 'mobile', 'موبايل', 'جوال')

# تاريخ الجهة المُرسِلة: بعد «التاريخ» (عربي) أو «Date/Dated» (إنجليزي، شائع بالإيميلات).
# ثلاث صيغ للتاريخ: اسم شهر إنجليزي (June 20, 2026 / 20 June 2026) أو رقمي (20/6/2026).
# «(?<![ء-ي])» = تسميةُ الحقل القائمة بذاتها فقط: ترفض «بالتاريخ/وبتأريخ» الظرفية
# (إحالات المتن: «المرقم … بتأريخ …») — تاريخٌ خاطئ أسوأ من فراغ (توصية استشارية).
_SENDER_DATE_RE = re.compile(
    r'(?:(?<![ء-ي])الت[أا]ريخ|\bdated\b|\bdate\b)\s*[:/=.\-]?\s*('
    r'[A-Za-z]{3,9}\.?\s+\d{1,2}\s*,?\s*\d{2,4}'
    r'|\d{1,2}\s+[A-Za-z]{3,9}\.?\,?\s*\d{2,4}'
    r'|[\d٠-٩]{1,4}\s*[/\-.]\s*[\d٠-٩]{1,2}\s*[/\-.]\s*[\d٠-٩]{1,4}'
    r')', re.I)

# حدّ منطقة الرأس: في الرسالة العراقية الرسمية تاريخُ الكتاب يقع دائماً فوق سطر
# الموضوع (م/ /الموضوع/Subject)، وكلُّ تاريخٍ تحته إحالةٌ في المتن. القطعُ عند
# العلامة (حصراً) + سقف 15 سطراً غير فارغ (شبكة أمان للإيميلات والكتب بلا علامة).
_SUBJECT_CUT_RE = re.compile(
    r'^\s*(?:الموضوع|بخصوص|بشأن|م\s*[/:\-.,،]|(?i:subject|subj)\b)')
_HEADER_MAX_LINES = 15


def _header_zone(text: str, max_lines: int = _HEADER_MAX_LINES) -> str:
    """يقتطع منطقة الرأس: حتى أول سطرِ علامةِ موضوعٍ (حصراً) أو سقف الأسطر، أيّهما أسبق."""
    out, kept = [], 0
    for ln in (text or '').split('\n'):
        if not ln.strip():
            continue
        if _SUBJECT_CUT_RE.search(ln):
            break
        out.append(ln)
        kept += 1
        if kept >= max_lines:
            break
    return '\n'.join(out)

# إزالة تشويه OCR/طبقات المسح داخل نافذة التاريخ فقط (بعد العلامة):
# «Date: lul 22026» = «Jul 2, 2026» بحرف J→l وفاصلة ساقطة — نمطٌ مرصود في
# طبقات الإيميلات الممرَّرة عبر ماسحات المكاتب. النافذة الضيّقة تمنع العبث بالنصّ.
_DATE_MARKER_RE = re.compile(r'(?:الت[أا]ريخ|\bdated\b|\bdate\b)\s*[:/=.\-]?\s*', re.I)
_MONTH_GARBLE_RE = re.compile(r'\b[lI1](an|un|ul)\b', re.I)      # lul→Jul، Ian→Jan، 1un→Jun
_FUSED_DAY_YEAR_RE = re.compile(r'\b(\d{1,2})(20\d{2})\b')       # 22026 → 2 2026


def _degarble_date_zone(text: str) -> str:
    """يُصحّح تشويهات الشهر/الأرقام في المقطع الذي يلي علامة التاريخ مباشرةً."""
    def _fix(seg):
        seg = _MONTH_GARBLE_RE.sub(lambda m: 'J' + m.group(1), seg)
        return _FUSED_DAY_YEAR_RE.sub(r'\1 \2', seg)
    out, last = [], 0
    for m in _DATE_MARKER_RE.finditer(text):
        if m.end() < last:
            continue
        end = min(len(text), m.end() + 22)
        out.append(text[last:m.end()])
        out.append(_fix(text[m.end():end]))
        last = end
    out.append(text[last:])
    return ''.join(out)


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
                has_group = '(' in pattern
                number = match.group(1) if has_group else match.group(0)
                # الأنماط المعنونة (لها مجموعة التقاط) أوثق من «رقم مجرّد»
                confidence = 0.95 if has_group else 0.80
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
                            if _is_plausible_date(date_obj):
                                return (date_obj, 0.95)
                    else:
                        day, month, year = match.groups()
                        date_obj = datetime(int(year), int(month), int(day))
                        if _is_plausible_date(date_obj):
                            return (date_obj, 0.92)
                except (ValueError, AttributeError):
                    pass

        # محاولة استخراج أي تاريخ
        try:
            # البحث عن أرقام يمكن أن تكون تاريخاً — كل نمط بخياراته الصحيحة:
            #   DD-MM-YYYY → dayfirst=True | YYYY-MM-DD → yearfirst (لا dayfirst وإلا قُلب الشهر/اليوم)
            date_patterns = [
                (r'\d{1,2}[-/]\d{1,2}[-/]\d{4}', {'dayfirst': True}),
                (r'\d{4}[-/]\d{1,2}[-/]\d{1,2}', {'yearfirst': True, 'dayfirst': False}),
            ]

            for pattern, opts in date_patterns:
                match = re.search(pattern, text)
                if match:
                    date_obj = date_parser.parse(match.group(0), **opts)
                    if _is_plausible_date(date_obj):
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
        استخراج عنوان/موضوع المستند:
        1) يفضّل مؤشّر موضوع صريح (الموضوع / بعنوان / بخصوص / م-).
        2) وإلا يتخطّى الترويسة (سطور لاتينية الغالب أو أسماء جهات رسمية) ويأخذ
           أوّل سطر عربي جوهري.
        3) احتياطياً: أوّل الأسطر (السلوك القديم).
        """
        # علاماتٌ مدعومة بالبيانات (قيست على مستندات حقيقية: 38%→40% بلا تراجع).
        # «م/» تُكتب بأخطاء OCR (م، م. م,) فوسّعنا فاصلها؛ و«بشأن/حول» علامتا موضوع
        # عراقيّتان شائعتان كانتا غائبتين. وأُضيفت «Subject/Subj/سبجكت» للإيميلات
        # الإنجليزية (العنوان بعدها إنجليزيّ — لا يُصفّى كترويسة).
        # مجموعتان بأولوية حتمية: الكتب ثنائية العمودين (عربي + ترجمة إنكليزية)
        # يقلب OCR ترتيب أسطرها — فالعربية (النصّ الأصلي المعتمد) تُمسح أولاً
        # دائماً، والإنكليزية لا تُجرَّب إلا عند غيابها (توجيه مالك).
        arabic_markers = (
            r'الموضوع\s*[:/\-]?\s*([^\n]{3,80})',
            r'بعنوان\s*\(?\s*([^)\n]{3,80})',   # حتى القوس المغلق أو نهاية السطر
            r'بخصوص\s*[:/\-]?\s*([^\n]{3,80})',
            r'بشأن\s*[:/\-]?\s*([^\n]{3,80})',
            r'(?:^|\s)حول\s*[:/\-.،]?\s*([^\n]{3,80})',
            r'(?:^|\s)م\s*[/:\-.,،]\s*([^\n]{3,80})',
            r'سبجكت\s*[:/\-]?\s*([^\n]{3,80})',
        )
        english_markers = (
            r'(?i:subject|subj)\s*[:.\-]\s*([^\n]{3,80})',
        )
        letterhead_hints = ('جمهورية', 'وزارة', 'الشركة العامة', 'محطة', 'مديرية', 'هيئة',
                            'republic', 'ministry', 'company', 'station', 'division', 'general')
        # سطرٌ يبدأ باسم جهة/قسم = ترويسة لا موضوع (نطابق البداية لا مجرّد الاحتواء،
        # كي لا نُسقط عنواناً يذكر «قسم» في وسطه). يعالج التقاط اسم القسم من الترويسة.
        org_prefixes = ('قسم', 'دائرة', 'شعبة', 'مكتب', 'شركة', 'مديرية', 'هيئة',
                        'وزارة', 'جمهورية', 'نظام الإدارة', 'نظام الاداره')
        stop_words = {'من', 'إلى', 'هذا', 'ذلك', 'كل', 'بعض', 'أي', 'التي', 'الذي',
                      'أن', 'إن', 'كان', 'كانت', 'هو', 'هي', 'هم', 'أنت', 'نحن'}

        def _words(s: str, cap: int = num_words) -> str:
            s = s.translate(_INVISIBLE_MARKS)               # أسقِط علامات LTR/RTL الخفيّة
            ws = [w.strip(' /:؛،.-') for w in s.split()]    # لواحق ترقيم عالقة
            ws = [w for w in ws if w and w not in stop_words]
            return ' '.join(ws[:cap])

        # أسقِط العلامات الخفية (LRM/RLM من طبقات النصّ) قبل مطابقة العلامات —
        # «م‏/» كانت تُفشل علامة م/ فيسقط الموضوع لمسار الاحتياط (بلاغ مالك).
        lines = [ln.translate(_INVISIBLE_MARKS).strip()
                 for ln in (text or '').split('\n') if ln.strip()]
        lines = [ln for ln in lines if ln]
        if not lines:
            return ''

        # ── ضمّ تتمّة الموضوع الملتفّ (توصية استشارية، حالة حقيقية #11222) ──
        # الموضوع الطويل يلتفّ لسطرٍ ثانٍ («م/ تجهيز … من شركة» ⏎ «عمران التركية»).
        # نضمّ سطراً واحداً فقط إذا أوحى المُلتقَط بالالتفاف وخلا التالي من بدايات
        # الحقول/المتن. تاريخ/عدد بعده = حقل؛ «نرافق/نود/تحية…» = متن.
        _connectors = ('من', 'إلى', 'الى', 'على', 'عن', 'في', 'مع', 'و', 'عبر', 'خلال')
        _field_starts = ('إلى', 'الى', 'م/', 'م :', 'الموضوع', 'التاريخ', 'بتاريخ', 'بتأريخ',
                         'العدد', 'الرقم', 'نسخة', 'ص.ب', 'هاتف', 'فاكس', 'المرفقات', 'المرفق',
                         'to:', 'from:', 'subject', 'subj', 'date:', 'ref', 'cc:', 'attn', 'attachment')
        _body_openers = ('نرافق', 'نود', 'نأمل', 'نرجو', 'يرجى', 'يُرجى', 'برجاء', 'تحية',
                         'وبعد', 'السلام', 'إشارة', 'اشارة', 'بالإشارة', 'بالاشارة', 'استناداً',
                         'استنادا', 'إلحاقاً', 'الحاقا', 'عطفاً', 'عطفا', 'بناءً', 'بناء',
                         'نحيطكم', 'نعلمكم', 'نعرض', 'تفضلوا', 'أرجو', 'لديكم', 'طلبكم',
                         # افتتاحيات المتن الإنجليزية (إيميلات) — تُقارَن على المُصغَّر
                         'dear', 'greetings', 'attention', 'attn', 'we ', 'please', 'kindly',
                         'with reference', 'reference is', 'this letter', 'warm')

        def _join_wrapped(captured: str, idx: int) -> str:
            wraps = (len(captured) >= 20 or len(captured) >= 78
                     or captured.split()[-1] in _connectors)
            if not wraps or idx + 1 >= len(lines):
                return captured
            nxt = lines[idx + 1]
            low = nxt.lower()
            if (sum(1 for c in nxt if '؀' <= c <= 'ۿ') < 4
                    and sum(1 for c in low if 'a' <= c <= 'z') < 4):
                return captured
            if any(low.startswith(p) for p in _field_starts):
                return captured
            if any(low.startswith(p) for p in _body_openers):
                return captured
            if nxt.lstrip().startswith(('(', '﴾', '«', ')')):
                return captured
            return captured + ' ' + nxt

        # 1) مؤشّر موضوع صريح (سقف الكلمات 12 هنا — الموضوع الملتفّ أطول):
        #    مسحان بأولوية العربية (انظر تعليق المجموعتين أعلاه)
        for markers in (arabic_markers, english_markers):
            for idx, line in enumerate(lines):
                for pat in markers:
                    m = re.search(pat, line)
                    if m and len(m.group(1).strip()) > 3:
                        return _words(_join_wrapped(m.group(1).strip(), idx), cap=12)

        # 2) تخطّي الترويسة → أوّل سطر عربي جوهري
        for line in lines:
            letters = [c for c in line if c.isalpha()]
            if letters and sum(1 for c in letters if ord(c) < 128) / len(letters) > 0.5:
                continue  # سطر لاتيني الغالب (ترويسة)
            if any(h in line.lower() for h in letterhead_hints):
                continue  # سطر يحمل اسم جهة رسمية (ترويسة)
            if any(line.startswith(p) for p in org_prefixes):
                continue  # سطرٌ يبدأ باسم قسم/جهة = ترويسة لا موضوع
            if re.match(r'^(?:إلى|الى|السادة|السيد)\b|^(?:إلى|الى)\s*/', line):
                continue  # سطر المُرسَل إليه («إلى/ الجهات…») ليس موضوعاً أبداً (بلاغ مالك)
            if line.lstrip().startswith(('(', '﴾', '«', ')')):
                continue  # شعار/علامة مائية بين قوسين (مثل شعارات وطنية) — لا موضوع
            if sum(1 for c in line if '؀' <= c <= 'ۿ') >= 8:
                return _words(line)

        # 3) احتياطي
        return _words(' '.join(lines[:3]))

    def extract_sender_date(self, text: str) -> Tuple[Optional[datetime], float]:
        """تاريخ رسالة الجهة المُرسِلة — من علامة «التاريخ» (عربي) أو «Date/Dated»
        (إنجليزي، شائع بالإيميلات) **في منطقة الرأس فقط**: تواريخ المتن إحالاتٌ
        لكتبٍ أخرى («المرقم … بتأريخ …») والتقاطها إيجابيةٌ كاذبة أسوأ من الفراغ —
        فلا سقوط لكامل النصّ. يفهم أسماء الأشهر الإنجليزية والصيغ الرقمية، ويعيد
        المحاولة بعد إزالة تشويه نافذة التاريخ («lul 22026» → «Jul 2 2026»)."""
        zone = _header_zone(text or '')
        result = self._sender_date_once(zone)
        if result[0] is None:
            fixed = _degarble_date_zone(zone)
            if fixed != zone:
                result = self._sender_date_once(fixed)
        return result

    def _sender_date_once(self, text: str) -> Tuple[Optional[datetime], float]:
        m = _SENDER_DATE_RE.search(text)
        if not m:
            return (None, 0.0)
        cand = m.group(1).translate(_AR_DIGITS)
        # رقمي أولاً (extract_date يعالج ترتيب اليوم/الشهر/السنة بدقّة)
        date_obj, _c = self.extract_date(cand)
        if date_obj and _is_plausible_date(date_obj):
            return (date_obj, 0.80)
        # اسم شهر إنجليزي → dateutil يفهمه (June 20, 2026)
        try:
            date_obj = date_parser.parse(cand, dayfirst=True)
            if _is_plausible_date(date_obj):
                return (date_obj, 0.80)
        except (ValueError, TypeError, OverflowError):
            pass
        return (None, 0.0)

    def extract_sender_number(self, text: str) -> Tuple[Optional[str], float]:
        """رقم صادر الجهة المُرسِلة — مطبوعٌ في المستندات المكتوبة/الإيميلات ككودٍ
        مركّب بعد «العدد/ref/rf/ro/id» (مثل KHL/25/32)، **في منطقة الرأس فقط**:
        «العدد» تحت سطر الموضوع إحالةٌ لكتابٍ آخر («كتابنا العدد 51/55 في…») —
        قِيس: 41/45 إيجابية كاذبة كانت إحالات متن. الأكواد الشرعية أسفل الرأس
        تبقى مُغطّاة ببصمات الجهة (تبحث النصّ كاملاً ببادئات مؤكَّدة).
        يتجاهل الفاكس/الهاتف. المكتوب بخطّ اليد لا يُقرأ (يبقى None)."""
        t = _header_zone(text or '').translate(_AR_DIGITS)
        for m in _SENDER_NUM_RE.finditer(t):
            code = re.sub(r'\s+', '', m.group(1)).strip('/-. ')
            pre = t[max(0, m.start() - 14):m.start()].lower()
            if any(b in pre for b in _SENDER_NUM_BAD):
                continue                              # سياق فاكس/هاتف → ليس رقم صادر
            if len(re.sub(r'\D', '', code)) >= 2:     # أرقامٌ كافية (ليس ضجيجاً)
                return code, 0.70
        return None, 0.0

    def extract_all_data(self, text: str) -> Dict:
        """
        استخراج جميع البيانات من النص
        """
        book_number, book_number_conf = self.extract_book_number(text)
        date, date_conf = self.extract_date(text)
        sender_date, sender_date_conf = self.extract_sender_date(text)
        sender_number, sender_number_conf = self.extract_sender_number(text)
        secret_level, secret_conf = self.extract_secret_level(text)
        book_kind, kind_conf = self.extract_book_kind(text)
        entities = self.extract_entities(text)
        title = self.extract_title_keywords(text)

        return {
            'book_number': book_number,
            'book_number_confidence': book_number_conf,
            'date': date.isoformat() if date else None,
            'date_confidence': date_conf,
            'sender_date': sender_date.isoformat() if sender_date else None,
            'sender_date_confidence': sender_date_conf,
            'sender_number': sender_number,
            'sender_number_confidence': sender_number_conf,
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
