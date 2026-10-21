param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('LETTERSYS')]
    [string]$ConfirmProductionRelease,
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{40}$')]
    [string]$ReleaseCommit
)

# RELEASE-SCRIPT-VERSION=20261021-2 (UI-only: no migrations)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$App = 'D:\lettersys\app'
$Root = 'D:\lettersys'
$Vpy = Join-Path $Root 'venv\Scripts\python.exe'
$ServiceName = 'LetterSys'
$Port = 1312
$ExpectedOldHead = '22a81bdfbbbb80cc4e09b18a3a8daa43016a8cb3'
$RequiredReleaseBase = '22a81bdfbbbb80cc4e09b18a3a8daa43016a8cb3'
$MigrationName = $null
$RollbackMigration = $null
$LogPath = Join-Path 'D:\migration\logs' ("release_live_{0}.log" -f (Get-Date -Format 'yyyyMMdd_HHmmss'))
$script:CodeUpdated = $false
$script:MigrationApplied = $false
$script:ServiceStopped = $false
$script:OldHead = $null

function Write-ReleaseLog([string]$Message) {
    $line = '{0} {1}' -f (Get-Date -Format s), $Message
    Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8
    Write-Host $line
}

# Windows PowerShell 5.1 turns native stderr (git progress, Python warnings)
# into terminating errors under 'Stop'; success is judged by exit code only.
function Invoke-Native([string]$File, [string[]]$Arguments) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = @(& $File @Arguments 2>&1 | ForEach-Object { "$_" })
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
    $global:LASTEXITCODE = $code
    return ,$output
}

function Invoke-Checked([string]$File, [string[]]$Arguments, [string]$Step) {
    Write-ReleaseLog "START $Step"
    $output = Invoke-Native $File $Arguments
    $code = $LASTEXITCODE
    foreach ($text in $output) {
        Add-Content -LiteralPath $LogPath -Value $text -Encoding UTF8
        Write-Host $text
    }
    $global:LASTEXITCODE = $code
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE"
    }
    Write-ReleaseLog "OK $Step"
}

function Get-DbFacts {
    $probe = "import os; os.chdir(r'D:\lettersys\app'); os.environ.setdefault('DJANGO_SETTINGS_MODULE','lettersys.settings'); import django; django.setup(); from django.db import connection; connection.ensure_connection(); c=connection.cursor(); c.execute('SELECT current_database(), current_user, inet_server_addr(), inet_server_port()'); print('|'.join(str(v) for v in c.fetchone()))"
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $result = & $Vpy -c $probe 2>$null
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
    if ($code -ne 0) { throw 'Could not verify the production database connection.' }
    return "$(@($result)[-1])".Trim()
}

function Test-ServiceHealth {
    $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if (-not $service -or $service.Status -ne 'Running') { return $false }
    $login = (& curl.exe -s -o NUL --max-time 15 -w '%{http_code}' "http://127.0.0.1:$Port/login/").Trim()
    $static = (& curl.exe -s -o NUL --max-time 15 -w '%{http_code}' "http://127.0.0.1:$Port/static/app.js").Trim()
    $devLogin = (& curl.exe -s -o NUL --max-time 15 -w '%{http_code}' "http://127.0.0.1:$Port/dev-login/").Trim()
    $evilHost = (& curl.exe -s -o NUL --max-time 15 -w '%{http_code}' -H 'Host: evil.example' "http://127.0.0.1:$Port/login/").Trim()
    $media = (& curl.exe -s -o NUL --max-time 15 -w '%{http_code} %{redirect_url}' "http://127.0.0.1:$Port/media/books/x.pdf").Trim()
    $sweeper = Select-String -Path "$Root\logs\waitress.err.log" -Pattern '\[sweeper\] started' -ErrorAction SilentlyContinue
    return ($login -eq '200' -and $static -eq '200' -and $devLogin -eq '404' -and
        $evilHost -eq '400' -and $media -like '302 *login*' -and [bool]$sweeper)
}

# The service reports Stopped before its Waitress child exits; give the
# listener up to 30 seconds to close instead of racing it.
function Wait-PortReleased([int]$Seconds = 30) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    do {
        if (-not (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)) {
            return $true
        }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)
    return $false
}

function Restore-OldRelease {
    Write-ReleaseLog "ROLLBACK requested; code update=$script:CodeUpdated migration recorded=$script:MigrationApplied"
    $service = Get-Service -Name $ServiceName
    if ($service.Status -ne 'Stopped') {
        Stop-Service -Name $ServiceName
        $service = Get-Service -Name $ServiceName
        $service.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(45))
    }
    $script:ServiceStopped = $true
    if (-not (Wait-PortReleased)) {
        throw 'Production port 1312 remains bound during rollback.'
    }
    if ($script:MigrationApplied) {
        Invoke-Checked $Vpy @(
            (Join-Path $App 'manage.py'), 'migrate', 'core', $RollbackMigration, '--noinput'
        ) 'reverse administration migration before restoring old code'
    }
    if ($script:CodeUpdated) {
        Invoke-Checked 'git.exe' @('-C', $App, 'switch', '-C', 'main', $script:OldHead) 'restore previous production revision'
        Invoke-Checked $Vpy @((Join-Path $App 'manage.py'), 'collectstatic', '--noinput') 'restore previous static manifest'
    }
    Start-Service -Name $ServiceName
    (Get-Service -Name $ServiceName).WaitForStatus('Running', [TimeSpan]::FromSeconds(60))
    $script:ServiceStopped = $false
    $deadline = (Get-Date).AddSeconds(60)
    do {
        if (Test-ServiceHealth) {
            Write-ReleaseLog 'ROLLBACK HEALTHY; previous application is serving'
            return
        }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    throw "Rollback service health failed. Review $LogPath before any further action."
}

