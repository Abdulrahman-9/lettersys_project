@echo off
REM ════════════════════════════════════════════════════════════════════════════
REM  تركيبُ وكيل المسح على حاسبة كاتبة — يُنفَّذ مرّةً واحدةً لكلّ حاسبة بيد المسؤول،
REM  والكاتبةُ لا تكتب شيئاً.
REM
REM  الاستعمال (أصلُ خادم LetterSys بصيغة IP:المنفذ — هي الموصى بها قبل TLS):
REM      install_agent.bat http://192.0.2.10:8000
REM
REM  تحذير: كلُّ أصلٍ تُمرّره هنا **منحٌ كامل**: أيُّ صفحةٍ على ذلك العنوان تستطيع سردَ
REM  ماسحات هذه الحاسبة وبدءَ مسحٍ وقراءةَ كلِّ ما يُمسَح. لذلك:
REM    1. كلُّ وسيطٍ يُتحقَّق من شكله أوّلاً (مخطّط + مضيف + منفذٌ اختياريّ، لا أكثر)،
REM       فسطرٌ مثل `install_agent.bat http://evil.example/x` لا يُكتَب أبداً.
REM    2. ثمّ يُعرَض agent.json الناتج ويُطلَب `y` صريحةً قبل أيّ كتابة.
REM    3. اسمٌ مفردٌ على `http` (مثل `http://lettersys`) يُنبَّه عليه: قابلٌ للانتحال
REM       على شبكة ويندوز (LLMNR/NBT-NS/mDNS) — لا تُضِف الاسمَ إلّا بـ`https` بعد
REM       وصول شهادة. التفصيلُ في README.md (قسم «قائمةُ الأصول»).
REM  وسطرُ أمرٍ لم تكتبه أنت خارجَ النطاق: مَن يختار أمرَك يستطيع تشغيلَ أيّ شيء —
REM  الحارسُ هنا لوسيطٍ يبدو بريئاً (عنوانٌ فقط) أُرسل إلى مَن ينفّذ المُثبِّت.
REM
REM  يفعل ثلاثةَ أشياء فقط:
REM    1. يكتب %LOCALAPPDATA%\LetterSys\agent.json بالأصول المُمرَّرة (بعد الموافقة).
REM    2. يضع اختصارَ التشغيل التلقائيّ في shell:startup.
REM    3. يحذف agent_token.txt القديم (لم يبقَ له معنى بعد إسقاط التوكِن).
REM ════════════════════════════════════════════════════════════════════════════
setlocal

if "%~1"=="" (
    echo.
    echo [خطأ] مرّر أصلاً واحداً على الأقل، مثلاً:
    echo     install_agent.bat http://192.0.2.10:8000
    echo.
    exit /b 2
)

REM مجلّدُ السكربت يُحتجَز قبل الحلقة: `shift` يُزحزح `%0` أيضاً، فـ`%~dp0` بعدها
REM يشير إلى وسيطٍ لا إلى السكربت (كان اختصارُ بدء التشغيل يُنشَأ بهدفٍ فاسد).
set "SCRIPT_DIR=%~dp0"
set "DATA_DIR=%LOCALAPPDATA%\LetterSys"
set "JSON_FILE=%DATA_DIR%\agent.json"
set "LS_TMP=%TEMP%\lettersys_agent_%RANDOM%%RANDOM%.json"

REM ── 1) تحقَّق من كلّ وسيط قبل أيّ كتابة ──
set "LS_ORIGINS="
:collect
if "%~1"=="" goto compose
set "LS_ARG=%~1"
powershell -NoProfile -Command "exit ([int]($env:LS_ARG -notmatch '^https?://[A-Za-z0-9._-]+(:[0-9]{1,5})?$'))"
if errorlevel 1 goto badarg
call :warn_if_spoofable
if defined LS_ORIGINS (set "LS_ORIGINS=%LS_ORIGINS% %LS_ARG%") else (set "LS_ORIGINS=%LS_ARG%")
shift
goto collect

