"""
core.messaging.api.mail_endpoints
===================================
REST API endpoints for thread-based messaging operations.

Routes (thread-centric):
  POST /mail/api/compose/                  — send new message
  POST /mail/api/inbox/sync/               — trigger IMAP sync manually
  POST /mail/api/inbox/<id>/read/          — mark message as read
  GET  /mail/api/thread/<id>/              — thread details + timeline
  POST /mail/api/thread/<id>/status/       — change thread status
  POST /mail/api/bulk-send/                — bulk send to multiple entities
  GET  /mail/api/template/<id>/preview/    — preview template with book context
  POST /mail/api/settings/test-smtp/       — SMTP test (delegates to email_endpoints)
  POST /mail/api/settings/test-imap/       — IMAP connection test
  GET  /mail/api/stats/                    — email statistics
"""

import json
import logging
import re

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from core.decorators import rate_limit

logger = logging.getLogger('lettersys')

EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$')


def _sanitize_header(value: str) -> str:
    """إزالة أحرف CRLF لمنع Email Header Injection"""
    return value.replace('\r', '').replace('\n', '').replace('\0', '')


def _valid_email(addr: str) -> bool:
    return bool(EMAIL_REGEX.match(addr.strip()))


def _json(request):
    try:
        return json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return {}


# ══════════════════════════════════════════════════════
#  1. Send new message
# ══════════════════════════════════════════════════════

@login_required
@require_http_methods(['POST'])
@rate_limit('mail_compose', max_attempts=20, window_seconds=300, by='user')
def api_compose(request):
    """
    POST JSON:
    {
      "to": "addr@example.com",
      "cc": "copy@example.com",           // optional
      "subject": "Subject",
      "body": "<p>Body</p>",
      "book_id": 42,                       // optional
      "entity_id": 5,                      // optional
      "template_id": 3,                    // optional — overrides subject+body if given
      "thread_id": 7                       // optional — send within existing thread
    }
    """
    from core.models import Book, Entity, EmailTemplate, EmailThread
    from core.messaging.engines.smtp import send_book_notification

    data = _json(request)
    to_addr   = _sanitize_header(data.get('to', '').strip())
    cc_raw    = _sanitize_header(data.get('cc', '').strip())
    subject   = _sanitize_header(data.get('subject', '').strip())
    body      = data.get('body', '').strip()
    book_id   = data.get('book_id')
    entity_id = data.get('entity_id')
    tpl_id    = data.get('template_id')
    thread_id = data.get('thread_id')

    if not to_addr:
        return JsonResponse({'success': False, 'message': 'حقل "إلى" مطلوب'}, status=400)

    if not _valid_email(to_addr):
        return JsonResponse({'success': False, 'message': 'عنوان البريد الإلكتروني غير صالح'}, status=400)

    # Fetch optional entities — الكتاب ضمن نطاق المستخدم لا مطلقاً: وإلاّ عُلّقت
    # الرسالة على كتاب غيره وظهرت في سجلّه.
    from core.messaging.scoping import scope_books

    visible_books = scope_books(Book.objects.all(), request.user)
    book   = visible_books.filter(pk=book_id).first()     if book_id   else None
    entity = Entity.objects.filter(pk=entity_id).first() if entity_id else None

    # كتابٌ طُلب ولم يُحلَّ (غير موجود أو خارج نطاقك) = رفضٌ صريح، لا سقوطٌ
    # صامتٌ إلى إرسالٍ بلا كتاب: المستخدم يظنّ رسالته عُلّقت على كتابه.
    if book_id and book is None:
        return JsonResponse({'success': False, 'message': 'الكتاب غير موجود'}, status=404)

    # Template overrides subject+body if given
    if tpl_id:
        tpl = EmailTemplate.objects.filter(pk=tpl_id, is_active=True).first()
        if tpl:
            ctx = {'book': book, 'entity': entity, 'user': request.user}
            subject = tpl.render_subject(ctx)
            body    = tpl.render_body(ctx)

    if not subject or not body:
        return JsonResponse({'success': False, 'message': 'الموضوع والنص مطلوبان'}, status=400)

    # لا سقوطَ إلى «أوّل كتابٍ في القاعدة»: ``BookEmailLog.book`` صار اختياريّاً
    # (هجرة 0061)، فالرسالة بلا كتابٍ تُسجَّل بلا كتاب بدل أن تُعلَّق على كتابٍ
    # لا صلة له بها.

    cc_list = [x.strip() for x in cc_raw.split(',') if x.strip()] if cc_raw else []

    try:
        log = send_book_notification(
            book=book,
            recipients=[to_addr],
            subject=subject,
            html_body=body,
            cc=cc_list,
            trigger='manual',
            sent_by=request.user,
            entity=entity,
        )

        # Link to existing thread or create new one
        if thread_id:
            thread = EmailThread.objects.filter(pk=thread_id).first()
        else:
            thread = EmailThread.objects.create(
                book=book if book_id else None,
                entity=entity,
                created_by=request.user,
                subject=subject,
                status=EmailThread.STATUS_WAITING,
            )

        if log and thread:
            log.thread = thread
            log.save(update_fields=['thread'])

        return JsonResponse({
            'success': True,
            'message': f'تم الإرسال إلى {to_addr}',
            'thread_id': thread.pk if thread else None,
        })

    except Exception as e:
        logger.exception(f"mail_api compose error: {e}")
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


