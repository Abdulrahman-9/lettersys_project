<#
Install the LetterSys desktop control panel on the server. Run elevated (the deploy script does).

Copies the panel into Program Files: only administrators can change files there, and that matters because the
desktop shortcut runs the panel elevated (D:\lettersys\tools is writable by every signed-in user - Fable 11-19).
Writes panel.config.json and puts a shortcut on the desktop that asks UAC once when it is opened.
ASCII on purpose; the Arabic shortcut name comes from strings.ar.json.
#>
param(
    [string]$Source = $PSScriptRoot,
    [string]$Target = (Join-Path $env:ProgramFiles 'LetterSys\Panel'),
    [string]$Service = 'LetterSys',
    [int]$Port = 1312,
    [string]$HostHeader = 'follow2',
    [string]$OfficialUrl = 'http://follow2:1312',
    [string]$LogDir = 'D:\lettersys\logs',
    [string]$GuidePath = 'D:\lettersys\app\var\guide\index.html',
    [string]$AppDir = 'D:\lettersys\app',
    # The public desktop: the deploy script runs elevated as another account, whose own desktop nobody sees.
    [string]$Desktop = [Environment]::GetFolderPath('CommonDesktopDirectory')
)
$ErrorActionPreference = 'Stop'

$identity = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Open PowerShell with Run as administrator.'
}

New-Item -ItemType Directory -Force -Path $Target | Out-Null
foreach ($name in 'LetterSys-Panel.ps1', 'strings.ar.json') {
    Copy-Item -LiteralPath (Join-Path $Source $name) -Destination (Join-Path $Target $name) -Force
}
$config = [ordered]@{
    service = $Service; port = $Port; hostHeader = $HostHeader; officialUrl = $OfficialUrl
    logDir = $LogDir; guidePath = $GuidePath; appDir = $AppDir
}
$utf8 = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText((Join-Path $Target 'panel.config.json'), ($config | ConvertTo-Json), $utf8)

$strings = [IO.File]::ReadAllText((Join-Path $Target 'strings.ar.json'), [Text.Encoding]::UTF8) | ConvertFrom-Json
$lnk = Join-Path $Desktop ($strings.shortcut_name + '.lnk')
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($lnk)
$shortcut.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$shortcut.Arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + (Join-Path $Target 'LetterSys-Panel.ps1') + '"'
$shortcut.WorkingDirectory = $Target
$shortcut.IconLocation = (Join-Path $env:SystemRoot 'System32\shell32.dll') + ',15'
$shortcut.Description = $strings.title
$shortcut.Save()
# "Run as administrator": bit 0x20 of byte 0x15 in the .lnk header.
$bytes = [IO.File]::ReadAllBytes($lnk)
$bytes[0x15] = $bytes[0x15] -bor 0x20
[IO.File]::WriteAllBytes($lnk, $bytes)

Write-Host "[panel] Installed in $Target"
Write-Host "[panel] Desktop shortcut: $lnk"
