# -*- coding: utf-8 -*-
"""
Unified Notifications - نظام موحد للإشعارات
Toast notifications, messages, alerts - كل البيانات في مكان واحد
"""

from django.contrib import messages
import logging

logger = logging.getLogger(__name__)


def notify_success(request, message, extra_tags=''):
    """
    إشعار نجاح
    
    Args:
        request: HTTP request
        message: نص الرسالة
        extra_tags: tags إضافية (مثلاً: 'toast', 'persistent')
    """
    tag = f"toast success {extra_tags}".strip()
    messages.success(request, message, extra_tags=tag)
    logger.info(f"Success: {message}")


def notify_error(request, message, extra_tags='', exception=None):
    """
    إشعار خطأ
    
    Args:
        request: HTTP request
        message: نص الرسالة
        extra_tags: tags إضافية
        exception: الاستثناء الأصلي (للتسجيل)
    """
    tag = f"toast error {extra_tags}".strip()
    messages.error(request, message, extra_tags=tag)
    if exception:
        logger.error(f"Error: {message}", exc_info=exception)
    else:
        logger.error(f"Error: {message}")


def notify_warning(request, message, extra_tags=''):
    """
    إشعار تحذير
    
    Args:
        request: HTTP request
        message: نص الرسالة
        extra_tags: tags إضافية
    """
    tag = f"toast warning {extra_tags}".strip()
    messages.warning(request, message, extra_tags=tag)
    logger.warning(f"Warning: {message}")


def notify_info(request, message, extra_tags=''):
    """
    إشعار معلومات
    
    Args:
        request: HTTP request
        message: نص الرسالة
        extra_tags: tags إضافية
    """
    tag = f"toast info {extra_tags}".strip()
    messages.info(request, message, extra_tags=tag)
    logger.info(f"Info: {message}")


def notify_bulk(request, successes=0, failures=0, warnings=0):
    """
    إشعار عملية جماعية (مثل حذف متعدد)
    
    Args:
        request: HTTP request
        successes: عدد العناصر الناجحة
        failures: عدد العناصر الفاشلة
        warnings: عدد التحذيرات
    """
    if successes:
        notify_success(request, f"✓ تم إكمال {successes} عملية بنجاح")
    if failures:
        notify_error(request, f"✗ فشلت {failures} عملية")
    if warnings:
        notify_warning(request, f"⚠ {warnings} تحذير")
