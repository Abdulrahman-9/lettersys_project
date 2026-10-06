# -*- coding: utf-8 -*-
"""فهارسُ الاستخراج المشتقّة — **مشتركةٌ على مستوى العمليّة** تُبنى مرّةً وتُعاد حين يتغيّر مصدرُها.

**لماذا:** الخدمةُ (`AIExtractionService`) تُبنى لكلّ طلب، ومعها `EntityMatcher`
و`SenderNumberProfiles` — فكان فهرسُ ذاكرة الترويسة (TF-IDF على ~5,400 ترويسة) يُبنى من
الصفر في **كلّ** استخراج: 1.6–1.8 ث مقيسة على 18 كتاباً مختوماً (2026‑10‑05)، وبصماتُ
الترقيم 0.16 ث (مرّتين حين يعمل حارسُ المطبوع). الكاشُ الذي كتبه الكودُ على النسخة
(عمرٌ 300/900 ث) لم يكن يعيش أكثرَ من طلبٍ واحد.

**العقد — النتيجةُ هي نفسُها حرفاً:** البناءُ دالّةٌ حتميّةٌ في صفوف القاعدة، فالفهرسُ
المشترك يساوي فهرساً يُبنى الآن ما دام مصدرُه لم يتغيّر. ويُعاد البناءُ متى:
  ١. حُفظ أو حُذف صفٌّ من LetterheadMemory أو Book أو Entity، أو تغيّرت جهاتُ كتاب، عبر
     التطبيق (إشاراتُ جانغو في `core/signals.py`) — إبطالٌ عند إيداع المعاملة؛
  ٢. اختلفت **بصمةُ القاعدة** (أعدادٌ وأقصى معرّفاتٍ ومجاميعُ مفاتيح وآخرُ تعديل) عمّا كانت
     عليه عند البناء — تلتقط كتابةَ عمليّةٍ أخرى (أوامرُ الإدارة) والتحديثَ الجماعيّ
     (`queryset.update`) الذي لا يُطلق إشارة؛
  ٣. مضى العمرُ المعلَن في الكود من قبلُ (300 ث للذاكرة، 900 ث للبصمات) — شبكةُ أمانٍ أخيرة
     لما لا تراه البصمة (إعادةُ تسمية جهةٍ من عمليّةٍ أخرى).
والجيلُ والبصمةُ يُقرآن **قبل** البناء: تغيّرٌ أثناءه يُسقط الناتجَ عند أوّل قراءةٍ تالية.
والبناءُ تحت قفل؛ الطلبُ الذي يصل أثناء بناءٍ ينتظره ولا يرى القديم. والقيمةُ المنشورة
لا تُعدَّل بعد نشرها (المستهلكون يقرؤون فقط) فتُشارَك بين خيوط الخادم بلا قفل.

**إعادةُ البناء في الخلفيّة بعد الحفظ:** حلقةُ الكاتب «استخرج ← احفظ ← استخرج»، وكلُّ حفظٍ
يُبطل الفهرس — فبلا بناءٍ مسبق يدفع الاستخراجُ التالي الثمنَ كاملاً ويضيع المكسب. يُجدوَل
البناءُ بعد الإيداع (`transaction.on_commit`) في خيطٍ واحدٍ يجمع الطلبات، فيجهز والكاتبُ
يمسح الصفحةَ التالية.

**العمرُ صفرٌ = بلا مشاركة:** `settings_test` يضبطه صفراً فيُبنى الفهرسُ عند كلّ نداءٍ كما
كان — لا تسرّبَ بين اختبارٍ وآخر (التراجعُ لا يُطلق إشارات). المشاركةُ نفسُها مختبَرةٌ
باختباراتٍ مخصّصة تضبط العمرَ صراحةً.
"""
import logging
import threading
import time
from typing import Callable, NamedTuple, Optional

logger = logging.getLogger('lettersys')

_REGISTRY = []
_DEBOUNCE_SEC = 0.5


class _State(NamedTuple):
    generation: int
    signature: tuple
    built_at: float
    value: object


