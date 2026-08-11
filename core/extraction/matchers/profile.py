# -*- coding: utf-8 -*-
"""بصمة الجهة الاستخراجية — تعلّم شكل رقم الصادر لكل جهة من كتبها المؤكَّدة.

الفكرة (مقيسة على البيانات): لكل جهة قالب ترقيم شبه ثابت وبادئة حرفية مميّزة
(NK-20260237 لنفط خانة، MF-2026-195 وEBN-2025050 لـZhongman، CPL للواحة...).
بعد أن تحدّد ذاكرةُ الترويسة المُرسِلَ، نبحث في النصّ عن رقمٍ «بشكل أرقامه
المعتادة» — فنلتقط ما فاتته العلامات العامة ونُصحّح الالتقاط الناقص.

فهرسٌ مُشتقّ في الذاكرة (كنمط فهرس ذاكرة الترويسة): يُبنى من الكتب المؤكَّدة عند
أول استخدام ويتجدّد دورياً — كل كتاب يُحفَظ يُثري البصمة تلقائياً، بلا هجرات.

حدّ صادق مقيس: أرقام المستندات المكتوبة يدوياً لا تظهر في نصّ OCR أصلاً
(≈12% تتبّعاً فقط في العيّنة التاريخية) — البصمة تخدم المطبوع/الرقمي، وهو
موضع الإخفاقات الفعلية.
"""
import logging
import re
import time
from collections import Counter, defaultdict
from typing import NamedTuple, Optional

logger = logging.getLogger(__name__)

_AR_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789')
_REFRESH_SEC = 900          # تجديد الفهرس كل 15 دقيقة (كسلياً عند الاستخدام)
_MIN_PREFIX_LEN = 2         # بادئة حرفية ≥ حرفين — حرفٌ واحد (مثل «و») مبهم
_MIN_DIGITS = 3             # مجموع خانات القالب ≥ 3 — يستبعد الشظايا
# كلمات تسبق الرقم لكنها علامات لا بادئات كود (العدد: 123 ≠ كود «العدد123»)
_CTX_STOPWORDS = {'REF', 'RF', 'RO', 'RI', 'ID', 'NO', 'NUM', 'NUMBER', 'REFERENCE',
                  'DATE', 'DATED', 'FAX', 'TEL', 'PHONE', 'BOX', 'PO'}


class ProfileHit(NamedTuple):
    value: str
    confidence: float
    template: str            # القالب الذي طابق — قابلية تفسير («من أين»)


def induce_template(value: str) -> str:
    """يستنتج قالب الشكل: NK-20260237→L2-D8، MF-2026-195→L2-D4-D3، هغ/881→ح2/D3."""
    s = str(value or '').strip().translate(_AR_DIGITS)
    runs = []
    for ch in s:
        if ch.isdigit():
            t = 'D'
        elif 'a' <= ch.lower() <= 'z':
            t = 'L'
        elif '؀' <= ch <= 'ۿ':
            t = 'ح'
        else:
            t = ch
        if runs and runs[-1][0] == t and t in 'DLح':
            runs[-1][1] += 1
        else:
            runs.append([t, 1])
    return ''.join(f'{t}{n}' if t in 'DLح' else t * n for t, n in runs)


def _leading_letters(value: str) -> str:
    """البادئة الحرفية للقيمة (NK من NK-20260237) — فارغة إن بدأت برقم."""
    m = re.match(r'[A-Za-z؀-ۿ]+', str(value or '').strip())
    return m.group() if m else ''


def _render_runs(runs) -> str:
    """يحوّل أشواط القالب إلى جسد نمطٍ: خانات بأطوالها + فواصل مرنة
    (OCR قد يحيط «-» بمسافات)."""
    parts = []
    for t, n, lit in runs:
        n = int(n or 1)
        if t == 'D':
            parts.append(r'\d{%d}' % n)
        elif t == 'L':
            parts.append('[A-Za-z]{%d}' % n)
        elif t == 'ح':
            parts.append('[ء-ي]{%d}' % n)
        else:
            parts.append(r'\s*' + re.escape(lit) + r'\s*')
    return ''.join(parts)