try {
    if ($ConfirmProductionRelease -ne 'LETTERSYS') {
        throw 'Confirmation must be LETTERSYS.'
    }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Open PowerShell with Run as administrator.'
    }
    $freeMB = [int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1024)
    if ($freeMB -lt 600) {
        throw "Only $freeMB MB RAM is free; at least 600 MB is required. Close applications and retry."
    }
    if ((Get-Location).Path -ne $App) { Set-Location $App }
    if (-not (Test-Path $Vpy)) { throw 'Production virtual environment is missing.' }
    $registry = Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Services\LetterSys\Parameters'
    if ($registry.Application -ne (Join-Path $Root 'venv\Scripts\python.exe') -or
        $registry.AppDirectory -ne $Root -or
        $registry.AppParameters -notmatch 'waitress --listen=0\.0\.0\.0:1312 .*wsgi_prod:application') {
        throw 'LetterSys service configuration differs from the verified Waitress deployment.'
    }

    $dbFacts = Get-DbFacts
    if ($dbFacts -notmatch '^lettersys\|lettersys_user\|(::1|127\.0\.0\.1)\|5432$') {
        throw "Unexpected production DB identity: $dbFacts"
    }
    $service = Get-Service -Name $ServiceName
    if ($service.Status -ne 'Running') { throw 'Production LetterSys service is not running.' }
    if (-not (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)) {
        throw 'Production listener on port 1312 is missing.'
    }
    if (git status --porcelain=v1) { throw 'Production checkout is not clean.' }
    $script:OldHead = (git rev-parse HEAD).Trim()
    if ($script:OldHead -ne $ExpectedOldHead) { throw "Unexpected production revision $script:OldHead." }
    $target = $ReleaseCommit.ToLowerInvariant()
    Invoke-Checked 'git.exe' @(
        '-C', $App, 'fetch', 'origin', 'release/dept-admin-dashboard'
    ) 'fetch reviewed release branch'
    $fetchedCommit = (& git.exe -C $App rev-parse FETCH_HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $fetchedCommit -ne $target) {
        throw 'Fetched release branch does not match the pinned ReleaseCommit.'
    }
    git cat-file -e "$target^{commit}"
    if ($LASTEXITCODE -ne 0) { throw 'Pinned release commit is not available in the local repository.' }
    git merge-base --is-ancestor $RequiredReleaseBase $target
    if ($LASTEXITCODE -ne 0) {
        throw 'Release target does not contain the reviewed code commit.'
    }
    git merge-base --is-ancestor $script:OldHead $target
    if ($LASTEXITCODE -ne 0) {
        throw 'Release target is not a fast-forward from the installed revision.'
    }
    $changedFiles = @(git diff --name-only $script:OldHead $target)
    $allowed = @(
        'core/views/admin_panel.py', 'core/views/dashboard.py', 'core/tests_dashboard_roles.py',
        'static/css/admin_command.css', 'static/css/dashboard_command.css',
        'static/js/admin_command.js', 'static/js/dashboard_fx.js', 'static/service-worker.js',
        'templates/base.html', 'templates/core/admin_panel.html', 'templates/core/dashboard.html',
        'templates/core/_admin_org_node.html', 'templates/core/_admin_overview.html',
        'templates/core/_dashboard_insights.html',
        'scripts/release_live_windows.ps1'
    )
    $unexpected = @($changedFiles | Where-Object { $_ -notin $allowed })
    if ($unexpected.Count) { throw "Unexpected release files: $($unexpected -join ', ')" }
    if (@($changedFiles | Where-Object { $_ -like 'core/migrations/*' }).Count) {
        throw 'This UI-only release must not contain migrations.'
    }
    Write-ReleaseLog "PRECHECK PASS user=$($identity.Name) freeMB=$freeMB db=$dbFacts old=$script:OldHead target=$target"
    Write-ReleaseLog "FILES $($changedFiles -join ',')"

    $script:ServiceStopped = $true
    Stop-Service -Name $ServiceName
    $service = Get-Service -Name $ServiceName
    $service.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(45))
    if (-not (Wait-PortReleased)) {
        throw 'Production port 1312 remains bound after service stop.'
    }
    Write-ReleaseLog 'SERVICE STOPPED; production writes through web service are paused'

    $timestamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $backupDirectory = "D:\migration\backups\lettersys_release_$timestamp"
    New-Item -ItemType Directory -Path $backupDirectory | Out-Null
    & icacls.exe $backupDirectory /inheritance:r /grant:r "$($env:USERDOMAIN)\$($env:USERNAME):(OI)(CI)F" 'SYSTEM:(OI)(CI)F' 'BUILTIN\Administrators:(OI)(CI)F' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not restrict fresh backup directory permissions.' }
    $freshBackup = Join-Path $backupDirectory "lettersys_pre_release_$timestamp.dump"
    $backupProbe = @"
