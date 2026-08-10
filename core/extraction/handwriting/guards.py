"""حارسا انبعاث رقم الجهة — يمنعان القصاصة الخاطئة من تلويث الحقل.

بوّابة الثقة (`reader.CONF_GATE`) تقيس ثقة النموذج فيما رآه، لا صحّة ما رآه.
وقياس 2026-07-21 على 38 مستنداً حقيقياً كشف انعكاساً خبيثاً: **الأرقام المطبوعة
أسهل ما يقرأه CRNN**، فأعلى الثقات هي بالضبط أكثر الحالات وقوعاً على المنطقة
الخاطئة — 11149 انبعث «99» بثقة 0.95 من إحالة متنٍ مطبوعة، و11119 انبعث «3»
بثقة 0.94 والحقيقة «1231».

حارسان مستقلّان، كلاهما مجّانيّ (لا نموذج ولا وسم):

1. `printed_region_veto` — Tesseract يقرأ خطّ اليد عندنا بنسبة ≈ صفر (مقيس)،
   فكلّ ما يقرؤه بثقةٍ داخل الشريط **مطبوعٌ بالتعريف**. رقمان مطبوعان فأكثر
   داخل القصاصة ⟵ المنطقة ليست حقل «العدد» اليدوي ⟵ ارفض.

2. `SequencePlausibility` — أرقام كلّ جهة شبه متتالية خلال السنة، والقاعدة
   مرجعٌ موثوق (هامش خطأ الموظّف ضئيل — أكّده المالك). مرشّحٌ خارج مدى الجهة
   الأخير أو مخالفٌ لطولها المعتاد = قراءةُ ركامٍ لا رقمُ جهة.

**حارسان لا مُصحِّحان:** لا يُعدَّل مرشّحٌ أبداً إلى أقرب قيمةٍ معقولة — الرفض
الصامت أسلم من تخمينٍ يبدو صحيحاً.
"""

from __future__ import annotations

import datetime
import logging
from collections import Counter
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# ثقة Tesseract التي فوقها نعتبر الكلمة مطبوعةً يقيناً. 55 مُتحفَّظة: خطّ اليد
# عندنا لا يبلغها (Tesseract ≈ 0% عليه)، والطباعة تتجاوزها بمريح.
PRINT_CONF = 55.0
# رقمٌ واحد مطبوع قد يكون شظيّة جدول؛ رقمان فأكثر = كتلة مطبوعة حقيقية.
MIN_PRINTED_DIGITS = 2

# لا نثق بتاريخ جهةٍ قبل هذا العدد من الأرقام المؤكَّدة — دونه يمرّ المرشّح
# (الحارس يمتنع، ولا يمنع).
MIN_HISTORY = 5
# 365 مقيسة على الـ38: تقتل 13 قراءةً خاطئة مقابل 12 عند 180، وتخفض الامتناع
# 5→4، وصفر قراءةٍ صحيحة مقتولة. توسيعها إلى 3650 لا يضيف شيئاً.
LOOKBACK_DAYS = 365
# الهامش **غير متماثل عمداً**: تسلسل الجهة يصعد فقط، والكتاب قيد الفحص أحدثُ
# من كلّ ما في القاعدة ⟵ المنطقة المعقولة تقع فوق `hi` لا حوله. هامشٌ سخيّ
# لأعلى وضيّقٌ لأسفل.
RANGE_MARGIN_MIN = 50
RANGE_MARGIN_UP = 0.50
RANGE_MARGIN_DOWN = 0.10
# تصفير السنة: مطلع كانون الثاني يعود العدّاد إلى 1 بينما تاريخ القاعدة كلّه
# من السنة الماضية، فيبدو المرشّح الصحيح «تحت المدى». نمتنع لا نرفض.
YEAR_RESET_MONTHS = (1, 2)


def _center_inside(box, wx0, wy0, ww, wh) -> bool:
    """مركز الكلمة داخل الشريط — لا مجرّد تماسّ.

    التقاطع المجرّد يكفي لأن يُبطل قصاصةً **صحيحة**: الشريط بعرض ثمانية أضعاف
    التسمية، فرقم هاتفٍ مطبوعٍ في الترويسة يلامس حافّته فينقضها. المركز يفصل
    «الكلمة داخل الشريط» عن «الكلمة تلامسه».
    """
    x0, y0, x1, y1 = box
    cx, cy = wx0 + ww / 2.0, wy0 + wh / 2.0
    return x0 <= cx <= x1 and y0 <= cy <= y1


