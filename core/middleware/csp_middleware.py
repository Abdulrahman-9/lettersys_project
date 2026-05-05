"""
core.middleware.csp_middleware
================================
Middleware لإضافة Content Security Policy header لكل الاستجابات.

يقرأ الإعداد من settings:
  - SECURE_CONTENT_SECURITY_POLICY        → يُرسَل كـ Content-Security-Policy
  - SECURE_CONTENT_SECURITY_POLICY_REPORT_ONLY → يُرسَل كـ Content-Security-Policy-Report-Only
"""

from django.conf import settings
from django.utils.deprecation import MiddlewareMixin


class CSPMiddleware(MiddlewareMixin):
    """يضيف CSP header لكل استجابة HTML."""

    def process_response(self, request, response):
        # لا نضيف CSP للـ static files أو ملفات الوسائط
        path = getattr(request, 'path', '')
        if path.startswith(('/static/', '/media/')):
            return response

        csp = getattr(settings, 'SECURE_CONTENT_SECURITY_POLICY', None)
        csp_ro = getattr(settings, 'SECURE_CONTENT_SECURITY_POLICY_REPORT_ONLY', None)

        if csp and 'Content-Security-Policy' not in response:
            response['Content-Security-Policy'] = csp

        if csp_ro and 'Content-Security-Policy-Report-Only' not in response:
            response['Content-Security-Policy-Report-Only'] = csp_ro

        return response
