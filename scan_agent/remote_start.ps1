$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)

$env:LETTERSYS_AGENT_HOST = '0.0.0.0'
$env:LETTERSYS_AGENT_PORT = '17865'
$env:LETTERSYS_AGENT_ALLOWED_ORIGINS = 'http://172.16.2.16:8000'

if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 -m scan_agent
    exit $LASTEXITCODE
}

if (Get-Command python -ErrorAction SilentlyContinue) {
    & python -m scan_agent
    exit $LASTEXITCODE
}

Write-Host "Python was not found on this machine. Install Python 3.11/3.12 first, then run this script again."
exit 1
