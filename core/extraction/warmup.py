# -*- coding: utf-8 -*-
"""إحماءُ الاستخراج عند إقلاع الخادم — كي لا يدفع أوّلُ كاتبٍ بعد التشغيل ثمنَ التحميل.

**المقيس (2026‑10‑05):** أوّلُ استخراجٍ بعد إعادة تشغيل الجهاز أخذ **24.3 ث** مقابل ~5.5 ث
للكتاب نفسه بعده: استيرادُ sklearn أوّلَ مرّة وقرصٌ بارد (فهرسُ الذاكرة وحده 18.5 ث)،
وجلساتُ ONNX، وأوّلُ تشغيلٍ لـTesseract. بعد إعادة الخدمة وحدها الفارقُ 2–4 ث.

يُستدعى من `lettersys/wsgi.py` و`lettersys/asgi.py` وحدهما: عمليّاتُ الخدمة تستوردهما،
وأوامرُ الإدارة والاختبارات لا تستوردهما — فلا يجري الإحماءُ أثناء `migrate` أو اختبار.
ومُطفأٌ افتراضيّاً مع DEBUG (`EXTRACTION_WARMUP`): خادمُ التطوير يُعاد كثيراً، وكلُّ إعادةٍ
كانت ستحمل sklearn وONNX فوراً على جهاز 8 GB.
خيطٌ خلفيّ لا يؤخّر فتحَ المنفذ؛ كلُّ خطوةٍ مستقلّة وفشلُها يُسجَّل ولا يرمي (قاعدةٌ لم
تجهز بعد عند الإقلاع — تُعاد المحاولة — أو وزنٌ غائب). لا يغيّر شيئاً ممّا يُخرجه الاستخراج:
يقدّم العملَ نفسَه في الزمن فقط.
"""
import logging
import threading
import time

logger = logging.getLogger('lettersys')

_DB_RETRIES, _DB_RETRY_SEC = 3, 5.0
_start_lock = threading.Lock()
_started = False


def _shared_indexes():
    from django.db.utils import OperationalError
    from core.extraction.matchers.entity import MEMORY_INDEX
    from core.extraction.matchers.profile import PROFILES_INDEX
    from sklearn.metrics.pairwise import cosine_similarity  # noqa: F401 — استيرادٌ كسولٌ في مطابقة الأسماء
    for attempt in range(1, _DB_RETRIES + 1):
        try:
            MEMORY_INDEX.get()
            PROFILES_INDEX.get()
            return
        except OperationalError:
            if attempt == _DB_RETRIES:
                raise
            time.sleep(_DB_RETRY_SEC)      # القاعدةُ قد تُقلع بعد الخادم


def _detector():
    from core.extraction.handwriting import detector
    detector._get_session()


def _readers():
    """قارئُ التاريخ مفردٌ مقيمٌ أصلاً — يُحمَّل الآن. وقارئُ العدد يُنشأ لكلّ طلب، فلا جلسةَ
    مقيمةَ تُحمَّل له: يُقرأ ملفُّه وحده فيدفأ في ذاكرة النظام بلا ذاكرةٍ تبقى محجوزة."""
    from core.extraction.handwriting.date_reader import get_date_reader
    from core.extraction.handwriting.reader import HandwrittenNumberReader
    date_reader = get_date_reader()
    if date_reader.available:
        date_reader._ensure_session()
    number_model = HandwrittenNumberReader().model_path
    try:
        with open(number_model, 'rb') as fh:
            while fh.read(1 << 20):
                pass
    except OSError:
        pass


def _tesseract():
    from PIL import Image
    from core.extraction.ocr.providers import TesseractOCRProvider
    prov = TesseractOCRProvider()
    prov._pytesseract.image_to_string(Image.new('L', (96, 32), 255), lang=prov.lang, config='--psm 7')


_STEPS = (('shared-indexes', _shared_indexes), ('detector', _detector),
          ('readers', _readers), ('tesseract', _tesseract))


def _warm():
    from django.db import close_old_connections, connections
    t0 = time.perf_counter()
    done = []
    try:
        close_old_connections()
        for label, step in _STEPS:
            ts = time.perf_counter()
            try:
                step()
                done.append('%s %.1fs' % (label, time.perf_counter() - ts))
            except Exception as exc:               # noqa: BLE001 — إحماءٌ اختياريّ: الطلبُ يحمّل بنفسه
                logger.warning('[warmup] %s تعذّر: %s', label, exc)
    finally:
        connections.close_all()                    # اتّصالاتُ هذا الخيط وحده
    logger.info('[warmup] الاستخراجُ جاهز في %.1f ث — %s', time.perf_counter() - t0, ' · '.join(done))


def start_extraction_warmup():
    """يبدأ الإحماءَ مرّةً واحدةً لكلّ عمليّة في خيطٍ خلفيّ إن كان مُفعَّلاً (`EXTRACTION_WARMUP`)
    — يُعيد الخيطَ، أو None إن كان مُطفأً أو بدأ من قبل (wsgi وasgi قد يُستوردان معاً)."""
    global _started
    from django.conf import settings
    if not getattr(settings, 'EXTRACTION_WARMUP', False):
        return None
    with _start_lock:
        if _started:
            return None
        _started = True
    thread = threading.Thread(target=_warm, name='extraction-warmup', daemon=True)
    thread.start()
    return thread
