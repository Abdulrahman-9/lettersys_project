$ErrorActionPreference = 'Stop'
$ServiceName = 'LetterSys'
$ExpectedAppDirectory = 'D:\lettersys'
$ExpectedPort = 1312

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
$isAdministrator = $principal.IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)

if (-not $isAdministrator) {
    $arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    Start-Process -FilePath (Join-Path $PSHOME 'powershell.exe') `
        -Verb RunAs `
        -ArgumentList $arguments
    exit 0
}

$service = Get-Service -Name $ServiceName -ErrorAction Stop
$parametersPath = "HKLM:\SYSTEM\CurrentControlSet\Services\$ServiceName\Parameters"
if (-not (Test-Path -LiteralPath $parametersPath)) {
    throw "NSSM configuration for service '$ServiceName' was not found."
}

$parameters = Get-ItemProperty -LiteralPath $parametersPath -ErrorAction Stop
if ($parameters.AppDirectory -ne $ExpectedAppDirectory -or
    $parameters.AppParameters -notmatch 'waitress\s+--listen=0\.0\.0\.0:1312\b' -or
    $parameters.AppParameters -notmatch 'wsgi_prod:application') {
    throw "Service '$ServiceName' does not match the documented LetterSys deployment at $ExpectedAppDirectory on port $ExpectedPort. Nothing was started."
}

if ($service.Status -ne 'Running') {
    Start-Service -Name $ServiceName -ErrorAction Stop
    $service = Get-Service -Name $ServiceName
    $service.WaitForStatus(
        [System.ServiceProcess.ServiceControllerStatus]::Running,
        [TimeSpan]::FromSeconds(60)
    )
}

$deadline = (Get-Date).AddSeconds(60)
do {
    $listener = Get-NetTCPConnection -State Listen -LocalPort $ExpectedPort `
        -ErrorAction SilentlyContinue |
        Where-Object { $_.LocalAddress -in @('0.0.0.0', '172.16.2.16', '::') } |
        Select-Object -First 1
    if ($listener) {
        Write-Host "LetterSys service is running on port $ExpectedPort."
        Write-Host 'Open the existing LetterSys app icon to use the application.'
        exit 0
    }
    Start-Sleep -Seconds 1
} while ((Get-Date) -lt $deadline)

throw "The LetterSys service is running, but no listener appeared on port $ExpectedPort within 60 seconds. Check the Windows service and its logs."
