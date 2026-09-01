# -*- coding: utf-8 -*-
"""قارئُ تاريخ الجهة (D2) — CRNN بطقم `0123456789/`.

**نسبُه:** انطلاقةٌ دافئة من أوزان قارئ العدد T2.4 (فكرةُ المالك: «الأرقام هي
الأرقام، والفرقُ في التقطيع والصيغة والموضع»)، مصقولةً على 7,763 قصاصةً حقيقيّةً
بهندسة `x` وهدفِ CTC متعدّد المرشّحات (سنةٌ بأربع خاناتٍ أو خانتين × اتّجاهين ×
حشوٍ صفريّ أو بلا) — لأنّ الترتيب البصريّ يتبع أبجديّة الأرقام.

**المقيس على حجزٍ لم يُرَ (360 قصاصة، بمسار فكّ ترميز الإنتاج وصيغة ثقته H6):**
مطابقةٌ تامّة **71.1%** — ومنحنى العتبة: 0.98 ⟵ دقّة **90.2%** بتغطية **71%** ·
0.95 ⟵ 86.7% · 0.90 ⟵ 82.5%. وما دون 0.98 دقّتُه ~24% مشتقّاً، فلا شريحةَ
«صفراء» صادقة: **عتبةُ التأشير هنا 0.98 لا 0.65** (تلك معايرةُ نموذج العدد،
ونقلُها خطأٌ بالبناء).

**ما لا يفعله هذا القارئ:** لا يكتب في `sender_date` أبداً — مخرجُه اقتراحٌ
في مفتاحٍ منفصل، والخادمُ لا يملأ الحقل بحالٍ. القانون المُلزم (جذر تسميم
التواريخ): صفرُ ملءٍ **صامت**. وبقرار المالك (2026-09-01) تملأ **الواجهةُ**
الحقلَ من القراءة الخضراء وحدَها (≥0.98 · تحليلٌ `ok` · حارسُ الفارق سالم)،
موسومةً `autofilled` والقصاصةُ معروضةٌ للمطابقة — فالمملوءُ بلا لمسٍ يُستبعَد
من ذهب التدريب. وما دون الأخضر يبقى بانتظار نقرة.
ولا يُطعَم إلا قصاصةَ `date_geometry.crop_below_box` (هندسةُ تدريبه).
"""
import logging
import os
from typing import Optional, Tuple

from .reader import HandwrittenNumberReader

logger = logging.getLogger(__name__)

_DATE_MODEL = os.path.join('var', 'models', 'handwritten_dates_crnn.onnx')
_DATE_CHARSET = os.path.join('var', 'models', 'handwritten_dates_charset.json')

# فوقها يُعرض الاقتراح أخضرَ، وتحتها أحمرُ «يجب التصحيح يدوياً».
# مُشتقّةٌ من مسحٍ محليٍّ بصيغة الإنتاج على الحجز — لا منقولةٌ عن حقلٍ آخر.
DATE_CONF_GREEN = 0.98


class HandwrittenDateReader(HandwrittenNumberReader):
    """قارئُ التاريخ — نفسُ آلة CTC وثقةِ السلسلة H6، بأوزانٍ وطقمٍ آخرين.

    يستعمل `read()` وحده عمداً: `read_best` تجرّب قصاصةً بحدود الحبر، وتلك
    مُعايَرةٌ لشريط العدد ولم تُقَس على التواريخ — وأيّ قصاصةٍ لم يُدرَّب عليها
    القارئ تكسر عقد «توزيعٌ واحد».
    """

    def __init__(self, model_path: str = _DATE_MODEL,
                 charset_path: str = _DATE_CHARSET, session=None):
        super().__init__(model_path=model_path, charset_path=charset_path,
                         session=session)

    def read_best(self, pil_gray) -> Tuple[Optional[str], float]:   # noqa: D102
        return self.read(pil_gray)


_reader: Optional[HandwrittenDateReader] = None


def get_date_reader() -> HandwrittenDateReader:
    """مفردٌ كسول — تحميلُ ONNX مرّةً واحدة لكلّ عمليّة."""
    global _reader
    if _reader is None:
        _reader = HandwrittenDateReader()
    return _reader
