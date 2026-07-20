# -*- coding: utf-8 -*-
"""بروفايلات استخراج الجهات — المكتشف + المخزن + المُصادِق (فكرة المالك 2026-07-20:
«قواعد لكل جهة، والنموذج يتدرّب عليها تلقائياً عبر مكتشف البروفايل»).

نصفان:
  • learn_profiles(): يمسح الكتب المؤكَّدة ويستنتج لكل جهةٍ (لها ≥ MIN_BOOKS):
      - number_grammar: نحو رقم الجهة (أطوال الأرقام، أو كودٌ لاتينيّ) — يُتعلَّم لا يُكتب.
      - doc_type_top + نسبته، لغة المواضيع، رمز السجلّ، موضع «العدد».
    يُغطّي الجهات الجديدة آلياً كلّما نمت القاعدة. يحفظ var/entity_extraction_profiles.json.
  • EntityProfileStore: محمِّلٌ حيٌّ للأنبوب — يُقسّي أي قارئ (v5/Qari/VLM) بلا GPU:
      validate_number() **آمنٌ: رفضٌ/تأكيدٌ فقط، لا قصٌّ أعمى** (ثبت أن القصّ الأعمى
      يكسر أرقاماً صحيحة — القياس الأعمى 2026-07-20). doc_type_prior() للترجيح.

كلّه محلّيٌّ، بلا إنترنت، بلا تدريب — يخدم النصف الفوريّ من الحلقة الذاتيّة."""
import json
import os
import re
from collections import Counter

MIN_BOOKS = 3
PROFILES_PATH = os.path.join('var', 'entity_extraction_profiles.json')
_AR_DIGITS = {0x0660 + i: 48 + i for i in range(10)}


def _learn_number_grammar(values):
    """يستنتج نمط أرقام الجهة من قيمها المؤكَّدة. يعيد dict أو None."""
    digits, codes = [], []
    for v in values:
        v = str(v or '').strip().translate(_AR_DIGITS)
        if not v:
            continue
        if re.fullmatch(r'\d{1,8}', v):
            digits.append(v)
        elif re.search(r'\d', v):
            codes.append(v)
    total = len(digits) + len(codes)
    if total < MIN_BOOKS:
        return None
    g = {'n': total, 'digits_ratio': round(len(digits) / total, 2)}
    if digits:
        lens = sorted(len(d) for d in digits)
        g['digit_len_min'] = lens[0]
        g['digit_len_max'] = lens[-1]
        g['digit_len_mode'] = Counter(lens).most_common(1)[0][0]
    if codes and len(codes) >= max(3, 0.3 * total):
        pref = re.sub(r'\d+$', '', os.path.commonprefix(codes))
        tails = [len(re.sub(r'\D', '', c[len(pref):])) for c in codes]
        tails = [t for t in tails if t > 0]
        if len(pref) >= 2 and tails:
            g['code_prefix'] = pref
            g['code_regex'] = re.escape(pref) + r'[\-/ ]?\d{%d,%d}' % (min(tails), max(tails))
    return g


def learn_profiles(min_books=MIN_BOOKS, out_path=PROFILES_PATH):
    """المكتشف: يبني بروفايل كل جهةٍ نشطة لها ≥ min_books كتب مؤكَّدة. يعيد
    (profiles, stats). آمنٌ للذاكرة: استعلاماتٌ خفيفة، بلا تحميل صور."""
    from core.models import Book, Entity
    doc_prof = _load_json(os.path.join('var', 'entity_doc_profiles.json'))
    priors = _load_json(os.path.join('var', 'handwriting_layout_priors.json'))

    profiles = {}
    n_gram = self_ok = self_n = 0
    store = EntityProfileStore.__new__(EntityProfileStore)   # للفحص الذاتيّ بلا ملف
    for ent in Entity.objects.filter(is_active=True):
        qs = Book.objects.filter(is_deleted=False, issuing_entities=ent)
        n = qs.count()
        if n < min_books:
            continue
        nums = list(qs.exclude(sender_number__isnull=True).exclude(sender_number='')
                    .values_list('sender_number', flat=True)[:400])
        types = Counter(qs.exclude(document_type='').exclude(document_type__isnull=True)
                        .values_list('document_type', flat=True)[:400])
        titles = list(qs.exclude(title='').exclude(title__isnull=True)
                      .values_list('title', flat=True)[:120])
        ar = sum(1 for t in titles if len(re.findall(r'[ء-ي]', t)) > len(t) * 0.3)
        gram = _learn_number_grammar(nums)
        if gram:
            n_gram += 1
            for v in nums[:60]:
                self_n += 1
                ok, _ = _validate_number(gram, v)
                self_ok += int(ok is not None)
        dp = doc_prof.get(str(ent.id), {})
        profiles[str(ent.id)] = {
            'name': ent.name, 'books': n,
            'entity_code': dp.get('entity_code') or None,
            'lang': dp.get('lang'),
            'number_grammar': gram,
            'doc_type_top': types.most_common(1)[0][0] if types else None,
            'doc_type_top_ratio': round(types.most_common(1)[0][1] / sum(types.values()), 2) if types else None,
            'title_arabic_ratio': round(ar / len(titles), 2) if titles else None,
            'number_label_prior': priors.get(str(ent.id)),
        }
    if out_path:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(profiles, f, ensure_ascii=False, indent=1)
    stats = {'entities': len(profiles), 'with_number_grammar': n_gram,
             'grammar_self_consistency': round(self_ok / max(1, self_n), 3)}
    return profiles, stats