def _template_regex(template: str, prefixes) -> Optional[re.Pattern]:
    """يبني نمط بحثٍ من قالبٍ يبدأ بحروف: البادئات المؤكَّدة حرفياً (تحلّ محلّ شوط
    الحروف الأول) + أشواط الخانات بأطوالها. None إن كان القالب مبهماً (رقمي مجرّد
    أو بادئة قصيرة) — تلك تُترك للعلامات العامة (العدد/ref) صوناً للدقّة."""
    if not prefixes:
        return None
    runs = re.findall(r'([DLح])(\d*)|(.)', template)
    if sum(int(n or 1) for t, n, _ in runs if t == 'D') < _MIN_DIGITS:
        return None
    first = next(((t, int(n or 1)) for t, n, lit in runs if t or lit), None)
    if not first or first[0] not in ('L', 'ح') or first[1] < _MIN_PREFIX_LEN:
        return None
    alt = '(?:' + '|'.join(re.escape(p) for p in sorted(prefixes)) + ')'
    body_runs = runs[1:]
    # طبقات الماسحات تُسقط الشرطة بعد البادئة («ADO627» بدل «ADO-627» — ADO #11291
    # قراءةً بالعين 2026-08-10) فتفلت من القالب الحرفي. الشرطة الأولى اختيارية؛
    # الدقّة مصونة بأطوال الخانات الحرفية وحارسَي الطرفين (لا التقاط من داخل كود أطول).
    if body_runs and not body_runs[0][0] and body_runs[0][2] in '-–—':
        alt += r'(?:\s*[-–—]\s*)?'
        body_runs = body_runs[1:]
    body = alt + _render_runs(body_runs)
    try:
        return re.compile('(?<![A-Za-z0-9؀-ۿ])' + body + r'(?!\d)', re.IGNORECASE)
    except re.error:
        return None


