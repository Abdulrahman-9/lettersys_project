"""
core.messaging.views.ui
========================
Web UI views for the mail section of LetterSys.

URL patterns:
  /mail/                     → hub (redirect → sent)
  /mail/sent/                → Sent messages
  /mail/inbox/               → Inbox
  /mail/compose/             → Compose new message
  /mail/compose/<book_id>/   → Compose linked to a book (pre-filled)
  /mail/thread/<id>/         → Thread view
  /mail/settings/            → SMTP + IMAP settings (staff)
  /mail/templates/           → Manage templates (staff)
  /mail/templates/new/       → Create template
  /mail/templates/<id>/edit/ → Edit template
  /mail/templates/<id>/delete/ → Delete template
"""

import logging
import re

from django.contrib import messages
from django.contrib.auth.decorators import login_required

from core.views.helpers import staff_required
from django.core.paginator import Paginator
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

logger = logging.getLogger('lettersys')


# ══════════════════════════════════════════════════════
#  Hub
# ══════════════════════════════════════════════════════

@login_required
def mail_hub(request):
    """Redirect to sent mail view."""
    return redirect('mail_sent')


# ══════════════════════════════════════════════════════
#  Sent
# ══════════════════════════════════════════════════════

@login_required
def mail_sent(request):
    from core.models import BookEmailLog, Entity
    from core.messaging.scoping import mailable_book, scope_sent_logs

    # النطاق أوّلاً ثم المرشّحات، والإحصاءات أدناه على المصفَّى نفسه — كي لا
    # يُسرّب العدّادُ ما تُخفيه القائمة.
    logs = BookEmailLog.objects.select_related('book', 'entity', 'sent_by', 'thread')
    qs = scope_sent_logs(logs, request.user).order_by('-sent_at')

    # «عرض كل المراسلات ←» من صفحة الكتاب (`?book=`) — كان الرابطُ يُمرَّر ولا
    # يُقرأ فيفتح الصادرَ كلَّه. المجموعةُ هنا هي **ما تعرضه بطاقةُ الكتاب نفسُها**
    # (email/logs ببوّابة `mailable_book`) لا أضيقَ منها: نطاقُ «صادري» يُحسب
    # بمُنشئ الكتاب، فزميلُ القسم كان يرى البطاقةَ ملأى والرابطَ فارغاً.
    book_filter = None
    if request.GET.get('book'):
        book_filter = mailable_book(request.user, request.GET.get('book'))
        qs = (logs.filter(book=book_filter).order_by('-sent_at')
              if book_filter is not None else logs.none())

    status_filter  = request.GET.get('status', '')
    entity_filter  = request.GET.get('entity', '')
    trigger_filter = request.GET.get('trigger', '')
    search         = request.GET.get('q', '').strip()

    if status_filter:
        qs = qs.filter(status=status_filter)
    if entity_filter:
        qs = qs.filter(entity_id=entity_filter)
    if trigger_filter:
        qs = qs.filter(trigger=trigger_filter)
    if search:
        qs = qs.filter(subject__icontains=search) | \
             qs.filter(to_address__icontains=search)

    paginator = Paginator(qs, 25)
    page      = paginator.get_page(request.GET.get('page'))
    entities  = Entity.objects.filter(is_active=True).order_by('name')

    visible = scope_sent_logs(BookEmailLog.objects.all(), request.user)
    stats = {
        'total':   visible.count(),
        'sent':    visible.filter(status='sent').count(),
        'failed':  visible.filter(status='failed').count(),
        'pending': visible.filter(status='pending').count(),
    }

    return render(request, 'core/mail/hub.html', {
        'active_tab':     'sent',
        'page_obj':       page,
        'entities':       entities,
        'stats':          stats,
        'status_filter':  status_filter,
        'entity_filter':  entity_filter,
        'trigger_filter': trigger_filter,
        'search':         search,
        'book_filter':    book_filter,
        'STATUS_CHOICES':  BookEmailLog.STATUS_CHOICES,
        'TRIGGER_CHOICES': BookEmailLog.TRIGGER_CHOICES,
    })


# ══════════════════════════════════════════════════════
#  Inbox
# ══════════════════════════════════════════════════════

#: أقلّ فاصل بين مزامنتين تلقائيتين عند فتح الوارد.
INBOX_SYNC_COOLDOWN_SECONDS = 120


#: قفلٌ يمنع مزامنتين متزامنتين — انظر ``_autosync_inbox_if_due``.
INBOX_SYNC_LOCK_KEY = 'lock:inbox_autosync'


