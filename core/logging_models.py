"""
===================================================
Models for Logging System
===================================================
"""

from django.db import models
from django.contrib.auth.models import User


class UserActivityLog(models.Model):
    """سجلُّ حركات المستخدمين — **مَن رأى ومَن حمّل ومَن صدّر**.

    طلبُ المالك: «من رأى، من شاهد، من استلم، من فرّق، من عدّل، من حذف — كلّ
    الحركات يجب أن تُحفظ في سجلّ الحركات للأدمن الرئيسيّ لكلّ قسم فضلاً عن
    السوبر أدمن».

    **وتقسيمُ العمل مع ``BookHistory`` مقصود:** أفعالُ العمل (تعديلٌ وتفريقٌ
    وعهدةٌ وقيدٌ وحذف) تبقى هناك لأنّها **تُعرض لكلّ من يرى الكتاب**؛ ووضعُ
    القراءة معها يجعل كلَّ زميلٍ يرى مَن قرأ ماذا — تسريبُ أداة المراقبة لغير
    أصحابها. فالقراءةُ هنا، وبوّابتُها رئيسُ القسم والسوبر أدمن حصراً.

    **والطيُّ اليوميّ هو ما يجعل الفكرة ممكنة:** قراءةٌ خامّةٌ لكلّ فتحةٍ تُنتج
    ربعَ مليون صفٍّ سنويّاً ولا تُجيب سؤالاً أفضل. صفٌّ واحدٌ لكلّ
    ``(مستخدم، كتاب، فعل، يوم)`` بعدّادٍ يجيب «مَن رأى» **ويعطي خطّاً زمنيّاً**
    بعُشر الحجم.

    **وما يخرج من الجهاز لا يُطوى أبداً** (تحميلٌ وتصديرٌ وطباعةٌ ورابطٌ موقَّع
    وفتحُ سرّيٍّ بتفويض): طيُّ «حمّله خمس مرّات» في صفٍّ واحد **إتلافُ دليل**.
    """

    #: أفعالٌ تُطوى يوميّاً — فتحٌ متعمَّدٌ لا ظهورٌ في قائمة.
    VIEW_BOOK = 'VIEW_BOOK'
    VIEW_ATTACHMENT = 'VIEW_ATTACHMENT'
    FOLDED_ACTIONS = (VIEW_BOOK, VIEW_ATTACHMENT)

    ACTION_CHOICES = [
        # ── قراءةٌ مطويّةٌ يوميّاً ──
        (VIEW_BOOK, 'فتح كتاب'),
        (VIEW_ATTACHMENT, 'عرض مرفق'),
        # ── إخراجُ بياناتٍ من الجهاز: كلُّ واقعةٍ صفّ ──
        ('DOWNLOAD_ATTACHMENT', 'تحميل مرفق'),
        ('EXPORT_DATA', 'تصدير بيانات'),
        ('PRINT', 'طباعة'),
        ('SHARED_LINK_OPEN', 'فتح رابط مشاركة'),
        ('SECRET_VIEW', 'اطّلاع على سرّي'),
        ('VIEW_AUDIT_LOG', 'فتح سجلّ الحركات'),
        # ── إدارة: تغييرُ صلاحيّةٍ واقعةٌ تُسجَّل، ومنحٌ بلا أثرٍ يُبطل السجلّ ──
        ('CREATE_DEPARTMENT', 'إنشاء قسم'),
        ('EDIT_DEPARTMENT', 'تعديل قسم'),
        ('ASSIGN_USER', 'إسناد موظّف/دور'),
        ('CREATE_GROUP', 'إنشاء عنقود'),
        ('EDIT_GROUP', 'تعديل عنقود'),
        # ── حسابات ──
        ('LOGIN', 'تسجيل دخول'),
        ('LOGOUT', 'تسجيل خروج'),
        ('LOGIN_FAILED', 'محاولة دخول فاشلة'),
        # ── قديمة (تبقى للتوافق؛ أفعالُ العمل موطنُها BookHistory) ──
        ('CREATE_BOOK', 'إنشاء كتاب'),
        ('EDIT_BOOK', 'تعديل كتاب'),
        ('DELETE_BOOK', 'حذف كتاب'),
        ('BACKUP_DATA', 'نسخ احتياطي'),
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

    book = models.ForeignKey(
        'core.Book', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='activity', verbose_name='الكتاب',
        help_text='بدونه يستحيل سؤال «مَن قرأ هذا الكتاب؟»'
    )
    #: **لقطةُ قسم الفاعل وقتَ الحدث** — لا القسمَ الحيّ. المستخدم ينتقل بين
    #: الأقسام، ونطاقُ أدمن القسم يجب أن يعكس أين كان حينها.
    department = models.ForeignKey(
        'core.Department', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='activity', verbose_name='قسم الفاعل'
    )
    #: يومُ الحدث بالتوقيت المحلّيّ (لا UTC) — مفتاحُ الطيّ.
    day = models.DateField('اليوم', null=True, blank=True)
    count = models.PositiveIntegerField('عدد المرّات', default=1)
    last_seen_at = models.DateTimeField('آخر مرّة', null=True, blank=True)

    class Meta:
        verbose_name = 'سجل نشاط مستخدم'
        verbose_name_plural = 'سجلات أنشطة المستخدمين'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['-timestamp']),
            models.Index(fields=['user', '-timestamp']),
            models.Index(fields=['action', '-timestamp']),
            # «مَن رأى هذا الكتاب؟» في صفحة الكتاب
            models.Index(fields=['book', '-timestamp'], name='activity_book_idx'),
            # نطاقُ أدمن القسم — أسخنُ استعلامٍ في شاشة السجلّ
            models.Index(fields=['department', '-timestamp'], name='activity_dept_idx'),
        ]
        constraints = [
            # صفٌّ واحدٌ لكلّ (مستخدم، كتاب، فعل، يوم) — **للأفعال المطويّة
            # فقط**. وما يخرج من الجهاز يبقى صفّاً لكلّ واقعة.
            models.UniqueConstraint(
                fields=['user', 'book', 'action', 'day'],
                condition=models.Q(action__in=('VIEW_BOOK', 'VIEW_ATTACHMENT')),
                name='uniq_folded_activity_per_day',
            ),
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
