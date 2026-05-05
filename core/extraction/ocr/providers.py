# -*- coding: utf-8 -*-
"""
core.extraction.ocr.providers
===============================
OCR provider factory — EasyOCR (offline) and Azure Vision (online).
"""
import base64
import io
import ipaddress
import logging
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

        # Poll for result
        poll_interval = 0.8
        max_tries = int(30 / poll_interval)
        for _ in range(max_tries):
            time.sleep(poll_interval)
            pr = requests.get(op_location, headers={'Ocp-Apim-Subscription-Key': self.api_key}, timeout=self.timeout)
            if pr.status_code != 200:
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
                            conf = 1.0  # Azure often omits per-line confidence; assume high if detected
                        confidences.append(float(conf))
                raw_text = '\n'.join(lines)
                avg_conf = float(np.mean(confidences)) if confidences else (1.0 if lines else 0.0)
                return {
                    'raw_text': raw_text,
                    'avg_confidence': avg_conf,
                    'details': None,
                    'num_lines': len(lines),
                    'processing_time': time.time() - start,
                }
            elif status in ('failed', 'error'):
                logger.error(f"[AzureOCR] Read operation failed: {data}")
                break

        return {'raw_text': '', 'avg_confidence': 0.0, 'details': None, 'num_lines': 0, 'processing_time': time.time() - start}


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
