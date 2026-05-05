# 🤖 تفعيل وضع محاكاة الماسح الضوئي
# Enable Scan Simulator Mode

Write-Host "🔧 تفعيل وضع محاكاة الماسح الضوئي..." -ForegroundColor Cyan
Write-Host "🔧 Enabling Scan Simulator Mode..." -ForegroundColor Cyan

# تعيين المتغيرات البيئية للجلسة الحالية
[System.Environment]::SetEnvironmentVariable("SCAN_SIMULATOR_MODE", "True", "Process")
[System.Environment]::SetEnvironmentVariable("SCAN_SIMULATOR_DELAY", "3", "Process")

Write-Host "✅ تم تعيين المتغيرات البيئية:" -ForegroundColor Green
Write-Host "   SCAN_SIMULATOR_MODE = True" -ForegroundColor Green
Write-Host "   SCAN_SIMULATOR_DELAY = 3" -ForegroundColor Green

Write-Host ""
Write-Host "🚀 الآن يمكنك تشغيل الخادم بأمان بدون برنامج Canon CaptureOnTouch" -ForegroundColor Yellow
Write-Host "🚀 Now you can safely run the server without Canon CaptureOnTouch program" -ForegroundColor Yellow

Write-Host ""
Write-Host "▶️  تشغيل الخادم..." -ForegroundColor Cyan

# تشغيل الخادم
python manage.py runserver 0.0.0.0:8000

