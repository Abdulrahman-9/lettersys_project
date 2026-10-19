# LetterSys Scripts Documentation

This folder contains utility scripts for system administration, OCR training, and server management.

---

## 🎯 Quick Reference

| Script | Type | Purpose | Status | Usage |
|--------|------|---------|--------|-------|
| `preload_ocr_model.py` | Python | Pre-cache EasyOCR models on startup | ✅ Active | `python scripts/preload_ocr_model.py` |
| `optimize_startup.py` | Python | Optimize Django startup performance | ⚠️ Optional | `python scripts/optimize_startup.py` |
| `get_entities.py` | Python | Export entity list to JSON/CSV | ✅ Active | `python scripts/get_entities.py` |
| `manage_users.py` | Python | Create/update/delete user accounts | ✅ Active | `python scripts/manage_users.py` |
| `run_server_background.py` | Python | Run Django development server in background | ⚠️ Dev-only | `python scripts/run_server_background.py` |
| `train_ocr_local.py` | Python | Train local EasyOCR model with feedback | ⚠️ Experimental | `python scripts/train_ocr_local.py` |
| `start_django.ps1` | PowerShell | Start Django server (Windows) | ⚠️ Dev-only | `.\scripts\start_django.ps1` |
| `auto_train.ps1` | PowerShell | Auto-train OCR model on schedule | ⚠️ Beta | `.\scripts\auto_train.ps1` |
| `quick_train.ps1` | PowerShell | Quick OCR training shortcut | ⚠️ Beta | `.\scripts\quick_train.ps1` |
| `enable_scan_simulator.ps1` | PowerShell | Enable scan device simulator | ⚠️ Dev-only | `.\scripts\enable_scan_simulator.ps1` |
| `enable_scan_simulator.bat` | Batch | Batch wrapper for scan simulator | ⚠️ Dev-only | `scripts\enable_scan_simulator.bat` |
| `manage_server_background.ps1` | PowerShell | Manage background server process | ⚠️ Dev-only | `.\scripts\manage_server_background.ps1` |

### Current Windows LAN service

The live LetterSys service is the existing Windows `LetterSys` service
(NSSM + Waitress) on **port 1312**. The production path is not Django's
development server:

- On the server, use the installed **Start LetterSys Server** shortcut. The
  checked launcher is `start_lettersys_service.ps1`; it starts the existing
  service only after checking its configured application directory and port.
- From another device on the company LAN, open `http://172.16.2.16:1312`.
- For the current service's deployment and safety procedures, see
  [`../docs/WINDOWS_LAN_DEPLOYMENT.md`](../docs/WINDOWS_LAN_DEPLOYMENT.md)
  and [`../docs/LAUNCH_RUNBOOK.md`](../docs/LAUNCH_RUNBOOK.md).

Do not use `runserver`, `start_django.ps1`, or a background development helper
to start, replace, or update this LAN service. Do not install the alternative
Daphne/Caddy setup over the existing Waitress service.
`start_django.ps1` is a development helper that binds `0.0.0.0:8000`; do not
use that broad development bind as a substitute for the guarded service on
port 1312.

### DB Health Command (Django)

`python manage.py db_healthcheck`

Checks:
- Database connectivity
- Migration graph conflicts
- Pending migrations (warning by default, error with `--strict`)
- Model drift via `makemigrations --check --dry-run`

Examples:
```bash
python manage.py db_healthcheck
python manage.py db_healthcheck --strict
python manage.py db_healthcheck --skip-model-check
```

---

## 📝 Detailed Documentation

### Production Scripts (Active ✅)

#### `preload_ocr_model.py`
**Purpose**: Pre-cache EasyOCR model files during startup to avoid first-request latency  
**When to Use**: Before deploying to production with EasyOCR  
**Command**: 
```bash
python scripts/preload_ocr_model.py
```
**Output**: Downloads Arabic language model (~80MB) and caches to `~/.EasyOCR/model_zoo/`  
**Notes**: 
- Requires internet connection (first time only)
- Use if `AI_PROVIDER=easyocr` in `.env`
- Safe to run multiple times (idempotent)

---

#### `get_entities.py`
**Purpose**: Export organization/entity list for reporting or integration  
**When to Use**: Need to sync entities to external system  
**Command**:
```bash
python scripts/get_entities.py [--format json|csv] [--output FILE]
```
**Examples**:
```bash
python scripts/get_entities.py --format json --output entities.json
python scripts/get_entities.py --format csv --output entities.csv
python scripts/get_entities.py  # prints to stdout
```
**Output**: Active entities with id, code, name, email  

---

#### `manage_users.py`
**Purpose**: Manage user accounts (create, update, delete, list) from command line  
**When to Use**: Batch user setup or automation  
**Command**:
```bash
python scripts/manage_users.py --action [create|update|delete|list] [--username NAME] [--password PASS] [--role admin|controller|entry|viewer]
```
**Examples**:
```bash
# Create new user
python scripts/manage_users.py --action create --username john --password SecurePass123 --role entry

# List all users
python scripts/manage_users.py --action list

# Delete user
python scripts/manage_users.py --action delete --username john
```
**Notes**:
- Always use strong passwords
- Roles: admin (full access) | controller (manage entities) | entry (create books) | viewer (read-only)

