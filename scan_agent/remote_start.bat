@echo off
REM جاهز للاستخدام على الجهاز الثاني (الذي يملك الماسح)
REM استخدم هذا الملف بدل كتابة الأوامر يدويًا.

setlocal
set "LETTERSYS_AGENT_HOST=0.0.0.0"
set "LETTERSYS_AGENT_PORT=17865"
set "LETTERSYS_AGENT_ALLOWED_ORIGINS=http://172.16.2.16:8000"

REM ابحث عن Python في PATH، أو استخدم py launcher
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    py -3 -m scan_agent
    exit /b %ERRORLEVEL%
)

where python >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    python -m scan_agent
    exit /b %ERRORLEVEL%
)

REM إن لم يجد Python، اطلب تثبيته أو استخدم المسار الكامل للـ Python
echo.
echo Python not found in PATH.
echo Install Python 3.11 or 3.12, then run this file again.
echo Or replace the last command with the full path to python.exe.
exit /b 1
