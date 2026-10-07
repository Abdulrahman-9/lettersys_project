# -*- coding: utf-8 -*-
"""ممرّاتُ القراءة المتوازية داخل الاستخراج الواحد — المخرَجُ نفسُه حرفاً، والزمنُ أقصر.

**ما يتوازى:** ثلاثُ قراءاتٍ خامٍ لا تعتمد إحداها على الأخرى ولا على القاعدة:
  r1  — قراءةُ Tesseract الرئيسيّة للصورة المحسَّنة (وتصعيدُها الثنائيُّ بقاعدته داخلها)؛
  r4  — جدولُ كلمات Tesseract لصورة مسار خطّ اليد (300dpi رماديّة)؛
  det — صناديقُ det2، وdet1 احتياطاً حين يصمت det2 وجلستُه محمَّلةٌ أصلاً.
الرسمُ يبقى على خيط الاستخراج تحت `MUPDF_LOCK`؛ الممرُّ يقرأ صورةً جاهزةً فقط.
قِيس على 18 كتاباً (2026‑10‑05): القراءتان كاملتان متتاليتان، كلٌّ 1.0–3.1 ث.

**العقد — لماذا لا يتغيّر حرف:**
  · الممرُّ دالّةٌ نقيّةٌ في الملفّ والأوزان والإعدادات (Tesseract وONNX حتميّان مقيساً، ومتزامنين
    كذلك)، لا يكتب `result` ولا القاعدةَ ولا البيئةَ ولا متغيّراً عامّاً؛
  · قيمتُه تُستهلك **حيث كان كودُ اليوم سيحسبها وبشرطه** — وإن لم يكن سيحسبها تُرمى؛
  · أيُّ فشلٍ أو **تدهورٍ صامت** في الممرّ (`core/extraction/degrade.py`) ⟵ يُحسَب الشيءُ نفسُه
    على خيط الاستخراج بكود اليوم في موضعه؛ ولا يُستهلك جزءٌ من قيمة؛
  · لا مهلةَ للممرّات (مهلةُ `process_image` كما هي)، ولا تحميلَ نموذجٍ داخل ممرّ؛
  · **ولا يعمل خيطُ الاستخراج شيئاً آخر والممرّاتُ جارية** (`finish()` قبل أن يتابع): ما يجري
    عليه بعدها (فهرسُ الجهات، صندوقُ الموضوع، CRNN) يبتلع أعطاله ولا يراه علَمُ التدهور، فلا
    يُعرَّض لضغط ذاكرةٍ صنعه التوازي. الممرّاتُ تتوازى فيما بينها وحدها.

**القبول (`admit`)** — وإلّا فالمسارُ المتسلسل، وهو كودُ اليوم حرفاً:
  · الإعداد `EXTRACTION_LANES`، ومحرّكُ Tesseract وحده (يقرّره المُستدعي)؛
  · هذا هو الاستخراجُ **الوحيد** الجاري في العمليّة — كاتبتان معاً تعملان متسلسلتين كاليوم؛
  · ذاكرةٌ فعليّةٌ حرّة ≥ `EXTRACTION_LANES_MIN_FREE_MB` **و**متّسعُ التزامٍ ≥
    `EXTRACTION_LANES_MIN_COMMIT_MB`: إخفاقُ malloc — وهو ما يُدهوِر المخرَجَ صامتاً — تحكمه
    سعةُ الالتزام لا الذاكرةُ الحرّةُ وحدها (مراجعةُ الخيوط والذاكرة 2026‑10‑06).
"""
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from core.extraction import degrade

logger = logging.getLogger('lettersys')

#: «لم يُحسَب في الممرّ» — يحسبه خيطُ الاستخراج بكود اليوم في موضعه.
NOT_RUN = object()

# مقابضُ الاختبار وأداة القبول وحدهما — لا تُضبط في الإنتاج.
_TEST_JITTER = None           # (ms, random.Random) ⟵ تأخيرٌ عشوائيٌّ قبل كلّ ممرّ
_TEST_FAULTS = set()          # ممرّاتٌ تُفشَل عمداً
_TEST_DEGRADE = set()         # ممرّاتٌ تُوسَم «متدهورةً» بعد نجاحها
_TEST_MEMORY_MB = None        # قراءةُ ذاكرةٍ مفروضة (الحرّةُ = متّسعُ الالتزام)

_FANOUT_SLOTS = threading.BoundedSemaphore(1)
_state_lock = threading.Lock()
_active = 0
_pool = None
stats = {}


class LaneFailed(Exception):
    """فشلٌ أو تدهورٌ داخل ممرّ — يعني «احسبه بالتسلسل»، لا خطأً في الاستخراج."""


def _bump(key):
    with _state_lock:
        stats[key] = stats.get(key, 0) + 1


def enabled():
    from django.conf import settings
    return bool(getattr(settings, 'EXTRACTION_LANES', False))


def extraction_enter():
    global _active
    with _state_lock:
        _active += 1


def extraction_exit():
    global _active
    with _state_lock:
        _active = max(0, _active - 1)


def active_extractions():
    with _state_lock:
        return _active


