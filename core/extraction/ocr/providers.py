# -*- coding: utf-8 -*-
"""
core.extraction.ocr.providers
===============================
OCR provider factory — EasyOCR (offline) and Azure Vision (online).
"""
import io
import ipaddress
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

import cv2
import numpy as np
import requests

from core.extraction.ocr.service import OCRService

logger = logging.getLogger('lettersys')


def _validate_azure_endpoint(endpoint: str) -> str:
    """التحقق من أن endpoint يشير فقط إلى Azure Cognitive Services (حماية SSRF)"""
    parsed = urlparse(endpoint)
    if not parsed.scheme in ('http', 'https'):
        raise ValueError("Azure endpoint must use http or https scheme")
    hostname = parsed.hostname or ''
    # منع الـ private IPs
    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            raise ValueError(f"Private/loopback IP not allowed in Azure endpoint: {hostname}")
    except ValueError as exc:
        if 'not allowed' in str(exc):
            raise
    # التحقق من النطاق المسموح به
    allowed_suffixes = ('.cognitiveservices.azure.com', '.api.cognitive.microsoft.com')
    if not any(hostname.endswith(s) for s in allowed_suffixes):
        raise ValueError(f"Azure endpoint hostname must end with one of {allowed_suffixes}, got: {hostname}")
    return endpoint


class BaseOCRProvider:
    name = 'base'

    def extract(self, image_path_or_bytes: Any) -> Dict[str, Any]:
        raise NotImplementedError


class EasyOCROfflineProvider(BaseOCRProvider):
    name = 'easyocr'

    def __init__(self):
        self._ocr = OCRService()

    def extract(self, image_path_or_bytes: Any) -> Dict[str, Any]:
        start = time.time()
        data = self._ocr.extract_text(image_path_or_bytes, detail=True)
        # Normalize keys
        result = {
            'raw_text': data.get('raw_text', ''),
            'avg_confidence': float(data.get('avg_confidence', data.get('confidence', 0.0) or 0.0)),
            'details': data.get('details'),
            'num_lines': data.get('num_lines', 0),
            'processing_time': time.time() - start,
        }
        return result


class AzureOCRProvider(BaseOCRProvider):
    """
    Azure Computer Vision Read API (v3.2)
    Requires: endpoint like https://<resource>.cognitiveservices.azure.com
              api_key string
    """
    name = 'azure'

    def __init__(self, endpoint: str, api_key: str, timeout: int = 30):
        self.endpoint = _validate_azure_endpoint(endpoint).rstrip('/')
        self.api_key = api_key
        self.timeout = timeout

    def _bytes_from_input(self, image_path_or_bytes: Any) -> bytes:
        if isinstance(image_path_or_bytes, (str, Path)):
            with open(str(image_path_or_bytes), 'rb') as f:
                return f.read()
        if hasattr(image_path_or_bytes, 'read'):
            return image_path_or_bytes.read()
        if isinstance(image_path_or_bytes, (bytes, bytearray)):
            return bytes(image_path_or_bytes)
        # Assume numpy image
        if isinstance(image_path_or_bytes, np.ndarray):
            ok, buf = cv2.imencode('.png', image_path_or_bytes)
            if not ok:
                raise ValueError('Failed to encode image for Azure OCR')
            return buf.tobytes()
        raise ValueError('Unsupported image input for Azure OCR')

    def extract(self, image_path_or_bytes: Any) -> Dict[str, Any]:
        start = time.time()
        image_bytes = self._bytes_from_input(image_path_or_bytes)

        analyze_url = f"{self.endpoint}/vision/v3.2/read/analyze"
        headers = {
            'Ocp-Apim-Subscription-Key': self.api_key,
            'Content-Type': 'application/octet-stream'
        }

        r = requests.post(analyze_url, headers=headers, data=image_bytes, timeout=self.timeout)
        if r.status_code not in (200, 202):
            logger.error(f"[AzureOCR] Analyze request failed: {r.status_code} {r.text}")
            return {'raw_text': '', 'avg_confidence': 0.0, 'details': None, 'num_lines': 0, 'processing_time': time.time() - start}

        op_location = r.headers.get('Operation-Location')
        if not op_location:
            logger.error("[AzureOCR] Missing Operation-Location header")
            return {'raw_text': '', 'avg_confidence': 0.0, 'details': None, 'num_lines': 0, 'processing_time': time.time() - start}

        # Poll for result — exponential backoff: 1s → 1.5s → 2.25s → … max 5s
        poll_interval = 1.0
        max_wait = self.timeout  # نفس timeout الكلي للـ POST
        elapsed_poll = 0.0
        attempt = 0
        while elapsed_poll < max_wait:
            time.sleep(poll_interval)
            elapsed_poll += poll_interval
            attempt += 1
            try:
                pr = requests.get(
                    op_location,
                    headers={'Ocp-Apim-Subscription-Key': self.api_key},
                    timeout=min(self.timeout, 10),
                )
            except requests.RequestException as req_exc:
                logger.warning('[AzureOCR] Poll request error (attempt %d): %s', attempt, req_exc)
                poll_interval = min(poll_interval * 1.5, 5.0)
                continue

            if pr.status_code != 200:
                poll_interval = min(poll_interval * 1.5, 5.0)
                continue

            data = pr.json()
            status = data.get('status') or data.get('statusCode')
            if status == 'succeeded':
                lines = []
                confidences = []
                for read_result in (data.get('analyzeResult') or {}).get('readResults', []):
                    for line in read_result.get('lines', []):
                        lines.append(line.get('text', ''))
                        conf = line.get('appearance', {}).get('style', {}).get('confidence')
                        if conf is None:
                            conf = 1.0
                        confidences.append(float(conf))
                raw_text = '\n'.join(lines)
                avg_conf = float(np.mean(confidences)) if confidences else (1.0 if lines else 0.0)
                logger.info('[AzureOCR] Succeeded after %d polls, %d lines', attempt, len(lines))
                return {
                    'raw_text': raw_text,
                    'avg_confidence': avg_conf,
                    'details': None,
                    'num_lines': len(lines),
                    'processing_time': time.time() - start,
                }
            elif status in ('failed', 'error'):
                logger.error('[AzureOCR] Read operation failed: %s', data)
                break
            # 'running' or 'notStarted' → زيادة الفترة تدريجياً
            poll_interval = min(poll_interval * 1.5, 5.0)

        logger.warning('[AzureOCR] Exhausted polling budget (%ds)', max_wait)
        return {'raw_text': '', 'avg_confidence': 0.0, 'details': None, 'num_lines': 0, 'processing_time': time.time() - start}


