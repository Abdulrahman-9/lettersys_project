param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('LETTERSYS')]
    [string]$ConfirmProductionRelease
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$App = 'D:\lettersys\app'
$Python = 'D:\lettersys\venv\Scripts\python.exe'
$Candidate = Split-Path $PSScriptRoot -Parent
$ExpectedHead = 'b84e678cb4bb9b27988fdb70a3fdb1ebcc4958b0'
$PgRestore = 'C:\Program Files\PostgreSQL\16\bin\pg_restore.exe'
$BackupRoot = 'D:\migration\backups'
$Stopped = $false
$MigrationStarted = $false
$Updated = $false

function Invoke-Checked([string]$File, [string[]]$Arguments) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $File @Arguments
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
    if ($code -ne 0) { throw "$File failed with exit code $code." }
}

function Get-Revision([string]$Directory) {
    $value = & git -C $Directory rev-parse HEAD
    if ($LASTEXITCODE -ne 0) { throw "Cannot read revision in $Directory." }
    return "$value".Trim()
}

function Assert-Clean([string]$Directory) {
    $changes = & git -C $Directory status --porcelain
    if ($LASTEXITCODE -ne 0 -or $changes) { throw "Checkout is not clean: $Directory." }
}

try {
    $service = Get-Service -Name LetterSys
    if ($service.Status -ne 'Running') { throw 'LetterSys must be running before release.' }
    foreach ($path in @($Python, $PgRestore, $App, $BackupRoot)) {
        if (-not (Test-Path -LiteralPath $path)) { throw "Required path is missing: $path." }
    }
    $registry = Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Services\LetterSys\Parameters'
    if ($registry.Application -ne $Python -or $registry.AppDirectory -ne 'D:\lettersys' -or
        $registry.AppParameters -notmatch 'waitress --listen=0\.0\.0\.0:1312 .*wsgi_prod:application') {
        throw 'Production service configuration differs from the reviewed deployment.'
    }
    Assert-Clean $App
    if ((Get-Revision $Candidate) -eq $ExpectedHead) {
        $mergeHead = & git -C $Candidate rev-parse MERGE_HEAD
        if ($LASTEXITCODE -ne 0 -or "$mergeHead".Trim() -ne '556c906e333e011ec0566d27d4cb8ef492209c03') {
            throw 'Candidate is not the prepared outgoing-numbering merge.'
        }
        Invoke-Checked 'git' @('-C', $Candidate, 'diff', '--exit-code')
        Invoke-Checked 'git' @('-C', $Candidate, 'diff', '--cached', '--check')
        Invoke-Checked 'git' @('-C', $Candidate, 'commit',
            '-m', 'Merge external outgoing sequence with deployed reservation improvements',
            '-m', 'Preserve production b84e678 and join migration branches with guarded deployment.',
            '-m', 'Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>')
    }
    Assert-Clean $Candidate
    if ((Get-Revision $App) -ne $ExpectedHead) {
        throw 'Production changed since preparation. Reconcile the candidate before release.'
    }
    $target = Get-Revision $Candidate
    Invoke-Checked 'git' @('-C', $Candidate, 'merge-base', '--is-ancestor', $ExpectedHead, $target)
    Invoke-Checked 'git' @('-C', $App, 'fetch', $Candidate, $target)
    if ((& git -C $App rev-parse FETCH_HEAD).Trim() -ne $target) {
        throw 'Imported release revision does not match the candidate.'
    }

    Push-Location $Candidate
    try {
        $env:PYTHONIOENCODING = 'utf-8'
        Invoke-Checked $Python @('manage.py', 'test',
            'core.tests_numbering', 'core.tests_numbering_per_dept',
            'core.tests_perpetual_numbering', 'core.tests_reservation_identity',
            'core.tests_reservation_admin', 'core.tests_reservation_recycle',
            'core.tests_reservation_ttl', 'core.tests_secrecy', 'core.tests_book_scope',
            'core.tests_outgoing_upgrade',
            '--settings=lettersys.settings_test', '--noinput')
        Invoke-Checked $Python @('manage.py', 'makemigrations', '--check', '--dry-run',
            '--settings=lettersys.settings_test')
        Invoke-Checked 'node' @('--test', 'scripts\tests_reservation_ui.cjs')
        Invoke-Checked 'node' @('--check', 'static\extraction_smart.js')
        $dataAudit = @'
import os
os.chdir(r'D:\lettersys\app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lettersys.settings')
import django
django.setup()
from django.db.models import Count, Q
from core.models import Book
summary = Book.all_objects.filter(kind='outgoing_external').aggregate(
        total=Count('pk'),
        imported=Count('pk', filter=~Q(source_ref='')),
        app_created=Count('pk', filter=Q(source_ref='')),
        numberless=Count('pk', filter=Q(our_number='')),
        training=Count('pk', filter=Q(is_training=True)),
        deleted=Count('pk', filter=Q(is_deleted=True)),
)
print('Outgoing-external data audit (read-only):', summary)
'@
        Invoke-Checked $Python @('-c', $dataAudit) 'audit outgoing-external records (read-only)'
        } finally {
        Pop-Location
    }

    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $directory = Join-Path $BackupRoot "lettersys_outgoing_$stamp"
    New-Item -ItemType Directory -Path $directory | Out-Null
    $dump = Join-Path $directory 'database.dump'
    $metadata = Join-Path $directory 'release.json'
    @{
        previous = $ExpectedHead
        target = $target
        created = (Get-Date -Format o)
        migration = '0086_merge_outgoing_reservation'
    } | ConvertTo-Json | Set-Content -LiteralPath $metadata -Encoding UTF8

    # Test stop/start authorization before changing code or data.
    Stop-Service -Name LetterSys
    $Stopped = $true
    $service.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(45))
    if (Get-NetTCPConnection -State Listen -LocalPort 1312 -ErrorAction SilentlyContinue) {
        throw 'Port 1312 is still bound; refusing deployment.'
    }
    Push-Location $App
    try {
        $backupCode = @'
import json, os, subprocess, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lettersys.settings')
import django
django.setup()
from django.conf import settings
from django.db import connection
from django.db.migrations.loader import MigrationLoader
with connection.cursor() as cursor:
    cursor.execute('SELECT current_database(), current_user')
    identity = cursor.fetchone()
if identity != ('lettersys', 'lettersys_user'):
    raise RuntimeError('Unexpected production database identity')
loader = MigrationLoader(connection)
if ('core', '0085_reservation_assignment_time') not in loader.applied_migrations:
    raise RuntimeError('Expected reservation migration is not applied')
if ('core', '0085_outgoing_external_sequence') in loader.applied_migrations:
    raise RuntimeError('Outgoing migration is already applied; review before retry')
database = settings.DATABASES['default']
environment = os.environ.copy()
environment['PGPASSWORD'] = database['PASSWORD']
command = [
    r'C:\Program Files\PostgreSQL\16\bin\pg_dump.exe',
    '--no-password', '--host', database.get('HOST') or 'localhost',
    '--port', str(database.get('PORT') or 5432),
    '--username', database['USER'], '--dbname', database['NAME'],
    '--format=custom', '--no-owner', '--no-acl', '--file', sys.argv[1],
]
subprocess.run(command, env=environment, check=True, timeout=600)
print('Production database backup completed.')
'@
        Invoke-Checked $Python @('-c', $backupCode, $dump)
        if ((Get-Item -LiteralPath $dump).Length -lt 100000) {
            throw 'Backup is implausibly small.'
        }
        $hash = (Get-FileHash -LiteralPath $dump -Algorithm SHA256).Hash
        Set-Content -LiteralPath "$dump.sha256" -Value $hash -Encoding ASCII
        Invoke-Checked $PgRestore @('--list', $dump)
        Invoke-Checked $PgRestore @('--file=NUL', $dump)
        if ((Get-FileHash -LiteralPath $dump -Algorithm SHA256).Hash -ne $hash) {
            throw 'Backup changed during validation.'
        }
        Assert-Clean $App
        if ((Get-Revision $App) -ne $ExpectedHead) { throw 'Production changed during preflight.' }
        $Updated = $true
        Invoke-Checked 'git' @('-C', $App, 'merge', '--ff-only', $target)
        Invoke-Checked $Python @('manage.py', 'check', '--deploy')
        Invoke-Checked $Python @('manage.py', 'migrate', '--plan')
        $MigrationStarted = $true
        Invoke-Checked $Python @('manage.py', 'migrate', '--noinput')
        Invoke-Checked $Python @('manage.py', 'collectstatic', '--noinput')
        Invoke-Checked $Python @('manage.py', 'migrate', '--check')
    } finally {
        Pop-Location
    }
    Start-Service -Name LetterSys
    $service.WaitForStatus('Running', [TimeSpan]::FromSeconds(60))
    $Stopped = $false
    $healthy = $false
    $deadline = (Get-Date).AddSeconds(60)
    do {
        $status = & curl.exe -s -o NUL --max-time 10 -w '%{http_code}' 'http://127.0.0.1:1312/login/'
        if ($LASTEXITCODE -eq 0 -and $status -eq '200') { $healthy = $true; break }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    if (-not $healthy) { throw 'Service started but HTTP health check failed.' }
    Write-Host "RELEASE COMPLETE: $target"
    Write-Host "Verified database backup: $dump"
    Write-Host 'Now run authenticated browser checks for reservation, save, and reopen.'
} catch {
    Write-Error -Message $_ -ErrorAction Continue
    if ($Stopped -and -not $Updated -and -not $MigrationStarted) {
        Start-Service -Name LetterSys
        Write-Warning 'No code or migration change occurred. Original service restarted.'
    } elseif ($Stopped) {
        Write-Warning 'Service remains stopped. Do not restore old code over a changed database.'
        Write-Warning "Inspect backup and release metadata under $BackupRoot before recovery."
    }
    throw
}
