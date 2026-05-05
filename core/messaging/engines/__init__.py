"""
core.messaging.engines
======================
Email engine implementations (SMTP, IMAP, etc.)

Classes:
  - SMTPEngine  → Handle SMTP operations (send emails)
  - IMAPEngine  → Handle IMAP operations (fetch emails)
"""

from .smtp import SMTPEngine
from .imap import IMAPEngine

__all__ = ['SMTPEngine', 'IMAPEngine']
