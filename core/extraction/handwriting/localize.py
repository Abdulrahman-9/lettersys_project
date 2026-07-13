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
_TOP_ZONE = 0.35           # التسمية الشرعية في أعلى ~ثلث الصفحة — تحتها جُمل متن
_PRIOR_RADIUS = 0.14       # قرب prior الجهة يقبل مرشّحاً خارج الحزام (وُسّع 0.09→0.14
                           # بعد قياس v2: تسميات شرعية عند y≈0.38 قرب prior ȳ≈0.27 كانت
                           # تُرفض؛ القطر مقيَّد بمحيط الـprior فلا يبلغ جُمل المتن الدنيا)
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

    def find_label(self, tsv: dict, width: int, height: int,
                   entity_id=None) -> Optional[LabelBox]:
        """أفضل مرشّح تسمية: داخل حزام أعلى-الصفحة (يرفض نسخ المتن — خطأ المسبار
        الرئيس)، أو قريبٌ من prior الجهة؛ الأعلى في الصفحة يفوز. خلايا جدول
        الجودة («Date Rev») مرفوضة. وعند غياب أي تسمية مقروءة: السقوط لموضع
        الجهة المُتعلَّم نفسه (جهات «الصفر»)."""
        prior = self.priors.get(entity_id) if (self.priors and entity_id) else None
        best = None
        for i, raw in enumerate(tsv.get('text', [])):
            t = (raw or '').strip().strip(':.ـ ')
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
            if best is None or y < best[1]:
                best = (i, y)
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
    def strip_bbox(label: LabelBox, width: int, height: int):
        """صندوق شريط الرقم: يسار التسمية (RTL)، بهندسة المسبار المُثبَتة."""
        x1 = max(0, label.left - 2)
        x0 = max(0, label.left - 8 * max(label.width, 40))
        y0 = max(0, label.top - int(0.6 * label.height))
        y1 = min(height, label.top + int(1.6 * label.height))
        return (x0, y0, x1, y1)

    def locate(self, img, tsv: dict, entity_id=None):
        """الواجهة العليا: (مقصوصة الشريط، صندوق التسمية) أو None."""
        label = self.find_label(tsv, img.width, img.height, entity_id=entity_id)
        if label is None:
            return None
        box = self.strip_bbox(label, img.width, img.height)
        if box[2] - box[0] < 30:   # شريط أضيق من أن يحوي رقماً
            return None
        return img.crop(box), label
