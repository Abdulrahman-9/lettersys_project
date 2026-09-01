# -*- coding: utf-8 -*-
"""تموضع شريط الرقم اليدوي — مرساة التسمية المطبوعة + prior تخطيط الجهة.

رؤية المالك المقيسة: لكل جهة شكل كتاب ثابت وموضعٌ مخصَّص للرقم في رأس الصفحة
(مسبار 2026-07-06: عناقيد المواضع ضيّقة — القسم القانوني x̄=0.19,ȳ=0.16؛
بدرة x̄=0.88,ȳ=0.15). خطأ المسبار الرئيس كان التقاط «رقم/عدد» من جُمل المتن —
يعالجه هنا شرطُ أعلى-الصفحة + قرب prior الجهة؛ وجهات «الصفر» (ترويسة بلا تسمية
مقروءة) يعالجها السقوط لمنطقة الـprior نفسها.
"""
import json
import logging
import os
import re
from typing import NamedTuple, Optional

logger = logging.getLogger(__name__)

# التسمية المطبوعة التي يسبق المكتوبُ اليدوي جوارَها (يسارها في RTL) — لكل حقل
# مرساته: «العدد» للرقم و«التاريخ» للتاريخ (مُرتكز v2). تسمية التاريخ مُرسّاة
# بحدود الكلمة كي لا تلتقط «بتاريخ» الظرفية من إحالات المتن.
_LABEL_RES = {
    'number': re.compile(r'عدد|^رقم$|^الرقم$|^ref\.?:?$', re.I),
    'date': re.compile(r'^ال?ت[أا]ريخ$|^date$', re.I),
}
_LABEL_RE = _LABEL_RES['number']   # توافق خلفي

# ترويسة نظام إدارة الجودة (IMS) جدولٌ يحمل «Date Rev» و«Rev No.» و«Doc No.» —
# وقياسٌ بصريّ على 8,704 شريط تاريخ أثبت أن مرساة «Date» كانت تلتقط خليّة الجدول
# (وهي أعلى الصفحة فتفوز بقاعدة «الأعلى يفوز») فيخرج القصّ حدودَ جدولٍ لا تاريخاً.
# الحلّ: أيّ مرشّحٍ يجاوره في سطره أحدُ ألفاظ الجدول يُرفض.
_TABLE_CONTEXT = re.compile(r'^(rev|doc|no\.?|ims|form|f\s*-?\d)', re.I)

# **التطويل يكسر مطابقة التسمية** (اكتُشف بالعين 2026-08-11): ترويسات المذكّرات تكتب
# «العـــدد» و«التأريــخ» بمحرف التطويل (U+0640) بين الحروف، فـ`عدد` لا تطابق «عـدد».
# النتيجة: المُموضِع يتخطّى تسمية الترويسة الحقيقيّة ويقع على «العدد» في اقتباس المتن
# (قِيس: #11287/11253/11254 — التسمية الحقيقيّة y=625 والمُلتقَط y=1018). التطبيع يجب
# أن يُسقط التطويل من **داخل** الكلمة لا من أطرافها فقط.
_TATWEEL = 'ـ'


def _norm_label(raw) -> str:
    """تطبيعُ رمزٍ من TSV قبل مطابقة التسمية: إسقاط التطويل داخلياً + تقليم الفواصل."""
    return (raw or '').replace(_TATWEEL, '').strip().strip(':.  ')

