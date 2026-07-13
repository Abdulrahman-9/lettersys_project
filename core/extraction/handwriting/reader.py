# -*- coding: utf-8 -*-
"""قارئ الأرقام اليدوية — غلاف تشغيل ONNX لنموذج CRNN-CTC (مرحلة 3).

عقد المعالجة منسوخ حرفياً من preprocess_strip في سكربت التدريب (v4/v5):
شريط رمادي بحبر داكن على ورق فاتح → قلب (255-x) → ارتفاع 64 → توحيد قياسي.
الإخراج: (النص المقروء، درجة ثقة 0-1) — والثقة متوسط احتمالات المحارف
المنبعثة (softmax عند إطار انبعاث كل محرف)، فتصلح لبوابة قبولٍ صادقة:
دون العتبة ⇒ فراغ صريح لا تخمين (مبدأ المالك).

الجلسة كسولة ومفردة لكل عملية — onnxruntime على المعالج، بلا PyTorch."""
import json
import logging
import os
from typing import Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

_MODEL_PATH = os.path.join('var', 'models', 'handwritten_digits_crnn.onnx')
_CHARSET_PATH = os.path.join('var', 'models', 'handwritten_digits_charset.json')
_STRIP_H, _MAX_W = 64, 512

# بوابة الثقة — مُعايَرة على 128 شريطاً حقيقياً محجوزاً (v5، 2026-07-13):
# عند 0.90: دقة 96.6% فوق العتبة بتغطية 91.4% (0.95 ⇒ 97.3%/87.5%).
# الحقل اقتراحٌ يُراجَع أمام المستند مع شارة ثقة — لا يُحفظ آلياً.
CONF_GATE = 0.90


class HandwrittenNumberReader:
    """قارئ مفرد كسول: `read(صورة PIL رمادية) → (نص أو None، ثقة)`."""

    def __init__(self, model_path: str = _MODEL_PATH,
                 charset_path: str = _CHARSET_PATH, session=None):
        self.model_path = model_path
        self.charset = '0123456789'
        self.blank = 0
        if os.path.exists(charset_path):
            try:
                with open(charset_path, encoding='utf-8') as f:
                    meta = json.load(f)
                self.charset = meta.get('charset', self.charset)
                self.blank = int(meta.get('blank', 0))
            except (OSError, ValueError) as exc:
                logger.warning('[handwriting] تعذّر قراءة charset: %s', exc)
        self._session = session          # حقن للاختبارات
        self._input_name = 'image'

    @property
    def available(self) -> bool:
        return self._session is not None or os.path.exists(self.model_path)

    def _ensure_session(self):
        if self._session is None:
            import onnxruntime as ort   # استيراد كسول — لا يثقل إقلاع الخادم
            self._session = ort.InferenceSession(
                self.model_path, providers=['CPUExecutionProvider'])
            self._input_name = self._session.get_inputs()[0].name
        return self._session

    @staticmethod
    def preprocess(pil_gray) -> np.ndarray:
        """عقد v4/v5 الحرفي: قلبٌ فتوحيد ارتفاع 64 فتقييس — (1,1,64,W)."""
        w, h = pil_gray.size
        nw = max(32, min(_MAX_W, int(w * _STRIP_H / max(1, h))))
        img = pil_gray.resize((nw, _STRIP_H))
        arr = 255.0 - np.asarray(img, dtype=np.float32)
        arr = (arr - arr.mean()) / (arr.std() + 1e-6)
        return arr[None, None]

    def read(self, pil_gray) -> Tuple[Optional[str], float]:
        """يقرأ شريطاً؛ يعيد (None, 0.0) عند غياب النموذج أو فراغ القراءة —
        فشلُ القارئ لا يُفشل الأنبوب أبداً (تدهور رشيق)."""
        if not self.available:
            return None, 0.0
        try:
            sess = self._ensure_session()
            logits = sess.run(None, {self._input_name: self.preprocess(pil_gray)})[0][0]
        except Exception as exc:
            logger.warning('[handwriting] فشل الاستدلال: %s', type(exc).__name__)
            return None, 0.0
        # softmax مستقر عددياً لكل إطار زمني
        z = logits - logits.max(axis=-1, keepdims=True)
        probs = np.exp(z)
        probs /= probs.sum(axis=-1, keepdims=True)
        path = logits.argmax(-1)
        prev, chars, confs = self.blank, [], []
        for t, k in enumerate(path):
            if k != self.blank and k != prev:
                chars.append(self.charset[k - 1])
                confs.append(float(probs[t, k]))
            prev = k
        if not chars:
            return None, 0.0
        return ''.join(chars), float(np.mean(confs))
