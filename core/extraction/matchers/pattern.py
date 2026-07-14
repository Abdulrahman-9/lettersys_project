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
_SENDER_NUM_CODE = (
                    # رمز السجلّ العربي (قد يحمل رقماً: «ش13») ثم التسلسل — بفاصل
                    # شرطة/مائل أو **مسافة**: «ش13/2571» ، «ش8/د/1844» ، «ش13 2571».
                    # (صيغة الصادر الخارجي من مكتب المدير العام — توجيه المالك.)
                    # يتقدّم البدائل: صنف [A-Za-z؀-ۿ] لا يشمل الأرقام اللاتينية بعد
                    # تطبيع الأرقام العربية، فكانت هذه الصيغة تفلت كلياً.
                    # مقاطع الرمز قد تكون حرفية («ش8/د») أو رقمية («ش/12») —
                    # كتب قسم تقنية المعلومات تكتبها «العدد: ش/12 1556».
                    # مقاطع الرمز يفصلها شرطة/مائل **أو مسافة** («ح م/ 903» — قسم
                    # حماية المنشآت)، وقد تكون رقمية («ش/12»).
                    r'([ء-ي]{1,4}[0-9]{0,3}'
                    r'(?:(?:\s*[/\-]\s*|\s+)(?:[ء-ي]{1,4}[0-9]{0,3}|[0-9]{1,3}))*'
                    r'(?:\s*[/\-]\s*|\s+)[0-9]{2,6}\b'
                    r'|[A-Za-z؀-ۿ]{1,7} ?[/\-] ?[A-Za-z؀-ۿ]{1,7}[\-]? ?[0-9]{3,14}'  # مقطعان: EBS-MdOC20260594 ، QPC- MdOC-20260083
                    r'|[A-Za-z؀-ۿ]{1,7} ?[/\-] ?[0-9][0-9/\-]{1,18}'
                    r'|[0-9]{1,6} ?[/\-] ?[ء-ي]{1,4}'                  # رقم ثم حرف سجلّ عربي: 241/و ، 12/ص
                    r'|[0-9]{2,6} ?[/\-] ?[0-9][0-9/\-]{1,18}'
                    r'|[0-9]{4,12})')   # الحدّ 4 خانات: خفضُه لـ3 قِيس فرفع الكاذبة 9→23
                                        # (خربشات خط اليد تُقرأ خطأً بجوار «العدد») — يُعاد
                                        # فتحه لاحقاً خلف بوّابة بصمة الجهة (قابلية التتبّع)
# «reference» (والاختصارات) + حشو اختياري «number/no» — يلتقط «Reference Number: MF-2026-195».
# «(?<![ء-ي])» = تسمية الحقل القائمة بذاتها: ترفض «بالعدد/والعدد» الظرفية (إحالات
# المتن: «كتابنا بالعدد 51/55 في…») — قِيس على المخزَّن: 41/45 إيجابية كاذبة كانت
# إحالات؛ يكملها حصرُ البحث بمنطقة الرأس في extract_sender_number.
# الفاصل يشمل «/» و«\» — قِيس على 331 كتاباً: «العدد / 585» صيغة شائعة في أعالي
# الكتب العربية (توجيه المالك، مُتحقَّق: الالتقاط 8→22 كتاباً بها وحدها).
_SENDER_NUM_RE = re.compile(
    r'(?:(?<![ء-ي])(?:العدد|الرقم)|(?:reference|ref|rf|ro|ri|id)\b(?:[.\s]{0,2}(?:number|no)\.?)?)\s*[\\/:.#=\-]?\s*'
    + _SENDER_NUM_CODE,
    re.I)
_SENDER_NUM_BAD = ('fax', 'tel', 'phone', 'هاتف', 'فاكس', 'ص.ب', 'mobile', 'موبايل', 'جوال')

