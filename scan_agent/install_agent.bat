@echo off
chcp 65001 >nul
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
REM  يفعل هذا فقط:
REM    1. يكتب %LOCALAPPDATA%\LetterSys\agent.json بالأصول المُمرَّرة (بعد الموافقة).
REM    2. إن جاء من حزمة التوزيع (python\ بجوار scan_agent\ — يبنيها build_dist.ps1):
REM       ينسخهما إلى %LOCALAPPDATA%\LetterSys\agent فلا يحتاج الجهازُ Python مثبَّتاً
REM       ولا يعمل الوكيلُ من مسار شبكة. (من نسخة المشروع: run_agent.bat كما كان.)
REM    3. يضع اختصارَ التشغيل التلقائيّ في shell:startup ويشغّل الوكيلَ الآن.
REM    4. يحذف agent_token.txt القديم (لم يبقَ له معنى بعد إسقاط التوكِن).
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

REM ── 3) الوقتُ التشغيليّ: Python المضمَّن + الحزمة إلى مجلّد المستخدم ──
REM `robocopy "%SCRIPT_DIR%."`: الشرطةُ الخلفيّة الختاميّة قبل علامة الاقتباس تُفسد
REM تحليلَ robocopy للوسيط؛ النقطةُ تُنهي المسارَ بلا شرطة.
set "AGENT_DIR=%DATA_DIR%\agent"
set "LS_TARGET=%SCRIPT_DIR%run_agent.bat"
set "LS_ARGS="
set "LS_WORKDIR=%SCRIPT_DIR%.."
if exist "%SCRIPT_DIR%..\python\pythonw.exe" (
    call :stop_running_agent
    robocopy "%SCRIPT_DIR%..\python" "%AGENT_DIR%\python" /MIR /NFL /NDL /NJH /NJS /NP >nul
    if errorlevel 8 goto copyfail
    robocopy "%SCRIPT_DIR%." "%AGENT_DIR%\scan_agent" /MIR /XD __pycache__ naps2_portable /XF tests_agent.py /NFL /NDL /NJH /NJS /NP >nul
    if errorlevel 8 goto copyfail
    set "LS_TARGET=%AGENT_DIR%\python\pythonw.exe"
    set "LS_ARGS=-m scan_agent"
    set "LS_WORKDIR=%AGENT_DIR%"
    echo [تمّ] نُسخ الوكيلُ ووقتُه التشغيليّ إلى %AGENT_DIR%
)

REM ── 4) اختصارُ بدء التشغيل، ثمّ شغّله الآن (بلا إعادة إقلاع) ──
REM المساراتُ تُمرَّر إلى PowerShell عبر البيئة لا بالاقتباس المفرد: مسارٌ فيه فاصلةٌ
REM عليا (اسمُ مستخدمٍ مثل O'Brien) كان يكسر السطرَ أو يُحقن فيه شيفرة.
set "LS_LINK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\LetterSys Scan Agent.lnk"
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:LS_LINK); $s.TargetPath=$env:LS_TARGET; $s.Arguments=$env:LS_ARGS; $s.WorkingDirectory=$env:LS_WORKDIR; $s.Save()"
echo [تمّ] اختصارُ التشغيل التلقائيّ: %LS_LINK%
REM الاختباراتُ تشغّل هذا السكربتَ فعلاً في صندوقٍ مؤقّت — لا تُطلق وكيلاً حقيقيّاً منها.
if not defined LETTERSYS_INSTALL_NO_START (
    start "" "%LS_LINK%"
    echo [تمّ] شُغّل الوكيل
)

REM ── 5) توكِنٌ قديم لم يبقَ له معنى ──
if exist "%DATA_DIR%\agent_token.txt" (
    del /q "%DATA_DIR%\agent_token.txt"
    echo [تمّ] حُذف agent_token.txt القديم
)

echo.
echo انتهى. افتح صفحةَ الإدخال الذكي — يظهر المؤشّر «جاهز» خلال ثوانٍ.
endlocal
exit /b 0

:stop_running_agent
REM تحديثٌ فوق وكيلٍ يعمل: ملفّاتُه مقفلةٌ ومنفذُه محجوز. نوقف نسختَنا المنسوخة وحدها
REM (pythonw من مجلّد agent)، لا أيَّ pythonw آخر على الجهاز.
powershell -NoProfile -Command "Get-Process pythonw -ErrorAction SilentlyContinue | Where-Object { $_.Path -like ($env:AGENT_DIR + '\*') } | Stop-Process -Force"
goto :eof

:copyfail
echo.
echo [خطأ] تعذّر نسخُ الوكيل إلى %AGENT_DIR% — لم يُنشأ اختصارُ التشغيل.
echo.
exit /b 4

:cancel
del /q "%LS_TMP%" 2>nul
echo.
echo [أُلغي] لم يُكتب شيء ولم يُغيَّر %JSON_FILE%.
echo.
exit /b 1
