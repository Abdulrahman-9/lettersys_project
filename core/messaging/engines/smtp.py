"""
core.messaging.engines.smtp
===========================
SMTP Engine for LetterSys — handles email sending operations

Classes:
  - SMTPEngine: Main SMTP orchestrator

Usage:
    from core.messaging.engines.smtp import SMTPEngine
    
    engine = SMTPEngine()
    log = engine.send_book_notification(
        book=book,
        recipients=['user@example.com'],
        subject='...',
        html_body='...'
    )
"""

import logging
import re
from email.utils import make_msgid
from typing import Optional

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.template.loader import render_to_string
from django.utils import timezone

logger = logging.getLogger('lettersys')


class SMTPEngine:
    """
    SMTP Email Engine — handles connection, building, and sending emails.
    
    Attributes:
        email_cfg: EmailSettings instance (DB config, optional)
    """
    
    def __init__(self, email_cfg=None):
        """
        Initialize SMTP engine.
        
        Args:
            email_cfg: Optional EmailSettings instance. If None, uses default settings.
        """
        self.email_cfg = email_cfg
    
    def get_connection(self):
        """
        Build SMTP connection from EmailSettings or Django settings.
        
        Returns:
            django.core.mail.EmailBackend connection
        """
        if self.email_cfg and self.email_cfg.is_active and self.email_cfg.smtp_host:
            return get_connection(
                backend='django.core.mail.backends.smtp.EmailBackend',
                host=self.email_cfg.smtp_host,
                port=self.email_cfg.smtp_port,
                username=self.email_cfg.smtp_user,
                password=self.email_cfg.smtp_password,
                use_tls=self.email_cfg.smtp_use_tls,
                use_ssl=self.email_cfg.smtp_use_ssl,
                fail_silently=False,
            )
        # Fallback: Django default settings
        return get_connection(fail_silently=False)
    
    def _build_from_address(self) -> str:
        """
        Build official From address.
        
        Returns:
            str: "Organization Name <email@example.com>"
        """
        if self.email_cfg and self.email_cfg.org_email:
            name = self.email_cfg.org_name or 'LetterSys'
            return f'{name} <{self.email_cfg.org_email}>'
        return settings.DEFAULT_FROM_EMAIL
    
    def _html_to_plain(self, html: str) -> str:
        """
        Convert HTML to plain text (no external libraries).
        
        Args:
            html: HTML string
            
        Returns:
            str: Plain text version
        """
        text = re.sub(r'<br\s*/?>', '\n', html, flags=re.IGNORECASE)
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()
    
    def _render_notification_html(self, book, entity, direction: str) -> str:
        """
        Build HTML for email notification.
        
        Falls back to simple HTML if template not found.
        
        Args:
            book: Book instance
            entity: Entity instance
            direction: 'received' or 'sent'
            
        Returns:
            str: HTML content
        """
        try:
            from django.template.loader import get_template
            get_template('core/email/book_notification.html')
            return render_to_string('core/email/book_notification.html', {
                'book': book,
                'entity': entity,
                'cfg': self.email_cfg,
                'direction': direction,
                'direction_label': 'استلام كتاب' if direction == 'received' else 'إرسال كتاب',
            })
        except Exception:
            # Fallback: simple HTML
            dir_label = 'تم استلام كتابكم' if direction == 'received' else 'كتاب رسمي صادر إليكم'
            sig_html = ''
            if self.email_cfg and self.email_cfg.email_signature:
                sig_html = f'<p style="color:#666;font-size:12px">{self.email_cfg.email_signature}</p>'
            
            return f"""
            <div dir="rtl" style="font-family:Arial,sans-serif;max-width:600px;margin:auto">
              <div style="background:#7c5a3a;color:white;padding:16px;border-radius:8px 8px 0 0">
                <h2 style="margin:0">{self.email_cfg.org_name or 'LetterSys' if self.email_cfg else 'LetterSys'} — {dir_label}</h2>
              </div>
              <div style="border:1px solid #e2e8f0;border-top:0;padding:20px;border-radius:0 0 8px 8px">
                <table style="width:100%;border-collapse:collapse">
                  <tr><td style="padding:8px;color:#666;width:140px">رقم القيد</td><td style="padding:8px;font-weight:bold">{book.our_number}</td></tr>
                  <tr style="background:#f9f6f0"><td style="padding:8px;color:#666">العنوان</td><td style="padding:8px">{book.title}</td></tr>
                  <tr><td style="padding:8px;color:#666">التاريخ</td><td style="padding:8px">{book.date}</td></tr>
                  <tr style="background:#f9f6f0"><td style="padding:8px;color:#666">النوع</td><td style="padding:8px">{getattr(book, 'kind_label', '')}</td></tr>
                </table>
              </div>
              {sig_html}
            </div>
            """
    
    def send_book_notification(
        self,
        book,
        recipients: list[str],
        subject: str,
        html_body: str,
        cc: Optional[list[str]] = None,
        trigger: str = 'auto',
        sent_by=None,
        entity=None,
        attachments: Optional[list] = None,
    ):
        """
        Send email notification linked to a book and log the result.
        
        Args:
            book: Book instance
            recipients: List of To addresses
            subject: Email subject
            html_body: HTML email body
            cc: Optional list of CC addresses
            trigger: 'auto' | 'manual' | 'reminder'
            sent_by: Optional User who triggered send
            entity: Optional Entity associated with send
            attachments: Optional list of (filename, content, mimetype) tuples
            
        Returns:
            BookEmailLog instance
        """
        from core.models import BookEmailLog
        
        cc = cc or []
        to_str = ', '.join(recipients)
        
        # Create pending log entry
        log = BookEmailLog.objects.create(
            book=book,
            sent_by=sent_by,
            entity=entity,
            to_address=to_str,
            cc_addresses=', '.join(cc),
            subject=subject,
            body_html=html_body,
            trigger=trigger,
            status=BookEmailLog.STATUS_PENDING,
        )
        
        # Check if sending is enabled
        if not self.email_cfg or not self.email_cfg.is_active:
            log.status = BookEmailLog.STATUS_FAILED
            log.error_msg = 'إرسال الإيميل معطّل من إعدادات النظام'
            log.save(update_fields=['status', 'error_msg'])
            logger.warning(f'[SMTPEngine] Skipped — email disabled. Book={book.pk}')
            return log
        
        try:
            connection = self.get_connection()
            from_addr = self._build_from_address()
            reply_to = [self.email_cfg.reply_to] if self.email_cfg.reply_to else [
                self.email_cfg.org_email or from_addr
            ]
            
            # Build plain text from HTML
            plain_text = self._html_to_plain(html_body)
            
            # Message-ID صريح ومحفوظ — بدونه لا يمكن ربط أي رد وارد بهذه الرسالة.
            # (لو تُرك لـDjango لَولّده وقت الإرسال ولَضاع، فيبقى الحقل
            # ``smtp_message_id`` فارغاً كما كان الحال.)
            domain = (from_addr.split('@')[-1] or 'lettersys.local').strip('> ')
            message_id = make_msgid(domain=domain)

            # Create email with alternatives
            msg = EmailMultiAlternatives(
                subject=subject,
                body=plain_text,
                from_email=from_addr,
                to=recipients,
                cc=cc,
                reply_to=reply_to,
                connection=connection,
                headers={'Message-ID': message_id},
            )
            msg.attach_alternative(html_body, 'text/html')

            if attachments:
                for fname, content, mime in attachments:
                    msg.attach(fname, content, mime)

            msg.send()

            log.status = BookEmailLog.STATUS_SENT
            log.smtp_message_id = message_id
            log.delivered_at = timezone.now()
            log.save(update_fields=['status', 'smtp_message_id', 'delivered_at'])
            logger.info(f'[SMTPEngine] Sent to={to_str} subject="{subject}" book={book.pk} mid={message_id}')
        
        except Exception as exc:
            log.status = BookEmailLog.STATUS_FAILED
            log.error_msg = str(exc)[:1000]
            log.save(update_fields=['status', 'error_msg'])
            logger.error(f'[SMTPEngine] Failed book={book.pk}: {exc}', exc_info=True)
        
        return log
    
    def send_book_saved_notification(self, book, sent_by=None):
        """
        Send auto-notification after book save to interested entities.
        
        Called automatically on book save if configured.
        
        Args:
            book: Book instance
            sent_by: Optional User who triggered notification
            
        Returns:
            List of BookEmailLog instances created
        """
        if not self.email_cfg or not self.email_cfg.is_active or not self.email_cfg.send_on_save:
            return []
        
        logs = []
        
        # ── Incoming: notify issuing entity ──
        if book.is_incoming:
            for entity in book.issuing_entities.filter(
                notify_on_receive=True,
                is_active=True,
            ).exclude(email=''):
                html = self._render_notification_html(book, entity, 'received')
                subject = f'تم استلام كتابكم: {book.our_number}'
                cc = entity.get_cc_list() if hasattr(entity, 'get_cc_list') else []
                log = self.send_book_notification(
                    book=book,
                    recipients=[entity.email],
                    subject=subject,
                    html_body=html,
                    cc=cc,
                    trigger='auto',
                    sent_by=sent_by,
                    entity=entity,
                )
                logs.append(log)
        
        # ── Outgoing: notify receiving entity ──
        if book.is_outgoing:
            for entity in book.receiving_entities.filter(
                notify_on_send=True,
                is_active=True,
            ).exclude(email=''):
                html = self._render_notification_html(book, entity, 'sent')
                subject = f'كتاب رسمي: {book.our_number} — {book.title[:60]}'
                cc = entity.get_cc_list() if hasattr(entity, 'get_cc_list') else []
                log = self.send_book_notification(
                    book=book,
                    recipients=[entity.email],
                    subject=subject,
                    html_body=html,
                    cc=cc,
                    trigger='auto',
                    sent_by=sent_by,
                    entity=entity,
                )
                logs.append(log)
        
        return logs
    
    def send_manual_email(self, book, to_addresses: list[str], subject: str, body: str,
                          cc: Optional[list[str]] = None, sent_by=None, entity=None):
        """
        Send manual email from user interface.
        
        Args:
            book: Book instance
            to_addresses: List of recipient emails
            subject: Email subject
            body: Email body (HTML)
            cc: Optional CC addresses
            sent_by: Optional User who sent
            entity: Optional Entity associated
            
        Returns:
            BookEmailLog instance
        """
        return self.send_book_notification(
            book=book,
            recipients=to_addresses,
            subject=subject,
            html_body=body,
            cc=cc,
            trigger='manual',
            sent_by=sent_by,
            entity=entity,
        )
    
    def test_connection(self) -> dict:
        """
        Test SMTP connection (used from settings panel).

        يبني اتصال SMTP **صريحاً** من إعدادات قاعدة البيانات بدل ``get_connection()``:
        ذاك يسقط إلى backend الافتراضي حين ``is_active=False``، وهو في وضع DEBUG
        الـconsole backend الذي ينجح ``open()`` عليه دائماً — فكان الزر يُبلّغ
        «نجاح» حتى بلا خادم ولا كلمة مرور. الاختبار يجب أن يختبر الحقيقة.

        Returns:
            dict: {'success': bool, 'message': str}
        """
        cfg = self.email_cfg
        if not cfg:
            return {'success': False, 'message': 'لا توجد إعدادات بريد محفوظة.'}

        missing = [label for value, label in (
            (cfg.smtp_host,     'خادم SMTP'),
            (cfg.smtp_user,     'اسم المستخدم'),
            (cfg.smtp_password, 'كلمة المرور'),
        ) if not value]
        if missing:
            return {'success': False,
                    'message': 'إعدادات SMTP ناقصة: ' + '، '.join(missing)}

        try:
            conn = get_connection(
                backend='django.core.mail.backends.smtp.EmailBackend',
                host=cfg.smtp_host,
                port=cfg.smtp_port,
                username=cfg.smtp_user,
                password=cfg.smtp_password,
                use_tls=cfg.smtp_use_tls,
                use_ssl=cfg.smtp_use_ssl,
                fail_silently=False,
            )
            conn.open()
            conn.close()
            return {'success': True, 'message': 'تم الاتصال بخادم SMTP بنجاح ✓'}
        except Exception as e:
            return {'success': False, 'message': f'فشل الاتصال: {e}'}


