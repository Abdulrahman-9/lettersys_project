"""
core.messaging.api.email_endpoints
====================================
REST API endpoints for book/entity-scoped email operations.

Routes (book-centric):
  POST /books/api/email/send/               — manual email send
  GET  /books/api/email/logs/<book_id>/     — book email logs
  POST /books/api/email/test-smtp/          — SMTP connection test (canonical)
  GET|POST /books/api/email/settings/       — read/update email settings
  GET  /books/api/email/entity/<id>/        — entity email info
  POST /books/api/email/entity/<id>/update/ — update entity email fields
"""

import json
import logging
import re

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from core.decorators import rate_limit

logger = logging.getLogger('lettersys')

EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$')


def _sanitize_header(value: str) -> str:
    """إزالة أحرف CRLF لمنع Email Header Injection"""
    return value.replace('\r', '').replace('\n', '').replace('\0', '')


def _validate_email(addr: str) -> bool:
    return bool(EMAIL_REGEX.match(addr.strip()))


# ── 1. Manual email send ────────────────────────────────────────
@login_required
@require_http_methods(['POST'])
@rate_limit('email_send', max_attempts=20, window_seconds=300, by='user')
def send_email(request):
    """
    POST body JSON:
    {
      "book_id": 42,
      "to": ["addr@example.com"],
      "cc": ["copy@example.com"],      // optional
      "subject": "Subject text",
      "body": "<p>HTML body</p>",
      "entity_id": 5                    // optional
    }
    """
    from core.models import Book, Entity
    from core.messaging.engines.smtp import send_manual_email

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'success': False, 'message': 'بيانات غير صالحة'}, status=400)

    book_id   = data.get('book_id')
    to_list   = data.get('to', [])
    subject   = _sanitize_header(data.get('subject', '').strip())
    body      = data.get('body', '').strip()
    cc_list   = data.get('cc', [])
    entity_id = data.get('entity_id')

    if not book_id or not to_list or not subject or not body:
        return JsonResponse({'success': False, 'message': 'book_id, to, subject, body مطلوبة'}, status=400)

    # التحقق من صحة عناوين البريد الإلكتروني
    invalid = [e for e in to_list if not _validate_email(e)]
    if invalid:
        return JsonResponse({'success': False, 'message': f'عناوين بريد غير صالحة: {invalid}'}, status=400)

    try:
        book = Book.objects.get(pk=book_id)
    except Book.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'الكتاب غير موجود'}, status=404)

    entity = None
    if entity_id:
        try:
            entity = Entity.objects.get(pk=entity_id)
        except Entity.DoesNotExist:
            pass

    log = send_manual_email(
        book=book,
        to_addresses=to_list,
        subject=subject,
        body=body,
        cc=cc_list or None,
        sent_by=request.user,
        entity=entity,
    )

    return JsonResponse({
        'success': log.status == 'sent',
        'status': log.status,
        'log_id': log.pk,
        'message': 'تم الإرسال بنجاح' if log.status == 'sent' else log.error_msg,
    })


# ── 2. Book email logs ──────────────────────────────────────────
@login_required
@require_http_methods(['GET'])
def book_email_logs(request, book_id):
    from core.models import Book, BookEmailLog

    try:
        book = Book.objects.get(pk=book_id)
    except Book.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'الكتاب غير موجود'}, status=404)

    logs = BookEmailLog.objects.filter(book=book).order_by('-sent_at').values(
        'id', 'to_address', 'cc_addresses', 'subject', 'status',
        'trigger', 'sent_at', 'error_msg',
    )

    data = []
    for log in logs:
        data.append({
            **log,
            'sent_at': log['sent_at'].isoformat() if log['sent_at'] else None,
            'status_label': {'sent': 'أُرسِل', 'failed': 'فشل', 'pending': 'في الانتظار'}.get(log['status'], log['status']),
            'trigger_label': {'auto': 'تلقائي', 'manual': 'يدوي', 'reminder': 'تذكير'}.get(log['trigger'], log['trigger']),
        })

    return JsonResponse({'success': True, 'logs': data})


