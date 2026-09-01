# -*- coding: utf-8 -*-
"""كاشف صندوق «العدد» — استدلال ONNX على CPU، بعقد هندسةٍ صريح.

**لماذا وُجد:** أرضيّة قصاصة التاريخ تُشتقّ اليوم من تسمية «العدد» التي يقرأها
Tesseract، وهي **تصمت في ~42% من الصفحات** (موثَّقٌ في `_number_label_floor`) فيتسلّل
تاريخ ترويسة الأيزو. الكاشف يُطلق على **164/165** من صور التحقّق (99.4%) بمركزٍ داخل
الصندوق الصحيح في **96%** — أي يملك بالضبط ما ينقص الأرضيّة. لا يُزيح المسار القائم:
يملأ صمته فقط (قرار فيبل 2026-08-17).

**عقد الهندسة (اقرأه قبل أن تمسّ أيّ إحداثيّة):** الكاشف دُرِّب على **أعلى 55% من
الصفحة** مرسومةً بـ175dpi ثم مُلَبَّدةً (letterbox) إلى 1280×1280. فالاستدلال يجب أن
يُكرّر ذلك حرفيّاً، والصندوق العائد يُعاد إلى **إحداثيّات الصفحة الكاملة المُطبَّعة**
قبل أن يغادر هذه الوحدة. كلّ رقمٍ هنا مصحوبٌ بمقاسه المرجعيّ صراحةً — هكذا يموت فخّ
1600/2600/3500 بالبناء لا باليقظة.

النموذج: yolov8n صنفٌ واحد، mAP50 0.830 (det-b، T4 واحدة — وقد تفوّق على تدريب
لوحتين). يُحمَّل كسولاً ويُشارَك، ويصمت رشيقاً إن غاب الملفّ أو سقط الاستدلال:
غيابُ صندوقٍ يُعيدنا للسلوك السابق تماماً، ولا يكسر استخراجاً.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Optional, Tuple

import numpy as np

# استيرادٌ في الرأس لا داخل الدالّة: استيرادٌ كسولٌ داخل `_model_path` يستدعي
# `os.path.exists` عبر آلة الاستيراد عند أوّل نداء، فيكذب على أيّ اختبارٍ يعدّ
# ضرباتِ القرص (سقط `test_missing_model_probed_once_only` بذلك حرفيّاً).
from core.extraction.artifacts import detector_fallback_path, detector_path

logger = logging.getLogger(__name__)

IMGSZ = 1280          # مقاس التدريب — تغييره يُبطل الأوزان
TRAIN_CROP = 0.55     # أعلى 55% من الصفحة (نفس pack_detector_dataset.py)
CONF_MIN = 0.15       # نفس عتبة قياس البوّابة M1 في الدفتر

# فكُّ الترميز **يقوده الشكل** لا ثابتٌ مُستبدَل (خطّة فيبل 2026-08-26):
#   5 قنوات ⟵ [cx,cy,w,h,conf]           صنفٌ واحد (أوزانُ det-b القديمة)
#   6 قنوات ⟵ [cx,cy,w,h,c_number,c_subj] صنفان (أوزانُ det2)
# علّةُ الثابت الصارم كانت التباسَ محورٍ عند مرشَّحٍ واحد (5,1) — والتباسُ {5,6}
# مع محور المراسي (33,600) **مستحيلٌ بالبناء**. والمكسب: **التراجعُ يصير ملفَّ
# أوزانٍ فقط بلا revert كود**، والخطرُ الأصليّ (قراءةُ c0 على أنّها objectness
# فيُسقَط الصنفُ الثاني صامتاً) يموت في الحالتين.
_NC_BY_CHANNELS = {5: 1, 6: 2}
# ترتيبُ الصنفين **مُتحقَّقٌ منه لا مفترَض** — `package_det2_ds.py`:
#     CLASSES = ('number', 'subject')  # 0, 1 — الترتيب عقد
CLS_NUMBER, CLS_SUBJECT = 0, 1
_CLS_NAMES = ('number', 'subject')

_session = None
_sess_lock = threading.Lock()
_load_failed = False

# الاحتياطُ: أوزانُ det1 كاشفاً ثانياً حين يصمت det2 (خطّة فيبل S1).
# تصحيحُ تسميةٍ مُقيَّد: الصفحتان اللتان تراجعتا كانتا إصابتَي **صندوق det1**
# لا مسارِ الشريط — فالعلاجُ كاشفٌ احتياطيّ، ولو نُفِّذ بالاسم القديم لعُولج
# المسارُ الخطأ وضاعت الصفحتان.
_fb_session = None
_fb_failed = False


def _model_path() -> str:
    return detector_path()


def _get_session():
    """جلسةٌ واحدةٌ مُشارَكة — تحميلٌ ثانٍ على جهاز 8GB يعني انهياراً."""
    global _session, _load_failed
    if _session is not None or _load_failed:
        return _session
    with _sess_lock:
        if _session is not None or _load_failed:
            return _session
        path = _model_path()
        if not os.path.exists(path):
            logger.info('[detector] لا نموذج في %s — الكاشف صامت', path)
            _load_failed = True
            return None
        try:
            import onnxruntime as ort
            so = ort.SessionOptions()
            so.intra_op_num_threads = 1        # الجهاز 8GB — لا تُنافس عامل OCR
            so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            _session = ort.InferenceSession(path, so, providers=['CPUExecutionProvider'])
            logger.info('[detector] حُمِّل %s', path)
        except Exception as exc:
            logger.warning('[detector] تعذّر التحميل (%s) — تدهور رشيق', type(exc).__name__)
            _load_failed = True
    return _session


def _fallback_path() -> str:
    return detector_fallback_path()


def _get_fallback_session():
    """تُحمَّل **كسولاً عند أوّل صمتٍ فعليّ** — لا عند إقلاع الخادم.

    كلفتُها ~60–90 ميغابايت ولا تُدفع إلّا على الصفحات التي يصمت فيها det2
    (~8–20%)، وبنفس `intra_op_num_threads=1` كي لا تُنافس عامل OCR على 8GB.
    """
    global _fb_session, _fb_failed
    if _fb_session is not None or _fb_failed:
        return _fb_session
    with _sess_lock:
        if _fb_session is not None or _fb_failed:
            return _fb_session
        path = _fallback_path()
        if not os.path.exists(path):
            logger.info('[detector] لا كاشفَ احتياطيّ في %s', path)
            _fb_failed = True
            return None
        try:
            import onnxruntime as ort
            so = ort.SessionOptions()
            so.intra_op_num_threads = 1
            so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            _fb_session = ort.InferenceSession(path, so, providers=['CPUExecutionProvider'])
            logger.info('[detector] حُمِّل الاحتياطيّ %s', path)
        except Exception as exc:
            logger.warning('[detector] تعذّر تحميلُ الاحتياطيّ (%s)', type(exc).__name__)
            _fb_failed = True
    return _fb_session


def _letterbox(arr: np.ndarray, size: int) -> Tuple[np.ndarray, float, int, int]:
    """يُلبِّد إلى مربّعٍ بحفظ النسبة (كما يفعل ultralytics). يُعيد (الصورة، المقياس، dx, dy)."""
    h, w = arr.shape[:2]
    r = min(size / w, size / h)
    nw, nh = int(round(w * r)), int(round(h * r))
    from PIL import Image
    im = Image.fromarray(arr).resize((nw, nh), Image.BILINEAR)
    canvas = np.full((size, size, 3), 114, dtype=np.uint8)     # نفس حشو ultralytics
    dx, dy = (size - nw) // 2, (size - nh) // 2
    canvas[dy:dy + nh, dx:dx + nw] = np.asarray(im)
    return canvas, r, dx, dy


def _decode(sess, pil_img) -> dict:
    """فكُّ ترميزٍ مشترك — تستعمله جلسةُ det2 والاحتياطيّةُ معاً بلا تكرار."""
    empty = {n: None for n in _CLS_NAMES}
    try:
        W, H = pil_img.size
        ch = max(1, int(TRAIN_CROP * H))
        crop = np.asarray(pil_img.convert('RGB'))[:ch, :, :]
        canvas, r, dx, dy = _letterbox(crop, IMGSZ)
        x = canvas.astype(np.float32).transpose(2, 0, 1)[None] / 255.0
        out = sess.run(None, {sess.get_inputs()[0].name: x})[0]
        arr = out[0] if out.ndim == 3 else out
        if arr.shape[0] in _NC_BY_CHANNELS:
            pred, nc = arr.T, _NC_BY_CHANNELS[arr.shape[0]]
        elif arr.shape[-1] in _NC_BY_CHANNELS:
            pred, nc = arr, _NC_BY_CHANNELS[arr.shape[-1]]
        else:
            logger.warning('[detector] شكل مخرجاتٍ غير متوقّع %s — تخطٍّ', arr.shape)
            return empty
        if pred.size == 0:
            return empty

        res = dict(empty)
        for cls in range(nc):
            score = pred[:, 4 + cls]           # عمودُ الصنف — لا objectness
            i = int(score.argmax())
            c = float(score[i])
            if c < CONF_MIN:                   # صمتُ صنفٍ لا يُسكت الآخر
                continue
            cx, cy, bw, bh = (float(v) for v in pred[i, :4])
            x0 = (cx - bw / 2 - dx) / r
            y0 = (cy - bh / 2 - dy) / r
            x1 = (cx + bw / 2 - dx) / r
            y1 = (cy + bh / 2 - dy) / r
            box = [max(0.0, x0 / W), max(0.0, y0 / H),
                   min(1.0, x1 / W), min(1.0, y1 / H)]
            if box[0] < box[2] and box[1] < box[3]:
                res[_CLS_NAMES[cls]] = (box, c)
        return res
    except Exception as exc:
        logger.warning('[detector] فشل الاستدلال (%s) — تدهور رشيق', type(exc).__name__)
        return empty


def detect_boxes(pil_img) -> dict:
    """يُعيد `{'number': (box, conf)|None, 'subject': (box, conf)|None}`.

    المُدخَل صفحةٌ كاملة (PIL). القصُّ إلى أعلى 55% يجري داخليّاً كي لا يستطيع أيّ
    مُستدعٍ أن يخطئ في تكرار تحضير التدريب، والإحداثيّاتُ الخارجة مُطبَّعةٌ على
    **الصفحة الكاملة** لا على القصاصة — هذا نصّ العقد.

    مع أوزانٍ خماسيّة القنوات يكون `subject` دائماً None — وهو **مسارُ التراجع**.
    """
    sess = _get_session()
    if sess is None:
        return {n: None for n in _CLS_NAMES}
    return _decode(sess, pil_img)


def detect_number_box_fallback(pil_img):
    """كاشفُ det1 احتياطيّاً — يُستدعى **فقط** حين يصمت det2 عن العدد.

    خطرُه محدودٌ بالبناء: لا يعمل إلّا على صفحةٍ كانت ستبقى صامتة، وأسوأُ حالاته
    صندوقٌ زائفٌ ⟵ قراءةٌ دون بوّابة الثقة لا تمسّ حارس «واثقٌ‑ومخطئ».
    """
    sess = _get_fallback_session()
    if sess is None:
        return None
    return _decode(sess, pil_img).get('number')


def detect_number_box(pil_img) -> Optional[Tuple[list, float]]:
    """غلافٌ رقيقٌ يحفظ التوقيع القائم — فلا يتغيّر حرفٌ في `pipeline.py` بالإيداع 1."""
    return detect_boxes(pil_img).get('number')
