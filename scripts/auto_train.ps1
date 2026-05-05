# ===================================================
# سكريبت التدريب التلقائي الكامل
# ===================================================
# يقوم بـ:
#   1. استخراج البيانات من الأرشيف
#   2. التدريب المحلي
#   3. عرض النتائج
# ===================================================

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  🎓 نظام التدريب التلقائي الكامل لـ OCR" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

$projectPath = "C:\Users\fwz\Downloads\lettersys_django_bootstrap_v4_scan\lettersys_django_bootstrap_v4_scan\lettersys_project"

# التحقق من وجود البيانات الحالية
Write-Host "🔍 التحقق من البيانات الحالية..." -ForegroundColor Yellow
cd $projectPath
$result = python manage.py shell -c "from core.models import OCRFeedback; print(OCRFeedback.objects.filter(used_for_training=False).count())"
$pendingCount = [int]$result

if ($pendingCount -ge 100) {
    Write-Host "✅ وجدنا $pendingCount عينة جاهزة للتدريب!" -ForegroundColor Green
    Write-Host "   ننتقل مباشرة للتدريب..." -ForegroundColor Green
    Write-Host ""
} else {
    Write-Host "⚠️  عدد العينات الحالية: $pendingCount (نحتاج 100+)" -ForegroundColor Yellow
    Write-Host ""
    
    # الخيار: استخراج أم لا؟
    $extract = Read-Host "هل تريد استخراج بيانات من الأرشيف الآن؟ (y/n)"
    
    if ($extract -eq 'y' -or $extract -eq 'Y') {
        Write-Host ""
        Write-Host "============================================================" -ForegroundColor Cyan
        Write-Host "  📂 المرحلة 1: استخراج البيانات من الأرشيف" -ForegroundColor Yellow
        Write-Host "============================================================" -ForegroundColor Cyan
        Write-Host ""
        
        Write-Host "⏳ يستغرق ~30 دقيقة على CPU (5 ملفات × 3 صفحات)" -ForegroundColor Yellow
        Write-Host "   يمكنك ترك النافذة مفتوحة والقيام بعمل آخر..." -ForegroundColor Gray
        Write-Host ""
        
        # تشغيل الاستخراج
        python quick_extract_for_training.py
        
        if ($LASTEXITCODE -ne 0) {
            Write-Host ""
            Write-Host "❌ فشل الاستخراج!" -ForegroundColor Red
            Write-Host "   راجع الرسائل أعلاه لمعرفة المشكلة" -ForegroundColor Red
            exit 1
        }
        
        Write-Host ""
        Write-Host "✅ اكتمل الاستخراج بنجاح!" -ForegroundColor Green
        Write-Host ""
        
        # التحقق من العدد الجديد
        $result = python manage.py shell -c "from core.models import OCRFeedback; print(OCRFeedback.objects.filter(used_for_training=False).count())"
        $pendingCount = [int]$result
        Write-Host "📊 عدد العينات الجديد: $pendingCount" -ForegroundColor Cyan
        Write-Host ""
    } else {
        Write-Host ""
        Write-Host "⚠️  تم إلغاء الاستخراج" -ForegroundColor Yellow
        Write-Host "   سنحاول التدريب بالبيانات الموجودة..." -ForegroundColor Yellow
        Write-Host ""
    }
}

# التأكيد قبل التدريب
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  🎓 المرحلة 2: التدريب المحلي" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

if ($pendingCount -lt 10) {
    Write-Host "❌ البيانات غير كافية للتدريب (نحتاج 10+ على الأقل)" -ForegroundColor Red
    Write-Host "   العدد الحالي: $pendingCount" -ForegroundColor Red
    Write-Host ""
    Write-Host "💡 نصيحة: شغّل quick_extract_for_training.py أولاً" -ForegroundColor Yellow
    exit 1
}

Write-Host "📊 سنبدأ التدريب على $pendingCount عينة" -ForegroundColor Cyan
Write-Host "⏳ الوقت المتوقع: ~20-30 دقيقة" -ForegroundColor Yellow
Write-Host ""

$confirm = Read-Host "هل تريد بدء التدريب الآن؟ (y/n)"

if ($confirm -ne 'y' -and $confirm -ne 'Y') {
    Write-Host ""
    Write-Host "⚠️  تم إلغاء التدريب" -ForegroundColor Yellow
    Write-Host "   يمكنك تشغيله لاحقاً بـ: python train_ocr_local.py" -ForegroundColor Gray
    exit 0
}

Write-Host ""
Write-Host "🚀 بدء التدريب..." -ForegroundColor Green
Write-Host ""

# تشغيل التدريب
python train_ocr_local.py

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "❌ فشل التدريب!" -ForegroundColor Red
    Write-Host "   راجع ملف الـ log: training_log_*.txt" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  ✅ اكتمل التدريب بنجاح!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# عرض النموذج الجديد
Write-Host "📊 عرض النموذج الجديد..." -ForegroundColor Cyan
python manage.py shell -c @"
from core.models import OCRModelVersion
latest = OCRModelVersion.objects.latest('created_at')
print(f'')
print(f'النموذج الجديد:')
print(f'  • الإصدار: {latest.version}')
print(f'  • اللغة: {latest.get_language_display()}')
print(f'  • عدد العينات: {latest.training_samples}')
print(f'  • التحسن المقدر: +{latest.accuracy_improvement:.2f}%')
print(f'  • التاريخ: {latest.created_at.strftime("%Y-%m-%d %H:%M")}')
print(f'')
print(f'✅ النموذج جاهز للاستخدام!')
"@

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  📁 الملفات الناتجة" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# عرض الملفات
Get-ChildItem -Path $projectPath -Filter "training_dataset_*.jsonl" | ForEach-Object {
    Write-Host "  ✅ $($_.Name) ($('{0:N0}' -f ($_.Length / 1KB)) KB)" -ForegroundColor Green
}
Get-ChildItem -Path $projectPath -Filter "training_log_*.txt" | Select-Object -First 1 | ForEach-Object {
    Write-Host "  ✅ $($_.Name) ($('{0:N0}' -f ($_.Length / 1KB)) KB)" -ForegroundColor Green
}

Write-Host ""
Write-Host "🎉 تمت العملية بنجاح!" -ForegroundColor Green
Write-Host ""