class SharedIndex:
    """فهرسٌ مشتقٌّ واحدٌ لكلّ عمليّة — `get()` يُعيده جاهزاً أو يبنيه تحت قفل."""

    def __init__(self, name: str, build: Callable[[], object], signature: Callable[[], tuple],
                 ttl_setting: str, default_ttl: float, register: bool = True):
        self.name = name
        self._build = build
        self._signature = signature
        self._ttl_setting = ttl_setting
        self._default_ttl = float(default_ttl)
        self._build_lock = threading.Lock()
        self._gen_lock = threading.Lock()
        self._generation = 0
        self._state: Optional[_State] = None
        if register:                       # الإشاراتُ تُبطل المسجَّلَ وحده (فهارسُ الاختبار لا تُسجَّل)
            _REGISTRY.append(self)

    def ttl(self) -> float:
        from django.conf import settings
        return float(getattr(settings, self._ttl_setting, self._default_ttl))

    def invalidate(self):
        """إبطالٌ فوريّ: أيُّ قراءةٍ تالية تبني من جديد (أو تنتظر بناءً جارياً)."""
        with self._gen_lock:
            self._generation += 1

    def _valid(self, st: Optional[_State], ttl: float) -> bool:
        return (st is not None
                and st.generation == self._generation
                and (time.monotonic() - st.built_at) <= ttl
                and st.signature == self._signature())

    def get(self):
        ttl = self.ttl()
        if ttl <= 0:
            return self._build()               # بلا مشاركة: السلوكُ القديم حرفاً
        st = self._state
        if self._valid(st, ttl):
            return st.value
        with self._build_lock:
            st = self._state
            if self._valid(st, ttl):
                return st.value                # بناهُ خيطٌ آخر ونحن ننتظر القفل
            generation = self._generation
            signature = self._signature()
            t0 = time.perf_counter()
            value = self._build()
            self._state = _State(generation, signature, time.monotonic(), value)
            logger.info('[shared-index] %s بُني في %.2f ث', self.name, time.perf_counter() - t0)
            return value


def db_signature() -> tuple:
    """بصمةُ القاعدة لمصادر الفهرسين — تجميعاتٌ رخيصة لا تقرأ نصوصَ الترويسات.

    تلتقط الإضافةَ والحذفَ وتبديلَ الجهة/الكتاب في الذاكرة، وتعديلَ أعداد الجهات والحذفَ
    الناعمَ الجماعيّ في الكتب، وإعادةَ تسمية الجهات، وتبديلَ جهات الكتب (جدولا الربط) — أي
    ما تكتبه عمليّةٌ أخرى أو `queryset.update` بلا إشارة. ما يفوتها (تاريخُ كتابٍ عُدِّل من
    عمليّةٍ أخرى) يلتقطه العمر. المديرُ الأساسيّ عمداً: مديرُ الكتاب الافتراضيّ يُخفي المحذوف."""
    from django.db.models import Count, Max, Q, Sum
    from django.db.models.functions import Length
    from core.models import Book, Entity, LetterheadMemory

    lm = LetterheadMemory._base_manager.aggregate(
        n=Count('id'), mx=Max('id'), si=Sum('issuing_entity_id'), sr=Sum('receiving_entity_id'),
        sb=Sum('book_id'), mc=Max('created_at'))
    # عددُ المحذوف صراحةً: الحذفُ الناعمُ الجماعيّ (`books_api` يحذف دفعةً بـ`update`) لا
    # يُطلق إشارة، والبصماتُ تستثني المحذوف. وأطوالُ أعداد الجهات لا `updated_at`: هذا
    # يتغيّر مع كلّ أرشفةٍ أو هامش فيُعيد البناءَ بلا داع، وذاك ما يقرؤه الفهرسُ فعلاً.
    bk = Book._base_manager.aggregate(
        n=Count('id'), mx=Max('id'), nd=Count('id', filter=Q(is_deleted=True)),
        sl=Sum(Length('sender_number')))
    # أطوالُ الأسماء والرموز: إعادةُ تسمية جهةٍ من عمليّةٍ أخرى (`prepare_entities`) تُغيّر ما
    # يحمله فهرسُ الذاكرة (الاسمُ مخبوزٌ في صفوفه) ولا تُغيّر عدداً ولا معرّفاً.
    en = Entity._base_manager.aggregate(n=Count('id'), mx=Max('id'),
                                        nl=Sum(Length('name')), cl=Sum(Length('code')))
    links = tuple(
        tuple(sorted(through.objects.aggregate(
            n=Count('id'), se=Sum('entity_id'), sb=Sum('book_id')).items()))
        for through in (Book.issuing_entities.through, Book.receiving_entities.through))
    return (tuple(sorted(lm.items())), tuple(sorted(bk.items())), tuple(sorted(en.items())), links)


