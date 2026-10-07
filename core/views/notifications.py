# -*- coding: utf-8 -*-
"""
Notifications Views - معالجات الإشعارات
إدارة إشعارات المستخدمين (عرض، تحديد كمقروء)
"""

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.paginator import Paginator
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from ..models import Notification

#: صفحةٌ واحدةٌ تكفي يوماً من العمل؛ والأقدمُ في الصفحات التالية لا في رسمٍ واحدٍ بلا سقف.
PAGE_SIZE = 50


def _local(request, url):
    """رابطٌ داخليٌّ وحدَه — ``link_url`` نصٌّ مخزَّن، فلا يصير ``javascript:`` ولا موقعاً خارجيّاً."""
    url = (url or '').strip()
    if url.startswith('/') and url_has_allowed_host_and_scheme(
            url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return url
    return ''


def _forget_count(user):
    cache.delete(f'unread_notif_{user.pk}')


@login_required
def notifications_page(request):
    """«التنبيهات» — العنوانُ والرسالةُ والرابطُ إلى الكتاب، والأولويّةُ من الحقل لا من تحسُّس النصّ
    (تدقيقُ نيلسن 2026‑10‑07، A#11–13)."""
    qs = request.user.notifications.order_by('-created_at')
    page = Paginator(qs, PAGE_SIZE).get_page(request.GET.get('page'))
    for n in page.object_list:
        n.safe_link = _local(request, n.link_url)
    return render(request, 'core/notifications.html', {
        'page_obj': page,
        'notifications': page.object_list,
        'total_count': page.paginator.count,
        'unread_count': qs.filter(is_read=False).count(),
    })


@login_required
def notification_mark_read(request, pk):
    """تعليمُ إشعارٍ واحدٍ مقروءاً — و``next`` الداخليّ يفتح الكتابَ بعده في نقرةٍ واحدة."""
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    n = get_object_or_404(Notification, pk=pk, user=request.user)
    if not n.is_read:
        n.is_read = True
        n.read_at = timezone.now()
        n.save(update_fields=["is_read", "read_at"])
        _forget_count(request.user)
    return redirect(_local(request, request.POST.get('next')) or "notifications")


@login_required
def notification_mark_all_read(request):
    """«تعليم الكلّ كمقروء» — كان واحداً واحداً بإعادة تحميلٍ كاملة."""
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    request.user.notifications.filter(is_read=False).update(is_read=True, read_at=timezone.now())
    _forget_count(request.user)
    return redirect("notifications")