class SenderNumberProfiles:
    """فهرس بصمات الترقيم: جهة → قوالبها وبادئاتها المُتعلَّمة من الكتب المؤكَّدة."""

    def __init__(self):
        self._profiles = {}
        self._built_at = 0.0

    def _ensure_index(self):
        if self._profiles and (time.monotonic() - self._built_at) < _REFRESH_SEC:
            return
        from core.models import Book, LetterheadMemory
        through = Book.issuing_entities.through
        rows = (through.objects
                .filter(book__is_deleted=False)
                .exclude(book__sender_number__isnull=True)
                .exclude(book__sender_number='')
                .values_list('entity_id', 'book__sender_number'))
        profiles = defaultdict(lambda: {'templates': Counter(),
                                        'prefixes': defaultdict(Counter),
                                        'ctx_prefixes': defaultdict(Counter)})
        for eid, num in rows.iterator(chunk_size=2000):
            tmpl = induce_template(num)
            p = profiles[eid]
            p['templates'][tmpl] += 1
            prefix = _leading_letters(num)
            if prefix:
                p['prefixes'][tmpl][prefix] += 1

        # تعلّم الكود الكامل من ذاكرة الترويسة: المستخدمون يخزّنون آخر مقطعٍ فقط
        # («195») بينما الترويسة تحمل الكود الكامل («MF-2026-195») — نجد القيمة
        # المخزَّنة في النصّ ونوسّعها إلى الرمز المتّصل حولها، فنتعلّم قالبه الكامل
        # وبادئته. هذا «كيف التُقط الرقم في كل مرة سابقة» — مُكتشَفاً من الداتا بيس.
        lm_rows = (LetterheadMemory.objects
                   .exclude(issuing_entity=None)
                   .exclude(book=None)
                   .filter(book__is_deleted=False)
                   .exclude(book__sender_number__isnull=True)
                   .exclude(book__sender_number='')
                   .values_list('issuing_entity_id', 'book__sender_number', 'letterhead'))
        code_chars = set('0123456789-–—/ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz')
        for eid, num, head in lm_rows.iterator(chunk_size=1000):
            num = str(num).strip().translate(_AR_DIGITS)
            head = (head or '').translate(_AR_DIGITS)
            if not num or len(num) < 2:
                continue
            for m in re.finditer(r'(?<!\d)' + re.escape(num) + r'(?!\d)', head):
                lo, hi = m.start(), m.end()
                while lo > 0 and head[lo - 1] in code_chars:
                    lo -= 1
                while hi < len(head) and head[hi] in code_chars:
                    hi += 1
                token = head[lo:hi].strip('-–—/')
                prefix = _leading_letters(token)
                if (token == num or len(token) > 24 or len(prefix) < _MIN_PREFIX_LEN
                        or prefix.upper() in _CTX_STOPWORDS):
                    continue
                profiles[eid]['ctx_prefixes'][induce_template(token)][prefix.upper()] += 1
                break   # ظهور واحد يكفي لكل كتاب

        self._profiles = dict(profiles)
        self._built_at = time.monotonic()
        logger.info('[SenderNumberProfiles] فهرس البصمات جاهز — %d جهة', len(self._profiles))

    @staticmethod
    def _edit_distance(a: str, b: str) -> int:
        """مسافة تحرير بسيطة (Levenshtein) — بادئات قصيرة فقط، فلا حاجة لتحسينات."""
        if len(a) < len(b):
            a, b = b, a
        prev = list(range(len(b) + 1))
        for i, ca in enumerate(a, 1):
            cur = [i]
            for j, cb in enumerate(b, 1):
                cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
            prev = cur
        return prev[-1]

    def repair(self, value: str, entity_id) -> Optional[str]:
        """يُصحّح بادئةً شوّهها OCR بحرفٍ أو حرفين (llK-20260257 → NK-20260257):
        البادئة الملتقطة قريبةٌ (مسافة ≤2) من بادئةٍ مؤكَّدة **لهذه الجهة نفسها**،
        والخانات تُصان حرفياً، والقالب المُصحَّح معروفٌ للجهة — فلا إصلاح عابر
        للجهات (MF لا تصير NK لأن المقارنة داخل بادئات الجهة فقط)."""
        if not value or not entity_id:
            return None
        try:
            self._ensure_index()
        except Exception:
            return None
        profile = self._profiles.get(int(entity_id))
        if not profile:
            return None
        m = re.match(r'([A-Za-z]{1,7})([-/].+)$', str(value).strip())
        if not m:
            return None
        got_prefix, rest = m.group(1), m.group(2)
        known = Counter()
        for px in profile['prefixes'].values():
            known.update({p: c for p, c in px.items() if c >= 2})
        for px in profile['ctx_prefixes'].values():
            known.update({p: c for p, c in px.items() if c >= 2})
        for prefix in known:
            if prefix.upper() == got_prefix.upper():
                return None                      # سليمة أصلاً
        best = None
        for prefix, cnt in known.most_common():
            d = self._edit_distance(got_prefix.upper(), prefix.upper())
            if 0 < d <= 2 and (best is None or cnt > best[1]):
                candidate = prefix + rest
                tmpl = induce_template(candidate)
                if tmpl in profile['templates'] or tmpl in profile['ctx_prefixes']:
                    best = (candidate, cnt)
        return best[0] if best else None

    def find(self, text: str, entity_id) -> Optional[ProfileHit]:
        """يبحث في النصّ عن رقمٍ بقالب الجهة المعروف. أول مطابقة (رأس المستند عادةً
        قبل الإحالات في المتن). الثقة تكبر بعدد الأمثلة المؤكَّدة للقالب."""
        if not text or not entity_id:
            return None
        try:
            self._ensure_index()
        except Exception as exc:
            logger.warning('[SenderNumberProfiles] تعذّر بناء الفهرس: %s', exc)
            return None
        profile = self._profiles.get(entity_id)
        if not profile:
            return None
        normalized = text.translate(_AR_DIGITS)
        best = None   # (موضع المطابقة، عدد الأمثلة، القيمة، القالب)
        # مصدران للقوالب المُتعلَّمة: القيم المخزَّنة ببادئة، والأكواد الكاملة
        # المُكتشَفة من الترويسات (حيث خُزِّن آخر المقطع فقط) — كلاهما بادئته حرفية.
        sources = ([(t, c, profile['prefixes'].get(t)) for t, c in profile['templates'].most_common(4)]
                   + [(t, sum(px.values()), {p for p, c in px.items() if c >= 2} or set(px))
                      for t, px in sorted(profile['ctx_prefixes'].items(),
                                          key=lambda kv: -sum(kv[1].values()))[:4]])
        for tmpl, count, prefixes in sources:
            rx = _template_regex(tmpl, prefixes)
            if rx is None:
                continue
            m = rx.search(normalized)
            if m and (best is None or m.start() < best[0]):
                best = (m.start(), count, re.sub(r'\s+', '', m.group()), tmpl)
        if best is None:
            return None
        confidence = 0.85 if best[1] >= 2 else 0.75
        return ProfileHit(value=best[2], confidence=confidence, template=best[3])