def _validate_number(grammar, read):
    """المُصادِق الآمن (رفض/تأكيد فقط). يعيد (قيمة أو None، سبب).
    **لا قصٌّ أعمى** — أثبت القياسُ الأعمى أنه يكسر أرقاماً صحيحة."""
    if not grammar or not read:
        return None, 'no-grammar-or-read'
    s = str(read).strip().translate(_AR_DIGITS)
    rx = grammar.get('code_regex')
    if rx:
        m = re.search(rx, s, re.I)
        if m:
            return re.sub(r'\D', '', m.group(0)), 'code-match'
    if grammar.get('digits_ratio', 0) >= 0.6 and 'digit_len_min' in grammar:
        ds = re.sub(r'\D', '', s)
        if grammar['digit_len_min'] <= len(ds) <= grammar['digit_len_max']:
            return ds, 'in-range'              # تأكيدٌ (رفع ثقة)
        return None, 'out-of-range'            # رفضٌ آمن (طولٌ مستحيلٌ لهذه الجهة)
    return None, 'no-digit-grammar'


def _load_json(path):
    if os.path.exists(path):
        try:
            return json.load(open(path, encoding='utf-8'))
        except Exception:
            return {}
    return {}


def _norm_ar(s):
    s = str(s or '').lower().translate(_AR_DIGITS)
    s = re.sub(r'[ىي]', 'ي', s)
    s = re.sub(r'[أإآ]', 'ا', s)
    s = re.sub(r'ة', 'ه', s)
    s = re.sub(r'[ً-ٟ]', '', s)          # تشكيل
    return re.sub(r'\s+', ' ', re.sub(r'[^\wء-ي ]', ' ', s)).strip()


# كلماتٌ عامّة في أسماء الجهات — تُسقَط لأنها لا تُميّز
_GENERIC = {'قسم', 'دائره', 'شعبه', 'مكتب', 'شركه', 'هيئه', 'هياه', 'وحده', 'مديريه',
            'عامه', 'وزاره', 'النفط', 'الوسط', 'نفط', 'المحترم', 'المحترمه', 'السيد',
            'لجنه', 'الاداره', 'المشتركه', 'شؤون', 'محطه', 'الفرع', 'جمهوريه', 'العراق',
            'and', 'the', 'of', 'for', 'company', 'oil', 'ltd', 'limited', 'co'}


