[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [uri]$ServerUrl,
    [string]$DesktopPath = [Environment]::GetFolderPath('Desktop'),
    [string]$IconDirectory = (Join-Path $env:LOCALAPPDATA 'LetterSys')
)

$ErrorActionPreference = 'Stop'

if (-not $ServerUrl.IsAbsoluteUri -or $ServerUrl.Scheme -notin @('http', 'https')) {
    throw 'ServerUrl must be an absolute HTTP or HTTPS URL.'
}
if ($ServerUrl.UserInfo -or $ServerUrl.AbsoluteUri.Contains('"')) {
    throw 'ServerUrl must not contain credentials or double quotes.'
}
if (-not $DesktopPath -or -not (Test-Path -LiteralPath $DesktopPath -PathType Container)) {
    throw 'Desktop folder not found. Supply -DesktopPath with the actual desktop folder.'
}

$browserPaths = @(
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
    "$env:LOCALAPPDATA\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
)
$browser = $browserPaths | Where-Object {
    Test-Path -LiteralPath $_ -PathType Leaf
} | Select-Object -First 1
if (-not $browser) {
    throw 'Microsoft Edge or Google Chrome is required to open LetterSys in an app window.'
}

$sourceIcon = Join-Path (Split-Path -Parent $PSScriptRoot) 'static\favicon.ico'
if (-not (Test-Path -LiteralPath $sourceIcon -PathType Leaf)) {
    throw "Application icon not found: $sourceIcon"
}

$null = New-Item -ItemType Directory -Path $IconDirectory -Force
$iconPath = Join-Path $IconDirectory 'favicon.ico'
Copy-Item -LiteralPath $sourceIcon -Destination $iconPath -Force

$shortcutPath = Join-Path $DesktopPath 'LetterSys LAN.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $browser
$shortcut.Arguments = '--app="' + $ServerUrl.AbsoluteUri + '"'
$shortcut.WorkingDirectory = Split-Path -Parent $browser
$shortcut.IconLocation = $iconPath + ',0'
$shortcut.Description = 'LetterSys Smart Archive - ' + $ServerUrl.AbsoluteUri
$shortcut.Save()

$saved = $shell.CreateShortcut($shortcutPath)
if (-not (Test-Path -LiteralPath $shortcutPath -PathType Leaf) -or
    $saved.TargetPath -ne $browser -or $saved.Arguments -ne $shortcut.Arguments -or
    $saved.IconLocation -ne $shortcut.IconLocation) {
    throw "Shortcut verification failed: $shortcutPath"
}
Write-Output "Created and verified: $shortcutPath"
Write-Output "Server: $($ServerUrl.AbsoluteUri)"
Write-Output 'This shortcut opens the server; it does not start it or install a PWA.'
