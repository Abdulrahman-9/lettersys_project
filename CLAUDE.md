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

### Book Number Format — `core/numbering.py` is the SINGLE SOURCE
Never re-implement a numbering rule anywhere else. Parse/format/display/search/sort
all go through this module. (The rule used to live in eleven places and had already
drifted: the year floor was 2020 in one and 2000 in another.)

Rebased 2026-08-17 onto the number stamped inside the incoming stamp (ختم الوارد):

- **Current series** — bare, e.g. `2433`. One infinite series per register, **no
  yearly reset**, based on 2026's numbers. After 2432 comes 2433 in 2027 and beyond.
- **Tagged** — `{year}{seq:04d}`, e.g. `20250825`, for ledger year ≤ 2025. Displays
  as `825` with a separate `2025` tag. The year is the **source table's** year
  (`IIMAIL_2025`), not the document date.
- **Manual** — `outgoing_external` has no series of ours; its number comes from the
  Director General's office and is stored verbatim (duplicates allowed).
- **Numberless** — empty string. Supported exception; consumes no counter.
- **Training** — `T131`. Books entered during the training period; outside the
  official space by construction (leading non-digit). Purged at launch.

Source columns (measured, not guessed): incoming tables have both `WID` and `NUM` —
`WID` is a dense 1.00 series (our stamp number), `NUM` is scattered 0.02 (the
sender's number). Outgoing tables have **no `WID` column**; `NUM` is ours.

Uniqueness is `(kind, our_number)` scoped by migration 0058 to app-issued rows only —
paper-imported rows are exempt because the 2025 clerk really did stamp 825 twice.

Commands: `rebase_book_numbers` (idempotent, `--dry-run` by default, `--undo CSV`),
`purge_dev_seed_books` (keys off `is_training`). See `docs/LAUNCH_RUNBOOK.md`.

## أرقامٌ مسحوبة — لا تُقتبَس
- **الجهة المُصدِرة ليست 77% ولا 85%.** ذلك كان تسريبَ مطابقةٍ ذاتيّة (المستند يتعرّف
  على ترويسة نفسه المخزَّنة بتشابه 1.0). الصادق بعد إصلاح `exclude_book_id` (commit
  `0494e81`): **top-1 60% · top-3 73%** على 30 نصّاً، و**49.0%** على عيّنةٍ مُجمَّدة
  من 1000 استعلام بعد سقف الأصوات (`c53e1e7`). المتوسّط الكبير 21.4% فقط عبر 194 جهة.
- **96% للكاشف = تموضُّعٌ لا قراءة** (مركزٌ داخل الصندوق الصحيح)، و**90% لقصاصة
  التاريخ = ظهورُ قصاصةٍ لا صحّةُ تاريخ**. قراءة العدد من طرفٍ إلى طرف **لم تُقَس بعد**.
- السجلّ الكامل للمدحوض في `docs/REFUTED.md`، ومجموعات التقييم في `docs/EVAL_REGISTRY.md`.

## Consultation Rule
- إذا واجهت قراراً معمارياً أو خطأً غامضاً بعد محاولتين، استشر Opus عبر Agent tool قبل المتابعة.
- إذا طلب المستخدم صراحةً "استشر أوبوس"، استدعِ Agent بـ `model: "opus"` فوراً.
- Opus للتفكير والتوصية فقط — Sonnet ينفّذ.

## Current State
<!-- أحدِّث هذا القسم بعد كل جلسة عمل مهمة -->

### آخر تعديلات (2026-08-17) — إعادة بناء الترقيم
**11,183 رقماً أُعيد بناؤها على سلسلة ختم الوارد** (7,757 موسوم + 3,262 سلسلة جارية
+ 131 تدريب + 33 بلا رقم)، والعدّادات 2433/358/455 بلا عدّادٍ للصادر الخارجي.
- `core/numbering.py` صار مصدراً وحيداً موصولاً بالعرض والبحث والفرز والمستورد وإعادة البذر
- هجرة 0058: `is_training` + تضييق قيد التفرّد ليستثني المنقول من الورق
- حُذف `normalize_book_numbers` (يفرض بادئاتٍ أُلغيت)، و`purge_dev_seed_books` صار على `is_training`
- 229 حجزاً في الفضاء المُلغى حُذفت (حجزٌ واحد بالرقم 417 كان يبتلع 358–417)
- 729 اختباراً أخضر + 29 تحقّقاً على البيانات الحيّة · دليل التدشين في `docs/LAUNCH_RUNBOOK.md`

### آخر تعديلات (2026-08-11)
**ملفات:** `core/extraction/matchers/pattern.py` + `profile.py` — تواريخ إيميلات الشركات
- لاحقة ترتيبية بعد اليوم («July 29th, 2026» ومسوخها OCR «29"»/«5s») في `_DATE_VALUE_RE`/`_BARE_DATE_LINE_RE` + تجريدها قبل التحليل (`_DAY_SUFFIX_RE`)
- تاريخ ذيل التوقيع (ADO: لا تاريخ في الرأس إطلاقاً) — مرساة توقيع إنكليزية + سطر تاريخ عارٍ باسم شهر، ثقة 0.70
- عنوان: فاصلة كفاصل «Subject,» + بتّار ذيل الرموز («?-J.,I»)
- بصمة الرقم: الشرطة بعد البادئة اختيارية («ADO627» طبقةُ ماسحٍ أسقطت الشرطة)
- مُتحقَّق بالعين على مدخلات 11291–11295 الحقيقية + صفر تراجع على 35 نص كاش + 680 اختبار أخضر

### آخر تعديلات (2026-05-14)
**ملف:** `core/views/helpers.py` — `apply_search_filters()`
- إصلاح نمط `endswith` للأرقام ≤ 3 خانات (كان يجد أرقاماً خاطئة في الوارد)
- حذف `id_match` early-return (كان يعيد كتاباً واحداً خاطئاً)
- `sender_number`: regex بحدود رقمية بدلاً من `icontains` أو `=` مطلق
- إضافة `title__icontains` + `margin__icontains` لكلا مسارَي البحث (رقمي ونصي) وكـ fallback في `_pg_search`

### مُعلَّق / قادم
- فهرس pg_trgm على `our_number` لتسريع `endswith` في قواعد البيانات الكبيرة
- إضافة `document_type__icontains` للبحث النصي
