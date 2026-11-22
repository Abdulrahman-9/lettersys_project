"""الشبكة والأجهزة: من يتّصل بالنظام ومن أيّ متصفّح (طلبُ المالك 2026-11-18).

«الجهاز» هنا متصفّحٌ على حاسوبٍ لمستخدم ويندوز واحد، يعرفه الخادم بكوكي ``lx_device``. ينضمّ
بكودٍ من خمسة أرقام يصدره المدير العامّ من جهاز الخادم وحده. التسجيلُ **تنظيمٌ لا قفل**: الكوكي
يُنسخ، وكلمةُ المرور تبقى الحارس (حكمُ فيبل).

قواعدُ الحكم هنا وفي ``service`` وحده؛ والقوالبُ تقرأ ما يُعطى لها.
"""
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone


class BrowserDevice(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'غير مسجّل'
        ACTIVE = 'active', 'مسجّل'
        REVOKED = 'revoked', 'أُلغي تسجيله'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # SHA-256 للتوكِن بلا سرّ (كـWorkstation): تدويرُ SECRET_KEY لا يُسقط كلَّ الأجهزة دفعةً واحدة.
    token_hash = models.CharField(max_length=64, unique=True)
    cookie_renewed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    name = models.CharField('اسم الجهاز', max_length=60, blank=True)
    browser = models.CharField(max_length=40, blank=True)
    os = models.CharField(max_length=40, blank=True)
    last_ip = models.GenericIPAddressField(null=True, blank=True)
    last_seen = models.DateTimeField(null=True, blank=True, db_index=True)
    last_user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                  on_delete=models.SET_NULL, related_name='+')
    users = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name='browser_devices')
    requested_at = models.DateTimeField(null=True, blank=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name='+')
    dismissed_at = models.DateTimeField(null=True, blank=True)
    joined_at = models.DateTimeField(null=True, blank=True)
    joined_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                  on_delete=models.SET_NULL, related_name='+')
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name='+')
    has_scanner = models.BooleanField(null=True, blank=True)
    agent_version = models.CharField(max_length=20, blank=True)
    scanner_label = models.CharField(max_length=120, blank=True)
    scanner_state = models.CharField(max_length=12, blank=True)
    reported_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(Lower('name'), condition=Q(status='active'),
                                    name='devices_unique_active_name_ci'),
        ]

    def __str__(self):
        return self.name or f'{self.browser} · {self.os}'.strip(' ·') or str(self.pk)

    @property
    def is_active(self):
        return self.status == self.Status.ACTIVE


class PairingCode(models.Model):
    """كودُ انضمامٍ من خمسة أرقام: لمرّةٍ واحدة، عشرَ دقائق. ``for_device`` فارغٌ = كودٌ حرّ من
    «إضافة جهاز» يصلح لأوّل جهازٍ يكتبه؛ وإلّا فهو لطلبٍ بعينه ولا يعمل على غيره."""
    code_hash = models.CharField(max_length=64)
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
                                  related_name='+')
    issued_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    for_device = models.ForeignKey(BrowserDevice, null=True, blank=True, on_delete=models.CASCADE,
                                   related_name='codes')
    used_at = models.DateTimeField(null=True, blank=True)
    used_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                on_delete=models.SET_NULL, related_name='+')
    used_device = models.ForeignKey(BrowserDevice, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name='+')
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-issued_at']
        constraints = [
            # القيدُ لا يعرف الانتهاء: الخدمةُ تُغلق المنتهي قبل كلّ إصدار.
            models.UniqueConstraint(fields=['code_hash'],
                                    condition=Q(used_at__isnull=True, cancelled_at__isnull=True),
                                    name='devices_open_code_unique'),
        ]


class DeviceAttempt(models.Model):
    """كلُّ إدخالِ كود — صحيحٍ أو خاطئ. حدُّ المحاولات يُعدّ من هنا لا من الكاش (الإنتاجُ على
    LocMem يُصفَّر عند إعادة التشغيل)، فالجدولُ تدقيقٌ وحدٌّ معاً."""
    JOIN = 'join'
    DECLARE = 'declare'
    KIND_CHOICES = ((JOIN, 'كود انضمام'), (DECLARE, 'كود إعلان الخادم'))

    kind = models.CharField(max_length=8, choices=KIND_CHOICES)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
                             related_name='+')
    device = models.ForeignKey(BrowserDevice, null=True, blank=True, on_delete=models.SET_NULL,
                               related_name='+')
    ip = models.GenericIPAddressField(null=True, blank=True)
    ok = models.BooleanField(default=False)
    at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['-at']


class DevicePolicy(models.Model):
    """صفٌّ واحد: وضعُ البوّابة، وجهازُ الخادم المُعلَن، وعناوينُ الخادم لكشف تغيّرها."""
    MODE_OPEN = 'open'
    MODE_REMIND = 'remind'
    MODE_ONLY = 'only'
    MODE_CHOICES = (
        (MODE_OPEN, 'مفتوح لكلّ جهاز'),
        (MODE_REMIND, 'تنبيه غير المسجّل'),
        (MODE_ONLY, 'المسجّلة فقط'),
    )

    mode = models.CharField('ماذا يحدث لجهازٍ غير مسجّل', max_length=8, choices=MODE_CHOICES,
                            default=MODE_REMIND)
    server = models.ForeignKey(BrowserDevice, null=True, blank=True, on_delete=models.SET_NULL,
                               related_name='+', verbose_name='جهاز الخادم')
    server_declared_at = models.DateTimeField(null=True, blank=True)
    declare_code_hash = models.CharField(max_length=64, blank=True)
    declare_code_expires = models.DateTimeField(null=True, blank=True)
    server_addresses = models.JSONField(default=list, blank=True)
    previous_addresses = models.JSONField(default=list, blank=True)
    addresses_changed_at = models.DateTimeField(null=True, blank=True)
    # «من يُبلَّغ حين يتوقّف الخادم» — يضبطه المديرُ العامّ في «حالة الخادم»، ويُعرض للموظّف حين لا اتّصال.
    notify_name = models.CharField('من يُبلَّغ حين يتوقّف الخادم', max_length=80, blank=True)
    notify_phone = models.CharField('رقمُه الداخليّ أو هاتفه', max_length=40, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
