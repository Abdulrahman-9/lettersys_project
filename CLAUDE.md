# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```powershell
# Setup
cp .env.example .env          # then edit .env with DB credentials
python manage.py db_healthcheck
python manage.py migrate
python manage.py create_admin_user

# Development
python manage.py runserver
python manage.py check         # Django system check (no DB needed)

# Tests — always use settings_test (SQLite in-memory, no PostgreSQL required)
# Windows: set PYTHONIOENCODING first (migrations print Unicode chars that break cp1256)
$env:PYTHONIOENCODING="utf-8"; python manage.py test --settings=lettersys.settings_test
$env:PYTHONIOENCODING="utf-8"; python manage.py test core.tests_books_views --settings=lettersys.settings_test
$env:PYTHONIOENCODING="utf-8"; python manage.py test core.tests_security --settings=lettersys.settings_test

# Celery (requires Redis)
celery -A lettersys worker -l info
celery -A lettersys beat -l info

# Management commands
python manage.py seed_demo_books          # populate demo data
python manage.py check_overdue_books      # flag overdue books
python manage.py import_legacy            # import legacy data
python manage.py collectstatic            # production static files
```

## Architecture

### URL Routing
```
lettersys/urls.py        root — login, logout, dashboard, service-worker
└── books/ → core/urls.py
    ├── api/             DRF router (AttachmentMergeViewSet) + extraction APIs
    ├── extract/         extraction UI (include core.extraction.views.urls)
    ├── mail/            mail UI (include core.messaging.views.urls)
    ├── mail/api/        mail APIs (include mail_urlpatterns)
    └── api/email/       email APIs (include email_urlpatterns)