# ══════════════════════════════════════════════════════
#  2. Manual IMAP sync
# ══════════════════════════════════════════════════════

@login_required
@require_http_methods(['POST'])
@rate_limit('inbox_sync', max_attempts=5, window_seconds=60, by='user')
def api_inbox_sync(request):
    """Trigger IMAP sync immediately and return stats."""
    if not request.user.is_staff:
        return JsonResponse({'success': False, 'message': 'غير مصرح'}, status=403)
    try:
        from core.messaging.engines.imap import sync_inbox
        stats = sync_inbox()
        return JsonResponse({'success': True, **stats})
    except Exception as e:
        logger.exception(f"IMAP sync error: {e}")
        return JsonResponse({'success': False, 'message': str(e)}, status=500)


# ══════════════════════════════════════════════════════
#  3. Mark message as read
# ══════════════════════════════════════════════════════

@login_required
@require_http_methods(['POST'])
def api_mark_read(request, pk):
    from core.models import IncomingEmail, EmailSettings
    from core.messaging.scoping import scope_incoming

    # كانت تؤشّر **أيّ** رسالةٍ برقمها مقروءةً — كتابةٌ على بريد غيرك.
    msg = scope_incoming(IncomingEmail.objects.all(), request.user).filter(pk=pk).first()
    if not msg:
        return JsonResponse({'success': False, 'message': 'الرسالة غير موجودة'}, status=404)

    msg.is_read = True
    msg.save(update_fields=['is_read'])

    # Best-effort IMAP mark
    try:
        from core.messaging.engines.imap import IMAPEngine
        cfg = EmailSettings.get()
        if cfg.imap_sync_enabled and msg.imap_uid:
            engine = IMAPEngine(cfg)
            engine.mark_as_read(msg.imap_uid)
    except Exception:
        pass

    return JsonResponse({'success': True})


# ══════════════════════════════════════════════════════
#  4. Thread details
# ══════════════════════════════════════════════════════

