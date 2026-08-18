# ===================================================
#  تصدير مجموعة تدريب OCR من التصحيحات اليدوية
# ===================================================
#  يجمع تصحيحات OCRFeedback غير المستهلَكة ويكتبها JSONL جاهزاً لمسار التدريب
#  الفعلي (Kaggle/Lightning)، ثم يقف.
#
#  لا يُدرِّب هنا ولا يدّعي تدريباً: النسخة السابقة كانت تستدعي
#  quick_extract_for_training.py (غير موجود)، وتقرأ حقلَي get_language_display
#  و accuracy_improvement (غير موجودين على النموذج)، وتشير إلى مسارٍ خاطئ
#  للسكربت — فتفشل في أربعة مواضع قبل أن تصل إلى شيء.
# ===================================================

$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $PSScriptRoot
Set-Location $projectPath
$env:PYTHONIOENCODING = 'utf-8'

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  تصدير مجموعة تدريب OCR" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# ── العيّنات المتاحة ─────────────────────────────────────────────────────────
Write-Host "التحقق من التصحيحات غير المستهلَكة..." -ForegroundColor Yellow
$pending = python manage.py shell -c "from core.models import OCRFeedback; print(OCRFeedback.objects.filter(used_for_training=False).count())"
if (-not $?) { Write-Host "تعذّر الاتصال بقاعدة البيانات." -ForegroundColor Red; exit 1 }
$pendingCount = [int]($pending | Select-Object -Last 1).Trim()

Write-Host "  عيّنات جاهزة: $pendingCount" -ForegroundColor Cyan

if ($pendingCount -eq 0) {
    Write-Host ""
    Write-Host "لا تصحيحات غير مستهلَكة — لا شيء يُصدَّر." -ForegroundColor Yellow
    Write-Host "لتضمين ما استُهلك سابقاً:" -ForegroundColor Gray
    Write-Host "  python scripts\train_ocr_local.py --include-used" -ForegroundColor Gray
    exit 0
}
if ($pendingCount -lt 100) {
    Write-Host "  (الموصى به 500+ عيّنة؛ نُصدّر ما هو متاح)" -ForegroundColor DarkYellow
}

# ── التصدير ─────────────────────────────────────────────────────────────────
Write-Host ""
python scripts\train_ocr_local.py
# 0 = كُتبت مجموعة · 2 = لا شيء يستحقّ التصدير (ليس فشلاً) · غيرهما = خطأ
if ($LASTEXITCODE -eq 2) {
    Write-Host ""
    Write-Host "لم تُكتب مجموعة — راجع السبب أعلاه." -ForegroundColor Yellow
    exit 0
}
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "فشل التصدير — راجع الرسائل أعلاه." -ForegroundColor Red
    exit 1
}

# ── آخر مجموعة مُصدَّرة (حقولٌ موجودة فعلاً على النموذج) ─────────────────────
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  آخر مجموعة" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Cyan
python manage.py shell -c @"
from core.models import TrainingDataset
d = TrainingDataset.objects.order_by('-created_at').first()
if d:
    print('  المعرّف   :', d.id)
    print('  الاسم     :', d.name)
    print('  الحالة    :', d.get_status_display())
    print('  العيّنات   :', d.total_samples, '(عربي', d.arabic_samples, '| إنجليزي', d.english_samples, ')')
    print('  الملف     :', (d.metadata or {}).get('export_path', '-'))
    print('  التاريخ   :', d.created_at.strftime('%Y-%m-%d %H:%M'))
"@

Write-Host ""
Write-Host "الملفّات في var\training :" -ForegroundColor Cyan
Get-ChildItem -Path (Join-Path $projectPath 'var\training') -Filter "training_dataset_*.jsonl" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 5 | ForEach-Object {
        Write-Host ("  {0}  ({1:N0} KB)" -f $_.Name, ($_.Length / 1KB)) -ForegroundColor Green
    }

Write-Host ""
Write-Host "لم يجرِ تدريب — هذه خطوة التصدير وحدها." -ForegroundColor Yellow
Write-Host "بعد أن يكتمل التدريب فعلاً على المسار الخارجي، استهلِك العيّنات بـ:" -ForegroundColor Gray
Write-Host "  python scripts\train_ocr_local.py --mark-used <DATASET_ID>" -ForegroundColor Gray
Write-Host ""
