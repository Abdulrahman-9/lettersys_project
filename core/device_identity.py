# -*- coding: utf-8 -*-
"""
هوية الجهاز المحلية — Device Identity
=====================================

اسم/معرّف خاصّ بكل جهاز، مخزَّن **محلياً** (ملف على قرص الجهاز، خارج قاعدة البيانات
المشتركة وخارج git). يحلّ عيباً جوهرياً: ``NetworkSettings`` سجلٌّ مفرد مشترك في
الـDB، فلو خُزِّن اسم الجهاز فيه لدَاسه آخر جهاز يحفظ إعداداته. أمّا هنا فلكل جهاز
اسمه الثابت الذي لا يمسّه غيره.

المسار الافتراضي: ``BASE_DIR/.device_identity.json`` (يمكن تجاوزه عبر
``settings.DEVICE_IDENTITY_FILE``). آمن الفشل: يسقط إلى اسم المضيف إن تعذّر الملف.

الكاش مبنيٌّ على mtime الملف: يبقى ثابتاً داخل العملية، ويلتقط تلقائياً أيّ تغيير
خارجي (عامل آخر على نفس الجهاز أعاد التسمية، أو تحرير الملف يدوياً).
"""

import json
import logging
import socket
import uuid
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

_cache = None
_cache_key = None   # (str(path), mtime) — يُبطَل الكاش تلقائياً عند تغيّر الملف


def _identity_path() -> Path:
    override = getattr(settings, 'DEVICE_IDENTITY_FILE', None)
    if override:
        return Path(override)
    return Path(settings.BASE_DIR) / '.device_identity.json'


def _hostname() -> str:
    try:
        return socket.gethostname() or 'جهاز'
    except Exception:
        return 'جهاز'


def _mtime(path: Path):
    try:
        return path.stat().st_mtime if path.exists() else None
    except OSError:
        return None


def reset_cache():
    """للاختبارات — يمسح الكاش المحلي فيُعاد تحميل الملف."""
    global _cache, _cache_key
    _cache = None
    _cache_key = None


def _load() -> dict:
    """يقرأ الهوية (ينشئها بقيَم افتراضية عند أوّل مرة). مُكاش حسب mtime."""
    global _cache, _cache_key
    path = _identity_path()
    key = (str(path), _mtime(path))
    if _cache is not None and _cache_key == key:
        return _cache

    data = {}
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding='utf-8')) or {}
    except Exception as e:
        logger.warning('device_identity: تعذّر قراءة %s: %s', path, e)
        data = {}

    changed = False
    if not data.get('uuid'):
        data['uuid'] = uuid.uuid4().hex
        changed = True
    if not (data.get('name') or '').strip():
        data['name'] = _hostname()
        changed = True
    if changed:
        _write(data, path)

    _cache = data
    _cache_key = (str(path), _mtime(path))
    return data


def _write(data: dict, path: Path = None):
    path = path or _identity_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception as e:
        logger.warning('device_identity: تعذّر كتابة %s: %s', path, e)


def get_identity() -> dict:
    """نسخة من قاموس الهوية: {'uuid': ..., 'name': ...}."""
    return dict(_load())


def get_device_name() -> str:
    return (_load().get('name') or '').strip() or _hostname()


def get_device_uuid() -> str:
    return _load().get('uuid')


def set_device_name(name: str) -> str:
    """يضبط اسم هذا الجهاز محلياً ويعيد الاسم المطبَّق (يتجاهل الفارغ)."""
    global _cache, _cache_key
    name = (name or '').strip()[:100]
    if not name:
        return get_device_name()
    data = dict(_load())
    data['name'] = name
    path = _identity_path()
    _write(data, path)
    _cache = data
    _cache_key = (str(path), _mtime(path))
    return name
