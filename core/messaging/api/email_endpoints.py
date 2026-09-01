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


def _json_body(request) -> dict:
    """جسم JSON للطلب — قاموس فارغ إن كان غائباً أو تالفاً (الطلب قد يكون بلا جسم)."""
    try:
        return json.loads(request.body or b'{}')
    except (json.JSONDecodeError, ValueError):
        return {}


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

    from core.messaging.scoping import scope_books

    # الإرسال باسم كتابٍ يضع سجلّه في تاريخ ذلك الكتاب — فيلزم أن يكون ضمن نطاقك.
    try:
        book = scope_books(Book.objects.all(), request.user).get(pk=book_id)
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
    from core.messaging.scoping import scope_books

    # كانت النقطة تُعيد سجلّات بريد **أيّ** كتاب برقمه (عناوين المستلمين
    # والمواضيع) لأيّ مستخدمٍ مسجَّل. النطاق داخل الاستعلام: كتابُ غيرك
    # «غير موجود» لا «ممنوع».
    try:
        book = scope_books(Book.objects.all(), request.user).get(pk=book_id)
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
# هذه هي النقطة الوحيدة التي تحمل محدِّد المعدّل لهذا النطاق: الغلاف المفوِّض في
# ``mail_endpoints.api_test_smtp`` كان يحمل محدّداً بنفس المفتاح، فكانت كل نقرة
# تستهلك محاولتين وتنفد الحصّة بعد نقرتين ونصف. الحد هنا مقيس على واقع ضبط
# البريد (تجربة وخطأ: منفذ، تشفير، كلمة مرور) لا على 5 محاولات خانقة.
@login_required
@require_http_methods(['POST'])
@rate_limit('test_smtp', max_attempts=20, window_seconds=300, by='user')
def test_smtp(request):
    from core.models import EmailSettings
    from core.messaging.engines.smtp import test_smtp_connection

    if not request.user.is_staff:
        return JsonResponse({'success': False, 'message': 'غير مصرح'}, status=403)

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


# ── 4b. إرسال الكتاب بمرفقاته إلى الجهة المعنيّة ────────────────
#
# لماذا نقطة مستقلّة؟ لأن هذا التدفّق يعرف الجهة من الكتاب، ويُرفِق الملفات
# فعلياً — وهو ما لا تفعله ``send_email`` (إرسال حرّ) ولا ``api_compose``.
# محرّك SMTP يدعم المرفقات منذ البداية، لكن **لم يكن أحد يمرّرها**.

def _resolve_book_recipient(book):
    """الجهة المعنيّة بالكتاب + بريدها. وارد ⇒ المُصدِرة، صادر ⇒ المستقبِلة."""
    qs = book.issuing_entities if book.is_incoming else book.receiving_entities
    entity = qs.filter(is_active=True).exclude(email='').first()
    if entity is None:
        # قد توجد جهة بلا بريد — نميّز الحالتين برسالة صادقة
        any_entity = qs.first()
        if any_entity is not None:
            return None, f'الجهة «{any_entity.name}» ليس لها بريد إلكتروني مسجّل.'
        return None, 'لا توجد جهة معنيّة مرتبطة بهذا الكتاب.'
    return entity, None


def _book_email_defaults(book, entity):
    direction = 'استلام' if book.is_incoming else 'إرسال'
    subject = f'كتاب رقم {book.our_number} — {book.title[:80]}'
    return subject, direction


