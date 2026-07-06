"""
===================================================
Celery Tasks للمعالجة غير المتزامنة
===================================================

مهام معالجة البيانات في الخلفية
"""

from celery import shared_task, group, chain, chord
from celery.utils.log import get_task_logger
import logging
from datetime import datetime, timedelta

from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.html import strip_tags

from .models import Attachment, DataExtractionResult, Book, ExtractionFeedback
from .extraction.pipeline import AIExtractionService, process_extraction_task

logger = get_task_logger(__name__)


# ===================================================
# المهام الأساسية
# ===================================================

@shared_task(bind=True, max_retries=3)
def process_image_extraction(self, attachment_id: int):
    """
    معالجة استخراج بيانات من صورة واحدة
    
    Args:
        attachment_id: معرف المرفق
    
    Returns:
        dict: نتائج المعالجة
    """
    try:
        logger.info(f"بدء معالجة المرفق {attachment_id}")
        
        attachment = Attachment.objects.get(id=attachment_id)
        service = AIExtractionService()
        
        success, message, data = service.process_attachment(attachment)
        
        if success:
            logger.info(f"✅ تم استخراج البيانات من المرفق {attachment_id} بنجاح")
            return {
                'success': True,
                'attachment_id': attachment_id,
                'message': message,
                'confidence': data.get('overall_confidence', 0) if data else 0
            }
        else:
            logger.warning(f"⚠️ فشل الاستخراج للمرفق {attachment_id}: {message}")
            return {
                'success': False,
                'attachment_id': attachment_id,
                'message': message,
                'error': True
            }
    
    except Attachment.DoesNotExist:
        logger.error(f"❌ المرفق {attachment_id} غير موجود")
        return {
            'success': False,
            'attachment_id': attachment_id,
            'message': f'المرفق {attachment_id} غير موجود'
        }

    except Exception as exc:
        logger.error(f"❌ خطأ في معالجة المرفق {attachment_id}: {str(exc)}")
        try:
            raise self.retry(exc=exc, countdown=60, max_retries=3)
        except self.MaxRetriesExceededError:
            return {
                'success': False,
                'attachment_id': attachment_id,
                'message': f'فشل بعد 3 محاولات: {str(exc)}'
            }


# ===================================================
# مهام مختصرة للاستخراج عبر Celery
# ===================================================

@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={'max_retries': 3})
def process_attachment_extraction(self, attachment_id: int):
    """Run AI extraction for an existing attachment."""
    try:
        attachment = Attachment.objects.get(id=attachment_id)
    except Attachment.DoesNotExist:
        logger.error("Attachment %s not found", attachment_id)
        return {'status': 'error', 'message': 'attachment not found'}

    image_path = attachment.file.path
    logger.info("[Celery] Starting extraction for attachment %s", attachment_id)
    result = process_extraction_task(image_path=image_path, attachment_id=attachment_id)
    logger.info("[Celery] Finished extraction for attachment %s", attachment_id)
    return result


@shared_task(bind=True)
def process_image_path(self, image_path: str, attachment_id: int | None = None):
    """Process an arbitrary image path (ad-hoc)."""
    logger.info("[Celery] Processing image path %s", image_path)
    return process_extraction_task(image_path=image_path, attachment_id=attachment_id)


# ===================================================
# مهام حجز أرقام القيود
# ===================================================

@shared_task
def cleanup_expired_reservations():
    """
    تُشغَّل كل 15 دقيقة.
    تُحوّل الحجوزات التي انتهت مهلتها إلى حالة 'expired'.
    """
    from django.utils import timezone
    from .models import BookNumberReservation

    now = timezone.now()
    expired = BookNumberReservation.objects.filter(
        status__in=[BookNumberReservation.STATUS_ACTIVE, BookNumberReservation.STATUS_REACTIVATED],
        expires_at__lt=now
    )
    count = expired.count()
    if count:
        expired.update(
            status=BookNumberReservation.STATUS_EXPIRED,
            void_reason=BookNumberReservation.VOID_REASON_TIMEOUT,
            voided_at=now
        )
        logger.info(f'[Reservation] Expired {count} reservations')
    return {'expired': count}