# ── 3. SMTP connection test (CANONICAL — no duplicate in mail_endpoints) ──
@login_required
@require_http_methods(['POST'])
@rate_limit('test_smtp', max_attempts=5, window_seconds=300, by='user')
def test_smtp(request):
    from core.models import EmailSettings
    from core.messaging.engines.smtp import test_smtp_connection

    cfg = EmailSettings.get()
    result = test_smtp_connection(cfg)
    return JsonResponse(result)


# ── 4. Read/update email settings ──────────────────────────────
@login_required
@require_http_methods(['GET', 'POST'])
def email_settings(request):
    from core.models import EmailSettings

    if not request.user.is_staff:
        return JsonResponse({'success': False, 'message': 'غير مصرح'}, status=403)

    cfg = EmailSettings.get()

    if request.method == 'GET':
        return JsonResponse({
            'success': True,
            'settings': {
                'org_name':        cfg.org_name,
                'org_email':       cfg.org_email,
                'reply_to':        cfg.reply_to,
                'email_signature': cfg.email_signature,
                'smtp_host':       cfg.smtp_host,
                'smtp_port':       cfg.smtp_port,
                'smtp_use_tls':    cfg.smtp_use_tls,
                'smtp_use_ssl':    cfg.smtp_use_ssl,
                'smtp_user':       cfg.smtp_user,
                # Password intentionally excluded from response
                'is_active':       cfg.is_active,
                'send_on_save':    cfg.send_on_save,
            }
        })

    # POST — update settings
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'success': False, 'message': 'بيانات غير صالحة'}, status=400)

    allowed_fields = [
        'org_name', 'org_email', 'reply_to', 'email_signature',
        'smtp_host', 'smtp_port', 'smtp_use_tls', 'smtp_use_ssl',
        'smtp_user', 'smtp_password', 'is_active', 'send_on_save',
    ]
    update_fields = []
    for field in allowed_fields:
        if field in data:
            setattr(cfg, field, data[field])
            update_fields.append(field)

    if update_fields:
        cfg.save(update_fields=update_fields)
        logger.info(f'[EmailSettings] Updated by {request.user.username}: {update_fields}')

    return JsonResponse({'success': True, 'message': 'تم حفظ الإعدادات'})


# ── 5. Entity email info ────────────────────────────────────────
@login_required
@require_http_methods(['GET'])
def entity_email_info(request, entity_id):
    from core.models import Entity

    try:
        entity = Entity.objects.get(pk=entity_id)
    except Entity.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'الجهة غير موجودة'}, status=404)

    return JsonResponse({
        'success': True,
        'entity': {
            'id':                entity.id,
            'name':              entity.name,
            'code':              entity.code or '',
            'email':             entity.email,
            'email_cc':          entity.email_cc,
            'phone':             entity.phone,
            'address':           entity.address,
            'contact_person':    entity.contact_person,
            'notes':             entity.notes,
            'notify_on_receive': entity.notify_on_receive,
            'notify_on_send':    entity.notify_on_send,
        }
    })


# ── 6. Update entity email ─────────────────────────────────────
@login_required
@require_http_methods(['POST'])
def update_entity_email(request, entity_id):
    from core.models import Entity

    try:
        entity = Entity.objects.get(pk=entity_id)
    except Entity.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'الجهة غير موجودة'}, status=404)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'success': False, 'message': 'بيانات غير صالحة'}, status=400)

    allowed = ['email', 'email_cc', 'phone', 'address', 'contact_person',
               'notes', 'notify_on_receive', 'notify_on_send']
    update_fields = []
    for field in allowed:
        if field in data:
            setattr(entity, field, data[field])
            update_fields.append(field)

    if update_fields:
        entity.save(update_fields=update_fields)
        logger.info(f'[EntityEmail] Updated entity={entity_id} fields={update_fields} by {request.user.username}')

    return JsonResponse({'success': True, 'message': 'تم التحديث'})