```

### Single App, Three Sub-Packages
Everything lives in `core/`. The two refactored sub-packages have their own internal layering:

**`core/extraction/`** — AI/OCR pipeline
- `pipeline.py` — `AIExtractionService` orchestrator (image → OCR → patterns → entities → result)
- `ocr/` — `ImageProcessor`, `OCRService`, `EasyOCROfflineProvider`, `AzureOCRProvider`
- `matchers/` — `PatternMatcher` (dates, numbers), `EntityMatcher` (NER)
- `helpers.py` — `ExtractionWorkflow`, `ConfidenceAnalyzer`, `QuickFillAssistant`
- `api/endpoints.py` — REST views; `views/ui.py` — HTML views
- `learning.py` — feedback **analysis only** (patterns + per-field accuracy scores).
  ⚠️ `core/continuous_learning.py` **does not exist** (removed); the old pointer here
  misled several sessions. And note what the loop actually captures: `capture.py`
  `_FIELD_MAP` tracks **`title` and `secret_level` only** — `sender_number` is captured
  neither as a value nor as a location, so that field **cannot improve with use** today.
  The socket is live though: `persist_extraction_capture` (capture.py:69) fires post-commit
  with both `suggested` and `final`, and `DataExtractionResult.additional_data` (JSONField)
  is a ready carrier for the locator box that `pipeline.py:409` currently discards.

**`core/messaging/`** — email & IMAP (see `core/messaging/README.md` for full API)
- `engines/smtp.py` — `SMTPEngine`; `engines/imap.py` — `IMAPEngine`
- `api/email_endpoints.py` — book-scoped email APIs
- `api/mail_endpoints.py` — thread-based mail APIs
- `views/ui.py` — mail hub, inbox, compose, templates

**`core/views/`** — view layer (no business logic)
- `books_list.py` — `book_unified()` (main list) + `api_unified_data()` (AJAX endpoint)
- `filter_helpers.py` — `BookFilterEngine`, `BookSortEngine`, `get_counter_badges()`
- `books_api.py` — save/delete/status mutations
- `dashboard.py` — stats aggregation only
- `__init__.py` — re-exports everything for `lettersys/urls.py`

### Key Patterns

**Access control:** All views are `@login_required`. Superusers see all `Book` objects; regular users see only `created_by=request.user`.

**Book filtering** is centralised in `BookFilterEngine.apply_all_filters()`. The 7 tabs (all/incoming/outgoing/done/overdue/today/upcoming), text search, date range, entity, and status filters all go through this class. Do not add ad-hoc querysets in views.

**AJAX data flow** for the unified list: client JS calls `GET /books/api/unified/data/?tab=...&q=...` → `api_unified_data()` → `BookFilterEngine` → JSON `{books, pagination, active_filters}` → `BookUnifiedAjaxManager` re-renders the table via `history.pushState`.

**AI extraction mocking:** Controlled by `AI_ALLOW_MOCK_EXTRACTION` setting. Tests patch `core.extraction.api.endpoints.AIExtractionService` and `core.extraction.pipeline.*` — never the old shim paths.

**Email settings** are stored as a singleton DB model: `EmailSettings.get()`. Passwords are Fernet-encrypted in the DB.

**Book numbers** are managed via `BookSequence` model with optional reservation (`BookNumberReservation`).

### Data Model Highlights
- `Book` — 4 kinds: `incoming_internal`, `incoming_external`, `outgoing_internal`, `outgoing_external`. Soft delete via `is_deleted`. Due date tracked with `time_state` computed field.
- `Attachment` + `AttachmentVersion` — file versioning; merge via `MergeLog`.
- `DataExtractionResult` → `OCRResult` → `Attachment` — extraction chain.
- `EmailSettings` singleton (Fernet-encrypted SMTP/IMAP credentials).
- `BookSequence` + `BookNumberReservation` — number management.

### Settings
- Production: PostgreSQL + optional Redis (auto-detected via `REDIS_CACHE_URL`).
- Tests: `lettersys/settings_test.py` — SQLite in-memory, LocMemCache, Celery eager, no CSP.
- `AI_PROVIDER=offline` uses EasyOCR locally; `azure` uses Azure Cognitive Services.
- `pg_trgm` extension is required for full-text entity search; enabled by migration `0019`.

### Book Number Format (critical — affects search logic)
`our_number` has three formats after migrations 0033–0036:
- **New** (9 chars): `YYYY R NNNN` — year + register(1-4) + 4-digit-padded sequence
- **Old** (8 chars): `YYYY NNNN` — year + 4-digit-padded sequence (imported/legacy)
- **Compound** (11 chars): `YYYY NNNN VVV` — deduplicated entries; also has `series_no` + `version` fields

Register codes: `1`=incoming_internal, `2`=incoming_external, `3`=outgoing_internal, `4`=outgoing_external

Search logic lives entirely in `core/views/helpers.py::apply_search_filters()`.
Key rule: `our_number__endswith=padded` (4-digit) matches both old and new formats correctly
because the last 4 chars are always the sequence NNNN regardless of format.

## Consultation Rule
- إذا واجهت قراراً معمارياً أو خطأً غامضاً بعد محاولتين، استشر Opus عبر Agent tool قبل المتابعة.
- إذا طلب المستخدم صراحةً "استشر أوبوس"، استدعِ Agent بـ `model: "opus"` فوراً.
- Opus للتفكير والتوصية فقط — Sonnet ينفّذ.

## Current State
<!-- أحدِّث هذا القسم بعد كل جلسة عمل مهمة -->

### آخر تعديلات (2026-05-14)
**ملف:** `core/views/helpers.py` — `apply_search_filters()`
- إصلاح نمط `endswith` للأرقام ≤ 3 خانات (كان يجد أرقاماً خاطئة في الوارد)
- حذف `id_match` early-return (كان يعيد كتاباً واحداً خاطئاً)
- `sender_number`: regex بحدود رقمية بدلاً من `icontains` أو `=` مطلق
- إضافة `title__icontains` + `margin__icontains` لكلا مسارَي البحث (رقمي ونصي) وكـ fallback في `_pg_search`

### مُعلَّق / قادم
- فهرس pg_trgm على `our_number` لتسريع `endswith` في قواعد البيانات الكبيرة
- إضافة `document_type__icontains` للبحث النصي
