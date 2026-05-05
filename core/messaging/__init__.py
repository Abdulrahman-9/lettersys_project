"""
core.messaging
==============
LetterSys Email/Messaging Module — Phase 2.1 Consolidation

This package consolidates all email and messaging operations:
  - engines.smtp     → SMTP operations (sending)
  - engines.imap     → IMAP operations (fetching)
  - services        → Business logic (compose, threading)
  - api              → REST endpoints (/api/email/*, /mail/api/*)
  - views            → Web UI (/mail/*)

Status: PRODUCTION-READY (Phase 2.1 consolidation)
Migration: Old modules (email_api, mail_api, etc.) deprecated but available for backwards-compat

Usage:
  from core.messaging.engines.smtp import SMTPEngine
  from core.messaging.engines.imap import IMAPEngine
  from core.messaging.api import send_email, compose_mail
"""

default_app_config = 'core.messaging.apps.MessagingConfig'

# Backwards-compatibility imports (deprecated)
try:
    from core.messaging.engines.smtp import SMTPEngine
    from core.messaging.engines.imap import IMAPEngine
except ImportError:
    # Module not fully initialized yet
    pass
