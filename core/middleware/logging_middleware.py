"""
===================================================
Django Logging Middleware
===================================================

يوفر:
- تسجيل جميع requests/responses
- تتبع الأداء
- تسجيل الأخطاء
- تسجيل أفعال المستخدم
"""

import json
import time
import logging
from django.utils.deprecation import MiddlewareMixin
from django.conf import settings
from django.db import connection

logger = logging.getLogger('lettersys')


class RequestLoggingMiddleware(MiddlewareMixin):
    """
    Middleware لتسجيل جميع الطلبات
    """
    
    def process_request(self, request):
        """يُستدعى قبل معالجة الطلب"""
        request._request_start_time = time.time()
        
        # تسجيل معلومات الطلب
        log_data = {
            'method': request.method,
            'path': request.path,
            'user': str(request.user) if request.user.is_authenticated else 'Anonymous',
            'ip': self.get_client_ip(request),
        }
        
        logger.info(f"REQUEST: {request.method} {request.path}", extra=log_data)
        
        return None
    
    def process_response(self, request, response):
        """يُستدعى بعد معالجة الطلب"""
        # حساب مدة الطلب
        if hasattr(request, '_request_start_time'):
            duration = (time.time() - request._request_start_time) * 1000  # milliseconds
            
            # التحقق من أن response هو كائن صحيح وليس function
            if not hasattr(response, 'status_code'):
                return response
            
            # عدد استعلامات قاعدة البيانات
            db_queries = len(connection.queries)
            
            log_data = {
                'method': request.method,
                'path': request.path,
                'status_code': response.status_code,
                'duration_ms': round(duration, 2),
                'db_queries': db_queries,
                'user': str(request.user) if request.user.is_authenticated else 'Anonymous',
            }
            
            # تسجيل بمستوى مختلف حسب الحالة
            if response.status_code >= 500:
                logger.error(f"RESPONSE: {response.status_code} - {request.method} {request.path}", extra=log_data)
            elif response.status_code >= 400:
                logger.warning(f"RESPONSE: {response.status_code} - {request.method} {request.path}", extra=log_data)
            else:
                logger.info(f"RESPONSE: {response.status_code} - {request.method} {request.path}", extra=log_data)
            
            # إضافة معلومات الأداء للـ headers (اختياري)
            if settings.DEBUG:
                response['X-Request-Duration'] = f"{duration:.2f}ms"
                response['X-DB-Queries'] = str(db_queries)
        
        return response
    
    def process_exception(self, request, exception):
        """يُستدعى عند حدوث خطأ"""
        log_data = {
            'method': request.method,
            'path': request.path,
            'exception_type': type(exception).__name__,
            'exception_message': str(exception),
            'user': str(request.user) if request.user.is_authenticated else 'Anonymous',
            'ip': self.get_client_ip(request),
        }
        
        logger.exception(f"EXCEPTION: {type(exception).__name__} in {request.path}", extra=log_data)
        
        return None
    
    @staticmethod
    def get_client_ip(request):
        """الحصول على IP الحقيقي للمستخدم"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip


class PerformanceMonitoringMiddleware(MiddlewareMixin):
    """
    Middleware لمراقبة الأداء
    """
    
    # عتبات التنبيه
    SLOW_REQUEST_THRESHOLD = 1000  # 1 second
    MANY_QUERIES_THRESHOLD = 50
    
    def process_response(self, request, response):
        """تحليل الأداء وإصدار تنبيهات"""
        if not hasattr(request, '_request_start_time'):
            return response
        
        duration = (time.time() - request._request_start_time) * 1000
        db_queries = len(connection.queries)
        
        # تحذير للطلبات البطيئة
        if duration > self.SLOW_REQUEST_THRESHOLD:
            logger.warning(
                f"SLOW REQUEST: {request.method} {request.path} took {duration:.2f}ms",
                extra={
                    'duration_ms': round(duration, 2),
                    'threshold_ms': self.SLOW_REQUEST_THRESHOLD,
                    'path': request.path,
                }
            )
        
        # تحذير لعدد كبير من الاستعلامات
        if db_queries > self.MANY_QUERIES_THRESHOLD:
            logger.warning(
                f"MANY DB QUERIES: {request.method} {request.path} executed {db_queries} queries",
                extra={
                    'db_queries': db_queries,
                    'threshold': self.MANY_QUERIES_THRESHOLD,
                    'path': request.path,
                }
            )
        
        return response


class UserActivityLoggingMiddleware(MiddlewareMixin):
    """
    Middleware لتسجيل أنشطة المستخدمين
    """
    
    # الأنشطة المهمة للتسجيل
    TRACKED_ACTIONS = {
        '/books/add/': 'CREATE_BOOK',
        '/books/edit/': 'EDIT_BOOK',
        '/books/delete/': 'DELETE_BOOK',
        '/export/': 'EXPORT_DATA',
        '/backup/': 'BACKUP_DATA',
    }
    
    def process_response(self, request, response):
        """تسجيل الأنشطة المهمة"""
        if not request.user.is_authenticated:
            return response
        
        # التحقق من الأنشطة المتتبعة
        for path_pattern, action_name in self.TRACKED_ACTIONS.items():
            if path_pattern in request.path:
                self._log_user_activity(request, action_name, response.status_code)
                break
        
        return response
    
    def _log_user_activity(self, request, action, status_code):
        """تسجيل نشاط المستخدم"""
        log_data = {
            'user': str(request.user),
            'action': action,
            'path': request.path,
            'method': request.method,
            'status_code': status_code,
            'ip': RequestLoggingMiddleware.get_client_ip(request),
        }
        
        logger.info(f"USER ACTIVITY: {request.user} performed {action}", extra=log_data)