:badarg
echo.
echo [خطأ] أصلٌ غير صالح: %LS_ARG%
echo   الصيغةُ المقبولة: http(s)://مضيف[:منفذ] — بلا مسارٍ ولا شرطةٍ ختاميّة ولا مسافات.
echo   أمثلة:  http://192.0.2.10:8000    https://SERVER-NAME
echo   لم يُكتب شيء. وتذكّر: كلُّ أصلٍ هنا منحٌ كاملٌ لماسح هذه الحاسبة ولمستنداتها
echo   الممسوحة — لا تُضِف عنواناً أرسله لك أحد.
echo.
exit /b 2

:warn_if_spoofable
powershell -NoProfile -Command "$u=$env:LS_ARG; $h=([uri]$u).Host; exit ([int]($u -like 'http://*' -and $h -notmatch '^[0-9.]+$' -and $h -notlike '*.*'))"
if errorlevel 1 (
    echo.
    echo [تنبيه] %LS_ARG% اسمٌ مفردٌ على http: قابلٌ للانتحال على شبكة ويندوز
    echo         ^(LLMNR/NBT-NS/mDNS^) — أيُّ جهازٍ على الشبكة قد يُجيب بهذا الاسم فيصير
    echo         أصلاً موثوقاً عند وكيلك. الموصى به: صيغةُ IP:المنفذ الآن، والاسمُ
    echo         بـhttps بعد وصول شهادة.
)
goto :eof

REM ── 2) اكتب الملفَّ المرشَّح في مسارٍ مؤقّت واعرضه قبل أيّ تثبيت ──
:compose
powershell -NoProfile -Command "@{allowed_origins=@($env:LS_ORIGINS -split ' ' | Where-Object { $_ })} | ConvertTo-Json | Set-Content -LiteralPath $env:LS_TMP -Encoding utf8"
if not exist "%LS_TMP%" (
    echo [خطأ] تعذّر تجهيزُ agent.json المؤقّت — لم يُكتب شيء.
    exit /b 3
)

echo.
echo هذا ما سيُكتب إلى %JSON_FILE% :
echo ------------------------------------------------------------
type "%LS_TMP%"
echo ------------------------------------------------------------
echo كلُّ عنوانٍ في هذه القائمة منحٌ كاملٌ لماسح هذه الحاسبة ولكلّ ما تمسحه عليها.
echo لا توافق إلّا إن كان هذا عنوانَ خادم LetterSys في شركتك.
echo.
choice /c yn /n /m "أتوافق على الكتابة؟ [y/n] "
if errorlevel 2 goto cancel
if not errorlevel 1 goto cancel

if not exist "%DATA_DIR%" mkdir "%DATA_DIR%"
move /y "%LS_TMP%" "%JSON_FILE%" >nul
echo [تمّ] كُتب %JSON_FILE%

REM ── 3) اختصارُ بدء التشغيل ──
REM المساراتُ تُمرَّر إلى PowerShell عبر البيئة لا بالاقتباس المفرد: مسارٌ فيه فاصلةٌ
REM عليا (اسمُ مستخدمٍ مثل O'Brien) كان يكسر السطرَ أو يُحقن فيه شيفرة.
set "LS_TARGET=%SCRIPT_DIR%run_agent.bat"
if exist "%SCRIPT_DIR%..\LetterSysScanAgent.exe" set "LS_TARGET=%SCRIPT_DIR%..\LetterSysScanAgent.exe"
set "LS_LINK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\LetterSys Scan Agent.lnk"
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:LS_LINK); $s.TargetPath=$env:LS_TARGET; $s.WorkingDirectory=(Split-Path -LiteralPath $env:LS_TARGET); $s.Save()"
echo [تمّ] اختصارُ التشغيل التلقائيّ: %LS_LINK%

REM ── 4) توكِنٌ قديم لم يبقَ له معنى ──
if exist "%DATA_DIR%\agent_token.txt" (
    del /q "%DATA_DIR%\agent_token.txt"
    echo [تمّ] حُذف agent_token.txt القديم
)

echo.
echo انتهى. شغّل الوكيل الآن (أو أعد إقلاع الحاسبة) ثمّ افتح صفحةَ الإدخال الذكي.
endlocal
exit /b 0

:cancel
del /q "%LS_TMP%" 2>nul
echo.
echo [أُلغي] لم يُكتب شيء ولم يُغيَّر %JSON_FILE%.
echo.
exit /b 1