@login_required
def api_thread_detail(request, pk):
    from core.models import EmailThread
    from core.messaging.scoping import scope_threads

    # كانت تُعيد مواضيع الخيط وعناوين مراسليه لأيّ مستخدمٍ برقم الخيط.
    thread = scope_threads(EmailThread.objects.all(), request.user).filter(pk=pk) \
        .select_related('book', 'entity', 'created_by').first()
    if not thread:
        return JsonResponse({'success': False, 'message': 'الخيط غير موجود'}, status=404)

    sent = list(thread.sent_emails.select_related('sent_by').values(
        'id', 'subject', 'to_address', 'cc_addresses',
        'status', 'trigger', 'sent_at', 'sent_by__username',
    ))
    received = list(thread.incoming_emails.values(
        'id', 'from_address', 'from_name', 'subject',
        'is_read', 'received_at',
    ))

    return JsonResponse({
        'success': True,
        'thread': {
            'id':      thread.pk,
            'subject': thread.subject,
            'status':  thread.status,
            'book':    {'id': thread.book.pk, 'number': thread.book.our_number, 'title': thread.book.title} if thread.book else None,
            'entity':  {'id': thread.entity.pk, 'name': thread.entity.name} if thread.entity else None,
        },
        'sent':     sent,
        'received': received,
    })


# ══════════════════════════════════════════════════════
#  5. Change thread status
# ══════════════════════════════════════════════════════

@login_required
@require_http_methods(['POST'])
def api_thread_status(request, pk):
    from core.models import EmailThread
    data   = _json(request)
    status = data.get('status', '')
    valid  = [s for s, _ in EmailThread.STATUS_CHOICES]

    if status not in valid:
        return JsonResponse({'success': False, 'message': f'حالة غير صالحة. الخيارات: {valid}'}, status=400)

    from core.messaging.scoping import scope_threads

    # كانت تغيّر حالة **أيّ** خيطٍ برقمه — كتابةٌ على مراسلات غيرك.
    updated = scope_threads(EmailThread.objects.all(), request.user) \
        .filter(pk=pk).update(status=status)
    if not updated:
        return JsonResponse({'success': False, 'message': 'الخيط غير موجود'}, status=404)

    return JsonResponse({'success': True, 'status': status})


# ══════════════════════════════════════════════════════
#  6. Bulk send
# ══════════════════════════════════════════════════════

@login_required
@require_http_methods(['POST'])
@rate_limit('bulk_mail_send', max_attempts=5, window_seconds=300, by='user')
def api_bulk_send(request):
    """
    POST JSON:
    {
      "entity_ids": [1, 2, 3],
      "book_id": 42,            // optional
      "subject": "...",
      "body": "<p>...</p>",
      "template_id": 3          // optional — overrides subject+body
    }
    """
    from core.models import Entity, Book, EmailTemplate
    from core.messaging.engines.smtp import send_book_notification

    data       = _json(request)
    entity_ids = data.get('entity_ids', [])
    book_id    = data.get('book_id')
    subject    = data.get('subject', '').strip()
    body       = data.get('body', '').strip()
    tpl_id     = data.get('template_id')

    if not entity_ids:
        return JsonResponse({'success': False, 'message': 'entity_ids مطلوب'}, status=400)

    from core.messaging.scoping import scope_books

    visible_books = scope_books(Book.objects.all(), request.user)
    # اختياريّ: إرسالٌ جماعيّ لجهاتٍ قد لا يخصّ كتاباً بعينه (انظر هجرة 0061).
    book = visible_books.filter(pk=book_id).first() if book_id else None

    entities = Entity.objects.filter(pk__in=entity_ids, email__gt='')
    results  = {'sent': 0, 'skipped': 0, 'errors': []}

    for entity in entities:
        try:
            s, b = subject, body
            if tpl_id:
                tpl = EmailTemplate.objects.filter(pk=tpl_id, is_active=True).first()
                if tpl:
                    ctx = {'book': book, 'entity': entity, 'user': request.user}
                    s = tpl.render_subject(ctx)
                    b = tpl.render_body(ctx)
            if not s or not b:
                results['skipped'] += 1
                continue
            send_book_notification(
                book=book, recipients=[entity.email],
                subject=s, html_body=b,
                trigger='manual', sent_by=request.user, entity=entity,
            )
            results['sent'] += 1
        except Exception as e:
            results['errors'].append({'entity': entity.name, 'error': str(e)})
            logger.exception(f"bulk_send error for {entity.email}: {e}")

    return JsonResponse({'success': True, **results})


