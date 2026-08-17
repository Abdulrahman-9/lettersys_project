# -*- coding: utf-8 -*-
"""
قواعد رقم القيد — **المصدر الوحيد**.

كانت هذه القواعد مبعثرة في أحد عشر موضعاً (النموذج، البحث، إعادة البذر، المستورد،
أوامر التوحيد، ثلاثة قوالب، وJS) وقد انحرفت فعلاً: حدّ السنة كان 2020 في موضع
و2000 في آخر، فتُقرأ كتب 2000 و2007 و2014 قراءتين متناقضتين. كل من يحتاج تحليل
رقمٍ أو توليده أو عرضه أو البحث به يستدعي هذه الوحدة ولا يُعيد كتابة القاعدة.

═══ القاعدة (قرار المالك) ═══

  • **سلسلة واحدة لا نهائية** لكل سجلّ، أساسها أرقام سنة 2026.
    بعد 2432 يأتي 2433 — في 2027 و2028 وما بعدها. **لا تصفير سنوي بعد اليوم.**
    النظام هو المُصدِر، والكاتب يكتب ما يُصدره.

  • **بيانات 2025 وما قبلها تُوسَم بسنة إضافتها**: {السنة}{الرقم}.
    السبب مقيس: أرقام الوارد الداخلي تكرّرت بين 2025 و2026 في 2,432 رقماً،
    وبين 2025 و2026 في الوارد الخارجي 357، والصادر الداخلي 454. الوسم هو ما
    يفصلها. والسنة هي **سنة السجلّ الذي أُضيف فيه الكتاب** (اسم جدول المصدر)
    لا تاريخ المستند — سجلّ 2026 يحوي مستندات مؤرّخة 2025-12-30.

  • **لا بادئة سجلّ في الرقم إطلاقاً.** النوع يحمله عمود `kind`، والتفرّد
    (kind, our_number) — مقيس: صفر تصادم داخل أي نوع.

  • **الصادر الخارجي لا سلسلة له**: رقمه يصدر من مكتب المدير العام ويُكتب كما هو،
    ويجوز تكراره. (بياناته: 0، 109، 1555، 27189 — بلا تسلسل ولا ترتيب.)

  • **بلا رقم رسمي**: نصّ فارغ، ولا يستهلك عدّاداً.

  • **كتب التدريب**: `T{رقم}` من عدّاد منفصل — خارج فضاء السلسلة الرسمية بنيوياً،
    لأن أول خانة غير رقمية. تُحذف كلّها عند التدشين.

العرض دائماً بالرقم المجرّد كما هو مكتوب على الورق؛ الوسم يظهر منفصلاً.
"""
import re

# السنة التي صارت أرقامها أساس السلسلة اللانهائية. ما قبلها يُوسَم بسنته.
BASE_YEAR = 2026

# أقدم سنة نقبلها بادئةً — في البيانات كتب مؤرّخة 2000 و2007 و2014.
MIN_YEAR = 2000
MAX_YEAR = 2099

TRAINING_PREFIX = 'T'

#: السجلّات التي يمنحها النظام أرقاماً من سلسلته
SERIES_KINDS = ('incoming_internal', 'incoming_external', 'outgoing_internal')
#: السجلّ الذي يأتي رقمه من الخارج ولا سلسلة له
MANUAL_KINDS = ('outgoing_external',)

_TRAINING_RE = re.compile(r'^%s(\d+)$' % TRAINING_PREFIX, re.IGNORECASE)

#: بديل السنوات الموسومة — كلّها أقدم من سنة الأساس بالتعريف. سردُها صراحةً أوضح
#: من نطاقٍ رقميّ في regex، ويمنع أن تُقرأ '2026…' وسماً وهي سلسلةٌ جارية.
_TAGGED_YEARS = '|'.join(str(y) for y in range(MIN_YEAR, BASE_YEAR))

