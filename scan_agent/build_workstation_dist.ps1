# Assemble the LetterSys Workstation Distribution for clerk PCs:
#   <Out>\Setup.vbs                 Primary novice installer (native GUI launcher, no black console)
#   <Out>\Setup.cmd                 Fallback command-line installer
#   <Out>\config.json               Workstation configuration with pinned origin & cert hashes
#   <Out>\root_ca.cer               Public Root CA certificate (no private key)
#   <Out>\naps2_portable\           Full NAPS2 portable distribution (Console, GUI, worker, lib)
#   <Out>\python\                   Official Windows embeddable Python
#   <Out>\scan_agent\               Scan agent package and install_agent.bat
#   <Out>\THIRD_PARTY_LICENSES.txt  NAPS2 and Python licenses and source URLs
#   <Out>\SHA256SUMS.txt            Checksums for all files in the distribution
#
# ASCII-only on purpose: Windows PowerShell 5.1 reads BOM-less files as ANSI.
param(
    [Parameter(Mandatory = $true)][string]$EmbedZip,
    [Parameter(Mandatory = $true)][string]$Naps2Zip,
    [Parameter(Mandatory = $true)][string]$RootCertificate,
    [Parameter(Mandatory = $true)][string]$ServerOrigin,
    [Parameter(Mandatory = $true)][string]$Out,
    # Name of the SERVER computer; defaults to the build machine. Used only as a novice
    # mis-click guard so the client package refuses to install on the server itself.
    [string]$ServerMachineName = $env:COMPUTERNAME
)

$ErrorActionPreference = 'Stop'
if ([string]$ServerMachineName -cnotmatch '^[A-Za-z0-9][A-Za-z0-9_-]{0,62}$') { throw 'ServerMachineName must be a plain Windows computer name' }

if (Test-Path -LiteralPath $Out) {
    throw "Output folder already exists: $Out"
}

# 1. Validate inputs existence
if (-not (Test-Path -LiteralPath $EmbedZip -PathType Leaf)) {
    throw "EmbedZip file not found: $EmbedZip"
}
if (-not (Test-Path -LiteralPath $Naps2Zip -PathType Leaf)) {
    throw "Naps2Zip file not found: $Naps2Zip"
}
if (-not (Test-Path -LiteralPath $RootCertificate -PathType Leaf)) {
    throw "RootCertificate file not found: $RootCertificate"
}

# 2. Validate RootCertificate: public X.509 certificate only (strictly NO private key)
$cert = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2
try {
    $certType = [System.Security.Cryptography.X509Certificates.X509Certificate2]::GetCertContentType($RootCertificate)
    if ($certType -eq [System.Security.Cryptography.X509Certificates.X509ContentType]::Pkcs12) {
        throw "Security violation: RootCertificate contains a private key (PKCS12 / PFX archive). Only public certificate (.cer) is permitted."
    }
    $cert.Import($RootCertificate)
} catch {
    if ($_.Exception.Message -match "private key") {
        throw $_
    }
    throw "Failed to parse RootCertificate as an X.509 certificate: $_"
}
if ($cert.HasPrivateKey) {
    throw "Security violation: RootCertificate contains a private key. Only public certificate is permitted."
}
$certThumbprint = $cert.Thumbprint.ToUpperInvariant().Trim()
if ([string]::IsNullOrWhiteSpace($certThumbprint)) {
    throw "Invalid or empty thumbprint on RootCertificate."
}
$certSha256 = (Get-FileHash -LiteralPath $RootCertificate -Algorithm SHA256).Hash.ToUpperInvariant().Trim()

