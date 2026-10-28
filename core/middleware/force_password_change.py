from urllib.parse import urlsplit

from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse


class FirstLoginPasswordChangeMiddleware:
    """Require newly provisioned local accounts to replace their temporary password."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if user.is_authenticated:
            profile = getattr(user, 'profile', None)
            if profile and profile.must_change_password:
                allowed_paths = {
                    reverse('password_change'),
                    reverse('logout'),
                }
                asset_paths = (
                    urlsplit(settings.STATIC_URL).path,
                    urlsplit(settings.MEDIA_URL).path,
                )
                is_asset = any(
                    prefix and prefix != '/' and request.path_info.startswith(prefix)
                    for prefix in asset_paths
                )
                if request.path_info not in allowed_paths and not is_asset:
                    return redirect('password_change')
        return self.get_response(request)
