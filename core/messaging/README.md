# core/messaging — Email & Messaging Package

Consolidated email/messaging module for LetterSys. Replaces the legacy flat-file layout (`email_service.py`, `imap_service.py`, `email_api.py`, `mail_api.py`, `mail_views.py`).

---

## Package Structure

```
core/messaging/
├── __init__.py
├── README.md               ← this file
│
├── engines/                Engine layer — pure I/O, no HTTP
│   ├── __init__.py         (exports SMTPEngine, IMAPEngine)
│   ├── smtp.py             SMTPEngine class + compat functions
│   └── imap.py             IMAPEngine class + compat functions
│
├── api/                    REST API layer
│   ├── __init__.py
│   ├── email_endpoints.py  Book/entity-scoped email APIs
│   ├── mail_endpoints.py   Thread-based mail APIs
│   └── urls.py             URL routing (email_urlpatterns + mail_urlpatterns)
│
├── views/                  Web UI layer
│   ├── __init__.py
│   ├── ui.py               All mail section views
│   └── urls.py             URL routing for /mail/*
│
├── services/               Business logic layer (reserved for future use)
│   └── __init__.py
│
└── templates/              App-specific templates (optional override)
    └── core/messaging/
        └── email/
```

---

## Engines

### SMTPEngine (`core.messaging.engines.smtp`)

Handles all outbound email sending.

```python
from core.messaging.engines.smtp import SMTPEngine

engine = SMTPEngine(email_cfg)          # email_cfg: EmailSettings instance
engine.send_book_notification(book, recipients=['to@example.com'], subject='...', html_body='...')
engine.send_manual_email(book, to_addresses=['to@example.com'], subject='...', body='...')
engine.send_book_saved_notification(book, sent_by=request.user)
engine.test_connection()                # → {'success': bool, 'message': str}
```

**Backwards-compat functions** (deprecated — use class methods):
- `send_book_notification(book, recipients, subject, html_body, **kwargs)`
- `send_manual_email(book, to_addresses, subject, body, **kwargs)`
- `test_smtp_connection(cfg=None) → dict`
- `send_book_saved_notification(book, sent_by=None)`

---

### IMAPEngine (`core.messaging.engines.imap`)

Handles inbound email fetching and inbox sync.

```python
from core.messaging.engines.imap import IMAPEngine

engine = IMAPEngine(email_cfg)
stats = engine.sync_inbox()             # → {'fetched': int, 'new': int, 'errors': int}
result = engine.test_connection()       # → {'success': bool, 'message': str}
engine.mark_as_read(imap_uid=42)        # → bool
```

**Backwards-compat functions** (deprecated):
- `sync_inbox(cfg=None) → dict`
- `test_imap_connection(cfg=None) → dict`
- `mark_as_read_on_server(cfg, imap_uid) → bool`

---

## REST API Endpoints

### Book/Entity-scoped (`/books/api/email/`)

| Method | URL | View | Description |
|--------|-----|------|-------------|
| POST | `/books/api/email/send/` | `send_email` | Manual send |
| GET | `/books/api/email/logs/<book_id>/` | `book_email_logs` | Email logs for book |
| POST | `/books/api/email/test-smtp/` | `test_smtp` | **Canonical** SMTP test |
| GET/POST | `/books/api/email/settings/` | `email_settings` | Read/update settings |
| GET | `/books/api/email/entity/<id>/` | `entity_email_info` | Entity email info |
| POST | `/books/api/email/entity/<id>/update/` | `update_entity_email` | Update entity email |

### Thread-based (`/mail/api/`)

| Method | URL | View | Description |
|--------|-----|------|-------------|
| POST | `/mail/api/compose/` | `api_compose` | Send new message |
| POST | `/mail/api/inbox/sync/` | `api_inbox_sync` | Manual IMAP sync (staff) |
| POST | `/mail/api/inbox/<id>/read/` | `api_mark_read` | Mark as read |
| GET | `/mail/api/thread/<id>/` | `api_thread_detail` | Thread + timeline |
| POST | `/mail/api/thread/<id>/status/` | `api_thread_status` | Change thread status |
| POST | `/mail/api/bulk-send/` | `api_bulk_send` | Bulk send |
| GET | `/mail/api/template/<id>/preview/` | `api_template_preview` | Template preview |
| POST | `/mail/api/settings/test-smtp/` | `api_test_smtp` | SMTP test (delegates → canonical) |
| POST | `/mail/api/settings/test-imap/` | `api_test_imap` | IMAP connection test |
| GET | `/mail/api/stats/` | `api_mail_stats` | Email statistics |

> **No duplicate**: `/mail/api/settings/test-smtp/` delegates to `email_endpoints.test_smtp` — single implementation.

---

## Web UI Routes (`/mail/`)

| URL | View | Name |
|-----|------|------|
| `/mail/` | `mail_hub` | `mail_hub` |
| `/mail/sent/` | `mail_sent` | `mail_sent` |
| `/mail/inbox/` | `mail_inbox` | `mail_inbox` |
| `/mail/compose/` | `mail_compose` | `mail_compose` |
| `/mail/compose/<book_id>/` | `mail_compose` | `mail_compose_book` |
| `/mail/thread/<id>/` | `mail_thread` | `mail_thread` |
| `/mail/settings/` | `mail_settings` | `mail_settings` |
| `/mail/templates/` | `mail_templates` | `mail_templates` |
| `/mail/templates/new/` | `mail_template_edit` | `mail_template_new` |
| `/mail/templates/<id>/edit/` | `mail_template_edit` | `mail_template_edit` |
| `/mail/templates/<id>/delete/` | `mail_template_delete` | `mail_template_delete` |

---

## Legacy Files (Deprecated Shims)

These files remain for backwards compatibility but are not actively maintained:

| File | Status | Migration target |
|------|--------|-----------------|
| `core/email_service.py` | ⚠️ DEPRECATED | `core.messaging.engines.smtp.SMTPEngine` |
| `core/imap_service.py` | ⚠️ DEPRECATED | `core.messaging.engines.imap.IMAPEngine` |
| `core/email_api.py` | ⚠️ DEPRECATED | `core.messaging.api.email_endpoints` |
| `core/mail_api.py` | ⚠️ DEPRECATED | `core.messaging.api.mail_endpoints` |
| `core/mail_views.py` | ⚠️ DEPRECATED | `core.messaging.views.ui` |

---

## Celery Tasks

Tasks in `core/tasks.py` that use this package:

- **`sync_inbox_task`** — runs every 10 min via Celery Beat; uses `IMAPEngine` via `sync_inbox()`
- **`retry_failed_emails_task`** — runs every 30 min (scheduled in `CELERY_BEAT_SCHEDULE`
  as `retry-failed-emails-every-30-minutes`); retries each **original** log up to
  `BookEmailLog.MAX_RETRIES` then marks it `abandoned`. Retry rows carry `retry_of`
  and never re-enter the queue. Guarded by an atomic cache lock.

---

## Configuration

Email settings are stored in the `EmailSettings` singleton model (DB-backed):

```python
from core.models import EmailSettings
cfg = EmailSettings.get()   # always returns singleton instance
```

Key fields:
- SMTP: `smtp_host`, `smtp_port`, `smtp_user`, `smtp_password` (Fernet-encrypted), `smtp_use_tls/ssl`
- IMAP: `imap_host`, `imap_port`, `imap_user`, `imap_password` (Fernet-encrypted), `imap_sync_enabled`
- Behaviour: `is_active`, `send_on_save`, `org_name`, `org_email`
