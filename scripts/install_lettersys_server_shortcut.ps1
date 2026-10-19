$ErrorActionPreference = 'Stop'

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Launcher = Join-Path $PSScriptRoot 'start_lettersys_service.ps1'
$Icon = Join-Path $ProjectRoot 'static\favicon.ico'
$PowerShell = Join-Path $PSHOME 'powershell.exe'

foreach ($path in @($Launcher, $Icon, $PowerShell)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required file not found: $path"
    }
}

$shell = New-Object -ComObject WScript.Shell
$desktop = $shell.SpecialFolders('Desktop')
if (-not $desktop -or -not (Test-Path -LiteralPath $desktop -PathType Container)) {
    throw 'Windows Desktop folder was not found. Run this installer on the LetterSys server computer.'
}

$shortcutPath = Join-Path $desktop 'Start LetterSys Server.lnk'
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $PowerShell
$shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$Launcher`""
$shortcut.WorkingDirectory = $ProjectRoot
$shortcut.IconLocation = "$Icon,0"
$shortcut.Description = 'Start the existing LetterSys Windows service on port 1312'
$shortcut.Save()

$saved = $shell.CreateShortcut($shortcutPath)
if (-not (Test-Path -LiteralPath $shortcutPath -PathType Leaf) -or
    $saved.TargetPath -ne $PowerShell -or
    $saved.Arguments -ne $shortcut.Arguments) {
    throw "Shortcut verification failed: $shortcutPath"
}

Write-Output "Created and verified: $shortcutPath"
Write-Output 'This shortcut starts the existing LetterSys Windows service; it does not change the PostgreSQL database.'
