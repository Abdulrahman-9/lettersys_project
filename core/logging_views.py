"""
===================================================
API Views for Logging System
===================================================
"""

import json
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from .logging_models import ClientLog, ErrorLog


@login_required
@require_http_methods(["POST"])
def log_client_event(request):
    """
    استقبال سجلات من العميل (JavaScript)
    
    POST /api/logs/
    Body: {
        "sessionId": "...",
        "type": "EVENT|ERROR|METRIC",
        "eventType": "...",
        "data": {...},
        "url": "...",
        "userAgent": "..."
    }
    """
    try:
        data = json.loads(request.body)
        
        ClientLog.objects.create(
            session_id=data.get('sessionId', ''),
            log_type=data.get('type', 'EVENT'),
            event_type=data.get('eventType', ''),
            data=data.get('data', {}),
            url=data.get('url', ''),
            user_agent=data.get('userAgent', request.META.get('HTTP_USER_AGENT', ''))
        )
        
        # في حالة الأخطاء، حفظ في ErrorLog أيضاً
        if data.get('type') == 'ERROR':
            ErrorLog.objects.create(
                severity='ERROR',
                error_type=data.get('eventType', 'JAVASCRIPT_ERROR'),
                error_message=data.get('data', {}).get('message', ''),
                stack_trace=data.get('data', {}).get('stack', ''),
                user=request.user if request.user.is_authenticated else None,
                metadata=data.get('data', {})
            )
        
        return JsonResponse({'status': 'success'})
    
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)


@login_required
@require_http_methods(["POST"])
def log_client_batch(request):
    """
    استقبال دفعة من السجلات (حد أقصى 100 سجل)
    
    POST /api/logs/batch/
    Body: [{log1}, {log2}, ...]
    """
    try:
        logs_data = json.loads(request.body)

        # Rate limit: max 100 logs per batch
        if not isinstance(logs_data, list) or len(logs_data) > 100:
            return JsonResponse({'status': 'error', 'message': 'الحد الأقصى 100 سجل'}, status=400)

        client_logs = []
        for log_data in logs_data:
            client_logs.append(ClientLog(
                session_id=log_data.get('sessionId', ''),
                log_type=log_data.get('type', 'EVENT'),
                event_type=log_data.get('eventType', ''),
                data=log_data.get('data', {}),
                url=log_data.get('url', ''),
                user_agent=log_data.get('userAgent', request.META.get('HTTP_USER_AGENT', ''))
            ))
        
        ClientLog.objects.bulk_create(client_logs)
        
        return JsonResponse({
            'status': 'success',
            'count': len(client_logs)
        })
    
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
