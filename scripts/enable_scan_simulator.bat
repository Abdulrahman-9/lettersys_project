@echo off
REM 🤖 تفعيل وضع محاكاة الماسح الضوئي
REM Enable Scan Simulator Mode

echo.
echo 🔧 تفعيل وضع محاكاة الماسح الضوئي...
echo 🔧 Enabling Scan Simulator Mode...
echo.

REM تعيين المتغيرات البيئية
set SCAN_SIMULATOR_MODE=True
set SCAN_SIMULATOR_DELAY=3

echo ✅ تم تعيين المتغيرات البيئية:
echo    SCAN_SIMULATOR_MODE = %SCAN_SIMULATOR_MODE%
echo    SCAN_SIMULATOR_DELAY = %SCAN_SIMULATOR_DELAY%
echo.

echo 🚀 الآن يمكنك تشغيل الخادم بأمان بدون برنامج Canon CaptureOnTouch
echo 🚀 Now you can safely run the server without Canon CaptureOnTouch program
echo.

REM تشغيل الخادم
python manage.py runserver localhost:8000
