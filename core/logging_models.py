"""
===================================================
Models for Logging System
===================================================
"""

from django.db import models
from django.contrib.auth.models import User


class UserActivityLog(models.Model):
    """سجل أنشطة المستخدمين"""
    
    ACTION_CHOICES = [
        ('CREATE_BOOK', 'إنشاء كتاب'),
        ('EDIT_BOOK', 'تعديل كتاب'),
        ('DELETE_BOOK', 'حذف كتاب'),
        ('EXPORT_DATA', 'تصدير بيانات'),
        ('BACKUP_DATA', 'نسخ احتياطي'),
        ('LOGIN', 'تسجيل دخول'),
        ('LOGOUT', 'تسجيل خروج'),
        ('SEARCH', 'بحث'),
        ('SCANNER', 'استخدام السكانر'),
    ]
    
    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name='المستخدم'
    )
    username_snapshot = models.CharField(
        'اسم المستخدم (snapshot)', max_length=150, blank=True, default='',
        help_text='يُحفظ عند الإنشاء لضمان بقاء سجل التدقيق حتى لو حُذف المستخدم'
    )
    action = models.CharField(max_length=50, choices=ACTION_CHOICES, verbose_name='الإجراء')
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name='الوقت')
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name='عنوان IP')
    user_agent = models.TextField(blank=True, verbose_name='معلومات المتصفح')
    path = models.CharField(max_length=500, blank=True, verbose_name='المسار')
    method = models.CharField(max_length=10, blank=True, verbose_name='الطريقة')
    status_code = models.IntegerField(null=True, blank=True, verbose_name='رمز الحالة')
    metadata = models.JSONField(default=dict, blank=True, verbose_name='بيانات إضافية')
    
    class Meta:
        verbose_name = 'سجل نشاط مستخدم'
        verbose_name_plural = 'سجلات أنشطة المستخدمين'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['-timestamp']),
            models.Index(fields=['user', '-timestamp']),
            models.Index(fields=['action', '-timestamp']),
        ]

    def save(self, *args, **kwargs):
        if not self.pk and self.user_id and not self.username_snapshot:
            self.username_snapshot = self.user.username[:150]
        super().save(*args, **kwargs)

    def __str__(self):
        name = self.user.username if self.user_id and self.user else (self.username_snapshot or 'محذوف')
        return f"{name} - {self.get_action_display()} - {self.timestamp}"


class PerformanceLog(models.Model):
    """سجل الأداء"""
    
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name='الوقت')
    path = models.CharField(max_length=500, verbose_name='المسار')
    method = models.CharField(max_length=10, verbose_name='الطريقة')
    duration_ms = models.FloatField(verbose_name='المدة (ملي ثانية)')
    db_queries = models.IntegerField(verbose_name='عدد استعلامات قاعدة البيانات')
    status_code = models.IntegerField(verbose_name='رمز الحالة')
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='المستخدم')
    
    class Meta:
        verbose_name = 'سجل أداء'
        verbose_name_plural = 'سجلات الأداء'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['-timestamp']),
            models.Index(fields=['-duration_ms']),
            models.Index(fields=['path', '-timestamp']),
        ]
    
    def __str__(self):
        return f"{self.path} - {self.duration_ms}ms - {self.timestamp}"


class ErrorLog(models.Model):
    """سجل الأخطاء"""
    
    SEVERITY_CHOICES = [
        ('INFO', 'معلومة'),
        ('WARNING', 'تحذير'),
        ('ERROR', 'خطأ'),
        ('CRITICAL', 'خطير'),
    ]
    
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name='الوقت')
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, verbose_name='الخطورة')
    error_code = models.CharField(max_length=50, blank=True, verbose_name='رمز الخطأ')
    error_type = models.CharField(max_length=100, verbose_name='نوع الخطأ')
    error_message = models.TextField(verbose_name='رسالة الخطأ')
    stack_trace = models.TextField(blank=True, verbose_name='Stack Trace')
    path = models.CharField(max_length=500, blank=True, verbose_name='المسار')
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='المستخدم')
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name='عنوان IP')
    user_agent = models.TextField(blank=True, verbose_name='معلومات المتصفح')
    metadata = models.JSONField(default=dict, blank=True, verbose_name='بيانات إضافية')
    is_resolved = models.BooleanField(default=False, verbose_name='تم الحل')
    
    class Meta:
        verbose_name = 'سجل خطأ'
        verbose_name_plural = 'سجلات الأخطاء'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['-timestamp']),
            models.Index(fields=['severity', '-timestamp']),
            models.Index(fields=['is_resolved', '-timestamp']),
        ]
    
    def __str__(self):
        return f"{self.severity} - {self.error_type} - {self.timestamp}"


class ClientLog(models.Model):
    """سجلات من العميل (JavaScript)"""
    
    TYPE_CHOICES = [
        ('EVENT', 'حدث'),
        ('ERROR', 'خطأ'),
        ('METRIC', 'قياس'),
    ]
    
    session_id = models.CharField(max_length=100, verbose_name='معرف الجلسة')
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name='الوقت')
    log_type = models.CharField(max_length=20, choices=TYPE_CHOICES, verbose_name='النوع')
    event_type = models.CharField(max_length=100, blank=True, verbose_name='نوع الحدث')
    data = models.JSONField(default=dict, verbose_name='البيانات')
    url = models.CharField(max_length=500, blank=True, verbose_name='الرابط')
    user_agent = models.TextField(blank=True, verbose_name='معلومات المتصفح')
    
    class Meta:
        verbose_name = 'سجل عميل'
        verbose_name_plural = 'سجلات العملاء'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['-timestamp']),
            models.Index(fields=['session_id', '-timestamp']),
            models.Index(fields=['log_type', '-timestamp']),
        ]
    
    def __str__(self):
        return f"{self.log_type} - {self.event_type} - {self.timestamp}"
