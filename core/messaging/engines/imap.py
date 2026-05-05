"""
core.messaging.engines.imap
============================
IMAP Engine for LetterSys — handles email fetching and inbox sync

Classes:
  - IMAPEngine: Main IMAP orchestrator

Usage:
    from core.messaging.engines.imap import IMAPEngine
    
    engine = IMAPEngine(email_cfg)
    stats = engine.sync_inbox()
    # returns: {'fetched': int, 'new': int, 'errors': int}
"""

import email
import imaplib
import logging
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime
from typing import Optional

from django.utils import timezone

logger = logging.getLogger('lettersys')


class IMAPEngine:
    """
    IMAP Email Engine — handles connection, message fetching, and inbox sync.
    
    Attributes:
        email_cfg: EmailSettings instance (DB config)
    """

    def __init__(self, email_cfg=None):
        """
        Initialize IMAP engine.
        
        Args:
            email_cfg: Optional EmailSettings instance.
        """
        self.email_cfg = email_cfg

    # ════════════════════════════════════════════════════════
    # Connection
    # ════════════════════════════════════════════════════════

    def get_connection(self):
        """
        Build IMAP connection from EmailSettings.
        
        Returns:
            imaplib.IMAP4 or IMAP4_SSL instance, or None if config incomplete.
        """
        cfg = self.email_cfg
        if not cfg or not cfg.imap_host or not cfg.imap_user or not cfg.imap_password:
            logger.warning("IMAPEngine: Incomplete IMAP configuration")
            return None
        try:
            if cfg.imap_use_ssl:
                conn = imaplib.IMAP4_SSL(cfg.imap_host, cfg.imap_port)
            else:
                conn = imaplib.IMAP4(cfg.imap_host, cfg.imap_port)
            conn.login(cfg.imap_user, cfg.imap_password)
            return conn
        except imaplib.IMAP4.error as e:
            logger.error(f"IMAPEngine: Login failed — {e}")
            return None
        except OSError as e:
            logger.error(f"IMAPEngine: Network error — {e}")
            return None

    # ════════════════════════════════════════════════════════
    # Message Parsing Helpers
    # ════════════════════════════════════════════════════════

    @staticmethod
    def _decode_str(raw) -> str:
        """
        Decode email header which may be base64 or quoted-printable encoded.
        
        Args:
            raw: Raw header string
            
        Returns:
            str: Decoded header string
        """
        if not raw:
            return ""
        parts = decode_header(raw)
        decoded = []
        for part, charset in parts:
            if isinstance(part, bytes):
                decoded.append(part.decode(charset or 'utf-8', errors='replace'))
            else:
                decoded.append(part)
        return " ".join(decoded).strip()

    @staticmethod
    def _extract_body(msg: email.message.Message) -> tuple[str, str]:
        """
        Extract HTML and plain text body from message (handles multipart).
        
        Args:
            msg: email.message.Message instance
            
        Returns:
            tuple: (html_body, text_body) — both may be empty strings
        """
        html_body = ""
        text_body = ""

        if msg.is_multipart():
            for part in msg.walk():
                ct = part.get_content_type()
                cd = str(part.get("Content-Disposition", ""))
                if "attachment" in cd:
                    continue
                charset = part.get_content_charset() or 'utf-8'
                payload = part.get_payload(decode=True)
                if not payload:
                    continue
                content = payload.decode(charset, errors='replace')
                if ct == "text/html" and not html_body:
                    html_body = content
                elif ct == "text/plain" and not text_body:
                    text_body = content
        else:
            charset = msg.get_content_charset() or 'utf-8'
            payload = msg.get_payload(decode=True)
            if payload:
                content = payload.decode(charset, errors='replace')
                if msg.get_content_type() == "text/html":
                    html_body = content
                else:
                    text_body = content

        return html_body, text_body

    @staticmethod
    def _parse_received_at(msg: email.message.Message):
        """
        Parse message receive date from Date header.
        
        Args:
            msg: email.message.Message instance
            
        Returns:
            datetime: Timezone-aware datetime, falls back to now()
        """
        date_str = msg.get("Date", "")
        try:
            dt = parsedate_to_datetime(date_str)
            if timezone.is_naive(dt):
                dt = timezone.make_aware(dt)
            return dt
        except Exception:
            return timezone.now()

    # ════════════════════════════════════════════════════════
    # Thread Linking
    # ════════════════════════════════════════════════════════

    @staticmethod
    def _find_thread_for_reply(in_reply_to: str, references: str):
        """
        Find existing thread associated with a reply message.
        
        Priority: In-Reply-To → References (newest first) → None
        
        Args:
            in_reply_to: In-Reply-To header value
            references: References header value
            
        Returns:
            EmailThread instance or None
        """
        from core.models import EmailThread, BookEmailLog

        candidates = []
        if in_reply_to:
            candidates.append(in_reply_to.strip())
        if references:
            # References may contain multiple IDs — newest is last
            for ref in reversed(references.split()):
                ref = ref.strip()
                if ref and ref not in candidates:
                    candidates.append(ref)

        for mid in candidates:
            # Search in outbound email logs
            log = BookEmailLog.objects.filter(smtp_message_id=mid).select_related('thread').first()
            if log and log.thread:
                return log.thread
            # Search directly on thread ref
            thread = EmailThread.objects.filter(ref_message_id=mid).first()
            if thread:
                return thread

        return None

    # ════════════════════════════════════════════════════════
    # Main Operations
    # ════════════════════════════════════════════════════════

    def sync_inbox(self, cfg=None) -> dict:
        """
        Fetch new messages from IMAP and save as IncomingEmail objects.
        
        Args:
            cfg: Optional EmailSettings override (uses self.email_cfg if None)
            
        Returns:
            dict: {'fetched': int, 'new': int, 'errors': int}
        """
        from core.models import EmailSettings, EmailThread, IncomingEmail

        effective_cfg = cfg or self.email_cfg
        if effective_cfg is None:
            effective_cfg = EmailSettings.get()

        if not effective_cfg.imap_sync_enabled:
            logger.info("IMAPEngine: sync disabled in settings")
            return {'fetched': 0, 'new': 0, 'errors': 0}

        # Temporarily set cfg for connection
        original_cfg = self.email_cfg
        self.email_cfg = effective_cfg
        conn = self.get_connection()
        self.email_cfg = original_cfg

        if not conn:
            return {'fetched': 0, 'new': 0, 'errors': 1}

        stats = {'fetched': 0, 'new': 0, 'errors': 0}

        try:
            folder = effective_cfg.imap_folder or 'INBOX'
            conn.select(f'"{folder}"')

            # Fetch only UNSEEN messages
            _, data = conn.search(None, 'UNSEEN')
            uid_list = data[0].split() if data[0] else []

            logger.info(f"IMAPEngine: {len(uid_list)} new messages in {folder}")

            for uid_bytes in uid_list:
                stats['fetched'] += 1
                try:
                    _, msg_data = conn.fetch(uid_bytes, '(RFC822)')
                    raw_email = msg_data[0][1]
                    msg = email.message_from_bytes(raw_email)

                    message_id = (msg.get("Message-ID") or "").strip()
                    if not message_id:
                        # No Message-ID — generate synthetic one
                        message_id = f"<no-id-{uid_bytes.decode()}-{timezone.now().timestamp()}@local>"

                    # Deduplication by Message-ID
                    if IncomingEmail.objects.filter(message_id=message_id).exists():
                        logger.debug(f"IMAPEngine: Duplicate skipped — {message_id}")
                        continue

                    # Extract message fields
                    from_raw = msg.get("From", "")
                    from_name, from_addr = parseaddr(from_raw)
                    from_name = self._decode_str(from_name)
                    subject = self._decode_str(msg.get("Subject", ""))
                    in_reply_to = (msg.get("In-Reply-To") or "").strip()
                    references = (msg.get("References") or "").strip()
                    reply_to_raw = msg.get("Reply-To", "")
                    _, reply_to_addr = parseaddr(reply_to_raw)

                    html_body, text_body = self._extract_body(msg)
                    received_at = self._parse_received_at(msg)
                    imap_uid = int(uid_bytes.decode())

                    # Find or create thread
                    thread = self._find_thread_for_reply(in_reply_to, references)

                    if not thread:
                        # Create new orphan thread (open inbox)
                        thread = EmailThread.objects.create(
                            subject=subject or "(بدون موضوع)",
                            ref_message_id=message_id,
                            status=EmailThread.STATUS_OPEN,
                        )
                        logger.info(f"IMAPEngine: New thread '{subject}' from {from_addr}")
                    else:
                        # Update thread status to replied
                        thread.status = EmailThread.STATUS_REPLIED
                        thread.save(update_fields=['status', 'last_activity'])

                    IncomingEmail.objects.create(
                        thread=thread,
                        from_address=from_addr,
                        from_name=from_name,
                        reply_to=reply_to_addr,
                        subject=subject,
                        body_html=html_body,
                        body_text=text_body,
                        message_id=message_id,
                        in_reply_to=in_reply_to,
                        imap_uid=imap_uid,
                        received_at=received_at,
                    )
                    stats['new'] += 1
                    logger.info(f"IMAPEngine: Saved new message {message_id}")

                except Exception as e:
                    stats['errors'] += 1
                    logger.exception(f"IMAPEngine: Error processing message — {e}")

        finally:
            try:
                conn.close()
                conn.logout()
            except Exception:
                pass

        # Update last sync timestamp
        from core.models import EmailSettings as ES
        ES.objects.filter(singleton=1).update(imap_last_sync=timezone.now())

        logger.info(f"IMAPEngine: Sync complete: {stats}")
        return stats

    def test_connection(self, cfg=None) -> dict:
        """
        Test IMAP connection and return clear result.
        
        Args:
            cfg: Optional EmailSettings override
            
        Returns:
            dict: {'success': bool, 'message': str}
        """
        effective_cfg = cfg or self.email_cfg
        if not effective_cfg:
            return {'success': False, 'message': 'No IMAP configuration provided'}

        original_cfg = self.email_cfg
        self.email_cfg = effective_cfg
        conn = self.get_connection()
        self.email_cfg = original_cfg

        if not conn:
            return {'success': False, 'message': 'فشل الاتصال — تحقق من بيانات IMAP'}

        try:
            folder = effective_cfg.imap_folder or 'INBOX'
            status, data = conn.select(f'"{folder}"')
            if status != 'OK':
                return {'success': False, 'message': f'لم يتم فتح المجلد "{folder}"'}
            msg_count = int(data[0].decode())
            conn.close()
            conn.logout()
            return {
                'success': True,
                'message': f'الاتصال ناجح — {msg_count} رسالة في {folder}',
            }
        except Exception as e:
            return {'success': False, 'message': str(e)}

    def mark_as_read(self, imap_uid: int, cfg=None) -> bool:
        """
        Set \\Seen flag on message in IMAP server.
        
        Args:
            imap_uid: IMAP UID of message
            cfg: Optional EmailSettings override
            
        Returns:
            bool: True if successful
        """
        effective_cfg = cfg or self.email_cfg
        original_cfg = self.email_cfg
        self.email_cfg = effective_cfg
        conn = self.get_connection()
        self.email_cfg = original_cfg

        if not conn:
            return False
        try:
            folder = effective_cfg.imap_folder or 'INBOX' if effective_cfg else 'INBOX'
            conn.select(f'"{folder}"')
            conn.store(str(imap_uid).encode(), '+FLAGS', '\\Seen')
            conn.close()
            conn.logout()
            return True
        except Exception as e:
            logger.warning(f"IMAPEngine mark_as_read: {e}")
            return False


# ════════════════════════════════════════════════════════════════
# BACKWARDS COMPATIBILITY: Module-level functions (deprecated)
# ════════════════════════════════════════════════════════════════

def sync_inbox(cfg=None) -> dict:
    """⚠️ DEPRECATED: Use IMAPEngine(cfg).sync_inbox() instead."""
    from core.models import EmailSettings
    if cfg is None:
        cfg = EmailSettings.get()
    engine = IMAPEngine(cfg)
    return engine.sync_inbox()


def test_imap_connection(cfg=None) -> dict:
    """⚠️ DEPRECATED: Use IMAPEngine(cfg).test_connection() instead."""
    from core.models import EmailSettings
    if cfg is None:
        cfg = EmailSettings.get()
    engine = IMAPEngine(cfg)
    return engine.test_connection()


def mark_as_read_on_server(cfg, imap_uid: int) -> bool:
    """⚠️ DEPRECATED: Use IMAPEngine(cfg).mark_as_read(imap_uid) instead."""
    engine = IMAPEngine(cfg)
    return engine.mark_as_read(imap_uid)
