"""A signed browser identity survives login rotation without sharing holds."""
import logging
import re

from django.conf import settings
from django.core import signing

from .reservation_service import reservation_client_key


COOKIE_NAME = 'lettersys_reservation_browser'
COOKIE_SALT = 'core.reservation.browser.v1'
COOKIE_AGE = 365 * 24 * 60 * 60
logger = logging.getLogger('lettersys')


def browser_key(cookies, session_key):
    raw = cookies.get(COOKIE_NAME)
    if raw:
        try:
            key = signing.get_cookie_signer(salt=COOKIE_NAME + COOKIE_SALT).unsign(raw)
            if re.fullmatch(r'[0-9a-f]{64}', key):
                return key
        except signing.BadSignature:
            logger.warning('[Reservation] Invalid browser identity signature')
    return reservation_client_key(session_key)


def request_client_key(request):
    key = getattr(request, 'reservation_client_key', None)
    if key:
        return key
    if not request.session.session_key:
        request.session.save()
    key = browser_key(request.COOKIES, request.session.session_key)
    request.reservation_client_key = key
    return key


class ReservationIdentityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            request_client_key(request)
        response = self.get_response(request)
        if request.user.is_authenticated:
            key = request_client_key(request)
            if browser_key(request.COOKIES, None) != key:
                response.set_signed_cookie(
                    COOKIE_NAME, key, salt=COOKIE_SALT, max_age=COOKIE_AGE,
                    httponly=True, samesite='Lax',
                    secure=settings.SESSION_COOKIE_SECURE or request.is_secure(),
                )
        return response