# 3. Validate ServerOrigin: strict absolute HTTPS origin
$originRaw = $ServerOrigin.Trim()
if ($originRaw.EndsWith('/')) {
    $originRaw = $originRaw.Substring(0, $originRaw.Length - 1)
}
if ($originRaw -notmatch '^https://[A-Za-z0-9._-]+(:[0-9]{1,5})?$') {
    throw "Invalid ServerOrigin: must be a strict HTTPS origin (e.g. https://lettersys.lan:8443 or https://lettersys.lan) without path, query, or credentials."
}
try {
    $uri = [System.Uri]$originRaw
} catch {
    throw "Invalid ServerOrigin URI format: $_"
}
if ($uri.Scheme -ne 'https') {
    throw "ServerOrigin must use https scheme."
}
if ($uri.UserInfo) {
    throw "ServerOrigin must not contain user credentials."
}
if ($uri.Query -or $uri.Fragment) {
    throw "ServerOrigin must not contain query parameters or fragments."
}
if ($uri.AbsolutePath -and $uri.AbsolutePath -ne '/') {
    throw "ServerOrigin must not contain a path."
}
$canonicalHost = $uri.Host.ToLowerInvariant()
$canonicalPort = $uri.Port
if ($uri.IsDefaultPort -or $canonicalPort -eq 443) {
    $canonicalOrigin = "https://$canonicalHost"
} else {
    $canonicalOrigin = "https://${canonicalHost}:${canonicalPort}"
}

# 4. Reuse build_dist.ps1 to build python runtime and scan_agent package
$buildDistScript = Join-Path $PSScriptRoot 'build_dist.ps1'
if (-not (Test-Path -LiteralPath $buildDistScript -PathType Leaf)) {
    throw "build_dist.ps1 not found in $PSScriptRoot"
}
& $buildDistScript -EmbedZip $EmbedZip -Out $Out
if ($LASTEXITCODE -ne 0) {
    throw "build_dist.ps1 failed with exit code $LASTEXITCODE"
}

# 5. Extract the FULL NAPS2 portable distribution (Console + GUI + worker + lib) flat into
#    <Out>\naps2_portable, i.e. the App\ folder of the official portable zip. config.py looks
#    for scan_agent\naps2_portable\NAPS2.Console.exe; NAPS2.Portable.exe (expects App\) is dropped.
$stagingNaps2 = Join-Path $Out '_staging_naps2'
Expand-Archive -LiteralPath $Naps2Zip -DestinationPath $stagingNaps2
$consoles = @(Get-ChildItem -LiteralPath $stagingNaps2 -Recurse -Filter 'NAPS2.Console.exe' -File)
if ($consoles.Count -ne 1) {
    Remove-Item -LiteralPath $stagingNaps2 -Recurse -Force -ErrorAction SilentlyContinue
    throw "Expected exactly one NAPS2.Console.exe inside Naps2Zip, found $($consoles.Count): $Naps2Zip"
}
$naps2Dir = $consoles[0].DirectoryName
foreach ($required in @('NAPS2.exe', 'NAPS2.Console.exe')) {
    if (-not (Test-Path -LiteralPath (Join-Path $naps2Dir $required) -PathType Leaf)) {
        Remove-Item -LiteralPath $stagingNaps2 -Recurse -Force -ErrorAction SilentlyContinue
        throw "Naps2Zip is not the full portable distribution: $required missing"
    }
}
if (-not (Test-Path -LiteralPath (Join-Path $naps2Dir 'lib') -PathType Container)) {
    Remove-Item -LiteralPath $stagingNaps2 -Recurse -Force -ErrorAction SilentlyContinue
    throw 'Naps2Zip is not the full portable distribution: lib\ folder missing'
}
$destNaps2 = Join-Path $Out 'naps2_portable'
robocopy $naps2Dir $destNaps2 /E /NFL /NDL /NJH /NJS /NP | Out-Null
$rc = $LASTEXITCODE
Remove-Item -LiteralPath $stagingNaps2 -Recurse -Force -ErrorAction SilentlyContinue
if ($rc -ge 8) { throw "robocopy failed when copying NAPS2 ($rc)" }
foreach ($required in @('NAPS2.exe', 'NAPS2.Console.exe')) {
    if (-not (Test-Path -LiteralPath (Join-Path $destNaps2 $required) -PathType Leaf)) {
        throw "$required is missing from $destNaps2"
    }
}

# 6. Public root certificate (re-checked above: no private key, not PFX).
$certFileName = 'root_ca.cer'
Copy-Item -LiteralPath $RootCertificate -Destination (Join-Path $Out $certFileName) -Force

