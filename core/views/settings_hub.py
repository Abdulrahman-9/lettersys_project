# -*- coding: utf-8 -*-
"""
مركز الإعدادات الموحّد — Unified Settings Hub
============================================

صفحة واحدة بشريط تبويبات علوي يجمع كل إعدادات النظام:

* التبويبات البسيطة (عام، الإشعارات، الأمان، النسخ) تُعرَض وتُحفَظ هنا مباشرةً
  عبر عروض الحفظ أدناه — تبديلها لحظي بلا إعادة تحميل.
* الأدوات الثقيلة (البريد، العدّادات، الشبكة، الماسح، المستخدمون، السلة) تُحمَّل
  داخل لوحة المركز في إطار ``?embed=1`` بكامل صفحاتها العاملة، فلا يغادر
  المستخدم المركز. وضع التضمين نفسه يُدار في ``core.context_processors.embed_mode``.

قائمة التبويبات وترتيبها يعيشان في القالب ``core/settings/hub.html`` (مصدر واحد)،
والتبويب النشط يُشتقّ في العميل من ``?tab=`` — فلا حاجة لتكرارهما هنا.
"""

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from ..models import BackupSettings, NotificationSettings, SecuritySettings, SystemSettings
from .helpers import staff_required

logger = logging.getLogger(__name__)


@login_required
@staff_required
def settings_hub(request):
    """يعرض مركز الإعدادات. التبويب النشط يختاره العميل من ``?tab=``."""
    return render(request, 'core/settings/hub.html', {
        'notif_settings': NotificationSettings.get(),
        'sec_settings': SecuritySettings.get(),
        'backup_settings': BackupSettings.get(),
    })


@login_required
@staff_required
@require_http_methods(["POST"])
def settings_general_save(request):
    """يحفظ تبويب «عام» — هوية التطبيق المعروضة (اسم النظام + سطر الوصف)."""
    back = f"{reverse('settings_hub')}?tab=general"
    app_name = (request.POST.get('app_name') or '').strip()
    if not app_name:
        messages.error(request, 'اسم النظام مطلوب.')
        return redirect(back)

    obj = SystemSettings.get()
    obj.app_name = app_name[:100]
    obj.brand_subtitle = (request.POST.get('brand_subtitle') or '').strip()[:200]
    obj.save(update_fields=['app_name', 'brand_subtitle', 'updated_at'])
    messages.success(request, 'تم حفظ إعدادات النظام.')
    return redirect(back)


@login_required
@staff_required
@require_http_methods(["POST"])
def settings_notifications_save(request):
    """يحفظ تبويب «سياسة الإشعارات» — مفاتيح تتحكّم في أمر notify_overdue_books."""
    cfg = NotificationSettings.get()
    cfg.overdue_enabled = 'overdue_enabled' in request.POST
    cfg.notify_admins = 'notify_admins' in request.POST
    cfg.notify_creator = 'notify_creator' in request.POST
    cfg.email_admins = 'email_admins' in request.POST
    cfg.save(update_fields=['overdue_enabled', 'notify_admins', 'notify_creator',
                            'email_admins', 'updated_at'])
    messages.success(request, 'تم حفظ سياسة الإشعارات.')
    return redirect(f"{reverse('settings_hub')}?tab=notifications")


@login_required
@staff_required
@require_http_methods(["POST"])
def settings_security_save(request):
    """يحفظ تبويب «الأمان» — الحد الأدنى لطول كلمة المرور (يُطبَّق في شاشة الأدوار)."""
    back = f"{reverse('settings_hub')}?tab=security"
    raw = (request.POST.get('password_min_length') or '').strip()
    if not raw.isdigit():
        messages.error(request, 'قيمة غير صالحة للحد الأدنى لطول كلمة المرور.')
        return redirect(back)

    cfg = SecuritySettings.get()
    cfg.password_min_length = max(4, min(64, int(raw)))  # نطاق آمن
    cfg.save(update_fields=['password_min_length', 'updated_at'])
    messages.success(request, 'تم حفظ إعدادات الأمان.')
    return redirect(back)


@login_required
@staff_required
@require_http_methods(["POST"])
def settings_backup_save(request):
    """يحفظ تبويب «النسخ الاحتياطي» — إعدادات الجدولة التي تقرؤها مهمة scheduled_backup."""
    back = f"{reverse('settings_hub')}?tab=backup"
    cfg = BackupSettings.get()

    frequency = request.POST.get('frequency', cfg.frequency)
    valid_freqs = {c for c, _ in BackupSettings.FREQUENCY_CHOICES}
    if frequency not in valid_freqs:
        frequency = BackupSettings.FREQ_DAILY

    hour_raw = (request.POST.get('hour') or '').strip()
    retention_raw = (request.POST.get('retention_days') or '').strip()

    cfg.enabled = 'enabled' in request.POST
    cfg.frequency = frequency
    cfg.hour = max(0, min(23, int(hour_raw))) if hour_raw.isdigit() else cfg.hour
    cfg.retention_days = max(1, min(3650, int(retention_raw))) if retention_raw.isdigit() else cfg.retention_days
    cfg.save(update_fields=['enabled', 'frequency', 'hour', 'retention_days', 'updated_at'])
    messages.success(request, 'تم حفظ إعدادات النسخ الاحتياطي.')
    return redirect(back)
