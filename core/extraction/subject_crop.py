"""قصاصةُ الموضوع — «أين الموضوع؟» حين يصمت الاستخراج (قرارُ المالك 2026‑09‑11).

الصمتُ في حقل الموضوع قرارٌ مقيس (`pipeline.TITLE_DIRECT_FILL_SOURCES`): لا يُملأ
إلّا من علامةٍ صريحة، وما عداه اقتراحٌ أو فراغ. هذه الوحدةُ تُعطي الفراغَ **باباً**
لا تخميناً:

1. **اقتراحُ الموضع** (`propose_box`): صندوقٌ متعلَّمٌ من الجهة المُصدِرة إن كان لها
   ≥ ``MIN_SAMPLES`` قصّاتٍ مؤكَّدة (الوسيطُ لا المتوسّط — قصّةٌ شاذّة لا تجرّ الباقي)،
   وإلّا حزامُ البنية من هندسة TSV (بين سطر «إلى/» وسطر «تحيّة»)، وإلّا حزامٌ افتراضيّ.
2. **القراءةُ من الصندوق** (`read_box`): OCR القصاصةِ وحدَها مكبَّرةً، ثمّ حرّاسُ
   الخردة أنفسُهم التي تحرس الحقل — قيمةٌ لا تجتازها لا تبلغ الكاتب.
3. **التعلّمُ من المؤكَّد فقط** (`record_sample`): يُحفظ الصندوقُ عيّنةً للجهة حين
   يقبل الكاتبُ نصَّه **بلا تعديل**. تعديلُ النصّ لا يُعلّم — قد يكون الصندوقُ خطأً.
4. **البوّابةُ الخضراء** (`learned_fill`): جهةٌ بلغت العتبةَ ⟵ يُقرأ صندوقُها **قبل**
   مسح النصّ، وإن اجتاز الحرّاسَ مُلئ الحقلُ مباشرةً بمصدر ``learned_box`` وثقةٍ
   عالية — كالتاريخ.

**المخزن**: ملفُّ JSON في ``var/`` على نمط ``EntityProfileStore`` (بلا هجرة الآن)؛
يُهاجَر إلى جدولٍ في دفعة 0079 بعد T‑0 — انظر ``docs/LIFECYCLE_DECISIONS``.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import statistics
import threading
from typing import Dict, List, Optional

from .artifacts import artifact_path

logger = logging.getLogger(__name__)

MIN_SAMPLES = 3
LEARNED_CONFIDENCE = 0.92
MAX_SAMPLES_PER_ENTITY = 40
_LOCK = threading.Lock()


def store_path() -> str:
    return artifact_path('var', 'subject_boxes.json', setting='SUBJECT_BOXES_PATH')


# ── المخزن ────────────────────────────────────────────────────────────────
def _load() -> Dict:
    path = store_path()
    if os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as fh:
                return json.load(fh) or {}
        except Exception:
            logger.warning('subject_boxes.json تالف — يُبدأ من فراغ')
    return {}


def _save(data: Dict) -> None:
    path = store_path()
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _clamp(v) -> float:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if v < 0 else (1.0 if v > 1 else v)


def normalise_box(box) -> Optional[Dict[str, float]]:
    """صندوقٌ بكسورٍ 0–1 ``{x, y, w, h}``؛ أصغرُ من 2% في بُعدٍ = نقرةٌ طائشة ⟵ None."""
    if not isinstance(box, dict):
        return None
    out = {k: _clamp(box.get(k)) for k in ('x', 'y', 'w', 'h')}
    if out['w'] < 0.02 or out['h'] < 0.01:
        return None
    out['w'] = min(out['w'], 1.0 - out['x'])
    out['h'] = min(out['h'], 1.0 - out['y'])
    return {k: round(v, 4) for k, v in out.items()}


def samples_of(entity_id) -> List[Dict]:
    if not entity_id:
        return []
    return list(_load().get(str(entity_id), {}).get('samples', []))


def learned_box(entity_id) -> Optional[Dict[str, float]]:
    """الوسيطُ لكلّ بُعدٍ من عيّنات الجهة إن بلغت العتبة، وإلّا None."""
    samples = samples_of(entity_id)
    if len(samples) < MIN_SAMPLES:
        return None
    box = {k: round(statistics.median(s['box'][k] for s in samples), 4)
           for k in ('x', 'y', 'w', 'h')}
    return normalise_box(box)


def record_sample(entity_id, box, text, *, page=1, by=None) -> Optional[Dict]:
    """عيّنةٌ **مؤكَّدة** — يُستدعى فقط حين يقبل الكاتبُ نصَّ الصندوق بلا تعديل."""
    box = normalise_box(box)
    text = (text or '').strip()
    if not entity_id or box is None or not text:
        return None
    with _LOCK:
        data = _load()
        bucket = data.setdefault(str(entity_id), {'samples': []})
        bucket['samples'].append({
            'box': box, 'page': int(page or 1), 'text': text[:120],
            'by': getattr(by, 'username', '') if by else '',
        })
        bucket['samples'] = bucket['samples'][-MAX_SAMPLES_PER_ENTITY:]
        _save(data)
    return box


# ── الاقتراح ──────────────────────────────────────────────────────────────
_RECIP_RE = re.compile(r'^[\W\d]{0,3}\s*(?:إلى|الى|السادة|السيد)\b|^\s*to\b', re.I)
_GREET_RE = re.compile(r'تحي[ةه]|سلام|dear|greeting', re.I)
DEFAULT_BAND = {'x': 0.08, 'y': 0.22, 'w': 0.84, 'h': 0.14}


def structural_box(lines_geometry: List[Dict]) -> Optional[Dict[str, float]]:
    """حزامٌ بين سطر المُرسَل إليه وسطر التحيّة من هندسة الأسطر (كسورٌ 0–1).

    ``lines_geometry``: قائمةُ ``{text, x, y, w, h}`` بكسور. يُعيد None إن غابت
    المرساتان — فالحزامُ المفتوح يخطف الهوامشَ (قياسُ 2026‑08‑17: 0/8).
    """
    if not lines_geometry:
        return None
    ri = next((i for i, l in enumerate(lines_geometry) if _RECIP_RE.match(l.get('text', ''))), -1)
    if ri < 0:
        return None
    gi = next((i for i in range(ri + 1, min(ri + 13, len(lines_geometry)))
               if _GREET_RE.search(lines_geometry[i].get('text', ''))), -1)
    if gi < 0 or gi == ri + 1:
        return None
    inner = lines_geometry[ri + 1:gi]
    y0 = min(l['y'] for l in inner)
    y1 = max(l['y'] + l['h'] for l in inner)
    return normalise_box({'x': 0.06, 'y': max(0.0, y0 - 0.01), 'w': 0.88, 'h': (y1 - y0) + 0.02})


def propose_box(entity_id=None, lines_geometry=None) -> Dict:
    """``{box, source}``: ``learned`` ⟵ ``structural`` ⟵ ``default``."""
    box = learned_box(entity_id)
    if box:
        return {'box': box, 'source': 'learned', 'samples': len(samples_of(entity_id))}
    box = structural_box(lines_geometry or [])
    if box:
        return {'box': box, 'source': 'structural', 'samples': 0}
    return {'box': dict(DEFAULT_BAND), 'source': 'default', 'samples': 0}


# ── القراءة والتنظيف ───────────────────────────────────────────────────────
def crop_image(img, box: Dict[str, float], scale: float = 2.0):
    """قصُّ الصندوق من صورة PIL وتكبيرُه — OCR سطرٍ واحدٍ مكبَّرٍ أدقُّ من صفحةٍ كاملة."""
    W, H = img.size
    x0 = int(box['x'] * W); y0 = int(box['y'] * H)
    x1 = int((box['x'] + box['w']) * W); y1 = int((box['y'] + box['h']) * H)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None
    region = img.crop((x0, y0, x1, y1))
    if scale and scale != 1:
        region = region.resize((int(region.width * scale), int(region.height * scale)))
    return region


def clean_subject(raw: str) -> Optional[str]:
    """حرّاسُ الحقل أنفسُها: علاماتٌ خفيّة، ذيلُ خردة، خردةٌ محضة، كلماتٌ قليلة."""
    from .matchers.pattern import PatternMatcher
    text = (raw or '').strip()
    if not text:
        return None
    # أسقِط تسميةً باديةً («الموضوع:» / «م/») إن قُصّت مع السطر
    text = re.sub(r'^\s*(?:الموضوع|بخصوص|بشأن|م)\s*[:/\-.,،]?\s*', '', text)
    matcher = PatternMatcher()
    cleaned = matcher.extract_title_keywords('الموضوع: ' + text, num_words=12)
    return cleaned or None


def read_box(img, box: Dict[str, float], *, ocr=None) -> Dict:
    """يُعيد ``{text, raw, accepted}``؛ ``ocr(image) -> str`` قابلٌ للحقن في الاختبارات."""
    box = normalise_box(box)
    if box is None:
        return {'text': '', 'raw': '', 'accepted': False, 'reason': 'صندوقٌ أصغرُ من أن يُقرأ'}
    region = crop_image(img, box)
    if region is None:
        return {'text': '', 'raw': '', 'accepted': False, 'reason': 'صندوقٌ أصغرُ من أن يُقرأ'}
    if ocr is None:
        ocr = _default_ocr
    try:
        raw = ocr(region) or ''
    except Exception as exc:  # pragma: no cover - بيئة OCR
        logger.warning('subject box OCR failed: %s', exc)
        raw = ''
    text = clean_subject(raw)
    return {'text': text or '', 'raw': raw.strip(), 'accepted': bool(text),
            'reason': '' if text else 'القراءةُ لم تجتز حرّاسَ الخردة'}


def _default_ocr(region) -> str:
    """Tesseract عربيّ+إنجليزيّ على سطرٍ واحدٍ (psm 7)؛ EasyOCR احتياطاً إن غاب."""
    try:
        import pytesseract
        return pytesseract.image_to_string(region, lang='ara+eng', config='--psm 7')
    except Exception:
        pass
    try:
        from .ocr.service import extract_text_simple
        buf = io.BytesIO(); region.save(buf, format='PNG')
        return extract_text_simple(buf.getvalue())
    except Exception:
        return ''


# ── البوّابة الخضراء ───────────────────────────────────────────────────────
def learned_fill(img, entity_id, *, ocr=None) -> Optional[Dict]:
    """إن كان للجهة صندوقٌ متعلَّم وقُرئ منه موضوعٌ يجتاز الحرّاس ⟵ ``{text, box}``."""
    box = learned_box(entity_id)
    if box is None or img is None:
        return None
    out = read_box(img, box, ocr=ocr)
    if not out['accepted']:
        return None
    return {'text': out['text'], 'box': box, 'confidence': LEARNED_CONFIDENCE}


# ── الهندسة: أين يجلس الموضوع في الصفحة؟ ────────────────────────────────────
# إضافةٌ للاقتراح لا للاستخراج النصّيّ (لا تراجعَ: مسارُ الحقل لم يُمَسّ). خمسُ شواهدَ
# تُجمع في درجةٍ واحدة لكلّ سطرٍ داخل الحزام، ويُعرض الأعلى أوّلاً وبعده البدائل
# للنقر:
#   ١ مراسٍ: تحت آخر حقلِ رأسٍ (العدد/التاريخ/إلى) وفوق التحيّة أو أوّل سطرِ متن.
#   ٢ خطٌّ سفليّ: صفٌّ داكنٌ طويلٌ مباشرةً تحت السطر — الموضوعُ يُسطَّر كثيراً.
#   ٣ عرضٌ: الموضوعُ أقصرُ من سطر المتن (كامل العرض) وأطولُ من كلمة.
#   ٤ علامةٌ جزئيّة: «م» أو «/» في أوّل السطر وإن شُوِّهت البقيّة.
#   ٥ ذاكرةُ الجهة: إزاحةٌ نسبيّة عن سطر «إلى/» أصلبُ من الصندوق المطلق حين تنزلق الصفحة.
_FIELD_RE = re.compile(r'^[\W\d_]{0,6}(?:العدد|الرقم|التاريخ|التأريخ|date|ref|no\b)', re.I)
_BODY_RE = re.compile(r'^\s*(?:نود|نرجو|يرجى|إشارة|اشارة|الحاقا|إلحاقا|تحية|نرافق|بالاشارة|بالإشارة|أعلاه|اعلاه|we |please|kindly|with reference|reference is|this letter)', re.I)
_MARK_HINT_RE = re.compile(r'^\s*[اأآ]?م\s*[/:\-.,،]|^\s*/|الموضوع|بشأن|بخصوص|(?i:subj)')


def lines_from_tsv(tsv, width: int, height: int) -> List[Dict]:
    """أسطرُ Tesseract (block/par/line) ⟵ ``{text, x, y, w, h}`` بكسور، مرتّبةً من الأعلى."""
    try:
        rows = tsv.to_dict('records') if hasattr(tsv, 'to_dict') else list(tsv)
    except Exception:
        return []
    groups: Dict[tuple, List[Dict]] = {}
    for r in rows:
        try:
            if int(r.get('conf', -1)) < 0:
                continue
        except (TypeError, ValueError):
            continue
        word = str(r.get('text') or '').strip()
        if not word:
            continue
        key = (r.get('block_num'), r.get('par_num'), r.get('line_num'))
        groups.setdefault(key, []).append(r)
    out = []
    for words in groups.values():
        x0 = min(int(w['left']) for w in words); y0 = min(int(w['top']) for w in words)
        x1 = max(int(w['left']) + int(w['width']) for w in words)
        y1 = max(int(w['top']) + int(w['height']) for w in words)
        text = ' '.join(str(w['text']) for w in sorted(words, key=lambda w: -int(w['left'])))
        out.append({'text': text, 'x': x0 / width, 'y': y0 / height,
                    'w': (x1 - x0) / width, 'h': (y1 - y0) / height})
    return sorted(out, key=lambda l: l['y'])


def underline_rows(img, min_run: float = 0.25) -> List[float]:
    """صفوفُ الصورة (كسور y) التي فيها خطٌّ أفقيٌّ داكنٌ متّصلٌ بطول ≥ ``min_run`` من العرض."""
    try:
        import numpy as np
        g = img if img.mode == 'L' else img.convert('L')
        if g.width > 1400:
            g = g.resize((1400, int(g.height * 1400 / g.width)))
        a = np.asarray(g) < 128
        W = a.shape[1]
        rows = []
        for y in range(a.shape[0]):
            row = a[y]
            if row.sum() < W * min_run:
                continue
            # أطولُ امتدادٍ متّصل
            best = run = 0
            for v in row:
                run = run + 1 if v else 0
                best = max(best, run)
            if best >= W * min_run:
                rows.append(y / a.shape[0])
        return rows
    except Exception:
        return []


def _anchors(lines: List[Dict]) -> Dict[str, Optional[float]]:
    top = None; bottom = None; recip = None
    for l in lines:
        t = l.get('text', '')
        if _RECIP_RE.match(t):
            recip = l['y'] if recip is None else recip
            top = max(top or 0.0, l['y'] + l['h'])
        elif _FIELD_RE.match(t) and l['y'] < 0.45:
            top = max(top or 0.0, l['y'] + l['h'])
        elif (_GREET_RE.search(t) or _BODY_RE.match(t)) and (top is None or l['y'] > top):
            bottom = l['y'] if bottom is None else min(bottom, l['y'])
    return {'top': top, 'bottom': bottom, 'recip_y': recip}


def score_lines(lines: List[Dict], img=None) -> List[Dict]:
    """كلُّ سطرٍ في الحزام بدرجةٍ؛ الأعلى أوّلاً. يُعيد ``[{box, text, score, why}]``."""
    if not lines:
        return []
    a = _anchors(lines)
    top = a['top'] if a['top'] is not None else 0.10
    bottom = a['bottom'] if a['bottom'] is not None else min(0.60, top + 0.35)
    ul = underline_rows(img) if img is not None else []
    out = []
    for l in lines:
        t = l.get('text', '')
        if not (top - 0.005 <= l['y'] <= bottom):
            continue
        if _RECIP_RE.match(t) or _FIELD_RE.match(t) or _GREET_RE.search(t):
            continue
        ar_words = len(re.findall(r'[ء-ي]{2,}', t)); en_words = len(re.findall(r'[A-Za-z]{3,}', t))
        if ar_words + en_words < 1:
            continue
        score = 0.0; why = []
        if any(l['y'] + l['h'] <= r <= l['y'] + l['h'] + 0.012 for r in ul):
            score += 2.0; why.append('underline')
        if 0.15 <= l['w'] <= 0.80 and (ar_words + en_words) >= 2:
            score += 1.0; why.append('width')
        if _MARK_HINT_RE.search(t):
            score += 1.5; why.append('marker')
        if l['w'] > 0.85:
            score -= 1.0; why.append('full-width')
        if ar_words + en_words == 1 and l['w'] < 0.12:
            score -= 0.5
        # القربُ من الرأس: أوّلُ سطرٍ جوهريّ بعد الحقول أرجحُ من الأبعد
        score += max(0.0, 0.6 - 3.0 * (l['y'] - top))
        pad = 0.006
        box = normalise_box({'x': max(0.0, l['x'] - 0.02), 'y': l['y'] - pad,
                             'w': l['w'] + 0.04, 'h': l['h'] + 2 * pad})
        if box:
            out.append({'box': box, 'text': t[:80], 'score': round(score, 2), 'why': why})
    out.sort(key=lambda c: -c['score'])
    return out[:4]


def learned_relative(entity_id, lines: List[Dict]) -> Optional[Dict[str, float]]:
    """إزاحةٌ نسبيّة: إن حُفظت العيّناتُ مع ``rel_dy`` (فرقُ y عن سطر «إلى/») ووُجد
    السطرُ في هذه الصفحة ⟵ صندوقٌ يتبع الانزلاق؛ وإلّا الصندوقُ المطلق."""
    samples = [s for s in samples_of(entity_id) if s.get('rel_dy') is not None]
    if len(samples) < MIN_SAMPLES:
        return None
    a = _anchors(lines)
    if a['recip_y'] is None:
        return None
    dy = statistics.median(s['rel_dy'] for s in samples)
    base = learned_box(entity_id) or DEFAULT_BAND
    return normalise_box({'x': base['x'], 'y': a['recip_y'] + dy, 'w': base['w'], 'h': base['h']})


def propose(entity_id=None, lines=None, img=None) -> Dict:
    """``{box, source, candidates, samples}``: ``learned-relative`` ⟵ ``learned`` ⟵
    أعلى مرشّحٍ مُدرَّج ⟵ حزامُ البنية ⟵ الافتراضيّ. البدائلُ تُعرض دائماً للنقر."""
    lines = lines or []
    cands = score_lines(lines, img)
    n = len(samples_of(entity_id))
    rel = learned_relative(entity_id, lines)
    if rel:
        return {'box': rel, 'source': 'learned-relative', 'candidates': cands, 'samples': n}
    box = learned_box(entity_id)
    if box:
        return {'box': box, 'source': 'learned', 'candidates': cands, 'samples': n}
    if cands and cands[0]['score'] >= 1.0:
        return {'box': cands[0]['box'], 'source': 'scored', 'candidates': cands, 'samples': n}
    box = structural_box(lines)
    if box:
        return {'box': box, 'source': 'structural', 'candidates': cands, 'samples': n}
    return {'box': dict(DEFAULT_BAND), 'source': 'default', 'candidates': cands, 'samples': n}


def record_sample_with_anchor(entity_id, box, text, lines=None, *, page=1, by=None):
    """كـ``record_sample`` مع حفظ الإزاحة عن سطر «إلى/» إن وُجد (للاقتراح النسبيّ)."""
    box = normalise_box(box)
    if box is None:
        return None
    rel_dy = None
    a = _anchors(lines or [])
    if a['recip_y'] is not None:
        rel_dy = round(box['y'] - a['recip_y'], 4)
    saved = record_sample(entity_id, box, text, page=page, by=by)
    if saved is not None and rel_dy is not None:
        with _LOCK:
            data = _load()
            samples = data.get(str(entity_id), {}).get('samples', [])
            if samples:
                samples[-1]['rel_dy'] = rel_dy
                _save(data)
    return saved