---

### Optional/Experimental Scripts (⚠️)

#### `optimize_startup.py`
**Purpose**: Optimize startup and run safe DB/migration health checks  
**When to Use**: Debugging slow startup  
**Command**:
```bash
python scripts/optimize_startup.py
python scripts/optimize_startup.py --apply-migrations
```
**Notes**:
- Runs `python manage.py db_healthcheck` by default
- Does **not** apply migrations unless `--apply-migrations` is passed

---

#### `train_ocr_local.py`
**Purpose**: Train custom EasyOCR model on labeled feedback data  
**When to Use**: Improving OCR accuracy for specific document types  
**Command**:
```bash
python scripts/train_ocr_local.py --input training_data/ --output model.pt --epochs 10
```
**Status**: EXPERIMENTAL — requires significant training data and GPU  
**Notes**:
- Requires CUDA GPU for reasonable performance
- Use feedback from `ExtractionFeedback` model
- Long-running task (hours)

---

### Development Scripts (⚠️ Dev-only)

#### `start_django.ps1`
**Purpose**: Start Django development server on Windows  
**Command**: 
```powershell
.\scripts\start_django.ps1
```
**What it does**: 
- Activates venv
- Runs `python manage.py runserver 0.0.0.0:8000`

---

#### `enable_scan_simulator.ps1` / `enable_scan_simulator.bat`
**Purpose**: Enable virtual scan device for testing without hardware  
**When to Use**: Development/testing without physical scanner  
**Command** (PowerShell):
```powershell
.\scripts\enable_scan_simulator.ps1
```
**Command** (Batch):
```batch
scripts\enable_scan_simulator.bat
```
**What it does**: Loads virtual scanner driver (Windows-specific)  
**Notes**: Admin privileges may be required

---

#### `manage_server_background.ps1`
**Purpose**: Start/stop Django server as background process (Windows)  
**Command**:
```powershell
.\scripts\manage_server_background.ps1 -action start
.\scripts\manage_server_background.ps1 -action stop
```
**Notes**: Development-only, not for production use

---

#### `run_server_background.py`
**Purpose**: Run Django dev server in background (Linux/Mac)  
**Command**:
```bash
python scripts/run_server_background.py --start
python scripts/run_server_background.py --stop
```
**Notes**: Development-only

---

#### `auto_train.ps1` / `quick_train.ps1`
**Purpose**: Automated or quick OCR model training workflow  
**Status**: BETA — may have bugs  
**Command**:
```powershell
.\scripts\auto_train.ps1        # Full training pipeline
.\scripts\quick_train.ps1       # Quick iteration training
```
**Notes**: Requires training data + GPU  

---

## 🚀 Server startup

### Development only — loopback port 8000
```bash
# Legacy development helper; it binds 0.0.0.0:8000, not the live service.
.\scripts\start_django.ps1

# Local-only alternative:
python manage.py runserver 127.0.0.1:8000
```

Production release and backup operations are gated and environment-specific;
follow the current Windows LAN deployment and launch runbook linked above.
The former generic pre-deployment checklist is intentionally not retained here:
preloading OCR, exporting live entities, or running generic startup scripts is
not a substitute for the verified release procedure.

---

## 📋 Maintenance Schedule

| Script | Frequency | Purpose |
|--------|-----------|---------|
| `preload_ocr_model.py` | On deployment, quarterly updates | Keep OCR models fresh |
| `get_entities.py` | Weekly | Backup entity data |
| `manage_users.py` | As needed | User administration |
| `optimize_startup.py` | Monthly | Monitor performance |
| Training scripts | Ongoing | Improve accuracy |

---

## 🔧 Troubleshooting

### OCR Model Download Fails
```bash
# Check internet connection, then retry
python scripts/preload_ocr_model.py

# Or manually download to cache
mkdir ~/.EasyOCR/model_zoo
# Download model manually from HuggingFace
```

### User Management Issues
```bash
# Verify Django can access DB
python manage.py shell
>>> from django.contrib.auth import get_user_model
>>> get_user_model().objects.all()
```

### Server Won't Start
```bash
# Check debug logs
tail logs/django.log
# Verify PostgreSQL connection settings in .env
python manage.py db_healthcheck
```

---

## 📚 Related Documentation

- [SETUP_INSTRUCTIONS.md](../SETUP_INSTRUCTIONS.md) — Initial setup
- [README.md](../README.md) — Project overview
- [API_REFERENCE.md](../API_REFERENCE.md) — REST API docs
- [.env.example](../.env.example) — Environment variables

---

## 📌 Notes

- **Always backup data** before running user/entity management scripts
- **Development scripts** are not suitable for production
- **Training scripts** require significant resources (GPU, RAM, training data)
- **Version compatibility**: Scripts tested on Python 3.11+ with Django 4.2.14

---

**Last Updated**: 2026-04-30  
**Maintainer**: LetterSys Team  
**Status**: Phase 2.5 Dead Code Cleanup