# ختمُنا نحن على الكتاب الوارد يحمل حقلَين مطبوعَين اسمهما «العدد» و«التاريخ»
# مملوءَين بخطّ اليد — أي **مرساتَي البحث نفسهما، بخطّ يدٍ، في صندوقٍ عالي التباين**.
# فعلى كلّ واردٍ مختوم توجد «العدد» مرّتين: مرساة الجهة (إن وُجدت) ومرساتنا؛
# ومرساتنا أسهل التقاطاً ⟵ **النظام كان يقرأ رقمَنا ويكتبه مكان رقم الجهة**.
# مشاهدةٌ بالعين على المستندات الخام (2026-07-21، #11119): جهةٌ إنكليزية رقمها
# مطبوع «№ VD-1231» ولا خطّ يد فيها إطلاقاً — والأرقام اليدوية الوحيدة أختامُنا،
# فسجّلت الجهة 0 من 120 شريطاً. وهذا جذر تسمّم التواريخ نفسه [[date_labels_poisoned]].
# «وزارة النفط»/«شركة نفط الوسط» **لا تصلحان** علامةً: ترويسة IMS الداخلية تحملهما.
_OUR_STAMP = re.compile(r'المتابعة|الوارد|الصادر|m\s*\.?d\s*\.?o\s*\.?c', re.I)
_STAMP_NEAR_X = 3.0        # أضعاف عرض التسمية أفقياً
_STAMP_NEAR_Y = 4.0        # أضعاف ارتفاع التسمية عمودياً (الختم كتلةٌ لا سطر)
_TOP_ZONE = 0.35           # التسمية الشرعية في أعلى ~ثلث الصفحة — تحتها جُمل متن
_PRIOR_RADIUS = 0.09       # قرب prior الجهة يقبل مرشّحاً خارج حزام أعلى الصفحة.
                           # وُسّع 0.09→0.14 لأجل التاريخ، فصار **يُتوّج نصوص المتن
                           # مراسيَ شرعية** (#9178 «٤١ في ٢٠٢٦/٣/٨ المتضمنة انعقاد
                           # الاجتماع» → 41 بينما الحقيقة 884؛ وكذلك #8958 و#9259).
                           # وقياس 2026-07-21: الصفوف التي لا بصمةَ لجهتها أعطت دقّة
                           # 100% (5/5) مقابل 70% حين توجد بصمة ⟵ الحزام يضرّ الدقّة.
                           # أُعيد إلى 0.09 وقِيس على البطاقة المجمّدة.
_MIN_PRIOR_SAMPLES = 3     # لا نثق بـprior قبل 3 مشاهدات


class LabelBox(NamedTuple):
    left: int
    top: int
    width: int
    height: int
    text: str
    source: str            # 'label' (تسمية مرئية) أو 'prior' (سقوط لموضع الجهة)


class EntityLayoutPriors:
    """بصمات تخطيط الجهات: أين تقع تسمية «العدد» في كتب كل جهة (متوسّط جارٍ).

    مُشتقّة من الكتب المؤكَّدة عبر أمر `learn_number_layouts`، وتُخزَّن JSON خارج
    git (قرار 7 في الخطة) — تعلّمٌ يتراكم بلا هجرات."""

    def __init__(self, path: str):
        self.path = path
        self._data = {}
        if os.path.exists(path):
            try:
                with open(path, encoding='utf-8') as f:
                    self._data = {int(k): v for k, v in json.load(f).items()}
            except (OSError, ValueError) as exc:
                logger.warning('[handwriting] تعذّر تحميل priors: %s', exc)

    def get(self, entity_id) -> Optional[dict]:
        p = self._data.get(int(entity_id)) if entity_id else None
        return p if p and p.get('n', 0) >= _MIN_PRIOR_SAMPLES else None

    def learn(self, entity_id, x_norm: float, y_norm: float):
        p = self._data.setdefault(int(entity_id), {'x': x_norm, 'y': y_norm, 'n': 0})
        n = p['n']
        p['x'] = (p['x'] * n + x_norm) / (n + 1)
        p['y'] = (p['y'] * n + y_norm) / (n + 1)
        p['n'] = n + 1

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump({str(k): v for k, v in self._data.items()}, f, ensure_ascii=False, indent=1)

    def __len__(self):
        return len(self._data)