@shared_task
def notify_year_end():
    """
    تُشغَّل يومياً في ديسمبر.
    تُرسل تنبيهاً للمشرفين إذا كان تاريخ نهاية السنة قريباً.
    """
    from django.utils import timezone
    from django.contrib.auth.models import User
    from .models import BookSequence, BookNumberReservation

    now = timezone.now()
    if now.month != 12:
        return {'skipped': True}

    days_left = (31 - now.day)

    if days_left not in [7, 3, 1, 0]:
        return {'skipped': True, 'days_left': days_left}

    # إحصاء آخر رقم لكل سلسلة
    sequences = BookSequence.objects.all()
    summary_lines = [
        f"  • {seq}: آخر قيد = {seq.next_number - 1}"
        for seq in sequences
    ]
    summary = '\n'.join(summary_lines)

    msg = (
        f"⚠️ تنبيه نهاية السنة — متبقي {days_left} يوم/أيام على انتهاء {now.year}\n\n"
        f"سيبدأ النظام تلقائياً تسلسل {now.year + 1} في 1 يناير.\n\n"
        f"ملخص التسلسلات الحالية:\n{summary}"
    )

    admins = User.objects.filter(is_staff=True, is_active=True)
    for admin in admins:
        if admin.email:
            try:
                send_mail(
                    subject=f'[نظام الكتب] تنبيه نهاية السنة {now.year}',
                    message=msg,
                    from_email=None,
                    recipient_list=[admin.email],
                    fail_silently=True,
                )
            except Exception as e:
                logger.warning(f'[YearEnd] Email failed for {admin.email}: {e}')

    logger.info(f'[YearEnd] Notified {admins.count()} admins. {days_left} days left.')
    return {'notified': admins.count(), 'days_left': days_left}


@shared_task
def reset_sequences_new_year():
    """
    تُشغَّل في 1 يناير الساعة 00:05.
    تُؤرشف تسلسلات السنة المنتهية وتبدأ سلاسل السنة الجديدة.
    """
    from django.utils import timezone
    from .models import BookSequence, BookNumberReservation

    now  = timezone.now()
    year = now.year

    # لا تُنفَّذ إلا في يناير
    if now.month != 1:
        return {'skipped': True}

    sequences = BookSequence.objects.all()
    reset_count = 0
    for seq in sequences:
        old_val = seq.next_number
        if old_val > 1:  # لا تُعيد تعيين ما لم يبدأ
            seq.next_number = 1
            seq.save(update_fields=['next_number', 'updated_at'])
            reset_count += 1
            logger.info(f'[YearReset] {seq.kind}: reset from {old_val} to 1 for year {year}')

    # إلغاء أي حجوزات نشطة من السنة الماضية
    old_reservations = BookNumberReservation.objects.filter(
        status__in=[BookNumberReservation.STATUS_ACTIVE, BookNumberReservation.STATUS_REACTIVATED],
        year__lt=year
    )
    old_count = old_reservations.count()
    old_reservations.update(
        status=BookNumberReservation.STATUS_EXPIRED,
        void_reason=BookNumberReservation.VOID_REASON_YEAR_RESET,
        voided_at=now
    )

    logger.info(f'[YearReset] Reset {reset_count} sequences. Voided {old_count} old reservations.')
    return {'reset_sequences': reset_count, 'voided_reservations': old_count}


# ===================================================
# مهام البريد الإلكتروني (IMAP + إعادة إرسال)
# ===================================================

@shared_task(name='core.tasks.sync_inbox_task', ignore_result=True)
def sync_inbox_task():
    """
    مزامنة البريد الوارد عبر IMAP — تُشغَّل كل 10 دقائق عبر Celery Beat.
    لا تعمل إذا كانت إعدادات IMAP غير مفعّلة.
    """
    try:
        from .messaging.engines.imap import sync_inbox
        stats = sync_inbox()
        logger.info(f"IMAP sync task: {stats}")
        # مسح كاش badge الوارد
        from django.core.cache import cache
        cache.delete('mail_inbox_unread')
        return stats
    except Exception as e:
        logger.exception(f"sync_inbox_task error: {e}")
        return {'error': str(e)}


