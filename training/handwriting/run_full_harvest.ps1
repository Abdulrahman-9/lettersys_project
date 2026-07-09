# حصاد كامل منفصل عن جلسة المحرر — يكمل ولو انقطعت الجلسة.
# قابل للاستئناف بأمان: strips الموجودة + سجل processed.txt يُتخطّيان.
$ErrorActionPreference = 'Continue'
$env:PYTHONIOENCODING = 'utf-8'
Set-Location "c:\Users\fwz\Downloads\lettersys_django_bootstrap_v4_scan\lettersys_django_bootstrap_v4_scan\lettersys_project"
foreach ($off in 0..17) {
    $offset = $off * 500
    Add-Content "training\handwriting\harvest\harvest_run.log" "=== $(Get-Date -Format 'HH:mm:ss') دفعة offset=$offset ==="
    python manage.py harvest_number_strips --limit 500 --offset $offset *>> "training\handwriting\harvest\harvest_run.log"
}
Add-Content "training\handwriting\harvest\harvest_run.log" "=== $(Get-Date -Format 'HH:mm:ss') اكتمل الحصاد الكامل ==="
