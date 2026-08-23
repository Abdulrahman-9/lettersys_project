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

# بوابة الثقة — تحرس **مسار الشريط القديم وحده** (pipeline). مسار قصاصة الكاشف
# يُصدر بلا بوّابةٍ بأمر المالك، والتأشير مسؤوليّة الواجهة عند 0.65.
# صُودق عليها 2026-08-23 بسُلَّم H6 (أوزان T2.4، حجز 393 قصاصة كاشف):
#   >=0.90 ⟵ دقّة 94.5% بتغطية 89% · حدّ الواجهة 0.65 ⟵ 90.6% فوقه و**0.0%** تحته.
# القيمتان قائمتان من قبلُ ولم تُنتخَبا على الحجز — مُصادقةٌ لا انتخاب.
# (بروكسي: الحجز قصاصاتُ كاشفٍ لا أشرطةُ المُموضِع — والقارئ واحدٌ في المسارين.)
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
        # الاشتقاق **دائماً وأيّاً كان مسار البناء** — لا للمُحمَّل من الملفّ وحده.
        # العطب الخامس من صنف «حدّ القوالب» (2026-08-23): الجلسة المحقونة كانت
        # تتخطّى هذا السطر فيبقى الافتراضيّ 'image' بينما نموذج T2.4 اسمُ مُدخَله
        # 'input' ⟵ ValueError على كلّ قراءة، ومسحُ عتبةٍ كامل صفريّ النتائج.
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
        text = ''.join(chars)
        return text, self._sequence_confidence(probs, text)

    def _sequence_confidence(self, probs, text) -> float:
        """ثقةُ **السلسلة** لا ثقةُ الرموز — احتماليّة CTC الأماميّة مُطبَّعةً بالطول.

        **العطب الذي تُصلحه** (مقيسٌ 2026-08-19، استشارة فيبل): الصيغة السابقة كانت
        متوسّطَ احتماليّة الرمز عند الأطر **المُصدَّرة وحدها**، والحذفُ غيرُ مرئيٍّ لها
        **بالبناء** عبر ثلاث قنوات: أطرُ الفراغ (الرقم المحذوف يُصنَّف فراغاً والفراغ
        مُستبعَدٌ من المتوسّط) · أطرُ الامتداد (`k != prev` تبتلع رقماً يُصنَّف امتداداً
        لجاره) · وانهيارُ المكرّر («٢٢» بلا فراغٍ بينهما ينهار إلى «٢»، ولا إطارَ يحمل
        دليلَه). فكانت تقيس **وضوحَ ما خرج** ولا تستطيع التعبير عن الشكّ فيما **كُتم**.

        المعرض: قصاصةُ «٧٠٩٩» تُقرأ «799» بثقة **1.000** (كتاب 11305).

        وهذه تحسب `P(y|x)` للسلسلة المُفكَّكة نفسها بالتكرار الأماميّ القياسيّ، ثمّ
        تُطبَّع هندسيّاً بالطول. فإن بقيت كتلةٌ احتماليّةٌ على «7099» بينما خرج «799»،
        انخفضت `P(799)` — **والفجوةُ هي شكّ الحذف**، أيّاً كانت قناته.

        مقيسٌ على 1,781 زوجاً (فصلُ الصحيح عن الحذف، AUROC بمجال ثقة 300 عيّنة):
            **H6 هذه   0.903  [0.883, 0.921]**
            السابقة    0.734  [0.696, 0.764]
        وبقيّة المُرشَّحين دونهما (min 0.711 · p10 0.682 · هامش 0.672) — انظر
        `docs/EVAL_REGISTRY.md`. التكلفة O(T×|y|) على مصفوفةٍ محسوبةٍ أصلاً.
        """
        try:
            ext = [self.blank]
            for ch in text:
                ext.append(self.charset.index(ch) + 1)
                ext.append(self.blank)
            n_states = len(ext)
            lp = np.log(np.maximum(probs, 1e-12))
            neg = -1e30
            alpha = np.full(n_states, neg)
            alpha[0] = lp[0, ext[0]]
            if n_states > 1:
                alpha[1] = lp[0, ext[1]]
            for t in range(1, lp.shape[0]):
                prev_a, cur = alpha, np.full(n_states, neg)
                for i in range(n_states):
                    best = prev_a[i]
                    if i > 0:
                        best = np.logaddexp(best, prev_a[i - 1])
                    # القفزُ رمزين ممنوعٌ بين رمزين متساويين — شرط CTC للمكرّر
                    if i > 1 and ext[i] != self.blank and ext[i] != ext[i - 2]:
                        best = np.logaddexp(best, prev_a[i - 2])
                    cur[i] = best + lp[t, ext[i]]
                alpha = cur
            total = (float(np.logaddexp(alpha[-1], alpha[-2])) if n_states > 1
                     else float(alpha[0]))
            return float(np.exp(total / max(1, len(text))))
        except Exception as exc:
            # تدهورٌ رشيقٌ **نحو الصمت**: ثقةٌ صفريّة ترفضها البوّابة. الارتدادُ إلى
            # الصيغة القديمة كان سيُعيد العمى عن الحذف من الباب الخلفيّ بلا أثرٍ ظاهر.
            logger.warning('[handwriting] ثقةُ السلسلة تعذّرت (%s) — ثقةٌ صفريّة',
                           type(exc).__name__)
            return 0.0

    @staticmethod
    def _ink_bbox(pil_gray, pad: int = 8):
        """صندوق الحبر (أدكن من الخلفية بوضوح) أو None لشريط فارغ."""
        a = np.asarray(pil_gray, dtype=np.float32)
        if a.std() < 1:
            return None
        dark = a < (a.mean() - 1.2 * a.std())
        if dark.sum() < 40:
            return None
        ys, xs = np.where(dark)
        return (max(0, int(xs.min()) - pad), max(0, int(ys.min()) - pad),
                min(pil_gray.width, int(xs.max()) + pad),
                min(pil_gray.height, int(ys.max()) + pad))

    def read_best(self, pil_gray) -> Tuple[Optional[str], float]:
        """يقرأ الشريط الخام ومقصوصَ صندوق-الحبر ويعيد الأوثق — القصّ الضيق يطابق
        توزيع تدريب v5 (تحقق حي: خام 0.79-0.86 ← مقصوص 1.00 على نفس الأرقام)."""
        best = self.read(pil_gray)
        bb = self._ink_bbox(pil_gray)
        if bb:
            alt = self.read(pil_gray.crop(bb))
            # **انحياز القراءة القصيرة**: الثقة متوسّطٌ لكلّ محرف، فقراءةُ محرفٍ واحد
            # تغلب قراءةَ أربعة بحكم البناء لا بحكم الصواب. قياس 2026-07-21 على 250
            # كتاباً: **32 من 44 انبعاثاً خاطئاً** قراءاتُ خانةٍ أو خانتين لأرقامٍ أطول،
            # بثقةٍ تبلغ 0.999 (2386→«4» · 4095→«3» · 22812→«10» · 26247→«3»).
            # فلا يُزيح الأقصرُ الأطولَ بالثقة وحدها.
            if alt[0] and (not best[0]
                           or (len(alt[0]) >= len(best[0]) and alt[1] > best[1])):
                best = alt
        return best