@shared_task(name='core.tasks.retry_failed_emails_task', ignore_result=True)
def retry_failed_emails_task():
    """
    إعادة إرسال الإيميلات الفاشلة أو المعلّقة — تُشغَّل كل 30 دقيقة.
    تحاول مرة واحدة فقط لكل سجل (تجنب حلقة لانهائية).
    """
    from datetime import timedelta
    from django.utils import timezone
    from .models import BookEmailLog, EmailSettings
    from .messaging.engines.smtp import send_book_notification

    cfg = EmailSettings.get()
    if not cfg.is_active:
        return {'skipped': 'email not active'}

    # إيميلات فاشلة أو معلّقة منذ أكثر من 5 دقائق
    cutoff = timezone.now() - timedelta(minutes=5)
    qs = BookEmailLog.objects.filter(
        status__in=['failed', 'pending'],
        sent_at__lt=cutoff,
    ).select_related('book', 'entity', 'sent_by')[:20]

    retried = 0
    for log in qs:
        try:
            send_book_notification(
                book=log.book,
                recipients=[log.to_address],
                subject=log.subject,
                html_body=log.body_html,
                cc=[x.strip() for x in log.cc_addresses.split(',') if x.strip()],
                trigger=log.trigger,
                sent_by=log.sent_by,
                entity=log.entity,
            )
            retried += 1
        except Exception as e:
            logger.warning(f"retry_failed_emails: فشل إعادة إرسال log#{log.pk}: {e}")

    logger.info(f"retry_failed_emails: أعدت إرسال {retried}/{qs.count()} إيميل")
    return {'retried': retried}


@shared_task(name='core.tasks.network_heartbeat', ignore_result=True)
def network_heartbeat():
    """
    يُحدّث سجل هذا الجهاز في جدول NetworkNode كل دقيقة.
    يضمن أن حالة is_online=True وlast_seen حديثة دائماً،
    ويُظهر الجهاز كـ"متصل" في جدول الأجهزة على جميع الشاشات.
    لا تعمل إذا لم يكن الجهاز مُضبَّطاً بعد.
    """
    try:
        from .models import NetworkSettings
        from .network_views import _register_self
        cfg = NetworkSettings.get()
        if cfg.is_configured:
            _register_self(cfg)
    except Exception as exc:
        logger.warning('[NetworkHeartbeat] error: %s', exc)




# ===================================================
# النسخ الاحتياطي المجدول
# ===================================================

def _backup_is_due(cfg, now):
    """
    يقرّر إن كان النسخ المجدول مستحقّاً الآن — دالة نقية قابلة للاختبار.
    ``cfg``: BackupSettings، ``now``: datetime محلي.
    """
    if not cfg.enabled:
        return False
    if now.hour != cfg.hour:
        return False

    today = now.date()
    last = cfg.last_run_at
    if last is None:
        return True
    last_date = timezone.localtime(last).date() if timezone.is_aware(last) else last.date()
    if last_date >= today:
        return False  # نُفِّذ اليوم بالفعل

    if cfg.frequency == cfg.FREQ_DAILY:
        return True
    if cfg.frequency == cfg.FREQ_WEEKLY:
        return (today - last_date).days >= 7
    if cfg.frequency == cfg.FREQ_MONTHLY:
        return (last_date.year, last_date.month) != (today.year, today.month)
    return False


@shared_task(name='core.tasks.scheduled_backup', ignore_result=True)
def scheduled_backup():
    """
    نسخ احتياطي مجدول — يُشغَّل ساعياً عبر Celery beat، ويقرّر التنفيذ من BackupSettings.
    ينشئ نسخة مشفّرة، يحذف النسخ الأقدم من مدة الاحتفاظ، ويحدّث آخر تشغيل.
    """
    from .models import BackupSettings
    from .backup_service import create_encrypted_pg_backup, default_backup_dir, prune_old_backups

    cfg = BackupSettings.get()
    now = timezone.localtime()
    if not _backup_is_due(cfg, now):
        return {'skipped': True}

    try:
        path = create_encrypted_pg_backup()
    except Exception as exc:
        logger.exception('[scheduled_backup] فشل إنشاء النسخة: %s', exc)
        return {'error': str(exc)}

    removed = prune_old_backups(default_backup_dir(), cfg.retention_days)
    cfg.last_run_at = timezone.now()
    cfg.save(update_fields=['last_run_at', 'updated_at'])
    logger.info('[scheduled_backup] أُنشئت %s؛ حُذفت %s نسخة قديمة', path, removed)
    return {'backup': str(path), 'pruned': removed}


def get_task_status(task_id: str) -> dict:
    """الحصول على حالة مهمة Celery بالمعرف."""
    from celery.result import AsyncResult

    result = AsyncResult(task_id)

    return {
        'task_id': task_id,
        'status': result.status,
        'result': result.result if result.ready() else None,
        'ready': result.ready(),
        'successful': result.successful() if result.ready() else None,
        'failed': result.failed() if result.ready() else None,
    }
