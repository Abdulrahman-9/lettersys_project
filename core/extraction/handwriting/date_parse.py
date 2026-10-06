# -*- coding: utf-8 -*-
"""تحليلُ التاريخ المرسوم إلى ISO — **حتميٌّ وممتنعٌ عند الالتباس**.

المصدرُ الوحيد لهذه القاعدة (على سنّة `core/numbering.py`): يستهلكه الأنبوبُ
والالتقاطُ والاختبارات، فلا تنزلق نسخةٌ عن أخرى.

**ما يجعل المسألة أسهل ممّا تبدو (مقيسٌ 100/100 في بوّابة عين D1):** الشهر يقع
في الوسط دائماً بكلا الأبجديّتين — الهنديّة تُرسم يوماً/شهراً/سنةً فتظهر
بالبكسل معكوسةً (سنة يساراً) واللاتينيّة تظهر كما تُرسم. فالتباسُ «يوم/شهر»
الكلاسيكيّ **منتفٍ بنيويّاً**، ويبقى التباسٌ واحد: أيُّ الطرفين السنة.

**وما يُمنع منعاً باتّاً:** حسمُ ذلك الالتباس بالاحتمال الغالب (85% من الحبر
هنديّ ⟵ السنة يساراً). تخمينٌ صامتٌ بدقّة 85% في سجلٍّ رسميّ هو بعينه صنفُ
الخطيئة التي اجتُثّت بإزالة «افتراضيّ اليوم»؛ والامتناعُ هنا شبه مجّانيّ لأنّ
القصاصة معروضةٌ أمام عين الكاتب. وكذلك يُمنع «إصلاح» تاريخٍ غير صالحٍ إلى أقرب
صالح — 31/2 ليست 28/2، بل امتناع.

الحالات المُعادة في `status`:
    ok · invalid (شكلٌ أو مجالٌ فاسد) · ambiguous (طرفان صالحان سنةً ولم تحسم النافذة)
"""
import datetime
import re
from typing import Optional, Tuple

_YEAR_FLOOR = 2014          # أقدمُ سجلٍّ في القاعدة (IIMAIL_2014)
_SPLIT = re.compile(r'[/\\]')


def _two_digit_year_ok(v: int, today: datetime.date) -> bool:
    return _YEAR_FLOOR <= 2000 + v <= today.year + 1


def _two_end_candidates(a: int, m: int, b: int, today: datetime.date):
    """الطرفان ≤ 31 وبخانتين ⟵ كلاهما قد يكون سنةً بخانتين أو يوماً. تواريخُ صالحةٌ مرتّبة بلا تكرار."""
    cands = []
    for year2, day in ((a, b), (b, a)):
        if _two_digit_year_ok(year2, today):
            try:
                cands.append(datetime.date(2000 + year2, m, day))
            except ValueError:
                pass
    return sorted(set(cands))


def parse_drawn_date(raw: str, entry_date: Optional[datetime.date] = None,
                     window_days: int = 45,
                     today: Optional[datetime.date] = None) -> Tuple[Optional[str], str]:
    """`(iso أو None، الحالة)` من سلسلةٍ كما رسمها القارئ (مثل «2025/3/6»).

    `entry_date` تاريخُ قيدنا — يُستعمل **فقط** لفضّ التباس الطرفين بنافذة
    [قيد − window_days، قيد]، ولا يُستعمل حارساً هنا (الحراسةُ شأن الواجهة).
    """
    today = today or datetime.date.today()
    parts = [p for p in _SPLIT.split((raw or '').strip()) if p != '']
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return None, 'invalid'
    a, m, b = (int(p) for p in parts)
    if not (1 <= m <= 12):
        return None, 'invalid'
    la, lb = len(parts[0]), len(parts[2])

    def _mk(year, day):
        try:
            return datetime.date(year, m, day)
        except ValueError:
            return None

    cands = []
    # طرفٌ بثلاث خاناتٍ فأكثر سنةٌ حرفيّة — بحدٍّ عاقل يمنع «99/3/6» ⟵ سنة 99م
    # (خطأُ قراءةٍ لا تاريخ). الحدُّ فضفاضٌ عمداً: أرشيفٌ ورقيٌّ قد يسبق سجلّاتنا.
    if la >= 3:
        return ((_mk(a, b).isoformat(), 'ok')
                if 1990 <= a <= today.year + 1 and _mk(a, b) else (None, 'invalid'))
    if lb >= 3:
        return ((_mk(b, a).isoformat(), 'ok')
                if 1990 <= b <= today.year + 1 and _mk(b, a) else (None, 'invalid'))
    # خانتان بقيمةٍ تفوق أقصى يوم ⟵ سنةُ خانتين حصراً (لا يومَ بهذه القيمة).
    if a > 31 and b <= 31:
        d = _mk(2000 + a, b) if _two_digit_year_ok(a, today) else None
        return (d.isoformat(), 'ok') if d else (None, 'invalid')
    if b > 31 and a <= 31:
        d = _mk(2000 + b, a) if _two_digit_year_ok(b, today) else None
        return (d.isoformat(), 'ok') if d else (None, 'invalid')
    if a > 31 and b > 31:
        return None, 'invalid'
    # الطرفان ≤ 31 وبخانتين ⟵ كلاهما قد يكون سنةً بخانتين أو يوماً.
    cands = _two_end_candidates(a, m, b, today)
    if not cands:
        return None, 'invalid'
    if len(cands) == 1:
        return cands[0].isoformat(), 'ok'
    if entry_date:
        lo = entry_date - datetime.timedelta(days=window_days)
        inside = [c for c in cands if lo <= c <= entry_date]
        if len(inside) == 1:
            return inside[0].isoformat(), 'ok'
    return None, 'ambiguous'


def drawn_date_candidates(raw: str, entry_date: Optional[datetime.date] = None,
                          window_days: int = 45,
                          today: Optional[datetime.date] = None) -> list:
    """المرشّحان (ISO مرتّبة) حين يمتنع `parse_drawn_date` بـ«ambiguous» — **للعرض على
    الكاتب ليختار بنقرة، لا للحسم الآليّ** (بندُ نيلسن 7، مذكّرة فيبل 10): حظرُ التخمين
    بالاحتمال الغالب قائم، والكاتبُ يتعرّف على الصحيح من القصاصة بدل أن يكتبه.
    قائمةٌ فارغة لكلّ حالةٍ أخرى.

    **لا مرشّحَ بعد تاريخ القيد** (ولا بعد اليوم بلا قيد): تاريخُ الجهة يسبق وصولَ الكتاب،
    و«غامض» يعني بالبناء أنّ المرشّحَين كليهما خارج النافذة — فقد يقع أحدُهما في المستقبل،
    ونقرةٌ خاطئةٌ عليه تصير `confirmed` في ذهب التدريب. المرشّحُ الباقي وحدَه يبقى **زرّاً**
    لا حسماً. التصفيةُ هنا لا في `parse_drawn_date` (القيدُ هناك لفضّ الالتباس لا حارس)."""
    today = today or datetime.date.today()
    _iso, status = parse_drawn_date(raw, entry_date=entry_date, window_days=window_days, today=today)
    if status != 'ambiguous':
        return []
    a, m, b = (int(p) for p in _SPLIT.split((raw or '').strip()) if p != '')
    latest = entry_date or today
    return [c.isoformat() for c in _two_end_candidates(a, m, b, today) if c <= latest]
