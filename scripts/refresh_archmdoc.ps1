# ============================================================================
#  refresh_archmdoc.ps1 — تحديث قاعدة المصدر ARCHMDOC من ملف باكاب جديد.
#
#  يُشغَّل من الطرفية فقط، لا من التطبيق: العملية تستغرق ساعة إلى ثلاث، وتحتاج
#  جهازاً هادئاً. كل خطوة لها بوّابة تحقّق، والسكربت يتوقّف عند أول فشل.
#
#      powershell -ExecutionPolicy Bypass -File scripts\refresh_archmdoc.ps1 `
#          -BackupZip "D:\sql_temp\ARCHMDOC_backup_2026_07_21_131501_3635159.zip"
#
#  ما يفعله بالترتيب:
#    0. بوّابات: ذاكرة حرّة، ملفّ الحدّ محفوظ، نسخة PostgreSQL احتياطية.
#    1. سقف ذاكرة SQL Server (يُطبَّق **ويُتحقَّق منه**).
#    2. فكّ الضغط مرّة واحدة إلى مجلّد ثابت — ويُحتفظ به.
#    3. HEADERONLY + FILELISTONLY + VERIFYONLY قبل الالتزام بالساعة الطويلة.
#    4. وصول حصريّ ثم RESTORE ... WITH REPLACE.
#    5. بوّابات ما بعد الاستعادة: العدّ، أحدث تاريخ، ثبات المعرّفات.
#
#  الرجوع: باكاب أيار ما زال على القرص، ونسخة PostgreSQL من الخطوة 0.
# ============================================================================
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$BackupZip,
    [string]$Database   = 'ARCHMDOC',
    [string]$SqlServer  = 'localhost',
    [string]$SqlUser    = 'sa',
    [string]$DataDir    = 'D:\SQLData',
    [int]$MaxServerMemoryMB = 2048,
    [int]$MinFreeRamMB      = 2500,
    [switch]$SkipPgDump
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot

function Step($n, $text) { Write-Host "`n[$n] $text" -ForegroundColor Cyan }
function Ok($text)       { Write-Host "    OK  $text" -ForegroundColor Green }
function Die($text)      { Write-Host "    !!  $text" -ForegroundColor Red; exit 1 }

# كلمة السرّ من البيئة أو .env — لا تُمرَّر في سطر الأوامر ولا تُطبَع
$pw = $env:LEGACY_SQL_PASSWORD
if (-not $pw) {
    $envFile = Join-Path $ProjectRoot '.env'
    if (Test-Path $envFile) {
        $line = Select-String -Path $envFile -Pattern '^LEGACY_SQL_PASSWORD=(.*)$' | Select-Object -First 1
        if ($line) { $pw = $line.Matches[0].Groups[1].Value.Trim() }
    }
}
if (-not $pw) { Die 'LEGACY_SQL_PASSWORD غير موجود في البيئة ولا في .env' }
$env:SQLCMDPASSWORD = $pw     # sqlcmd يقرأها من البيئة، فلا تظهر في قائمة العمليات

# -b لازم: بدونه يُنهي sqlcmd برمز 0 حتى لو فشلت الدفعة، فيمضي السكربت على خطأ صامت.
function Sql($query, [switch]$Quiet) {
    $out = & sqlcmd -S $SqlServer -U $SqlUser -b -h -1 -W -Q $query 2>&1
    if ($LASTEXITCODE -ne 0) { Die "فشل sqlcmd: $out" }
    if (-not $Quiet) { $out | ForEach-Object { if ($_ -match '\S') { Write-Host "      $_" } } }
    return $out
}

# ── 0) البوّابات ────────────────────────────────────────────────────────────
Step 0 'بوّابات ما قبل التنفيذ'

if (-not (Test-Path $BackupZip)) { Die "ملف الباكاب غير موجود: $BackupZip" }
Ok "الباكاب موجود ($([math]::Round((Get-Item $BackupZip).Length/1GB,2)) ج.ب)"

$boundary = Join-Path $ProjectRoot "var\legacy_merge\boundary_$Database.json"
if (-not (Test-Path $boundary)) {
    Die @"
ملفّ الحدّ غير موجود: $boundary
الاستعادة تمحو النسخة الحالية، وبعدها يستحيل تمييز الصفوف التي استجدّت عن الصفوف
القديمة التي لم تُستورد. التقطه أوّلاً:
    python manage.py capture_legacy_boundary --database $Database --note "قبل استعادة جديدة"
"@
}
Ok "ملفّ الحدّ محفوظ: $boundary"