# ══════════════════════════════════════════════════════
#  7. Template preview
# ══════════════════════════════════════════════════════

@login_required
def api_template_preview(request, pk):
    from core.models import EmailTemplate, Book, Entity
    tpl = EmailTemplate.objects.filter(pk=pk).first()
    if not tpl:
        return JsonResponse({'success': False, 'message': 'القالب غير موجود'}, status=404)

    from core.messaging.scoping import scope_books

    book_id   = request.GET.get('book_id')
    entity_id = request.GET.get('entity_id')
    # القالب يُصيَّر برقم الكتاب وعنوانه — فمعاينةٌ بكتابِ غيرك تُسرّبهما.
    book   = scope_books(Book.objects.all(), request.user).filter(pk=book_id).first() if book_id else None
    entity = Entity.objects.filter(pk=entity_id).first() if entity_id else None

    ctx = {'book': book, 'entity': entity, 'user': request.user}
    return JsonResponse({
        'success': True,
        'subject': tpl.render_subject(ctx),
        'body':    tpl.render_body(ctx),
    })


# ══════════════════════════════════════════════════════
#  8. SMTP test — delegates to email_endpoints (no duplicate)
# ══════════════════════════════════════════════════════

@login_required
@require_http_methods(['POST'])
def api_test_smtp(request):
    """Delegates to canonical email_endpoints.test_smtp to avoid duplication.

    لا محدِّد معدّل هنا عمداً: النقطة الأصلية تحمله بنفس المفتاح، فكان وجوده في
    الطرفين يستهلك محاولتين لكل نقرة واحدة ويُنفِد الحصّة قبل أوانها.
    """
    if not request.user.is_staff:
        return JsonResponse({'success': False, 'message': 'غير مصرح'}, status=403)
    from core.messaging.api.email_endpoints import test_smtp
    return test_smtp(request)


# ══════════════════════════════════════════════════════
#  9. IMAP test
# ══════════════════════════════════════════════════════

@login_required
@require_http_methods(['POST'])
@rate_limit('test_imap', max_attempts=20, window_seconds=300, by='user')
def api_test_imap(request):
    if not request.user.is_staff:
        return JsonResponse({'success': False, 'message': 'غير مصرح'}, status=403)
    from core.models import EmailSettings
    from core.messaging.engines.imap import test_imap_connection
    cfg = EmailSettings.get()
    result = test_imap_connection(cfg)
    return JsonResponse(result)


# ══════════════════════════════════════════════════════
#  10. Email statistics
# ══════════════════════════════════════════════════════

@login_required
def api_mail_stats(request):
    from django.db.models import Count, Q
    from core.models import BookEmailLog, IncomingEmail, EmailThread

    from core.messaging.scoping import scope_incoming, scope_sent_logs, scope_threads

    # استعلام واحد لكل نموذج بدلاً من استعلامات منفصلة لكل حالة.
    # كلّها على المجموعة المرئيّة للمستخدم: عدّادٌ عامٌّ يكشف حجم مراسلات
    # الأقسام الأخرى ولو أُخفيت قوائمها.
    email_stats = scope_sent_logs(BookEmailLog.objects.all(), request.user).aggregate(
        sent_total=Count('id'),
        sent_ok=Count('id', filter=Q(status='sent')),
        sent_failed=Count('id', filter=Q(status='failed')),
        sent_pending=Count('id', filter=Q(status='pending')),
    )
    inbox_stats = scope_incoming(IncomingEmail.objects.all(), request.user).aggregate(
        inbox_total=Count('id'),
        inbox_unread=Count('id', filter=Q(is_read=False)),
    )
    thread_stats = scope_threads(EmailThread.objects.all(), request.user).aggregate(
        threads_open=Count('id', filter=Q(status='open')),
        threads_wait=Count('id', filter=Q(status='waiting')),
    )

    return JsonResponse({
        'success': True,
        **email_stats,
        **inbox_stats,
        **thread_stats,
    })
