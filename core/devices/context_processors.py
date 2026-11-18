"""شريطُ «هذا الجهاز غير مسجّل» في وضع التنبيه — يُقرأ ممّا عرفه الوسيطُ لهذا الطلب، بلا استعلام."""


def device_banner(request):
    pol = getattr(request, 'lx_policy', None)
    if pol is None or not pol.server_id or pol.mode != pol.MODE_REMIND:
        return {}
    device = getattr(request, 'lx_device', None)
    if device is not None and device.is_active:
        return {}
    match = getattr(request, 'resolver_match', None)
    if match is not None and match.url_name in ('device_join', 'network_settings'):
        return {}
    return {'device_banner': True}