def invalidate_extraction_indexes():
    """تُستدعى من إشارات الحفظ/الحذف: الإبطالُ والبناءُ في الخلفيّة **بعد الإيداع** لا قبله.

    إبطالٌ داخل معاملةٍ مفتوحة (`merge_entities` ذرّيّة) يدعو خيطاً آخر إلى البناء الآن —
    فيقرأ ما قبل الإيداع وينشره بالجيل الجديد، ويبقى قديماً لا تراه البصمةُ (إعادةُ تسمية)
    حتّى ينقضي العمر. وقبل الإيداع لا شيءَ تغيّر في عين الخيوط الأخرى أصلاً.
    خارج المعاملة يجري فوراً؛ والمعاملةُ المُلغاة لا تُبطل شيئاً (لم يتغيّر شيء)."""
    if not _REGISTRY:
        return
    from django.db import transaction
    transaction.on_commit(_invalidate_and_refresh)


def _invalidate_and_refresh():
    for index in _REGISTRY:
        index.invalidate()
    refresh_extraction_indexes_soon()


def refresh_extraction_indexes_soon():
    """يُجدوِل بناءً في الخلفيّة لكلّ فهرسٍ مشترك — لا يُنتظَر ولا يرمي."""
    from django.conf import settings
    if not getattr(settings, 'EXTRACTION_BACKGROUND_INDEXING', False):
        return
    for index in _REGISTRY:
        if index.ttl() > 0:
            _REBUILDER.request(index)


class _Rebuilder:
    """خيطٌ خلفيٌّ واحد يبني ما طُلب، ويجمع الطلبات المتلاحقة في بناءٍ واحد."""

    def __init__(self):
        self._lock = threading.Lock()
        self._pending = []
        self._thread: Optional[threading.Thread] = None

    def request(self, index: SharedIndex):
        with self._lock:
            if index not in self._pending:
                self._pending.append(index)
            if self._thread is not None:
                return                          # الخيطُ الجاري يلتقطه قبل أن يخرج
            self._thread = threading.Thread(target=self._run, name='extraction-index-rebuild',
                                            daemon=True)
            self._thread.start()

    def _run(self):
        from django.db import close_old_connections, connections
        try:
            # تريّثٌ قصير: حفظُ كتابٍ واحد يُطلق عدّةَ إشاراتٍ متلاحقة (الكتاب، جهتاه، صفُّ
            # الذاكرة) — فيُبنى مرّةً واحدةً بعدها كلّها لا مرّتين.
            time.sleep(_DEBOUNCE_SEC)
            close_old_connections()
            while True:
                with self._lock:
                    if not self._pending:
                        self._thread = None    # الخروجُ والفحصُ تحت القفل نفسِه: لا طلبَ يضيع
                        return
                    batch, self._pending = self._pending, []
                for index in batch:
                    try:
                        index.get()
                    except Exception as exc:   # noqa: BLE001 — بناءٌ مسبق اختياريّ؛ الطلبُ يبني بنفسه
                        logger.warning('[shared-index] بناءُ %s في الخلفيّة تعذّر: %s', index.name, exc)
        except Exception as exc:               # noqa: BLE001 — لا يموت الخيطُ ويبقى «جارياً» فيُسكت كلَّ طلبٍ بعده
            logger.warning('[shared-index] خيطُ البناء الخلفيّ توقّف: %s', exc)
            with self._lock:
                self._thread = None
        finally:
            connections.close_all()            # اتّصالاتُ هذا الخيط وحده


_REBUILDER = _Rebuilder()