def _autosync_inbox_if_due():
    """يجلب الردود عند فتح صفحة الوارد — بلا Celery ولا Redis.

    «المزامنة التلقائية» كانت وعداً بلا جدول: ``sync_inbox_task`` موجودة لكنها لم
    تكن مُدرَجة في ``CELERY_BEAT_SCHEDULE``، وCelery يحتاج Redis غير المتاح على
    كل نشر. فنجلب هنا عند الفتح — وهو الوقت الذي يهمّ فيه المستخدم فعلاً.

    **القطيع (سجلّ العيوب م1):** كانت البوّابة تقرأ ``imap_last_sync`` وهو ختمٌ
    لا يُكتب إلّا **بعد** انتهاء المزامنة. فكلّ الطلبات الواصلة أثناء مزامنةٍ
    جارية (وهي ثوانٍ على شبكةٍ بطيئة) تجتاز البوّابة معاً وتفتح اتصالات IMAP
    متوازية. لا يظهر ذلك بمستخدمٍ واحد، ويظهر يقيناً بقسمٍ كامل — وهذا بالضبط
    ما يرفع التعميمُ سترَه.

    فحارسان: قفلٌ ذرّيّ يُؤخَذ **قبل** العمل (``cache.add`` عمليّةٌ ذرّيّة
    بخلاف ``get`` ثمّ ``set``)، وختمُ تبريدٍ يُكتب عند **البدء** لا عند الانتهاء.

    قيدٌ موثَّق: على LocMemCache القفل لكلّ عمليّة لا لكلّ الخادم — الضمان
    الكامل يأتي مع Redis (مرحلة ز0). وأيّ فشلٍ لا يجوز أن يمنع عرض الصندوق.
    """
    from django.core.cache import cache

    from core.models import EmailSettings
    from core.messaging.engines.imap import IMAPEngine

    try:
        cfg = EmailSettings.get()
        if not cfg.imap_sync_enabled:
            return

        last = cfg.imap_last_sync
        if last and (timezone.now() - last).total_seconds() < INBOX_SYNC_COOLDOWN_SECONDS:
            return

        if not cache.add(INBOX_SYNC_LOCK_KEY, 1, timeout=INBOX_SYNC_COOLDOWN_SECONDS):
            return   # مزامنةٌ جارية الآن — لا نفتح ثانيةً بجانبها.

        try:
            # الختم عند البدء: يُغلق نافذة القطيع حتى لو تعثّرت المزامنة.
            cfg.imap_last_sync = timezone.now()
            cfg.save(update_fields=['imap_last_sync'])

            stats = IMAPEngine(cfg).sync_inbox()
            logger.info(f"[mail_inbox] مزامنة عند الفتح: {stats}")
        finally:
            cache.delete(INBOX_SYNC_LOCK_KEY)
    except Exception as e:
        # الصندوق يُعرَض من قاعدة البيانات على أي حال — لا نُسقط الصفحة لأجل IMAP.
        logger.warning(f"[mail_inbox] تعذّرت المزامنة عند الفتح — {e}")


@login_required
def mail_inbox(request):
    from core.models import IncomingEmail
    from core.messaging.scoping import scope_incoming

    _autosync_inbox_if_due()

    qs = scope_incoming(
        IncomingEmail.objects.select_related('thread', 'thread__book', 'thread__entity'),
        request.user,
    ).order_by('-received_at')

    read_filter = request.GET.get('read', '')
    search      = request.GET.get('q', '').strip()

    if read_filter == '0':
        qs = qs.filter(is_read=False)
    elif read_filter == '1':
        qs = qs.filter(is_read=True)
    if search:
        qs = qs.filter(subject__icontains=search) | \
             qs.filter(from_address__icontains=search)

    paginator    = Paginator(qs, 25)
    page         = paginator.get_page(request.GET.get('page'))
    unread_count = scope_incoming(
        IncomingEmail.objects.filter(is_read=False), request.user
    ).count()

    from core.scoping import can_manage_system

    return render(request, 'core/mail/hub.html', {
        'active_tab':   'inbox',
        'page_obj':     page,
        'unread_count': unread_count,
        # زرُّ «مزامنة الآن» بوّابةُ فعلٍ تُحسَب في العرض لا في القالب (§7.6).
        'can_sync_mail': can_manage_system(request.user),
        'read_filter':  read_filter,
        'search':       search,
    })


# ══════════════════════════════════════════════════════
#  Compose
# ══════════════════════════════════════════════════════

_REPLY_PREFIX = re.compile(r'^\s*(re|رد|ردّ)\s*:', re.IGNORECASE)


def reply_subject(subject):
    """«رد: …» مرّةً واحدة، وبطول عمود السجلّ — موضوعُ الخيط 300 وسجلُّ الإرسال 255،
    فبادئةٌ على موضوعٍ طويلٍ كانت ستكسر الحفظ."""
    from core.models import BookEmailLog

    s = (subject or '').strip()
    if not _REPLY_PREFIX.match(s):
        s = 'رد: ' + s
    return s[:BookEmailLog._meta.get_field('subject').max_length]