class NumberStripLocator:
    """يجد صندوق تسمية الحقل (أو موضع الجهة المُتعلَّم) ويقتصّ شريط المكتوب اليدوي.

    `field`: 'number' (العدد — الافتراضي) أو 'date' (التاريخ، مُرتكز v2).
    ملاحظة: مرّر لكل حقلٍ كائنَ priors خاصاً به — مواضع «العدد» و«التاريخ» تختلف."""

    def __init__(self, priors: Optional[EntityLayoutPriors] = None, field: str = 'number'):
        self.priors = priors
        self.field = field
        self._label_re = _LABEL_RES[field]

    @staticmethod
    def _in_qms_table(tsv: dict, i: int) -> bool:
        """هل المرشّح خليّةٌ في جدول ترويسة نظام الجودة؟ (يجاوره Rev/Doc/No/IMS
        في سطره) — «Date Rev» كانت تخطف مرساة التاريخ في كل كتب الشركة."""
        top_i, h_i, left_i = tsv['top'][i], tsv['height'][i], tsv['left'][i]
        for j, raw in enumerate(tsv.get('text', [])):
            t = (raw or '').strip().strip(':.')
            if not t or j == i:
                continue
            if abs(tsv['top'][j] - top_i) > max(8, h_i):        # سطرٌ آخر
                continue
            if abs(tsv['left'][j] - left_i) > 6 * max(20, tsv['width'][i]):
                continue                                        # بعيدٌ أفقياً
            if _TABLE_CONTEXT.match(t):
                return True
        return False

    @staticmethod
    def _in_our_stamp(tsv: dict, i: int) -> bool:
        """هل المرشّح حقلٌ داخل ختمنا نحن؟ (كتلةٌ ثنائية البعد لا سطر، فالجوار
        صندوقٌ حول المرشّح لا محاذاةُ سطر.)"""
        top_i, left_i = tsv['top'][i], tsv['left'][i]
        dx = _STAMP_NEAR_X * max(20, tsv['width'][i])
        dy = _STAMP_NEAR_Y * max(10, tsv['height'][i])
        for j, raw in enumerate(tsv.get('text', [])):
            t = (raw or '').strip().strip(':.ـ ')
            if not t or j == i or not _OUR_STAMP.search(t):
                continue
            if abs(tsv['top'][j] - top_i) <= dy and abs(tsv['left'][j] - left_i) <= dx:
                return True
        return False

    def find_label(self, tsv: dict, width: int, height: int,
                   entity_id=None, min_top: Optional[int] = None) -> Optional[LabelBox]:
        """أفضل مرشّح تسمية: داخل حزام أعلى-الصفحة (يرفض نسخ المتن — خطأ المسبار
        الرئيس)، أو قريبٌ من prior الجهة؛ الأعلى في الصفحة يفوز. خلايا جدول
        الجودة («Date Rev») مرفوضة. وعند غياب أي تسمية مقروءة: السقوط لموضع
        الجهة المُتعلَّم نفسه (جهات «الصفر»).

        `min_top` (بكسل): **ترجيحٌ لا إقصاء** — قانون المجال (بلاغ المالك 2026-08-11):
        تاريخ الجهة بعد «التاريخ» **أسفل «العدد»**، بينما «Date Rev» الإيزو يقبع في
        ترويسة نظام الجودة فوقه (وفيتو الجدول يعتمد قراءةَ الجار فيفشل حين يشوّه OCR
        «Rev»). فحين نعرف صفَّ «العدد» نُرجّح أقربَ مرشّحٍ **تحته**؛ وإن لم يوجد مرشّحٌ
        تحته يفوز الأعلى كالسابق. **الإقصاءُ الصارم قِيس فضرّ** (2026-08-11: أهدر 4 من 7
        قصاصاتٍ صحيحة حين اشتُقّت الأرضيّة من «العدد» في اقتباس متن) — فلا نُقصي أبداً."""
        prior = self.priors.get(entity_id) if (self.priors and entity_id) else None
        best = None
        for i, raw in enumerate(tsv.get('text', [])):
            t = _norm_label(raw)
            if not t or not self._label_re.search(t):
                continue
            x = (tsv['left'][i] + tsv['width'][i] / 2) / width
            y = (tsv['top'][i] + tsv['height'][i] / 2) / height
            in_top = y <= _TOP_ZONE
            near_prior = prior is not None and (
                ((x - prior['x']) ** 2 + (y - prior['y']) ** 2) ** 0.5 <= _PRIOR_RADIUS)
            if not (in_top or near_prior):
                continue   # نسخة متن («المرقم … في») — الرفض هنا حسم خطأ المسبار
            if self._in_qms_table(tsv, i):
                continue   # خليّة جدول الترويسة لا تسميةَ حقل
            if self._in_our_stamp(tsv, i):
                continue   # ختمنا نحن — رقمُنا لا رقمُ الجهة
            # الترتيب: الأعلى يفوز افتراضاً؛ ومع معرفة صفّ «العدد» (min_top) يُرجَّح
            # أوّلُ مرشّحٍ **تحته** (قانون المجال) على ما فوقه (خليّة الإيزو).
            rank = (0 if (min_top is None or tsv['top'][i] >= min_top) else 1, y)
            if best is None or rank < best[1]:
                best = (i, rank)
        if best is not None:
            i = best[0]
            return LabelBox(tsv['left'][i], tsv['top'][i], tsv['width'][i],
                            tsv['height'][i], (tsv['text'][i] or '').strip(), 'label')
        if prior is not None:
            # ترويسة بلا تسمية مقروءة (زخرفة/تشويه) — منطقة الجهة المُتعلَّمة تكفي
            w = int(0.08 * width)
            h = int(0.03 * height)
            return LabelBox(int(prior['x'] * width - w / 2), int(prior['y'] * height - h / 2),
                            w, h, '', 'prior')
        return None

    @staticmethod
    def rule_above(img, y: int, min_span: float = 0.25):
        """صفُّ آخر خطٍّ أفقيّ مستمرّ **فوق** `y` (بكسل)، أو None.

        أرضيّةُ قصٍّ لا مُصفاة: القصّ كان يصعد 0.6×ارتفاع التسمية بلا قيد فيجرف صفّ
        «No.1» من جدول IMS، فتضيع الخانة الأولى للرقم (١٧٥٤→154 · ١٧٨٥→3785 ·
        ١٨٠٧→187 — مشاهَدةٌ بالعين 2026-07-21).

        **درسٌ مدفوع:** أوّل نسخةٍ أخذت «آخر خطٍّ في أعلى 32% من الصفحة» ورفضت أيّ
        تسميةٍ فوقه — فانهارت التغطية 140→58 والنتيجة 18%→10%، لأن ذلك الخطّ يقع
        **تحت** سطر العدد في كثيرٍ من القوالب. الحدّ الصحيح مقيَّدٌ بالتسمية نفسها،
        ولا يرفض شيئاً أبداً.
        """
        try:
            import cv2
            import numpy as np

            cut = max(1, min(int(y), img.height))
            arr = np.asarray(img.convert('L').crop((0, 0, img.width, cut)), dtype=np.uint8)
            bw = cv2.threshold(arr, 0, 255,
                               cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
            span = max(20, int(img.width * min_span))
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (span, 1))
            lines = cv2.morphologyEx(bw, cv2.MORPH_OPEN, kernel)
            rows = np.flatnonzero(lines.sum(axis=1) >= span * 255)
            del arr, bw, lines
            if rows.size == 0:
                return None
            return int(rows.max())
        except Exception:      # لا يُسقط الأنبوب أبداً — المِرساة تحسينٌ لا شرط
            return None

    @staticmethod
    def strip_bbox(label: LabelBox, width: int, height: int, floor_y: int = 0):
        """صندوق شريط الرقم: يسار التسمية (RTL)، بهندسة المسبار المُثبَتة.

        `floor_y` = حافّة الجدول السفلى: لا يصعد القصّ فوقها فلا يجرف صفّ «No.1».
        """
        x1 = max(0, label.left - 2)
        x0 = max(0, label.left - 8 * max(label.width, 40))
        y0 = max(0, label.top - int(0.6 * label.height))
        if floor_y:
            y0 = max(y0, min(floor_y + 2, label.top))
        y1 = min(height, label.top + int(1.6 * label.height))
        return (x0, y0, x1, y1)

    def locate(self, img, tsv: dict, entity_id=None, min_top: Optional[int] = None):
        """الواجهة العليا: (مقصوصة الشريط، صندوق التسمية) أو None."""
        label = self.find_label(tsv, img.width, img.height, entity_id=entity_id,
                                min_top=min_top)
        if label is None:
            return None
        floor_y = self.rule_above(img, label.top) or 0
        box = self.strip_bbox(label, img.width, img.height, floor_y=floor_y)
        if box[2] - box[0] < 30:   # شريط أضيق من أن يحوي رقماً
            return None
        crop = img.crop(box)
        if self._is_blank(crop):
            # **طبقة القصاصات الفارغة** (2026-07-21): حين تقع التسمية قرب حافّة
            # الصفحة اليسرى (x < 0.18) يرتطم `x0` بالصفر فيصير الشريط هامشَ ورقةٍ
            # فارغاً. المولّد: مِرساة `Ref:` اللاتينية في الترويسات ثنائية اللغة —
            # تجلس يساراً **وقيمتها يمينها**، والقصّ لا يعرف إلا اليسار.
            # مقيس: 1,539 من 5,312 شريط تسمية أضيق من 8×40−2=318 بكسل (**29%**)،
            # و**صفرٌ صحيح** من 11 قصاصةً ضيّقة في عيّنة الـ250 مقابل انبعاثين خاطئين.
            # الامتناع هنا **لا يخسر شيئاً**: لا صواب تحته، وفيه خطأٌ يُحذَف.
            # (قصُّ اليمين للمراسي اللاتينية إصلاحٌ لاحق — قيمتها مطبوعةٌ غالباً،
            #  فلا يُوصَّل قبل نقض المنطقة المطبوعة.)
            del crop
            return None
        return crop, label

    @staticmethod
    def _is_blank(crop) -> bool:
        """هل القصاصة خاليةٌ من الحبر؟ (نفس معيار `reader._ink_bbox` تقريباً)"""
        try:
            import numpy as np

            a = np.asarray(crop.convert('L'), dtype=np.float32)
            if a.std() < 1:
                return True
            return int((a < (a.mean() - 1.2 * a.std())).sum()) < 40
        except Exception:
            return False