class EntityResolver:
    """مُعرّف الجهة الذكيّ واعي الاتجاه (توجيه المالك 2026-07-20: «استفد من الرموز
    لفصل الجهات؛ الوارد ليس كالصادر»). يطابق نصّ المنطقة الصحيحة (ترويسة للوارد،
    سطر «الى/» للصادر) ضدّ فهرس الجهات: كلماتٌ مميّزة + رمزُ السجلّ + بصمةٌ نادرة.

    الرمزُ لا يُستخرَج خاماً (0/61 — يُشوَّه/حرفٌ واحد)؛ بل يُرجّح جهةً اسمُها حاضرٌ
    في الترويسة (اسمُ الجهة موجودٌ 36%+، أوثق من «ش4» الخام)."""
    _cache = None

    def __init__(self):
        from core.models import Entity
        doc = _load_json(os.path.join('var', 'entity_doc_profiles.json'))
        name_code = {}
        for v in doc.values():
            c = str(v.get('entity_code') or '').strip()
            if c.lower() not in ('', 'none'):
                name_code[v.get('entity_name', '')] = c
        # ندرة الكلمة عبر كل الأسماء ⟵ وزنُ التمييز
        df = Counter()
        rows = []
        for e in Entity.objects.filter(is_active=True):
            toks = [t for t in _norm_ar(e.name).split() if len(t) > 1 and t not in _GENERIC]
            for t in set(toks):
                df[t] += 1
            rows.append((e.id, e.name, toks, name_code.get(e.name)))
        self.index = []
        for eid, name, toks, code in rows:
            key = {t for t in toks if df[t] <= 6}          # كلماتٌ نادرة = مميّزة
            self.index.append({'id': eid, 'name': name, 'key': key or set(toks),
                               'code': code})

    @classmethod
    def get(cls):
        if cls._cache is None:
            cls._cache = cls()
        return cls._cache

    def resolve(self, text, top_k=3):
        """يعيد [(score, id, name), …] الأعلى — مطابقةُ كلماتٍ مميّزة + رمز."""
        nt = ' ' + _norm_ar(text) + ' '
        toks = set(nt.split())
        scored = []
        for e in self.index:
            if not e['key']:
                continue
            hit = e['key'] & toks
            if not hit:
                continue
            score = len(hit) / len(e['key'])
            if e['code'] and (' ' + _norm_ar(e['code']) + ' ') in nt.replace('/', ' '):
                score += 0.25                              # الرمزُ حاضرٌ = ترجيح
            scored.append((round(score, 3), e['id'], e['name']))
        scored.sort(reverse=True)
        return scored[:top_k]

    def resolve_directional(self, header_text, recipient_text, kind):
        """واعي الاتجاه: الوارد ⟵ المُصدِرة من الترويسة؛ الصادر ⟵ المستلِمة من «الى/».
        يعيد dict{issuing, recipient} (كلٌّ ترشيحٌ أعلى أو None)."""
        incoming = kind.startswith('incoming')
        if incoming:
            iss = self.resolve(header_text, 1)
            return {'issuing': iss[0] if iss else None, 'recipient': 'us'}
        rec = self.resolve(recipient_text or header_text, 1)
        return {'issuing': 'us', 'recipient': rec[0] if rec else None}


class EntityProfileStore:
    """محمِّلٌ حيٌّ للبروفايلات — طبقة تقسيةٍ فوق أي قارئ. يُحمَّل مرّةً ويُخبَّأ."""
    _cache = None

    def __init__(self, path=PROFILES_PATH):
        self.profiles = _load_json(path)

    @classmethod
    def get(cls):
        if cls._cache is None:
            cls._cache = cls()
        return cls._cache

    def profile(self, entity_id):
        return self.profiles.get(str(entity_id)) if entity_id is not None else None

    def validate_number(self, entity_id, read):
        """يعيد (قيمة مؤكَّدة/مصحَّحة أو None، سبب). None مع سبب out-of-range = رفضٌ
        آمن (القيمة مستحيلة لنمط الجهة ⟵ صمتٌ أصدق من رقمٍ خاطئ)."""
        p = self.profile(entity_id)
        if not p or not p.get('number_grammar'):
            return read, 'no-profile'         # لا بروفايل ⟵ لا تدخّل (تمرير)
        return _validate_number(p['number_grammar'], read)

    def doc_type_prior(self, entity_id):
        """نوع الوثيقة الغالب للجهة إن كان مهيمناً (≥0.7) — مُرجِّحٌ لا حاسم."""
        p = self.profile(entity_id)
        if p and p.get('doc_type_top') and (p.get('doc_type_top_ratio') or 0) >= 0.7:
            return p['doc_type_top']
        return None

    def compose_number(self, entity_id, read):
        """المُصادِق المرن (توجيه المالك 2026-07-20): يقبل الشكلين — رقمٌ صرف أو كودٌ
        بحروفه — ويُخرج **الرقم الكامل بحروف رمز الجهة** (ش4/183). رمزُ الجهة خاصيّةٌ
        ثابتةٌ **حتميّة** (ش4 = التراخيص دائماً)، فإضافتُه للأرقام اليدوية (من v5/v6)
        آمنةٌ ومُثرية — لا تعلُّمَ هشّاً ولا قصٌّ أعمى. لا رمزَ للجهة ⟵ الأرقام كما هي."""
        raw = str(read or '').translate(_AR_DIGITS)
        # لو حَمَل النصّ رمزاً مطبوعاً أصلاً (ش4/… من Tesseract/Qari) خذ رمزه؛ وإلا رمز البروفايل
        m = re.match(r'\s*([ء-يA-Za-z][ء-يA-Za-z.]{0,4})\s*[/\-]\s*', raw)
        printed_code = m.group(1) if m else None
        digits = re.sub(r'\D', '', raw)
        if not digits:
            return read
        p = self.profile(entity_id) or {}
        code = printed_code or (p.get('entity_code') if str(p.get('entity_code') or '').strip().lower()
                                not in ('', 'none') else None)
        return f'{str(code).strip()}/{digits}' if code else digits
