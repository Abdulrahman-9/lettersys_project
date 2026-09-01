# مسح بصمات كل الجهات (≥3 كتب) — منفصلٌ عن جلسة المحرر، قابل للاستئناف.
$ErrorActionPreference = 'Continue'
$env:PYTHONIOENCODING = 'utf-8'
Set-Location "c:\Users\fwz\Downloads\lettersys_django_bootstrap_v4_scan\lettersys_django_bootstrap_v4_scan\lettersys_project"
$log = "var\entity_sweep.log"
Add-Content $log "=== $(Get-Date -Format 'HH:mm:ss') START ==="
python manage.py study_entity_layouts --all --min-books 3 --per-entity 6 --resume *>> $log
Add-Content $log "=== $(Get-Date -Format 'HH:mm:ss') ENTITY_SWEEP_COMPLETE ==="