class TesseractOCRProvider(BaseOCRProvider):
    """
    محرّك OCR محلّي خفيف عبر Tesseract (pytesseract) — أسرع وأخفّ من EasyOCR (بلا PyTorch).

    يقرأ إعداده من Django settings (كلّها اختيارية بقيم افتراضية معقولة):
      TESSERACT_CMD          مسار tesseract.exe — إن فارغ يُكتشف تلقائياً.
      TESSERACT_TESSDATA_DIR مجلّد ملفّات اللغة (*.traineddata) — يُمرَّر عبر TESSDATA_PREFIX.
      TESSERACT_LANG         اللغات (افتراضي 'ara+eng' — العربي وحده يُفسد الأرقام/الإنجليزي).
      TESSERACT_PSM          وضع تقسيم الصفحة (افتراضي '3' = تلقائي).

    `extract()` يستخدم تمريرة واحدة `image_to_data` فيستخرج النص (مُعاد البناء سطراً سطراً
    بترتيب RTL صحيح) ومتوسّط الثقة معاً — موفّراً للزمن على الأجهزة المحدودة.
    """
    name = 'tesseract'

    # مسارات شائعة على ويندوز عند غياب TESSERACT_CMD (NAPS2 يضمّ Tesseract أصلاً).
    _CMD_CANDIDATES = (
        r"C:\Program Files\NAPS2\lib\_win64\tesseract.exe",
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    )

    def __init__(self):
        from django.conf import settings as dj
        import pytesseract

        self._pytesseract = pytesseract
        self.cmd = getattr(dj, 'TESSERACT_CMD', '') or self._autodetect_cmd()
        self.tessdata_dir = getattr(dj, 'TESSERACT_TESSDATA_DIR', '') or ''
        self.lang = getattr(dj, 'TESSERACT_LANG', 'ara+eng') or 'ara+eng'
        self.psm = str(getattr(dj, 'TESSERACT_PSM', '3') or '3')
        # تصعيد تكيّفي: عند ثقة < العتبة يُجرَّب تحويل ثنائي (adaptive) ويُحتفَظ بالأعلى.
        # 0 = تعطيل. مُثبَت على عيّنة قاعدة البيانات (وسيط +6 عند ضعف الثقة).
        self.adaptive_threshold = float(getattr(dj, 'TESSERACT_ADAPTIVE_THRESHOLD', 0.75) or 0.0)

        if self.cmd:
            pytesseract.pytesseract.tesseract_cmd = self.cmd
        if self.tessdata_dir:
            # متغيّر بيئة أرصن من --tessdata-dir (يتعامل مع المسافات بلا مشاكل اقتباس).
            os.environ['TESSDATA_PREFIX'] = self.tessdata_dir

    @classmethod
    def _autodetect_cmd(cls) -> str:
        for candidate in cls._CMD_CANDIDATES:
            if os.path.exists(candidate):
                return candidate
        return 'tesseract'  # افتراض وجوده في PATH

    def _to_pil(self, image_path_or_bytes: Any):
        from PIL import Image
        if isinstance(image_path_or_bytes, (str, Path)):
            return Image.open(str(image_path_or_bytes))
        if hasattr(image_path_or_bytes, 'read'):
            return Image.open(io.BytesIO(image_path_or_bytes.read()))
        if isinstance(image_path_or_bytes, (bytes, bytearray)):
            return Image.open(io.BytesIO(bytes(image_path_or_bytes)))
        if isinstance(image_path_or_bytes, np.ndarray):
            arr = image_path_or_bytes
            if arr.ndim == 3 and arr.shape[2] == 3:  # cv2 BGR → RGB
                arr = cv2.cvtColor(arr, cv2.COLOR_BGR2RGB)
            return Image.fromarray(arr)
        raise ValueError('Unsupported image input for Tesseract OCR')

    def _run_tesseract(self, pil_img) -> tuple:
        """تمريرة OCR واحدة → (raw_text, avg_conf 0-1, num_lines)."""
        data = self._pytesseract.image_to_data(
            pil_img, lang=self.lang, config=f'--psm {self.psm}',
            output_type=self._pytesseract.Output.DICT,
        )
        # إعادة بناء النص: تجميع الكلمات حسب (block, par, line) ثم سطر لكل مجموعة.
        lines: Dict[tuple, list] = {}
        confidences = []
        for i in range(len(data['text'])):
            word = (data['text'][i] or '').strip()
            if not word:
                continue
            key = (data['block_num'][i], data['par_num'][i], data['line_num'][i])
            lines.setdefault(key, []).append(word)
            conf = float(data['conf'][i])
            if conf >= 0:  # ‑1 يعني «لا نص» — يُستثنى من المتوسّط
                confidences.append(conf)
        raw_text = '\n'.join(' '.join(words) for _, words in sorted(lines.items()))
        avg_conf = (sum(confidences) / len(confidences) / 100.0) if confidences else 0.0
        return raw_text, avg_conf, len(lines)

    def extract(self, image_path_or_bytes: Any) -> Dict[str, Any]:
        start = time.time()
        img = self._to_pil(image_path_or_bytes)
        raw_text, avg_conf, num_lines = self._run_tesseract(img)

        # تصعيد تكيّفي: عند ثقة منخفضة جرّب نسخة ثنائية (adaptive) واحتفظ بالأعلى ثقةً.
        # adaptive يرفع المستند النموذجي لكنه قد يدمّر شواذّ — «احتفظ بالأعلى» يلتقط
        # المكسب ويحتمي من الذيل الكارثي (مُثبَت على عيّنة قاعدة البيانات).
        if avg_conf < self.adaptive_threshold:
            try:
                from PIL import Image
                gray = np.array(img.convert('L'))
                binary = cv2.adaptiveThreshold(
                    gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
                b_text, b_conf, b_lines = self._run_tesseract(Image.fromarray(binary))
                if b_conf > avg_conf:
                    raw_text, avg_conf, num_lines = b_text, b_conf, b_lines
                    logger.info('[tesseract] adaptive escalation improved conf → %.2f', b_conf)
            except Exception as exc:  # noqa: BLE001 — التصعيد تحسين اختياري لا يُفشل OCR
                logger.warning('[tesseract] adaptive escalation failed: %s', exc)

        return {
            'raw_text': raw_text,
            'avg_confidence': avg_conf,
            'details': None,
            'num_lines': num_lines,
            'processing_time': time.time() - start,
        }


def build_offline_provider_from_settings(settings: Optional[Dict[str, str]] = None) -> BaseOCRProvider:
    """
    يختار محرّك OCR المحلّي حسب Django setting `AI_OFFLINE_ENGINE`:
      'tesseract' (افتراضي) → TesseractOCRProvider (خفيف/سريع)
      'easyocr'             → EasyOCROfflineProvider (PyTorch، احتياطي)
    """
    from django.conf import settings as dj
    engine = str(getattr(dj, 'AI_OFFLINE_ENGINE', 'tesseract') or 'tesseract').lower()
    if engine == 'easyocr':
        return EasyOCROfflineProvider()
    return TesseractOCRProvider()


def build_online_provider_from_settings(settings: Dict[str, str]) -> Optional[BaseOCRProvider]:
    provider = (settings or {}).get('AI_PROVIDER', 'offline').lower()
    if provider == 'azure':
        endpoint = settings.get('AI_AZURE_ENDPOINT')
        key = settings.get('AI_AZURE_KEY')
        if endpoint and key:
            return AzureOCRProvider(endpoint=endpoint, api_key=key)
        logger.warning('[AI] Azure provider selected but endpoint/key missing')
        return None
    return None