# رمز السجلّ العربي قبل الرقم («العدد: ش13/1844» — رمز القسم المُصدِر: ش13، ش4، د…).
# قِيس على 9,155 كتاباً مؤكَّداً: الموظف **يجرّد** الرمز العربي ويحفظ التسلسل وحده
# (الوارد الداخلي 99% رقمي صرف)، بينما **يُبقي** الأكواد اللاتينية للشركات الأجنبية
# (الوارد الخارجي: 11% بأكواد EBS-MdOC / NK / QPC…). فنطابق عُرفَه حرفياً:
# عربيٌّ ⇒ التسلسل فقط + الرمز يُعاد منفصلاً (إشارة هوية الجهة المُصدِرة)،
# لاتينيٌّ ⇒ الكود كما هو.
_AR_LETTERS = re.compile(r'[ء-ي]')
# رأس الرمز: حرفٌ/حرفان عربيان + رقم اختياري («ش13»، «د»، «ش8») — قد يتكرّر بفواصل
_SERIAL_RE = re.compile(r'\d{2,}')


def split_register_code(code: str):
    """يفصل رمز السجلّ العربي عن التسلسل — **لا تُجرَّد مسافاتُه قبل الاستدعاء**.
    القاعدة الحاسمة: **آخر مجموعة أرقام هي التسلسل**، وما قبلها هو الرمز:
      «ش13/2571» → ('2571', 'ش13')      | «ش13 2571» → ('2571', 'ش13')
      «ش8/د/1844» → ('1844', 'ش8/د')    | «ش/12 1556» → ('1556', 'ش/12')  ← قسم تقنية المعلومات
      «241/و» → ('241', None)            | لاتيني: (كما هو، None)
    (الفاصل مسافةً = صيغة الصادر الخارجي من مكتب المدير العام.)"""
    if not code or not _AR_LETTERS.search(code):
        return (re.sub(r'\s+', '', code) if code else code), None
    groups = list(_SERIAL_RE.finditer(code))
    if not groups:
        return re.sub(r'\s+', '', code), None
    serial = groups[-1].group(0)
    prefix = code[:groups[-1].start()].strip(' /-.')
    if not _AR_LETTERS.search(prefix):      # «241/و»: لا رمز — التسلسل وحده
        return serial, None
    return serial, re.sub(r'\s+', '', prefix)

# تاريخ الجهة المُرسِلة: بعد «التاريخ» (عربي) أو «Date/Dated» (إنجليزي، شائع بالإيميلات).
# ثلاث صيغ للتاريخ: اسم شهر إنجليزي (June 20, 2026 / 20 June 2026) أو رقمي (20/6/2026).
# «(?<![ء-ي])» = تسميةُ الحقل القائمة بذاتها فقط: ترفض «بالتاريخ/وبتأريخ» الظرفية
# (إحالات المتن: «المرقم … بتأريخ …») — تاريخٌ خاطئ أسوأ من فراغ (توصية استشارية).
# صيغ التاريخ المطبوعة كما قِيست فعلاً على 468 مستنداً رقمياً من 26 جهة إنكليزية
# (2026-07-14 — توجيه المالك «كل جهة لها صيغتها»): «June 20,2026» (بلا مسافة بعد
# الفاصلة، 20 مرة)، «August 6, 2025» (11)، «16 March 2026» (10)، «May 16 2026» (6)،
# «07 Aug., 2025»، و**«September2,2025» بلا مسافةٍ بين الشهر واليوم** — فالمسافة
# صارت اختيارية (\s*). الصيغة الرقمية نادرة (مرّة واحدة) فغموض ي/ش لا يهدّدنا عملياً.
# قيمة التاريخ (بلا علامة) — الصيغ المقيسة على مستندات الأرشيف الحقيقية:
#   «June 20,2026» ، «August 6, 2025» ، «16 March 2026» ، «10Aug.,2025» ،
#   «16\ 4 \ 2026» (الشرطة المقلوبة — كتابةٌ عربية شائعة كانت تُفقَد كلياً).
# السنة أربع خانات إلزامياً في الصيغ الحرفية: بدونها يخطف «3 May 16» (والـ«3»
# ضجيجُ OCR) مكانَ التاريخ الحقيقي «May 16 2026».
_DATE_VALUE_RE = re.compile(
    r'([A-Za-z]{3,9}\.?\s*\d{1,2}\s*,?\s*\d{4}'
    r'|\d{1,2}\s*[A-Za-z]{3,9}\.?\,?\s*\d{4}'
    r'|[\d٠-٩]{1,4}\s*[/\\\-.]\s*[\d٠-٩]{1,2}\s*[/\\\-.]\s*[\d٠-٩]{1,4})', re.I)

