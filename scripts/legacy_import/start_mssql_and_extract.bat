@echo off
REM ============================================================
REM تشغيل SQL Server عبر Docker واستخراج البيانات القديمة
REM شغّل هذا الملف بصلاحيات Administrator
REM ============================================================

SET BAK_DIR=D:\Abdulrhman Backup
SET EXPORT_DIR=%~dp0export
SET CONTAINER_NAME=lettersys_mssql_import
SET SA_PASS=LetterSys@Import2026

echo.
echo ===================================================
echo   LetterSys - استخراج البيانات القديمة
echo ===================================================
echo.

REM إنشاء مجلد الإخراج
if not exist "%EXPORT_DIR%" mkdir "%EXPORT_DIR%"

REM إيقاف أي كونتينر قديم بنفس الاسم
echo [1/5] تنظيف الكونتينرات القديمة...
docker stop %CONTAINER_NAME% 2>nul
docker rm %CONTAINER_NAME% 2>nul

REM التحقق من وجود الصورة
echo [2/5] التحقق من صورة SQL Server...
docker images mcr.microsoft.com/mssql/server:2019-latest --format "{{.ID}}" | findstr . >nul
if errorlevel 1 (
    echo تحميل صورة SQL Server 2019...
    docker pull mcr.microsoft.com/mssql/server:2019-latest
)

REM نسخ ملف BAK بدون أحرف عربية في الاسم (لتجنب مشاكل التوافق)
echo [3/5] تحضير ملف النسخة الاحتياطية...
copy "D:\Abdulrhman Backup\2026-05-03-14-09-01-قسم المتابعة.bak" "%EXPORT_DIR%\legacy.bak"
if errorlevel 1 (
    echo خطأ: تعذر نسخ ملف .bak - تحقق من المسار
    pause
    exit /b 1
)

REM تشغيل SQL Server
echo [4/5] تشغيل SQL Server...
docker run -d --name %CONTAINER_NAME% ^
    -e "ACCEPT_EULA=Y" ^
    -e "SA_PASSWORD=%SA_PASS%" ^
    -e "MSSQL_PID=Express" ^
    -p 1433:1433 ^
    -v "%EXPORT_DIR%:/export" ^
    mcr.microsoft.com/mssql/server:2019-latest

echo انتظار 30 ثانية لبدء تشغيل SQL Server...
timeout /t 30 /nobreak

REM نسخ ملف .bak داخل الكونتينر
echo [5/5] نسخ ملف النسخ الاحتياطي داخل الكونتينر...
docker cp "%EXPORT_DIR%\legacy.bak" %CONTAINER_NAME%:/backup/legacy.bak 2>nul || (
    docker exec %CONTAINER_NAME% mkdir -p /backup
    docker cp "%EXPORT_DIR%\legacy.bak" %CONTAINER_NAME%:/backup/legacy.bak
)

REM نسخ وتشغيل سكريبت الاستخراج
docker cp "%~dp0run_extraction.sh" %CONTAINER_NAME%:/run_extraction.sh
docker exec %CONTAINER_NAME% chmod +x /run_extraction.sh
docker exec -it %CONTAINER_NAME% /bin/bash /run_extraction.sh

echo.
echo ===================================================
echo  اكتمل الاستخراج! راجع مجلد:
echo  %EXPORT_DIR%
echo ===================================================
echo.
pause
