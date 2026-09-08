# -*- coding: utf-8 -*-
"""تصييرُ صفحةٍ من مرفقٍ إلى صورة — لأجل قصاصة الهامش.

**لماذا على الخادم:** المرفقُ PDF في الغالب، والعارضُ يفتحه في إطارِ المتصفّح
المدمج — فلا وصولَ من JS إلى بكسلاته لرسم مستطيلٍ فوقها. وتحميلُ pdf.js يعني
مكتبةً ثالثةً في نظامٍ قرارُه «صفر CDN وكلُّ الأصول محلّيّة». فتُصيَّر الصفحةُ
هنا بـPyMuPDF — وهي مركّبةٌ ومستعملةٌ أصلاً في هذا المشروع.

**والصورةُ مُخبَّأةٌ لا مُخزَّنة:** ملفٌّ جديدٌ لكلّ صفحةٍ يُضاعف 15.8 غيغا
من المرفقات بلا داعٍ، والتصييرُ رخيصٌ (~40ms للصفحة). فالكاشُ يحمل الناتج،
والقرصُ لا يحمل شيئاً.
"""

import hashlib
import io
import logging

from django.core.cache import cache

logger = logging.getLogger(__name__)

#: عرضُ الصورة المُصيَّرة — يكفي لتحديد هامشٍ بالعين ولا يُثقل الشبكة.
RENDER_WIDTH = 1400

#: سقفٌ للصفحات: مستندٌ من مئة صفحةٍ لا يُطلب منه إلّا أولاها عمليّاً.
MAX_PAGE = 50

CACHE_SECONDS = 60 * 60 * 6


def _cache_key(path, page, width):
    stamp = hashlib.sha1(f'{path}|{page}|{width}'.encode('utf-8')).hexdigest()
    return f'pagerender:{stamp}'


def render_page(file_path, page_number, width=RENDER_WIDTH):
    """``(bytes, mimetype)`` لصفحةٍ واحدة — أو ``(None, None)`` إن تعذّر.

    ``page_number`` يبدأ من **1** كما يقرؤه الإنسان، لا من صفر.

    **الصيغةُ تُختار بالمحاولة لا بالافتراض**: PyMuPDF قد تُبنى بلا WebP —
    وهي كذلك على هذا الجهاز فعلاً. والمحاولةُ الأولى كانت تفترض النجاح
    وتضع السقوطَ الاحتياطيّ في فرعٍ لا يُبلَغ، لأنّ الصيغةَ غيرَ المدعومة
    **ترمي** ولا تُعيد ``None``. وJPEG بعدها لا PNG: الصفحةُ صورةُ ورقٍ
    ممسوح، وPNG يُضاعف حجمَها بلا مكسب.
    """
    if page_number < 1 or page_number > MAX_PAGE:
        return None, None

    key = _cache_key(str(file_path), page_number, width)
    cached = cache.get(key)
    if cached is not None:
        return cached

    try:
        import fitz  # PyMuPDF

        with fitz.open(str(file_path)) as doc:
            if page_number > doc.page_count:
                return None, None
            page = doc[page_number - 1]
            # المقياسُ يُشتقّ من عرض الصفحة نفسِها لا من رقمٍ ثابت: صفحاتُ
            # الماسح تختلف أبعادُها، ورقمٌ مثبَّتٌ يُنتج صوراً بمقاييسَ شتّى —
            # وهو الفخُّ الذي كلّف قارئَ الأرقام في هذا المشروع مرّةً من قبل.
            zoom = width / max(page.rect.width, 1)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)

            result = None
            for fmt, mime in (('webp', 'image/webp'), ('jpg', 'image/jpeg'),
                              ('png', 'image/png')):
                try:
                    result = (pixmap.tobytes(fmt), mime)
                    break
                except (ValueError, RuntimeError):
                    continue
            if result is None:
                return None, None
    except Exception as exc:                       # noqa: BLE001 — الملفُّ خارجيّ
        logger.warning('تعذّر تصيير الصفحة %s من %s: %s', page_number, file_path, exc)
        return None, None

    cache.set(key, result, CACHE_SECONDS)
    return result


def page_count(file_path):
    """عددُ صفحات المرفق — صفرٌ إن لم يكن مستنداً يُفتح."""
    try:
        import fitz

        with fitz.open(str(file_path)) as doc:
            return doc.page_count
    except Exception:                              # noqa: BLE001
        return 0


def normalise_crop(raw):
    """يتحقّق من قصاصةٍ واردةٍ من العميل ويُعيدها مُطهَّرة — أو ``None``.

    **الإحداثيّاتُ كسورٌ من 0 إلى 1 لا بكسلات**: الصورةُ تُصيَّر بعرضٍ قد يتغيّر
    غداً، والبكسلُ يربط القصاصةَ بمقياسِ يومها فتنزلق عند أوّل تغيير. الكسرُ
    يبقى صحيحاً عند أيّ عرض.

    وترفض ما لا معنى له: مستطيلٌ بلا مساحة، أو خارج الصفحة، أو حقلٌ ناقص.
    """
    if not isinstance(raw, dict):
        return None

    try:
        page = int(raw.get('page', 1))
        x = float(raw['x'])
        y = float(raw['y'])
        w = float(raw['w'])
        h = float(raw['h'])
    except (KeyError, TypeError, ValueError):
        return None

    if page < 1 or page > MAX_PAGE:
        return None
    if not (0 <= x < 1 and 0 <= y < 1):
        return None
    if not (0 < w <= 1 and 0 < h <= 1):
        return None
    if x + w > 1.0001 or y + h > 1.0001:
        return None
    # قصاصةٌ أصغرُ من هذا نقرةٌ طائشةٌ لا تحديدٌ مقصود.
    if w * h < 0.0004:
        return None

    return {
        'page': page,
        'x': round(x, 5), 'y': round(y, 5),
        'w': round(w, 5), 'h': round(h, 5),
        'attachment': int(raw['attachment']) if str(raw.get('attachment', '')).isdigit() else None,
    }