# العلامة وحدها. **درس القراءة بالعين** (2026-07-14): اشتراطُ فاصلٍ نظيفٍ بين
# العلامة والتاريخ كان يُفقدنا كتباً حقيقية — الواقع فوضويّ:
#   «Date; 16\ 4 \ 2026» (فاصلة منقوطة) ، «Date3 May 16 2026» (OCR قرأ «:» رقماً!)
# فالبحث الآن **بنافذةٍ قصيرة** بعد العلامة (حتى 28 محرفاً، سطرٌ واحد) لا بالتصاق.
# المبدأ (بعد قراءة 20 كتاباً صامتاً بالعين): **تسامحٌ مع العلامة، صرامةٌ مع القيمة**.
# الدقّة يحرسها _DATE_VALUE_RE (تاريخٌ صريحٌ بسنةٍ رباعية) لا صحّةُ هجاء العلامة —
# فـOCR يشوّهها ويلصقها بما حولها، وهذه صيغُها المقيسة في مستندات حقيقية:
#   «Dater March 16,2026»       ← النقطتان قُرِئتا حرف r   (qurnain #7021)
#   «Dete: March 30, 2026»      ← «Date» قُرِئت «Dete»      (NK #7049)
#   «Date3 May 16 2026»         ← النقطتان قُرِئتا رقماً    (EBS #11189)
#   «Ref:ZU-20260015Date: …»    ← ملتصقة برقم             (Geo-Jade #7023)
#   «JMC ChairmanDate: 09 Feb»  ← ملتصقة بكلمة            (Zhongman #11097)
_DATE_LABEL_RE = re.compile(
    r'(?<![ء-ي])الت[أا]ريخ'
    r'|(?<![A-Za-z])[Dd][aeo]t[aec]?[a-z]?(?![a-z])'   # date/dete/dater/datc…
    r'|(?<=[A-Za-z0-9])Date(?![a-z])'                  # ملتصقة: «…ChairmanDate:»
)
_DATE_WINDOW = 28
# خليّة جدول ترويسة الجودة «Date Rev / May 2025» ليست تاريخ كتاب (نفس فخّ المُموضِع)
_TABLE_NEXT_RE = re.compile(r'^\W{0,3}(rev|doc|no\b)', re.I)


def _find_labeled_date(text: str):
    """يُعيد نصّ التاريخ الذي يلي علامةً في نافذتها، أو None."""
    for lm in _DATE_LABEL_RE.finditer(text or ''):
        tail = text[lm.end():lm.end() + _DATE_WINDOW].split('\n')[0]
        if _TABLE_NEXT_RE.match(tail):
            continue                       # «Date Rev» — خليّة جدول لا حقل
        vm = _DATE_VALUE_RE.search(tail)
        if vm:
            return vm.group(1)
    return None

# أسماء الأشهر التي يُشوّهها OCR في المسوحات: «luly 5 2026» (July)، «Aptil 23,2026»
# (April) — قِيسا في عيّنة EBS/BADRA. نصحّح الاسمَ بمسافة تحرير ≤1 من شهرٍ معروف
# (أو اختصاره) قبل التحليل، فتُقرأ التواريخ التي كانت تضيع كلياً.
_EN_MONTHS = ('january', 'february', 'march', 'april', 'may', 'june', 'july',
              'august', 'september', 'october', 'november', 'december')