$freeMB = [math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1KB)
if ($freeMB -lt $MinFreeRamMB) {
    Die @"
الذاكرة الحرّة $freeMB م.ب — المطلوب $MinFreeRamMB م.ب على الأقل.
أغلق محرّر الأكواد والمتصفّح وأي جلسات أخرى ثم أعد التشغيل. المستهلكون الفعليّون
هم هذه التطبيقات، لا خوادم التطوير (مجموعها ~125 م.ب فقط).
"@
}
Ok "الذاكرة الحرّة $freeMB م.ب"

$zombies = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
           Where-Object { $_.CommandLine -match 'runserver' }
if ($zombies) {
    Write-Host "    إيقاف $($zombies.Count) خادم تطوير..." -ForegroundColor Yellow
    $zombies | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

if (-not $SkipPgDump) {
    # المسار المطلق إلزامي: pg_dump ليس على PATH، والنسخة 13 المثبّتة بجانبها ترفض خادم 16.
    $pgDump = 'C:\Program Files\PostgreSQL\16\bin\pg_dump.exe'
    if (-not (Test-Path $pgDump)) { Die "pg_dump غير موجود: $pgDump" }
    $bkDir = 'D:\lettersys_data\backups'
    New-Item -ItemType Directory -Force -Path $bkDir | Out-Null
    $dump = Join-Path $bkDir ("pre_refresh_" + (Get-Date -Format 'yyyyMMdd_HHmmss') + ".dump")
    Write-Host '    نسخة PostgreSQL احتياطية...' -ForegroundColor Yellow
    & $pgDump -h localhost -U lettersys_user -d lettersys -Fc -f $dump
    if ($LASTEXITCODE -ne 0) { Die 'فشل pg_dump' }
    # البوّابة محتوى لا حجم: القاعدة ~76 م.ب فأي عتبة بالميغابايت تُنتج إنذاراً كاذباً.
    $listing = & 'C:\Program Files\PostgreSQL\16\bin\pg_restore.exe' --list $dump
    foreach ($t in @('core_book', 'core_attachment', 'core_entity')) {
        if ($listing -notmatch $t) { Die "النسخة الاحتياطية لا تحوي $t" }
    }
    Ok "نسخة احتياطية سليمة: $dump"
}

# ── 1) سقف ذاكرة SQL Server ─────────────────────────────────────────────────
Step 1 "تحديد ذاكرة SQL Server عند $MaxServerMemoryMB م.ب"
# 'show advanced options' أوّلاً وإلا فشل الأمر بـ Msg 15123 — وهو فشلٌ صامت
# بلا -b، فيمضي السكربت والذاكرة بلا سقف حتى تتجمّد الآلة.
Sql "EXEC sp_configure 'show advanced options', 1; RECONFIGURE;" -Quiet | Out-Null
Sql "EXEC sp_configure 'max server memory (MB)', $MaxServerMemoryMB; RECONFIGURE;" -Quiet | Out-Null
$inUse = (Sql "SET NOCOUNT ON; SELECT CAST(value_in_use AS bigint) FROM sys.configurations WHERE name='max server memory (MB)';" -Quiet |
          Where-Object { $_ -match '^\d+$' } | Select-Object -First 1)
if ([int]$inUse -ne $MaxServerMemoryMB) { Die "السقف لم يُطبَّق (القيمة الفعلية: $inUse)" }
Ok "السقف مُطبَّق ومُتحقَّق منه: $inUse م.ب"

# ── 2) فكّ الضغط ────────────────────────────────────────────────────────────
Step 2 'فكّ الضغط (مرّة واحدة، ويُحتفظ بالناتج)'
$extractDir = [IO.Path]::ChangeExtension($BackupZip, $null).TrimEnd('.')
$bak = Get-ChildItem -Path $extractDir -Filter *.bak -ErrorAction SilentlyContinue | Select-Object -First 1
if ($bak) {
    Ok "مستخرَج سلفاً: $($bak.FullName)"
} else {
    New-Item -ItemType Directory -Force -Path $extractDir | Out-Null
    Write-Host '    قد يستغرق 25-60 دقيقة (فحص Sophos الفوري يُبطئ الكتابة ولا يمكن استثناؤه بلا صلاحية مسؤول)...' -ForegroundColor Yellow
    python -c "import zipfile,sys; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" $BackupZip $extractDir
    if ($LASTEXITCODE -ne 0) { Die 'فشل فكّ الضغط' }
    $bak = Get-ChildItem -Path $extractDir -Filter *.bak | Select-Object -First 1
    if (-not $bak) { Die 'لا ملفّ .bak داخل الأرشيف' }
    Ok "استُخرج: $($bak.FullName)"
}
$bakPath = $bak.FullName

# ── 3) فحص الباكاب قبل الالتزام ─────────────────────────────────────────────
Step 3 'فحص الباكاب (رأس + بنية + تحقّق)'
Sql "RESTORE HEADERONLY FROM DISK = N'$bakPath'"
$fileList = Sql "RESTORE FILELISTONLY FROM DISK = N'$bakPath'"
$logical = @($fileList | ForEach-Object { ($_ -split '\s{2,}')[0] } | Where-Object { $_ -match '\S' })
if ($logical.Count -lt 2) { Die 'تعذّرت قراءة الأسماء المنطقية' }
Write-Host '    التحقّق من سلامة الأرشيف (5-15 دقيقة)...' -ForegroundColor Yellow
Sql "RESTORE VERIFYONLY FROM DISK = N'$bakPath'"
Ok 'الأرشيف سليم'

# ── 4) الاستعادة ────────────────────────────────────────────────────────────
Step 4 "استعادة [$Database] فوق النسخة الحالية"
Write-Host @"
    تحذير: هذه الخطوة تمحو نسخة $Database الحالية.
    الحدّ محفوظ، وباكاب أيار وباكاب هذا الملف كلاهما على القرص.
"@ -ForegroundColor Yellow
$answer = Read-Host '    اكتب YES للمتابعة'
if ($answer -ne 'YES') { Write-Host '    أُلغي.' -ForegroundColor Yellow; exit 0 }

# الوصول الحصريّ إلزامي: أي اتصال قائم (حتى تجمّع اتصالات pyodbc) يُفشل الاستعادة
# بعد انتظار طويل بـ"Exclusive access could not be obtained".
Sql "ALTER DATABASE [$Database] SET SINGLE_USER WITH ROLLBACK IMMEDIATE;" -Quiet | Out-Null
Ok 'وصول حصريّ'

$dataFile = Join-Path $DataDir "$Database.mdf"
$logFile  = Join-Path $DataDir "${Database}_log.ldf"
Write-Host '    الاستعادة جارية (60-150 دقيقة — التهيئة الفورية للملفّات معطّلة على هذا الجهاز)...' -ForegroundColor Yellow
try {
    Sql @"
RESTORE DATABASE [$Database] FROM DISK = N'$bakPath'
WITH REPLACE, RECOVERY, STATS = 5,
     MOVE N'$($logical[0])' TO N'$dataFile',
     MOVE N'$($logical[1])' TO N'$logFile';
"@
} finally {
    Sql "IF DATABASEPROPERTYEX('$Database','Status') = 'ONLINE' ALTER DATABASE [$Database] SET MULTI_USER;" -Quiet | Out-Null
}
Ok 'اكتملت الاستعادة'

# ── 5) بوّابات ما بعد الاستعادة ─────────────────────────────────────────────
Step 5 'التحقّق من النسخة الجديدة'
Sql "SET NOCOUNT ON; SELECT name, state_desc FROM sys.databases WHERE name = '$Database';"

Write-Host '    مقارنة الأعداد وأحدث تاريخ بالحدّ المحفوظ...' -ForegroundColor Yellow
python (Join-Path $ProjectRoot 'scripts\verify_archmdoc_refresh.py') --database $Database --boundary $boundary
if ($LASTEXITCODE -ne 0) {
    Die 'فشلت بوّابة التحقّق — لا تُشغّل الدمج. راجع المخرجات أعلاه.'
}

Write-Host @"

تمّ. الخطوة التالية:
  1) افتح صفحة «دمج البيانات» ← الخطوة ٣ لترى عدد الجديد.
  2) شغّل الدمج من الخطوة ٤ (يعمل بالخلفية بمؤشّر تقدّم).
  3) بعد نجاحه التقط الحدّ الجديد:
       python manage.py capture_legacy_boundary --database $Database --force --note "بعد دمج تمّوز"
"@ -ForegroundColor Green