def memory_mb():
    """(ذاكرةٌ فعليّةٌ حرّة، متّسعُ التزام) بالميغابايت — أو (None, None) إن تعذّرت القراءة."""
    if _TEST_MEMORY_MB is not None:
        return _TEST_MEMORY_MB, _TEST_MEMORY_MB
    try:
        import ctypes

        class _MemoryStatusEx(ctypes.Structure):
            _fields_ = [('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong),
                        ('ullTotalPhys', ctypes.c_ulonglong), ('ullAvailPhys', ctypes.c_ulonglong),
                        ('ullTotalPageFile', ctypes.c_ulonglong), ('ullAvailPageFile', ctypes.c_ulonglong),
                        ('ullTotalVirtual', ctypes.c_ulonglong), ('ullAvailVirtual', ctypes.c_ulonglong),
                        ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]
        status = _MemoryStatusEx()
        status.dwLength = ctypes.sizeof(_MemoryStatusEx)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None, None
        return status.ullAvailPhys // 1048576, status.ullAvailPageFile // 1048576
    except Exception:                      # noqa: BLE001 — غيرُ ويندوز أو عطل ⟵ لا توازي
        return None, None


def admit():
    """`LaneSet` أو None (⟵ المسارُ المتسلسل). غيرُ حاجب."""
    from django.conf import settings
    if not enabled():
        return None
    if active_extractions() != 1:
        _bump('sequential_busy')
        return None
    free, commit = memory_mb()
    with _state_lock:
        stats['last_free_mb'], stats['last_commit_mb'] = free, commit
    need_free = int(getattr(settings, 'EXTRACTION_LANES_MIN_FREE_MB', 300))
    need_commit = int(getattr(settings, 'EXTRACTION_LANES_MIN_COMMIT_MB', 500))
    if free is None or commit is None or free < need_free or commit < need_commit:
        _bump('sequential_memory')
        return None
    if not _FANOUT_SLOTS.acquire(blocking=False):
        _bump('sequential_slot')
        return None
    _bump('admitted')
    return LaneSet()


def _get_pool():
    global _pool
    with _state_lock:
        if _pool is None:
            _pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix='extraction-lane')
        return _pool


def _close_lane_db():
    """الممرُّ لا يلمس القاعدة؛ إن فعل خطأً يُغلق اتّصالُه ويُعَدّ (أداةُ القبول تشترط صفراً)."""
    try:
        from django.db import connections
        for conn in connections.all(initialized_only=True):
            if conn.connection is not None:
                _bump('db_touch')
                logger.error('[lanes] ممرٌّ فتح اتّصالَ قاعدة — أُغلق')
            conn.close()
    except Exception:                      # noqa: BLE001
        pass


def _guarded(name, fn):
    degrade.clear()
    try:
        if _TEST_JITTER is not None:
            ms, rng = _TEST_JITTER
            time.sleep(rng.uniform(0, ms) / 1000.0)
        if name in _TEST_FAULTS:
            raise LaneFailed('test fault')
        value = fn()
        if name in _TEST_DEGRADE:
            degrade.mark('test')
        why = degrade.reason()
        if why:
            raise LaneFailed('degraded: %s' % why)
        return value
    finally:
        degrade.clear()
        _close_lane_db()


class LaneSet:
    """ممرّاتُ استخراجٍ واحد. `take` يُعيد قيمةَ الممرّ أو يحسبها بكود اليوم (`inline`)."""

    def __init__(self):
        self._futures = {}
        self._released = False

    def start(self, name, fn):
        if name in self._futures or self._released:
            return
        try:
            self._futures[name] = _get_pool().submit(_guarded, name, fn)
            _bump('started_' + name)
        except RuntimeError as exc:        # المجمّعُ أُغلق مع إيقاف الخادم ⟵ يُحسَب بالتسلسل
            logger.warning('[lanes] تعذّر بدءُ %s: %s', name, exc)

    def started(self, name):
        return name in self._futures

    def take(self, name, inline):
        future = self._futures.get(name)
        if future is None:
            return inline()
        try:
            return future.result()
        except Exception as exc:           # noqa: BLE001 — أيُّ فشلٍ في الممرّ ⟵ كودُ اليوم
            _bump('fallback_' + name)
            logger.info('[lanes] %s ⟵ تسلسل (%s)', name, exc)
            return inline()

    def join_all(self):
        """ينتظر كلَّ ممرٍّ بدأ (قبل حذف الملفّ المؤقّت الذي تقرؤه) ويبتلع أخطاءها."""
        for future in list(self._futures.values()):
            try:
                future.result()
            except Exception:              # noqa: BLE001
                pass

    def release(self):
        if not self._released:
            self._released = True
            _FANOUT_SLOTS.release()

    def finish(self):
        """ينتظر الممرّاتِ كلَّها ويحرّر الفتحة. **يُنادى قبل أيّ عملٍ آخر لخيط الاستخراج**:
        بناءُ فهرس الجهات وقراءةُ صندوق الموضوع وCRNN تبتلع أعطالها على خيط الاستخراج، ولا
        يراها علَمُ التدهور — فلا تجري وممرٌّ يضغط على الذاكرة (مراجعة 2026‑10‑06). القيمُ
        تبقى في الممرّات فيأخذها `take` في مواضعها لاحقاً."""
        self.join_all()
        self.release()