@login_required
@require_http_methods(['GET'])
def book_email_preview(request, book_id):
    """معاينة ما سيُرسَل: الجهة، بريدها، وما سيُرفَق مقابل ما سيُحال إلى رابط.

    لا تقرأ بايتات الملفات — الأحجام فقط (انظر ``plan_book_attachments``).
    """
    from core.models import Book, EmailSettings
    from core.attachment_sharing import MAX_EMAIL_ATTACH_BYTES, human_size, plan_book_attachments

    from core.messaging.scoping import scope_books

    book = scope_books(
        Book.objects.filter(is_deleted=False), request.user
    ).filter(pk=book_id).first()
    if book is None:
        return JsonResponse({'success': False, 'message': 'الكتاب غير موجود'}, status=404)

    cfg = EmailSettings.get()
    entity, entity_error = _resolve_book_recipient(book)
    plan = plan_book_attachments(book)
    subject, _ = _book_email_defaults(book, entity)

    def _row(item, mode):
        return {'name': item['name'], 'size': item['size'],
                'size_label': human_size(item['size']), 'mode': mode}

    return JsonResponse({
        'success': True,
        'email_enabled': cfg.is_active,
        'book': {'id': book.id, 'number': book.our_number, 'title': book.title},
        'entity': None if entity is None else {
            'id': entity.id, 'name': entity.name,
            'email': entity.email, 'cc': entity.get_cc_list(),
        },
        'entity_error': entity_error,
        'subject': subject,
        'files': (
            [_row(i, 'attach') for i in plan['attach']]
            + [_row(i, 'link') for i in plan['link']]
            + [{'name': f['name'], 'size': 0, 'size_label': '—',
                'mode': 'failed', 'error': f['error']} for f in plan['failed']]
        ),
        'attach_bytes': plan['attach_bytes'],
        'attach_label': human_size(plan['attach_bytes']),
        'limit_label': human_size(MAX_EMAIL_ATTACH_BYTES),
        'has_links': bool(plan['link']),
    })


@login_required
@require_http_methods(['POST'])
@rate_limit('send_book_to_entity', max_attempts=20, window_seconds=300, by='user')
def send_book_to_entity(request, book_id):
    """يرسل الكتاب إلى جهته المعنيّة **مع مرفقاته**.

    ما يتجاوز ميزانية الإرفاق يُستبدَل برابط تحميل موقّع محدود المدة في متن
    الرسالة (خوادم البريد ترفض الرسائل الكبيرة).
    """
    from core.models import Book, EmailSettings
    from core.attachment_sharing import collect_book_attachments, human_size
    from core.messaging.engines.smtp import SMTPEngine

    from core.messaging.scoping import scope_books

    book = scope_books(
        Book.objects.filter(is_deleted=False), request.user
    ).filter(pk=book_id).first()
    if book is None:
        return JsonResponse({'success': False, 'message': 'الكتاب غير موجود'}, status=404)

    cfg = EmailSettings.get()
    if not cfg.is_active:
        return JsonResponse({
            'success': False,
            'message': 'إرسال البريد معطّل — فعّله من الإعدادات ← البريد الإلكتروني.',
        }, status=400)

    entity, entity_error = _resolve_book_recipient(book)
    if entity is None:
        return JsonResponse({'success': False, 'message': entity_error}, status=400)

    data = _json_body(request)
    subject = _sanitize_header((data.get('subject') or '').strip())
    if not subject:
        subject, _ = _book_email_defaults(book, entity)

    collected = collect_book_attachments(book, request)

    engine = SMTPEngine(cfg)
    html = engine._render_notification_html(
        book, entity, 'received' if book.is_incoming else 'sent',
    )
    if collected['linked']:
        rows = ''.join(
            f'<li><a href="{f["url"]}">{f["name"]}</a> — {human_size(f["size"])}</li>'
            for f in collected['linked']
        )
        html += (
            '<hr><p><strong>ملفات كبيرة لم تُرفَق بالرسالة</strong> '
            '(تتجاوز حد البريد) — حمّلها من الروابط التالية '
            '(صالحة لمدة محدودة):</p>'
            f'<ul>{rows}</ul>'
        )

    log = engine.send_book_notification(
        book=book,
        recipients=[entity.email],
        subject=subject,
        html_body=html,
        cc=entity.get_cc_list(),
        trigger='manual',
        sent_by=request.user,
        entity=entity,
        attachments=collected['attachments'],
    )

    sent_ok = getattr(log, 'status', '') == 'sent'
    return JsonResponse({
        'success': sent_ok,
        'message': (
            f'أُرسل الكتاب إلى {entity.name} <{entity.email}>'
            if sent_ok else
            f'فشل الإرسال: {getattr(log, "error_msg", "") or "سبب غير معروف"}'
        ),
        'attached': [name for name, _c, _m in collected['attachments']],
        'linked': [{'name': f['name'], 'size_label': human_size(f['size'])}
                   for f in collected['linked']],
        'failed': collected['failed'],
        'attached_label': human_size(collected['attached_bytes']),
    }, status=200 if sent_ok else 502)


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