import os, subprocess
os.chdir(r'D:\lettersys\app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lettersys.settings')
import django
django.setup()
from django.conf import settings
environment = os.environ.copy()
environment['PGPASSWORD'] = settings.DATABASES['default']['PASSWORD']
command = [r'C:\Program Files\PostgreSQL\16\bin\pg_dump.exe', '--no-password', '--host', 'localhost', '--port', '5432', '--username', 'lettersys_user', '--dbname', 'lettersys', '--format=custom', '--no-owner', '--no-acl', '--file', r'$freshBackup']
raise SystemExit(subprocess.run(command, env=environment, check=False).returncode)
"@
    Invoke-Checked $Vpy @('-c', $backupProbe) 'create fresh production database backup'
    if ((Get-Item $freshBackup).Length -lt 100000) { throw 'Fresh production backup is implausibly small.' }
    $freshHash = (Get-FileHash $freshBackup -Algorithm SHA256).Hash.ToLowerInvariant()
    Set-Content "$freshBackup.sha256" "$freshHash  $(Split-Path $freshBackup -Leaf)" -Encoding ascii
    & icacls.exe $freshBackup /inheritance:r /grant:r "$($env:USERDOMAIN)\$($env:USERNAME):F" 'SYSTEM:F' 'BUILTIN\Administrators:F' | Out-Null
    & icacls.exe "$freshBackup.sha256" /inheritance:r /grant:r "$($env:USERDOMAIN)\$($env:USERNAME):F" 'SYSTEM:F' 'BUILTIN\Administrators:F' | Out-Null
    if ($LASTEXITCODE -ne 0 -or (Get-FileHash $freshBackup -Algorithm SHA256).Hash.ToLowerInvariant() -ne $freshHash) {
        throw 'Fresh backup permissions or SHA-256 verification failed.'
    }
    $freshToc = & 'C:\Program Files\PostgreSQL\16\bin\pg_restore.exe' --list $freshBackup
    if ($LASTEXITCODE -ne 0 -or @($freshToc).Count -lt 100) { throw 'Fresh backup archive validation failed.' }
    Write-ReleaseLog "FRESH_BACKUP path=$freshBackup bytes=$((Get-Item $freshBackup).Length) sha256=$freshHash tocLines=$(@($freshToc).Count)"

    Invoke-Checked 'git.exe' @('-C', $App, 'merge', '--ff-only', $target) 'fast-forward production checkout'
    $script:CodeUpdated = $true
    $plan = Invoke-Native $Vpy @((Join-Path $App 'manage.py'), 'showmigrations', '--plan')
    if ($LASTEXITCODE -ne 0) { throw 'Could not inspect post-update migration plan.' }
    $pending = @($plan | Where-Object { "$_" -match '^\s*\[\s\]' })
    if ($pending.Count -ne 0) {
        throw "UI-only release expects no pending migrations; actual pending plan: $($pending -join ' | ')"
    }
    Invoke-Checked $Vpy @((Join-Path $App 'manage.py'), 'check') 'Django system check'
    Invoke-Checked $Vpy @((Join-Path $App 'manage.py'), 'collectstatic', '--noinput') 'collect production static files'

    Start-Service -Name $ServiceName
    (Get-Service -Name $ServiceName).WaitForStatus('Running', [TimeSpan]::FromSeconds(60))
    $script:ServiceStopped = $false
    $deadline = (Get-Date).AddSeconds(90)
    do {
        if (Test-ServiceHealth) {
            Write-ReleaseLog "RELEASE SUCCESS revision=$(git rev-parse --short HEAD) db=$dbFacts migrations=none freshBackup=$freshBackup"
            exit 0
        }
        Start-Sleep -Seconds 3
    } while ((Get-Date) -lt $deadline)
    throw 'Production HTTP health checks did not pass within 90 seconds.'
}
catch {
    Write-ReleaseLog "RELEASE FAILED: $($_.Exception.Message)"
    if ($script:ServiceStopped -or $script:CodeUpdated) {
        try {
            Restore-OldRelease
            Write-ReleaseLog "ROLLBACK COMPLETE; production service restored to $script:OldHead; migration-recorded=$script:MigrationApplied"
        } catch {
            Write-ReleaseLog "ROLLBACK FAILED: $($_.Exception.Message)"
            Write-Error "Service recovery needs administrator attention. Log: $LogPath"
            exit 2
        }
    }
    Write-Error "Release aborted. Review $LogPath."
    exit 1
}
