# -*- coding: utf-8 -*-
"""
Notifications Views - معالجات الإشعارات
إدارة إشعارات المستخدمين (عرض، تحديد كمقروء)
"""

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from ..models import Notification


@login_required
def notifications_page(request):
    """
    صفحة الإشعارات للمستخدم
    
    Args:
        request: HTTP request
    
    Returns:
        Rendered template with user notifications
    """
    notifs = request.user.notifications.order_by("-created_at")
    return render(request, "core/notifications.html", {"notifications": notifs})


@login_required
def notification_mark_read(request, pk):
    """
    تعليم إشعار واحد كمقروء
    
    Args:
        request: HTTP request
        pk: معرف الإشعار
    
    Returns:
        Redirect to notifications page
    """
    n = get_object_or_404(Notification, pk=pk, user=request.user)
    n.is_read = True
    n.save(update_fields=["is_read"])
    from django.core.cache import cache
    cache.delete(f'unread_notif_{request.user.pk}')
    return redirect("notifications")