def printed_region_veto(tsv: dict, box: Tuple[int, int, int, int],
                        min_conf: float = PRINT_CONF,
                        min_digits: int = MIN_PRINTED_DIGITS) -> Optional[str]:
    """يُعيد سبب الرفض إن كانت القصاصة تقع على كتلةٍ مطبوعة، وإلا None.

    `box` = (x0, y0, x1, y1) بإحداثيّات الصورة نفسها التي وُلّد منها `tsv`.
    """
    if not tsv:
        return None
    x0, y0, x1, y1 = box
    printed = []
    n = len(tsv.get('text', ()))
    for i in range(n):
        text = (tsv['text'][i] or '').strip()
        if not any(ch.isdigit() for ch in text):
            continue
        try:
            conf = float(tsv['conf'][i])
        except (TypeError, ValueError):
            continue
        if conf < min_conf:
            continue
        if not _center_inside((x0, y0, x1, y1), tsv['left'][i], tsv['top'][i],
                              tsv['width'][i], tsv['height'][i]):
            continue
        printed.append(text)
        if sum(len([c for c in t if c.isdigit()]) for t in printed) >= min_digits:
            return f'منطقة مطبوعة (Tesseract قرأ {printed!r} داخل الشريط)'
    return None


class SequencePlausibility:
    """معقوليّة المرشّح مقابل تسلسل أرقام الجهة في قاعدة البيانات.

    يُبنى كسولاً ويخزّن نتيجة كلّ جهة، فالكلفة استعلامٌ واحدٌ لكلّ جهة في العمر.
    """

    def __init__(self, lookback_days: int = LOOKBACK_DAYS, min_history: int = MIN_HISTORY):
        self.lookback_days = lookback_days
        self.min_history = min_history
        self._cache: dict = {}

    def _stats(self, entity_id):
        if entity_id in self._cache:
            return self._cache[entity_id]
        stats = None
        try:
            from core.models import Book

            since = datetime.date.today() - datetime.timedelta(days=self.lookback_days)
            raw = (Book.objects
                   .filter(issuing_entities__id=entity_id, date__gte=since)
                   .exclude(sender_number__isnull=True)
                   .exclude(sender_number='')
                   .values_list('sender_number', flat=True))
            digits = [s.strip() for s in raw if s and s.strip().isdigit()]
            if len(digits) >= self.min_history:
                vals = [int(s) for s in digits]
                lengths = Counter(len(s) for s in digits)
                stats = {
                    'n': len(digits),
                    'modal_len': lengths.most_common(1)[0][0],
                    'lo': min(vals),
                    'hi': max(vals),
                }
        except Exception as exc:            # قاعدةٌ غائبة/هجرة ناقصة — لا نُسقط الأنبوب
            logger.warning('[guards] تعذّر تاريخ الجهة %s (%s) — الحارس يمتنع',
                           entity_id, type(exc).__name__)
        self._cache[entity_id] = stats
        return stats

    def reject_reason(self, entity_id, candidate: str) -> Optional[str]:
        """سبب الرفض، أو None إن كان المرشّح معقولاً (أو لا تاريخ يكفي للحكم)."""
        if not entity_id or not candidate or not candidate.isdigit():
            return None
        stats = self._stats(entity_id)
        if not stats:
            return None                     # امتناعٌ لا منع
        modal = stats['modal_len']
        if not (modal - 1 <= len(candidate) <= modal + 1):
            return (f'طول {len(candidate)} يخالف طول الجهة المعتاد {modal} '
                    f'(من {stats["n"]} رقماً)')
        value = int(candidate)
        span = stats['hi'] - stats['lo']
        up = max(RANGE_MARGIN_MIN, int(RANGE_MARGIN_UP * span))
        down = max(RANGE_MARGIN_MIN, int(RANGE_MARGIN_DOWN * span))
        if value < stats['lo'] - down:
            if datetime.date.today().month in YEAR_RESET_MONTHS:
                return None                 # تصفير سنةٍ محتمل — امتناع
            return (f'{value} دون مدى الجهة [{stats["lo"]}, {stats["hi"]}] '
                    f'-{down} (من {stats["n"]} رقماً)')
        if value > stats['hi'] + up:
            return (f'{value} فوق مدى الجهة [{stats["lo"]}, {stats["hi"]}] '
                    f'+{up} (من {stats["n"]} رقماً)')
        return None