# 7. config.json pinning the origin and the root certificate (ASCII, no BOM).
$configData = [ordered]@{
    schema_version       = '1.0'
    package_role         = 'client'
    server_machine_name  = $ServerMachineName.ToUpperInvariant()
    server_origin        = $canonicalOrigin
    device_setup_url     = "$canonicalOrigin/books/device-setup/"
    root_cert_file       = $certFileName
    root_cert_sha256     = $certSha256
    root_cert_thumbprint = $certThumbprint
    created_at           = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
}
[IO.File]::WriteAllText((Join-Path $Out 'config.json'), (ConvertTo-Json -InputObject $configData -Depth 4), (New-Object Text.ASCIIEncoding))

# 8. Installer front ends, UI text and licenses at the package root.
foreach ($name in @('Setup.vbs', 'Setup.cmd', 'setup_messages.txt', 'THIRD_PARTY_LICENSES.txt')) {
    $src = Join-Path $PSScriptRoot $name
    if (-not (Test-Path -LiteralPath $src -PathType Leaf)) { throw "$name not found in $PSScriptRoot" }
    Copy-Item -LiteralPath $src -Destination (Join-Path $Out $name) -Force
}

# 9. <Out>\scan_agent holds the runtime only: drop installer/test/dev artifacts that
#    build_dist.ps1 copied, plus bytecode written by its smoke import (install_agent.bat
#    does not copy __pycache__, so listing it would break the installed-files check).
$distScanAgent = Join-Path $Out 'scan_agent'
Get-ChildItem -LiteralPath $distScanAgent -Force | Where-Object {
    $_.Name -like 'Setup.*' -or $_.Name -like 'setup_messages*' -or $_.Name -eq 'THIRD_PARTY_LICENSES.txt' -or
    $_.Name -like 'tests_*.py' -or $_.Name -like 'build_*.ps1' -or $_.Name -like 'test_sandbox*' -or $_.Name -eq '__pycache__'
} | Remove-Item -Recurse -Force
Get-ChildItem -LiteralPath $Out -Recurse -Force -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force

# Every runtime module of the source tree (including workstation.py) must ship.
$runtimeModules = @(Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.py' -File | Where-Object { $_.Name -notlike 'tests_*' })
foreach ($m in $runtimeModules) {
    if (-not (Test-Path -LiteralPath (Join-Path $distScanAgent $m.Name) -PathType Leaf)) {
        throw "Runtime module missing from package: scan_agent\$($m.Name)"
    }
}
$moduleNames = ($runtimeModules | Where-Object { $_.Name -ne '__init__.py' } | ForEach-Object { 'scan_agent.' + $_.BaseName }) -join ', '
& (Join-Path $Out 'python\python.exe') -B -c ('import ' + $moduleNames)
if ($LASTEXITCODE -ne 0) { throw "The embedded interpreter could not import: $moduleNames" }

# No secrets may ever ride along (server .env, databases, private keys, PFX).
$forbidden = @(Get-ChildItem -LiteralPath $Out -Recurse -Force -File | Where-Object {
    $_.Name -like '.env*' -or $_.Extension -in @('.pfx', '.p12', '.key', '.pem', '.sqlite3', '.db', '.dump', '.bak')
})
if ($forbidden.Count -gt 0) { throw "Forbidden file in package: $($forbidden[0].FullName)" }

# 10. SHA256SUMS.txt last: every file, relative backslash paths; Setup.cmd verifies all of it.
$base = (Resolve-Path -LiteralPath $Out).Path.TrimEnd('\') + '\'
$lines = Get-ChildItem -LiteralPath $Out -Recurse -Force -File |
    Where-Object { $_.Name -ne 'SHA256SUMS.txt' } |
    Sort-Object FullName |
    ForEach-Object { '{0}  {1}' -f (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash, $_.FullName.Substring($base.Length) }
[IO.File]::WriteAllText((Join-Path $Out 'SHA256SUMS.txt'), (($lines -join "`r`n") + "`r`n"), (New-Object Text.ASCIIEncoding))

Write-Output "Built LetterSys Workstation Distribution: $Out"
Write-Output "Server origin: $canonicalOrigin"
Write-Output "Root SHA256: $certSha256"
Write-Output "Root thumbprint: $certThumbprint"