def _reply_address(thread):
    """إلى مَن يُردّ: عنوانُ ردّ آخر وارد، ثمّ مرسِلُه، ثمّ أوّلُ مستلمي آخر صادر، ثمّ بريدُ الجهة."""
    last_in = thread.incoming_emails.order_by('-received_at').first()
    if last_in and (last_in.reply_to or last_in.from_address):
        return (last_in.reply_to or last_in.from_address).strip()
    last_out = thread.sent_emails.order_by('-sent_at').first()
    if last_out and last_out.to_address:
        return last_out.to_address.split(',')[0].strip()
    return (thread.entity.email if thread.entity_id else '') or ''


@login_required
def mail_compose(request, book_id=None):
    from core.models import Entity, EmailTemplate, EmailSettings
    from core.messaging.scoping import mailable_book, repliable_thread

    # «رد» من صفحة الخيط: ``?thread=`` كان يُهمَل فيُفتح نموذجٌ فارغ ويبدأ الإرسالُ خيطاً
    # جديداً (تدقيقُ نيلسن E#2). الردُّ يرث كتابَ خيطه؛ والخيطُ خارج النطاق «غير موجود».
    thread = None
    if request.GET.get('thread'):
        thread = repliable_thread(request.user, request.GET.get('thread'))
        if thread is None:
            raise Http404('المراسلة غير موجودة')
        if thread.book_id:
            book_id = thread.book_id

    book = None
    if book_id:
        # كتابُ غيرِك «غير موجود» لا «ممنوع»، فلا يُسرَّب وجودُه من فرق الرمزين.
        # والموضوعُ أدناه يُعبَّأ بالعنوان — فالسرّيُّ المغلقُ «غير موجود» أيضاً.
        book = mailable_book(request.user, book_id)
        if book is None:
            raise Http404('الكتاب غير موجود')

    entities  = Entity.objects.filter(is_active=True, email__gt='').order_by('name')
    templates = EmailTemplate.objects.filter(is_active=True).order_by('name')
    cfg       = EmailSettings.get()

    prefill = {}
    if book:
        related_entities = list(
            book.issuing_entities.filter(email__gt='') |
            book.receiving_entities.filter(email__gt='')
        )
        if related_entities:
            prefill['to']        = related_entities[0].email
            prefill['entity_id'] = related_entities[0].pk
        prefill['subject'] = f"بشأن كتاب رقم {book.our_number or ''} — {book.title}"
    if thread:
        reply_to = _reply_address(thread)
        if reply_to:
            prefill['to'] = reply_to
        prefill['entity_id'] = thread.entity_id or prefill.get('entity_id')
        prefill['subject'] = reply_subject(thread.subject)

    return render(request, 'core/mail/hub.html', {
        'active_tab': 'compose',
        'thread':     thread,
        'book':       book,
        'entities':   entities,
        'templates':  templates,
        'prefill':    prefill,
        'cfg':        cfg,
        'smtp_ok':    cfg.is_active,
    })


# ══════════════════════════════════════════════════════
#  Thread view
# ══════════════════════════════════════════════════════

@login_required
def mail_thread(request, thread_id):
    from core.models import EmailThread
    from core.messaging.scoping import can_view_thread

    thread = get_object_or_404(
        EmailThread.objects.select_related('book', 'entity', 'created_by'),
        pk=thread_id
    )
    if not can_view_thread(thread, request.user):
        # 403 لا 404 هنا عن قصد — على خلاف الكتب أعلاه: الخيط يُفتح من رابطٍ
        # قديم أو مشارَك، فرسالةٌ صريحة أنفع من «غير موجود»، ووجودُ رقم خيطٍ
        # ليس سرّاً. (صفحةُ الكتاب نفسُها صارت 404 — رقمُ الكتاب هويّةُ مستند.)
        # PermissionDenied لا نصٌّ عارٍ: صفحةُ 403 داخل القشرة بزرّ عودة (تدقيقُ نيلسن E#18)
        raise PermissionDenied("غير مصرح لك بالاطّلاع على هذه المراسلة")

    sent_emails = thread.sent_emails.select_related('sent_by').order_by('sent_at')
    received    = thread.incoming_emails.order_by('received_at')

    # Merge sent + received into chronological timeline
    timeline = []
    for m in sent_emails:
        timeline.append({'type': 'sent', 'obj': m, 'at': m.sent_at})
    for m in received:
        timeline.append({'type': 'received', 'obj': m, 'at': m.received_at})
    timeline.sort(key=lambda x: x['at'])

    # Mark unread messages as read
    unread = received.filter(is_read=False)
    if unread.exists():
        unread.update(is_read=True)
        # Best-effort IMAP mark
        try:
            from core.models import EmailSettings
            from core.messaging.engines.imap import IMAPEngine
            cfg = EmailSettings.get()
            if cfg.imap_sync_enabled:
                engine = IMAPEngine(cfg)
                for inc in unread:
                    if inc.imap_uid:
                        engine.mark_as_read(inc.imap_uid)
        except Exception:
            pass

    return render(request, 'core/mail/hub.html', {
        'active_tab': 'thread',
        'thread':     thread,
        'timeline':   timeline,
    })


