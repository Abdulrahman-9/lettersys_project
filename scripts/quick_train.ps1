# ===================================================
# سكريبت تدريب سريع - بدون توقف!
# ===================================================
# يقوم بـ: استخراج → تدريب → تلقائياً
# ===================================================

$projectPath = "C:\Users\fwz\Downloads\lettersys_django_bootstrap_v4_scan\lettersys_django_bootstrap_v4_scan\lettersys_project"
Set-Location -Path $projectPath

Write-Host ""
Write-Host "Starting auto training..." -ForegroundColor Green
Write-Host ""

# 1. الاستخراج
Write-Host "Step 1/2: Extract data (~30 min)..." -ForegroundColor Yellow
python quick_extract_for_training.py
Write-Host "Extraction completed." -ForegroundColor Green
Write-Host ""

# 2. التدريب
Write-Host "Step 2/2: Train (~20 min)..." -ForegroundColor Yellow
python train_ocr_local.py
Write-Host "Training completed." -ForegroundColor Green
Write-Host ""

Write-Host "Done! Check training_dataset_*.jsonl and training_log_*.txt" -ForegroundColor Green
Write-Host ""
