@echo off
REM ════════════════════════════════════════════════════════════════════════════
REM  تركيبُ وكيل المسح على حاسبة كاتبة — يُنفَّذ مرّةً واحدةً لكلّ حاسبة بيد المسؤول،
REM  والكاتبةُ لا تكتب شيئاً.
REM
REM  الاستعمال (مرّر أصلَ الخادم بالاسم وبالـIP:المنفذ معاً كي لا تنقطع الحاسبة
REM  عند تغيير العنوان يومَ التدشين):
REM      install_agent.bat http://lettersys http://172.16.2.16:8000
REM
REM  يفعل ثلاثةَ أشياء فقط:
REM    1. يكتب %LOCALAPPDATA%\LetterSys\agent.json بالأصول المُمرَّرة.
REM    2. يضع اختصارَ التشغيل التلقائيّ في shell:startup.
REM    3. يحذف agent_token.txt القديم (لم يبقَ له معنى بعد إسقاط التوكِن).
REM ════════════════════════════════════════════════════════════════════════════
setlocal EnableDelayedExpansion

if "%~1"=="" (
    echo.
    echo [خطأ] مرّر أصلاً واحداً على الأقل، مثلاً:
    echo     install_agent.bat http://lettersys http://172.16.2.16:8000
    echo.
    exit /b 2
)

set "DATA_DIR=%LOCALAPPDATA%\LetterSys"
if not exist "%DATA_DIR%" mkdir "%DATA_DIR%"

REM ── 1) agent.json: قائمةُ الأصول المسموح لها بتشغيل الماسح ──
set "JSON="
:collect
if "%~1"=="" goto write
if defined JSON (set "JSON=!JSON!, ")
set "JSON=!JSON!\"%~1\""
shift
goto collect

:write
> "%DATA_DIR%\agent.json" echo {"allowed_origins": [!JSON!]}
echo [تمّ] كُتب %DATA_DIR%\agent.json
type "%DATA_DIR%\agent.json"

REM ── 2) اختصارُ بدء التشغيل ──
set "TARGET=%~dp0run_agent.bat"
if exist "%~dp0..\LetterSysScanAgent.exe" set "TARGET=%~dp0..\LetterSysScanAgent.exe"
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
powershell -NoProfile -Command ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%STARTUP%\LetterSys Scan Agent.lnk');" ^
  "$s.TargetPath='%TARGET%'; $s.WorkingDirectory=(Split-Path '%TARGET%'); $s.Save()"
echo [تمّ] اختصارُ التشغيل التلقائيّ: %STARTUP%\LetterSys Scan Agent.lnk

REM ── 3) توكِنٌ قديم لم يبقَ له معنى ──
if exist "%DATA_DIR%\agent_token.txt" (
    del /q "%DATA_DIR%\agent_token.txt"
    echo [تمّ] حُذف agent_token.txt القديم
)

echo.
echo انتهى. شغّل الوكيل الآن (أو أعد إقلاع الحاسبة) ثمّ افتح صفحةَ الإدخال الذكي.
endlocal