# ════════════════════════════════════════════════════════════════
# BACKWARDS COMPATIBILITY: Module-level functions (deprecated)
# ════════════════════════════════════════════════════════════════

def send_book_notification(book, recipients: list[str], subject: str, html_body: str,
                          cc: Optional[list[str]] = None, trigger: str = 'auto',
                          sent_by=None, entity=None, attachments: Optional[list] = None):
    """⚠️ DEPRECATED: Use SMTPEngine().send_book_notification() instead."""
    from core.models import EmailSettings
    cfg = EmailSettings.get()
    engine = SMTPEngine(cfg)
    return engine.send_book_notification(
        book=book,
        recipients=recipients,
        subject=subject,
        html_body=html_body,
        cc=cc,
        trigger=trigger,
        sent_by=sent_by,
        entity=entity,
        attachments=attachments,
    )


def send_book_saved_notification(book, sent_by=None):
    """⚠️ DEPRECATED: Use SMTPEngine().send_book_saved_notification() instead."""
    from core.models import EmailSettings
    cfg = EmailSettings.get()
    engine = SMTPEngine(cfg)
    return engine.send_book_saved_notification(book, sent_by=sent_by)


def send_manual_email(book, to_addresses: list[str], subject: str, body: str,
                     cc: Optional[list[str]] = None, sent_by=None, entity=None):
    """⚠️ DEPRECATED: Use SMTPEngine().send_manual_email() instead."""
    from core.models import EmailSettings
    cfg = EmailSettings.get()
    engine = SMTPEngine(cfg)
    return engine.send_manual_email(
        book=book,
        to_addresses=to_addresses,
        subject=subject,
        body=body,
        cc=cc,
        sent_by=sent_by,
        entity=entity,
    )


def test_smtp_connection(email_cfg) -> dict:
    """⚠️ DEPRECATED: Use SMTPEngine(email_cfg).test_connection() instead."""
    engine = SMTPEngine(email_cfg)
    return engine.test_connection()
