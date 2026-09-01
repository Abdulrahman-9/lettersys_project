# حصاد شرائط التواريخ منفصلاً عن جلسة المحرر — ينجو من انقطاعها (درس اليوم:
# ثلاث محاولات ماتت مع الجلسة). قابل للاستئناف: strips_date + processed_date.
$ErrorActionPreference = 'Continue'
$env:PYTHONIOENCODING = 'utf-8'
Set-Location "c:\Users\fwz\Downloads\lettersys_django_bootstrap_v4_scan\lettersys_django_bootstrap_v4_scan\lettersys_project"
$log = "training\handwriting\harvest\date_harvest_run.log"
foreach ($off in 0..18) {
    $offset = $off * 500
    Add-Content $log "=== $(Get-Date -Format 'HH:mm:ss') chunk offset=$offset ==="
    python manage.py harvest_number_strips --field date --limit 500 --offset $offset *>> $log
}
Add-Content $log "=== $(Get-Date -Format 'HH:mm:ss') DATE_HARVEST_COMPLETE ==="