# ══════════════════════════════════════════════════════
#  Settings (staff only)
# ══════════════════════════════════════════════════════

@login_required
@staff_required
def mail_settings(request):
    from core.models import EmailSettings
    cfg = EmailSettings.get()

    if request.method == 'POST':
        _update_email_settings(cfg, request.POST)
        messages.success(request, "تم حفظ الإعدادات بنجاح")
        return redirect('mail_settings')

    return render(request, 'core/mail/hub.html', {
        'active_tab': 'settings',
        'cfg':        cfg,
    })


def _update_email_settings(cfg, data):
    """Update EmailSettings fields from POST data."""
    str_fields  = [
        'org_name', 'org_section', 'org_unit', 'org_email', 'reply_to', 'email_signature',
        'smtp_host', 'smtp_user', 'smtp_password',
        'imap_host', 'imap_user', 'imap_password', 'imap_folder',
    ]
    int_fields  = ['smtp_port', 'imap_port']
    bool_fields = [
        'smtp_use_tls', 'smtp_use_ssl', 'imap_use_ssl',
        'is_active', 'send_on_save', 'imap_sync_enabled',
    ]

    for f in str_fields:
        val = data.get(f, '').strip()
        # Do not clear password if empty value submitted
        if f in ('smtp_password', 'imap_password') and not val:
            continue
        setattr(cfg, f, val)

    for f in int_fields:
        try:
            setattr(cfg, f, int(data.get(f, getattr(cfg, f))))
        except (ValueError, TypeError):
            pass

    for f in bool_fields:
        setattr(cfg, f, f in data)  # checkbox present → True

    cfg.save()


# ══════════════════════════════════════════════════════
#  Templates (staff only)
# ══════════════════════════════════════════════════════

@login_required
@staff_required
def mail_templates(request):
    from core.models import EmailTemplate
    templates = EmailTemplate.objects.order_by('applicable_kind', 'name')

    return render(request, 'core/mail/hub.html', {
        'active_tab': 'templates',
        'templates':  templates,
    })


@login_required
@require_http_methods(['GET', 'POST'])
@staff_required
def mail_template_edit(request, template_id=None):
    """Create new template or edit existing one."""
    from core.models import EmailTemplate
    instance = None
    if template_id:
        instance = get_object_or_404(EmailTemplate, pk=template_id)

    if request.method == 'POST':
        data    = request.POST
        name    = data.get('name', '').strip()
        slug    = data.get('slug', '').strip()
        kind    = data.get('applicable_kind', 'any')
        subj    = data.get('subject_template', '').strip()
        body    = data.get('body_html', '').strip()
        active  = 'is_active'  in data
        default = 'is_default' in data

        if not name or not slug or not subj or not body:
            messages.error(request, "جميع الحقول مطلوبة")
        else:
            if instance:
                instance.name              = name
                instance.slug              = slug
                instance.applicable_kind   = kind
                instance.subject_template  = subj
                instance.body_html         = body
                instance.is_active         = active
                instance.is_default        = default
                instance.save()
                messages.success(request, f"تم تعديل القالب «{name}»")
            else:
                EmailTemplate.objects.create(
                    name=name, slug=slug, applicable_kind=kind,
                    subject_template=subj, body_html=body,
                    is_active=active, is_default=default,
                    created_by=request.user,
                )
                messages.success(request, f"تم إنشاء القالب «{name}»")
            return redirect('mail_templates')

    return render(request, 'core/mail/hub.html', {
        'active_tab':   'template_edit',
        'instance':     instance,
        'KIND_CHOICES': [('any', 'كل الأنواع'), ('incoming', 'وارد'), ('outgoing', 'صادر')],
    })


@login_required
@require_http_methods(['POST'])
def mail_template_delete(request, template_id):
    if not request.user.is_staff:
        raise PermissionDenied("حذفُ القوالب لمديري النظام.")
    from core.models import EmailTemplate
    tpl  = get_object_or_404(EmailTemplate, pk=template_id)
    name = tpl.name
    tpl.delete()
    messages.success(request, f"تم حذف القالب «{name}»")
    return redirect('mail_templates')
