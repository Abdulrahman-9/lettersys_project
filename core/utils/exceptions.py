# -*- coding: utf-8 -*-
"""
Custom Exceptions - استثناءات مخصصة موحدة
للتعامل الموحد مع الأخطاء في النظام
"""


class AppException(Exception):
    """
    الاستثناء الأساسي للتطبيق
    Base exception for the application
    """
    def __init__(self, message, code=None, status_code=400):
        self.message = message
        self.code = code or self.__class__.__name__
        self.status_code = status_code
        super().__init__(self.message)


class ValidationError(AppException):
    """
    خطأ في التحقق من البيانات
    Raised when data validation fails
    """
    def __init__(self, message, field=None):
        self.field = field
        super().__init__(message, code='VALIDATION_ERROR', status_code=400)


class PermissionError(AppException):
    """
    خطأ في الصلاحيات
    Raised when user lacks permission
    """
    def __init__(self, message="ليس لديك صلاحية الوصول"):
        super().__init__(message, code='PERMISSION_DENIED', status_code=403)


class NotFoundError(AppException):
    """
    الكائن غير موجود
    Raised when an object is not found
    """
    def __init__(self, message="العنصر المطلوب غير موجود"):
        super().__init__(message, code='NOT_FOUND', status_code=404)


class ConflictError(AppException):
    """
    تضارب في البيانات (مثلاً: رقم كتاب مكرر)
    Raised when there's a conflict in data
    """
    def __init__(self, message="تضارب في البيانات"):
        super().__init__(message, code='CONFLICT', status_code=409)


class ServerError(AppException):
    """
    خطأ في الخادم
    Raised for internal server errors
    """
    def __init__(self, message="حدث خطأ ما في الخادم"):
        super().__init__(message, code='SERVER_ERROR', status_code=500)
