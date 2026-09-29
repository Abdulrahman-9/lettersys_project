# Assemble the scan-agent distribution for clerk PCs (no Python install needed there):
#   <Out>\python\         official Windows embeddable Python (stdlib only); its ._pth gains '..'
#   <Out>\scan_agent\     this package (no tests, no caches)
#   <Out>\SHA256SUMS.txt
# Then, once per clerk PC:   <Out>\scan_agent\install_agent.bat http://<server-ip>:8000
# ASCII-only on purpose: Windows PowerShell 5.1 reads BOM-less files as ANSI.
param(
    [Parameter(Mandatory = $true)][string]$EmbedZip,   # python-3.12.x-embed-amd64.zip (python.org)
    [Parameter(Mandatory = $true)][string]$Out
)
$ErrorActionPreference = 'Stop'
if (Test-Path -LiteralPath $Out) { throw "Output folder already exists: $Out" }

$py = Join-Path $Out 'python'
Expand-Archive -LiteralPath $EmbedZip -DestinationPath $py
if (-not (Test-Path -LiteralPath (Join-Path $py 'pythonw.exe'))) { throw 'pythonw.exe missing: not an embeddable zip?' }
$pth = Get-ChildItem -LiteralPath $py -Filter 'python*._pth' | Select-Object -First 1
if (-not $pth) { throw 'No ._pth file in the embeddable zip' }
# '..' (relative to the ._pth file) puts <Out> on sys.path, so `pythonw -m scan_agent` resolves.
@(Get-Content -LiteralPath $pth.FullName) + '..' | Set-Content -LiteralPath $pth.FullName -Encoding ascii

robocopy $PSScriptRoot (Join-Path $Out 'scan_agent') /E /XD __pycache__ naps2_portable /XF tests_agent.py *.pyc /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed ($LASTEXITCODE)" }

# Smoke test with the embedded interpreter itself: the agent must import with no site-packages.
& (Join-Path $py 'python.exe') -c 'import scan_agent.__main__, scan_agent.server; print("import-ok")'
if ($LASTEXITCODE -ne 0) { throw 'The embedded interpreter could not import scan_agent' }

$base = (Resolve-Path -LiteralPath $Out).Path.TrimEnd('\') + '\'
Get-ChildItem -LiteralPath $Out -Recurse -File |
    ForEach-Object { '{0}  {1}' -f (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash, $_.FullName.Substring($base.Length) } |
    Set-Content -LiteralPath (Join-Path $Out 'SHA256SUMS.txt') -Encoding ascii
Write-Output "Built: $Out"