_MONTH_TOKEN_RE = re.compile(r'\b[A-Za-z]{3,9}\b')


def _edit_le1(a: str, b: str) -> bool:
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(1 for x, y in zip(a, b) if x != y) <= 1
    if len(a) > len(b):
        a, b = b, a
    return any(a == b[:i] + b[i + 1:] for i in range(len(b)))


_MONTH_ABBR = {m[:3] for m in _EN_MONTHS} | {'sept'}


def repair_month_name(text: str) -> str:
    """يُصحّح اسم شهرٍ شوّهه OCR («luly»→«July»، «Aptil»→«April») — بلا مساس بغيره.

    الشرط صارم: مسافة تحرير ≤1 من **الاسم الكامل** للشهر. (مطابقةُ البادئة
    الثلاثية بمسافة تحرير جرّبت فأسقطت «Dear» → «December» — الكلمة العادية
    أقرب لشهرٍ ممّا نظنّ، فلا تساهل هنا.)"""
    def _fix(m):
        tok = m.group()
        low = tok.lower()
        if low in _EN_MONTHS or low in _MONTH_ABBR:
            return tok                      # سليمٌ أصلاً (كاملاً أو اختصاراً)
        for mon in _EN_MONTHS:
            if _edit_le1(low, mon):
                return mon.capitalize()
        return tok
    return _MONTH_TOKEN_RE.sub(_fix, text)

# حدّ منطقة الرأس: في الرسالة العراقية الرسمية تاريخُ الكتاب يقع دائماً فوق سطر
# الموضوع (م/ /الموضوع/Subject)، وكلُّ تاريخٍ تحته إحالةٌ في المتن. القطعُ عند
# العلامة (حصراً) + سقف 15 سطراً غير فارغ (شبكة أمان للإيميلات والكتب بلا علامة).
_SUBJECT_CUT_RE = re.compile(
    r'^\s*(?:الموضوع|بخصوص|بشأن|م\s*[/:\-.,،]|(?i:subject|subj)\b)')
_HEADER_MAX_LINES = 15


def _header_zone(text: str, max_lines: int = _HEADER_MAX_LINES) -> str:
    """يقتطع منطقة الرأس: حتى أول سطرِ علامةِ موضوعٍ (حصراً) أو سقف الأسطر، أيّهما أسبق.
    يُسقط العلامات الخفية (LRM/RLM) — قِيس: ثاني أشيع «فاصل» بعد «العدد» في 331
    كتاباً حقيقياً هو ‎ الخفي (48 كتاباً) يُفشل علامتي الرقم والتاريخ."""
    out, kept = [], 0
    for ln in (text or '').split('\n'):
        ln = ln.translate(_INVISIBLE_MARKS)
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