#: يطابق الصيغة الموسومة وحدها: {سنة أقدم من الأساس}{تسلسل ≥ 4 خانات}
TAGGED_REGEX = r'^(?:%s)\d{4,}$' % _TAGGED_YEARS

#: ما يكتبه موظّف السجلّ حين لا رقم للكتاب. تحت القاعدة الجديدة «بلا رقم» تعني
#: حقلاً فارغاً فعلاً — لا `0NNNN`، فالبادئات أُلغيت كلّها.
NO_NUMBER_TOKENS = frozenset(
    ('بلا', 'بدون', 'لايوجد', 'لا يوجد', '-', '_', 'none', 'null'))


def is_no_number(raw):
    """هل هذه القيمة تعني «بلا رقم»؟ (فارغ، أو كلمة نفي، أو أصفار فقط)"""
    s = (raw or '').strip()
    return (not s) or (s.lower() in NO_NUMBER_TOKENS) or (s.isdigit() and not s.strip('0'))


class Parsed:
    """نتيجة تحليل رقم: السنة (أو None للسلسلة الجارية)، التسلسل، ونوع الرقم."""

    __slots__ = ('year', 'seq', 'kind_of', 'raw')

    def __init__(self, year, seq, kind_of, raw):
        self.year = year          # int أو None
        self.seq = seq            # int أو None
        self.kind_of = kind_of    # 'series' | 'tagged' | 'training' | 'manual' | 'blank' | 'unknown'
        self.raw = raw

    @property
    def is_official(self):
        return self.kind_of in ('series', 'tagged')

    def __repr__(self):
        return 'Parsed(year=%r, seq=%r, kind_of=%r, raw=%r)' % (
            self.year, self.seq, self.kind_of, self.raw)


def parse(our_number):
    """
    يحلّل رقماً مخزَّناً إلى (سنة، تسلسل، نوع).

    لا يحتاج معرفة نوع الكتاب: الصيغة وحدها تكفي.
      ''            → blank
      'T57'         → training
      '2433'        → series   (السلسلة الجارية، بلا سنة)
      '20250825'    → tagged   (سنة 2025، تسلسل 825)
      '7436'        → series أيضاً — والصادر الخارجي يُميَّز بنوعه لا بصيغته
      أي شيء آخر    → unknown  (يُعرض كما هو)
    """
    s = (our_number or '').strip()
    if not s:
        return Parsed(None, None, 'blank', s)

    m = _TRAINING_RE.match(s)
    if m:
        return Parsed(None, int(m.group(1)), 'training', s)

    if not s.isdigit():
        return Parsed(None, None, 'unknown', s)

    # موسوم بسنة: طوله ≥ 8 وبادئته سنة مقبولة أقدم من سنة الأساس.
    # اشتراط الطول يمنع خلط '2433' (تسلسل) بـ'2433' (سنة زائفة).
    if len(s) >= 8:
        y = int(s[:4])
        if MIN_YEAR <= y <= MAX_YEAR and y < BASE_YEAR:
            rest = s[4:]
            if rest.isdigit():
                return Parsed(y, int(rest), 'tagged', s)

    return Parsed(None, int(s), 'series', s)


def format_series(seq):
    """رقم السلسلة الجارية — مجرّد بلا سنة وبلا بادئة سجلّ."""
    return str(int(seq))


def format_tagged(seq, year):
    """رقم سنةٍ سابقة — موسوم بسنة إضافته، والتسلسل بأربع خانات على الأقل."""
    year = int(year)
    if not (MIN_YEAR <= year <= MAX_YEAR):
        raise ValueError('سنة خارج النطاق المقبول: %r' % year)
    return '%d%04d' % (year, int(seq))


def format_for_ledger_year(seq, ledger_year):
    """
    الصيغة الصحيحة حسب سنة السجلّ الذي أُضيف فيه الكتاب.

    `ledger_year` هو سنة الجدول في النظام القديم (IIMAIL_2025 ⇒ 2025)، لا تاريخ
    المستند. سنة الأساس فما فوق ⇒ مجرّد؛ ما قبلها ⇒ موسوم.
    """
    if ledger_year is None or int(ledger_year) >= BASE_YEAR:
        return format_series(seq)
    return format_tagged(seq, ledger_year)


