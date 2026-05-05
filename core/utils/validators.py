# -*- coding: utf-8 -*-
"""
Unified Validators - موحد والتحقق من الصحة
مكان موحد لجميع التحققات من البيانات
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from .exceptions import ValidationError
import re


def validate_file_size(file_obj, max_size_mb=50):
    """
    التحقق من حجم الملف
    
    Args:
        file_obj: الملف
        max_size_mb: الحد الأقصى بالميجابايت
    
    Raises:
        ValidationError: إذا تجاوز الحد الأقصى
    """
    max_bytes = max_size_mb * 1024 * 1024
    if file_obj.size > max_bytes:
        raise ValidationError(
            f"حجم الملف ({file_obj.size / (1024*1024):.1f}MB) يتجاوز الحد الأقصى ({max_size_mb}MB)",
            field='file'
        )


def validate_file_type(file_obj, allowed_types):
    """
    التحقق من نوع الملف
    
    Args:
        file_obj: الملف
        allowed_types: قائمة بالأنواع المسموحة (مثل: ['pdf', 'jpg', 'png'])
    
    Raises:
        ValidationError: إذا لم يكن النوع مسموحاً
    """
    file_ext = file_obj.name.split('.')[-1].lower()
    if file_ext not in allowed_types:
        raise ValidationError(
            f"نوع الملف '.{file_ext}' غير مسموح. الأنواع المسموحة: {', '.join(allowed_types)}",
            field='file'
        )


def validate_book_number(book_number):
    """
    التحقق من صيغة رقم الكتاب
    
    Args:
        book_number: رقم الكتاب
    
    Raises:
        ValidationError: إذا كانت الصيغة خاطئة
    """
    if not book_number or len(book_number) > 50:
        raise ValidationError(
            "رقم الكتاب يجب أن يكون بين 1 و 50 حرف",
            field='book_number'
        )
    
    # التحقق من الأحرف المسموحة (أرقام، أحرف، شرطات، مسافات)
    if not re.match(r'^[\w\s\-]{1,50}$', book_number, re.UNICODE):
        raise ValidationError(
            "رقم الكتاب يحتوي على أحرف غير مسموحة",
            field='book_number'
        )


def validate_entity_name(entity_name):
    """
    التحقق من اسم الجهة
    
    Args:
        entity_name: اسم الجهة
    
    Raises:
        ValidationError: إذا كان الاسم غير صالح
    """
    if not entity_name or len(entity_name) > 200:
        raise ValidationError(
            "اسم الجهة يجب أن يكون بين 1 و 200 حرف",
            field='name'
        )
    
    # التحقق من الأحرف (الأحرف العربية والإنجليزية والأرقام والمسافات فقط)
    if not re.match(r'^[\u0600-\u06FF\w\s\-]{1,200}$', entity_name, re.UNICODE):
        raise ValidationError(
            "اسم الجهة يحتوي على أحرف غير مسموحة",
            field='name'
        )


def validate_date_range(start_date, end_date):
    """
    التحقق من نطاق التواريخ (البداية <= النهاية)
    
    Args:
        start_date: تاريخ البداية
        end_date: تاريخ النهاية
    
    Raises:
        ValidationError: إذا كانت البداية بعد النهاية
    """
    if start_date and end_date and start_date > end_date:
        raise ValidationError(
            "تاريخ البداية يجب أن يكون قبل أو مساوياً لتاريخ النهاية"
        )


def validate_required_fields(data, required_fields):
    """
    التحقق من وجود الحقول المطلوبة
    
    Args:
        data: قاموس البيانات
        required_fields: قائمة الحقول المطلوبة
    
    Raises:
        ValidationError: إذا كان أي حقل مطلوب مفقود
    """
    missing = [field for field in required_fields if not data.get(field)]
    if missing:
        raise ValidationError(
            f"الحقول المطلوبة المفقودة: {', '.join(missing)}"
        )