# سطرُ تاريخٍ عارٍ (بلا علامة): قوالب الرسائل الغربية (Slb) تفتتح بالتاريخ وحده
# سطراً («July 6 , 2026»). القبول لصيَغ اسم الشهر فقط وبشرط أن يكون السطرُ كلُّه
# تاريخاً — الصيغ الرقمية المنعزلة مُستبعَدة عمداً: شظايا أختامٍ عربية بدت أسطراً
# (قِيس: قبولها رفع الكاذبة 2→5). خطأ التاريخ أسوأ من فراغه.
_BARE_DATE_LINE_RE = re.compile(
    r'^\s*('
    r'[A-Za-z]{3,9}\.?\s+\d{1,2}\s*,?\s*\d{4}'
    r'|\d{1,2}\s+[A-Za-z]{3,9}\.?,?\s*\d{4}'
    r')\s*$', re.I)
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
                         'حرصاً', 'حرصا', 'انطلاقاً', 'انطلاقا', 'تنفيذاً', 'تنفيذا',
                         # مفتتحات ظرفية شائعة في كتب الشركة (صورة المالك: «نظراً
                         # لارتفاع درجات الحرارة…» كانت تُلصق بالموضوع)
                         'نظراً', 'نظرا', 'بالنظر', 'وفقاً', 'وفقا', 'بالاستناد', 'ضمن',
                         'علماً', 'علما', 'تجدون', 'مرفق', 'المرفق', 'بموجب', 'بموافقة',
                         # افتتاحيات المتن الإنجليزية (إيميلات) — تُقارَن على المُصغَّر
                         'dear', 'greetings', 'attention', 'attn', 'we ', 'please', 'kindly',
                         'with reference', 'reference is', 'this letter', 'warm')

        def _join_wrapped(captured: str, idx: int) -> str:
            # دليل التفاف قويّ: ينتهي بكلمة ربط («… من شركة») أو بلغ سقف الالتقاط —
            # يضمّ ولو طالت التتمّة. دليل ضعيف (مجرّد الطول ≥20): يضمّ تتمّةً قصيرة
            # فقط («عمران التركية») — سطرُ متنٍ كامل العرض («حرصاً على تعزيز…»)
            # بدايةُ نصٍّ لا تتمّة (بلاغ مالك مقيس: 196→193 لولا استثناء القويّ).
            strong = len(captured) >= 78 or captured.split()[-1] in _connectors
            if not (strong or len(captured) >= 20) or idx + 1 >= len(lines):
                return captured
            nxt = lines[idx + 1]
            if not strong and len(nxt) > 45:
                return captured
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
        if result[0] is None:
            # اسم شهرٍ شوّهه OCR («luly 5 2026») — قِيس في كتب EBS/BADRA الممسوحة
            repaired = repair_month_name(zone)
            if repaired != zone:
                result = self._sender_date_once(repaired)
        if result[0] is None:
            # سطر تاريخ عارٍ في الرأس (قالب Slb الغربي) — انظر _BARE_DATE_LINE_RE
            for ln in zone.split('\n'):
                m = _BARE_DATE_LINE_RE.match(ln)
                if not m:
                    continue
                cand = m.group(1).translate(_AR_DIGITS)
                date_obj, _c = self.extract_date(cand)
                if not (date_obj and _is_plausible_date(date_obj)):
                    try:
                        date_obj = date_parser.parse(cand, dayfirst=True)
                    except (ValueError, TypeError, OverflowError):
                        continue
                if date_obj and _is_plausible_date(date_obj):
                    return (date_obj, 0.70)
        return result

    # تشويه OCR داخل التاريخ: حرف l/I يُقرأ بدل الرقم 1، وO بدل 0 («l8 February»،
    # «2l April»، «B\?\?bZ5») — قِيس في كتب ZPEC/اللجان الممسوحة. الإصلاح محصورٌ
    # في **المرشّح** بعد العلامة (لا النصّ كله) فلا يفسد كلمةً سليمة.
    _OCR_DIGITS = str.maketrans({'l': '1', 'I': '1', '|': '1', 'O': '0', 'o': '0'})

    @staticmethod
    def _repair_ocr_digits(cand: str) -> str:
        """يُصحّح l/I/O داخل مقاطع **رقمية محضة** شوّهها OCR: «l8»→«18»، «2l»→«21».

        الشرط الصارم (درس مؤلم بالقراءة بالعين): المقطع رقميٌّ إن لم يبقَ فيه بعد
        إسقاط الحروف المُلتبِسة إلا أرقام. اشتراطُ «فيه رقمٌ ما» وحده حوّل «April4»
        (شهرٌ ملتصقٌ باليوم) إلى «Apri14» فأهدر تواريخ سليمة — إفسادُ الإصلاح."""
        def _fix(tok):
            t = tok.group()
            if not re.search(r'\d', t):
                return t
            core = re.sub(r'[lI|Oo]', '', t)
            if core and re.fullmatch(r'\d+', core):
                return t.translate(PatternMatcher._OCR_DIGITS)
            return t                       # «April4» تبقى كما هي
        return re.sub(r'[\w|]+', _fix, cand)

    def _sender_date_once(self, text: str) -> Tuple[Optional[datetime], float]:
        raw = _find_labeled_date(text)
        if not raw:
            return (None, 0.0)
        cand = self._repair_ocr_digits(raw).translate(_AR_DIGITS)
        cand = cand.replace('\\', '/')          # «16\ 4 \ 2026» → «16/ 4 / 2026»
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

    # بعض الجهات (Slb) تضع رقم صادرها داخل سطر الموضوع نفسه: «Ref-135, Akkas…» —
    # لا في حقل رأسٍ منفصل. 16 كتاباً محفوظاً تُثبت أن المالك ينقل الرقم يدوياً
    # من العنوان كل مرّة. يقتطعه هذا النمط ويُنظّف العنوان.
    _TITLE_REF_RE = re.compile(r'^\s*(?:ref|rf)[.\-:\s]{0,3}(\d{2,6})\b[\s,.:؛،\-]*(.{4,})$', re.I)

    def split_ref_from_title(self, title: str) -> Tuple[Optional[str], str]:
        """إن بدأ العنوان بكود Ref-NNN: يعيد (الرقم، العنوان النظيف)؛ وإلا (None، كما هو)."""
        m = self._TITLE_REF_RE.match(title or '')
        if not m:
            return None, title or ''
        return m.group(1), m.group(2).strip()

    # نوع الوثيقة مطبوعٌ صراحةً في ترويسة نظام إدارة الجودة («مذكرة داخلية») —
    # فهو قراءةٌ لا تعلّمُ آلة (مصنّف حزيران قاس دون خطّ الأساس فرُمي). الترتيب
    # مقصود: الأخصّ أولاً. القيم مطابقة لأنواع قاعدة البيانات المستخدَمة فعلاً.
    _DOC_TYPE_RULES = (
        # الإعمام يُعرَف من مُخاطَبه: «كافة» قد تتقدّم («كافة الهيئات والاقسام»)
        # أو تتأخّر («الهيئات والاقسام المركزية كافة») — كلا الصيغتين في كتب الشركة.
        (re.compile(r'كافة\s+ال(?:هيئات|هيأت|هيات|اقسام)'
                    r'|ال(?:هيئات|هيأت|هيات)[^\n]{0,40}كافة'
                    r'|الاقسام[^\n]{0,30}كافة'
                    r'|(?:إلى|الى)\s*/\s*كافة'), 'اعمام'),
        (re.compile(r'\bاعمام\b|\bإعمام\b|\bتعميم\b|\bتعاميم\b'), 'اعمام'),
        (re.compile(r'ام[رﺭ]\s+اداري|أمر\s+إداري'), 'امر اداري'),
        (re.compile(r'مذكرة\s+داخلية|مذكره\s+داخليه'), 'مذكرة داخلية'),
        (re.compile(r'مراسلة\s+خارجية|مراسله\s+خارجيه'), 'مراسلة خارجية'),
        (re.compile(r'\bمحضر\b'), 'محضر'),
        (re.compile(r'\bتقرير\b'), 'تقرير'),
    )

    def extract_document_type(self, text: str) -> Tuple[Optional[str], float]:
        """نوع الوثيقة من ترويسة الرأس مباشرةً («مذكرة داخلية»، «اعمام»…).
        الإعمام يُكشف أيضاً من مُخاطَبه: «الى/ كافة الهيئات والاقسام المركزية»."""
        head = _header_zone(text or '', max_lines=20)
        for rx, value in self._DOC_TYPE_RULES:
            if rx.search(head):
                return value, 0.85
        return None, 0.0

    # مُخاطَب الكتاب: بعد «الى/» في رأس الصفحة (بنية الكتاب الرسمي)، أو «To:» في
    # الصادر الخارجي ثنائي اللغة. «الــى» بالتطويل واردةٌ في كتب الشركة.
    _RECIPIENT_RE = re.compile(
        r'^\s*(?:ا?ل?[اإ]?ـ*ل?ـ*ى|الى|إلى)\s*[/:]\s*(.{3,90})$'
        r'|^\s*to\s*[/:]\s*(.{3,90})$', re.M | re.I)

    def extract_recipient(self, text: str) -> Optional[str]:
        """اسم الجهة المُخاطَبة كما هو مكتوب بعد «الى/» (أو «To:») في الرأس.
        يُنظَّف من لواحق التأشير («… كافة ( قسم المتابعة )») ويبقى نصّاً خاماً
        للمطابقة — لا تفسير هنا."""
        head = _header_zone(text or '', max_lines=20)
        m = self._RECIPIENT_RE.search(head)
        if not m:
            return None
        name = m.group(1) or m.group(2) or ''
        name = re.sub(r'\s+', ' ', name).strip(' .:،-')
        # قوس التأشير اليدوي على الإعمام: «الهيئات والاقسام كافة ( قسم المتابعة )»
        name = re.sub(r'\s*\([^)]*\)\s*$', '', name).strip(' .:،-()')
        return name or None

    def extract_register_code(self, text: str) -> Optional[str]:
        """رمز سجلّ الجهة المُصدِرة من «العدد: ش13/1844» → «ش13» (أو None).
        إشارةُ هويةٍ قويّة للوارد الداخلي: الرمز مسجَّل لدينا لكل قسم."""
        t = _header_zone(text or '').translate(_AR_DIGITS)
        for m in _SENDER_NUM_RE.finditer(t):
            raw = m.group(1).strip('/-. ')          # بمسافاته: «ش13 2571» فاصلها مسافة
            pre = t[max(0, m.start() - 14):m.start()].lower()
            if any(b in pre for b in _SENDER_NUM_BAD):
                continue
            _serial, reg = split_register_code(raw)
            if reg:
                return reg
        return None

    def extract_sender_number(self, text: str) -> Tuple[Optional[str], float]:
        """رقم صادر الجهة المُرسِلة — مطبوعٌ في المستندات المكتوبة/الإيميلات ككودٍ
        مركّب بعد «العدد/ref/rf/ro/id» (مثل KHL/25/32)، **في منطقة الرأس فقط**:
        «العدد» تحت سطر الموضوع إحالةٌ لكتابٍ آخر («كتابنا العدد 51/55 في…») —
        قِيس: 41/45 إيجابية كاذبة كانت إحالات متن. الأكواد الشرعية أسفل الرأس
        تبقى مُغطّاة ببصمات الجهة (تبحث النصّ كاملاً ببادئات مؤكَّدة).
        يتجاهل الفاكس/الهاتف. المكتوب بخطّ اليد لا يُقرأ (يبقى None)."""
        t = _header_zone(text or '').translate(_AR_DIGITS)
        for m in _SENDER_NUM_RE.finditer(t):
            raw = m.group(1).strip('/-. ')            # بمسافاته (فاصل «ش13 2571»)
            pre = t[max(0, m.start() - 14):m.start()].lower()
            if any(b in pre for b in _SENDER_NUM_BAD):
                continue                              # سياق فاكس/هاتف → ليس رقم صادر
            if len(re.sub(r'\D', '', raw)) >= 2:      # أرقامٌ كافية (ليس ضجيجاً)
                # عُرف الموظف المقيس: الرمز العربي يُجرَّد، واللاتيني يبقى.
                serial, _reg = split_register_code(raw)
                return serial, 0.70
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
        doc_type, doc_type_conf = self.extract_document_type(text)
        register_code = self.extract_register_code(text)
        recipient = self.extract_recipient(text)

        return {
            'document_type': doc_type,
            'document_type_confidence': doc_type_conf,
            'register_code': register_code,
            'recipient': recipient,
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