def format_training(seq):
    return '%s%d' % (TRAINING_PREFIX, int(seq))


def display(our_number):
    """
    ما يراه المستخدم: **الرقم المجرّد كما هو مكتوب على الورق**.
    الوسم السنوي يُعرض منفصلاً (انظر `year_tag`) لا مدموجاً في الرقم.
    """
    p = parse(our_number)
    if p.kind_of == 'blank':
        return ''
    if p.seq is None:
        return p.raw
    if p.kind_of == 'training':
        return format_training(p.seq)
    return str(p.seq)


def year_tag(our_number):
    """وسم السنة للعرض بجوار الرقم، أو '' للسلسلة الجارية."""
    p = parse(our_number)
    return str(p.year) if p.year else ''


def search_patterns(digits):
    """
    أنماط regex تجد الرقم المكتوب في كل صيغه المخزَّنة.

    كتابة «825» يجب أن تجد:
      • كتاب السلسلة الجارية المخزَّن '825'
      • وكتاب 2025 المخزَّن '20250825'
      • وكتاب 2007 المخزَّن '20070825'
    ولا تجد '8250' ولا '1825' — المطابقة على التسلسل كاملاً لا كجزء.
    """
    n = str(int(digits))
    padded = n.zfill(4)
    return [
        r'^0*%s$' % n,                                   # السلسلة الجارية (بأصفار بادئة محتملة)
        r'^(?:%s)0*%s$' % (_TAGGED_YEARS, n),            # موسوم بسنة: تسلسل قصير مُصفَّر
        r'^(?:%s)%s$' % (_TAGGED_YEARS, padded),         # موسوم بسنة: تسلسل بأربع خانات
        r'^%s0*%s$' % (TRAINING_PREFIX, n),              # كتب التدريب
    ]


def year_search_pattern(year):
    """كتابة سنةٍ وحدها (مثل «2025») تجد كل كتب سجلّ تلك السنة."""
    y = int(year)
    if not (MIN_YEAR <= y < BASE_YEAR):
        return None
    return r'^%d\d{4,}$' % y


def sort_key_sql():
    """
    مفتاح فرزٍ رقميّ لا نصّي.

    الفرز النصّي يضع '10' قبل '9' ويخلط الموسوم بالمجرّد. نفرز على
    (السنة الفعّالة، التسلسل): السلسلة الجارية تُعامَل بسنة الأساس فتأتي بعد
    الموسوم، والتسلسل رقمٌ صحيح.
    """
    from django.db.models import Case, IntegerField, Value, When
    from django.db.models.functions import Cast, Length, Substr

    return {
        '_num_year': Case(
            When(our_number__regex=TAGGED_REGEX,
                 then=Cast(Substr('our_number', 1, 4), IntegerField())),
            default=Value(BASE_YEAR), output_field=IntegerField(),
        ),
        '_num_seq': Case(
            When(our_number__regex=TAGGED_REGEX,
                 then=Cast(Substr('our_number', 5), IntegerField())),
            When(our_number__regex=r'^\d+$', then=Cast('our_number', IntegerField())),
            default=Value(0), output_field=IntegerField(),
        ),
    }


def max_series_seq(numbers):
    """
    أعلى تسلسل في **السلسلة الجارية** ضمن مجموعة أرقام — أساس العدّاد.

    الموسوم بسنته وكتب التدريب و«بلا رقم» خارج فضاء السلسلة فلا تُحتسب: رقم 2025
    المخزَّن '20255782' ليس تسلسل 20,255,782، ولو حُسب لقفز العدّاد إلى الملايين.
    """
    top = 0
    for raw in numbers:
        p = parse(raw)
        if p.kind_of == 'series' and p.seq:
            top = max(top, p.seq)
    return top
