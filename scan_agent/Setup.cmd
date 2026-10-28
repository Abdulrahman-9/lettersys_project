@echo off
REM ============================================================================
REM  LetterSys Workstation Setup (per-user, non-elevated).
REM  ASCII + CRLF on purpose: cmd.exe mis-parses BOMs and LF-only labels.
REM  Primary novice entry point is Setup.vbs (hidden window + GUI dialogs); this
REM  file is the worker and the command-line fallback. Every step checks its exit
REM  code; the outcome is written to %LOCALAPPDATA%\LetterSys\install_result.json
REM  which is the ONLY thing Setup.vbs reads to decide what to tell the user.
REM
REM  Exit codes: 0 ready (agent healthy, scanner listed) | 1 cancelled |
REM  2 config invalid | 3 certificate pin invalid | 4 agent install failed |
REM  5 NAPS2 copy failed | 6 elevated | 7 package integrity failed |
REM  8 package component missing | 9 certificate store import failed |
REM  10 installed files verification failed | 11 this PC is the server (refused) |
REM  12 require_pairing flag could not be written |
REM  30 agent health failed |
REM  31 no scanner listed | 32 scanner list unknown/error
REM ============================================================================
setlocal EnableExtensions DisableDelayedExpansion

REM -- 0) Per-user guard: the agent, its shortcut and the root trust are per-user.
whoami /groups | findstr /c:"S-1-16-12288" /c:"S-1-16-16384" >nul
if not errorlevel 1 if not defined LETTERSYS_INSTALL_ALLOW_ELEVATED goto elevated

if not defined LOCALAPPDATA goto no_localappdata
set "PKG_DIR=%~dp0"
set "CONFIG_FILE=%~dp0config.json"
set "LS_DATA_DIR=%LOCALAPPDATA%\LetterSys"
set "LS_AGENT_DIR=%LOCALAPPDATA%\LetterSys\agent"
set "LS_NAPS2_DEST=%LOCALAPPDATA%\LetterSys\agent\scan_agent\naps2_portable"
set "LS_RESULT=%LOCALAPPDATA%\LetterSys\install_result.json"
set "LS_STATUS=%LOCALAPPDATA%\LetterSys\install_status.txt"
set "LS_DEVSTATE=%LOCALAPPDATA%\LetterSys\install_devices.json"
set "LS_DETAIL=%LOCALAPPDATA%\LetterSys\install_detail.txt"
set "LS_PORT=17865"
if defined LETTERSYS_AGENT_PORT set "LS_PORT=%LETTERSYS_AGENT_PORT%"
set "LS_EXIT=0"
set "LS_STAGE=validate"
set "LS_MSG="
set "LS_AGENT_INSTALLED=0"
set "LS_AGENT_STATUS=not_started"
set "LS_SERVER_STATUS=not_checked"
set "LS_DEVICE_STATUS=not_checked"
set "LS_BROWSER=0"
set "CFG_ORIGIN="
set "CFG_SETUP_URL="
set "CFG_CERT_FILE="
set "CFG_THUMB="

if not exist "%LS_DATA_DIR%" mkdir "%LS_DATA_DIR%"
if not exist "%LS_DATA_DIR%" goto no_localappdata
del /f /q "%LS_RESULT%" "%LS_DEVSTATE%" "%LS_DETAIL%" 2>nul
call :stage validate

REM -- 1) Package integrity BEFORE any effect: every file listed, hashed, safe paths.
if not exist "%PKG_DIR%SHA256SUMS.txt" goto missing_component
if not exist "%PKG_DIR%scan_agent\install_agent.bat" goto missing_component
if not exist "%PKG_DIR%python\pythonw.exe" goto missing_component
if not exist "%PKG_DIR%naps2_portable\NAPS2.Console.exe" goto missing_component
if not exist "%PKG_DIR%naps2_portable\NAPS2.exe" goto missing_component
if not exist "%PKG_DIR%naps2_portable\lib\" goto missing_component
if not exist "%CONFIG_FILE%" goto missing_config

echo [1/8] Verifying package files against SHA256SUMS.txt ...
powershell -NoProfile -Command "function D($m) { Write-Output $m; try { [IO.File]::WriteAllText($env:LS_DETAIL, $m) } catch {} }; try { $root = [IO.Path]::GetFullPath($env:PKG_DIR).TrimEnd('\'); $sums = Join-Path $root 'SHA256SUMS.txt'; $actual = @{}; foreach ($it in Get-ChildItem -LiteralPath $root -Recurse -Force) { if ($it.Attributes -band [IO.FileAttributes]::ReparsePoint) { D ('REPARSE_POINT ' + $it.FullName); exit 23 }; if (-not $it.PSIsContainer -and $it.FullName -ne $sums) { $actual[$it.FullName.ToUpperInvariant()] = $it.FullName } }; $bad = [IO.Path]::GetInvalidFileNameChars(); $seen = @{}; foreach ($line in [IO.File]::ReadAllLines($sums)) { if ($line -eq '') { continue }; if ($line -cnotmatch '^([0-9A-F]{64})  (.+)$') { D ('MANIFEST_BAD_LINE ' + $line); exit 21 }; $h = $matches[1]; $rel = $matches[2]; if ([IO.Path]::IsPathRooted($rel)) { D ('UNSAFE_PATH ' + $rel); exit 21 }; foreach ($seg in $rel.Split('\')) { if ($seg -eq '' -or $seg -eq '.' -or $seg -eq '..' -or $seg.IndexOfAny($bad) -ge 0 -or $seg.Trim() -cne $seg -or $seg.EndsWith('.')) { D ('UNSAFE_PATH ' + $rel); exit 21 } }; $full = [IO.Path]::GetFullPath((Join-Path $root $rel)); if (-not $full.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) { D ('UNSAFE_PATH ' + $rel); exit 21 }; $key = $full.ToUpperInvariant(); if ($seen.ContainsKey($key)) { D ('DUPLICATE_ENTRY ' + $rel); exit 21 }; $seen[$key] = 1; if (-not $actual.ContainsKey($key)) { D ('MISSING_FILE ' + $rel); exit 22 }; if ((Get-FileHash -LiteralPath $full -Algorithm SHA256).Hash -cne $h) { D ('HASH_MISMATCH ' + $rel); exit 22 } }; if ($seen.Count -eq 0) { D 'EMPTY_MANIFEST'; exit 20 }; foreach ($k in $actual.Keys) { if (-not $seen.ContainsKey($k)) { D ('UNLISTED_FILE ' + $actual[$k].Substring($root.Length + 1)); exit 23 } }; Write-Output ('PACKAGE_OK files=' + $seen.Count); exit 0 } catch { D ('MANIFEST_ERROR ' + $_.Exception.Message); exit 24 }"
if errorlevel 1 goto integrity_failed

REM -- 2) config.json + pinned public root certificate.
powershell -NoProfile -Command "function D($m) { Write-Output $m; try { [IO.File]::WriteAllText($env:LS_DETAIL, $m) } catch {} }; try { $cfg = [IO.File]::ReadAllText($env:CONFIG_FILE, [Text.Encoding]::UTF8) | ConvertFrom-Json } catch { D 'CONFIG_UNREADABLE'; exit 16 }; if ([string]$cfg.schema_version -ne '1.0') { D 'CONFIG_SCHEMA'; exit 16 }; if ([string]$cfg.package_role -cne 'client') { D 'CONFIG_PACKAGE_ROLE'; exit 16 }; $srv = [string]$cfg.server_machine_name; if ($srv -cnotmatch '^[A-Za-z0-9][A-Za-z0-9_-]{0,62}$') { D 'CONFIG_SERVER_MACHINE_NAME'; exit 16 }; if ($srv -ieq [string]$env:COMPUTERNAME) { D ('THIS_PC_IS_THE_SERVER ' + $srv); exit 17 }; $origin = [string]$cfg.server_origin; if ($origin -cnotmatch '^https://[a-z0-9.-]+(:[0-9]{1,5})?$') { D 'CONFIG_ORIGIN'; exit 11 }; if ([string]$cfg.device_setup_url -cne ($origin + '/books/device-setup/')) { D 'CONFIG_SETUP_URL'; exit 11 }; $certName = [string]$cfg.root_cert_file; if ($certName -cnotmatch '^[A-Za-z0-9_-]+\.cer$') { D 'CONFIG_CERT_NAME'; exit 16 }; if ([string]$cfg.root_cert_sha256 -cnotmatch '^[0-9A-F]{64}$' -or [string]$cfg.root_cert_thumbprint -cnotmatch '^[0-9A-F]{40}$') { D 'CONFIG_PINS'; exit 16 }; $certPath = Join-Path $env:PKG_DIR $certName; if (-not (Test-Path -LiteralPath $certPath -PathType Leaf)) { D 'CERT_MISSING'; exit 12 }; if ((Get-FileHash -LiteralPath $certPath -Algorithm SHA256).Hash -cne [string]$cfg.root_cert_sha256) { D 'CERT_SHA256_MISMATCH'; exit 13 }; try { $t = [Security.Cryptography.X509Certificates.X509Certificate2]::GetCertContentType($certPath); if ($t -ne [Security.Cryptography.X509Certificates.X509ContentType]::Cert) { D 'CERT_NOT_PUBLIC_CER'; exit 14 }; $c = New-Object Security.Cryptography.X509Certificates.X509Certificate2($certPath) } catch { D 'CERT_UNPARSEABLE'; exit 14 }; if ($c.HasPrivateKey) { D 'CERT_HAS_PRIVATE_KEY'; exit 14 }; if ($c.Thumbprint.ToUpperInvariant() -cne [string]$cfg.root_cert_thumbprint) { D 'CERT_THUMBPRINT_MISMATCH'; exit 15 }; exit 0"
set "LS_RC=%errorlevel%"
if "%LS_RC%"=="11" goto bad_config
if "%LS_RC%"=="16" goto bad_config
if "%LS_RC%"=="17" goto server_machine
if not "%LS_RC%"=="0" goto bad_cert

for /f "usebackq tokens=1,* delims==" %%A in (`powershell -NoProfile -Command "$cfg = [IO.File]::ReadAllText($env:CONFIG_FILE, [Text.Encoding]::UTF8) | ConvertFrom-Json; 'CFG_ORIGIN=' + $cfg.server_origin; 'CFG_SETUP_URL=' + $cfg.device_setup_url; 'CFG_CERT_FILE=' + $cfg.root_cert_file; 'CFG_THUMB=' + $cfg.root_cert_thumbprint"`) do (
    if "%%A"=="CFG_ORIGIN" set "CFG_ORIGIN=%%B"
    if "%%A"=="CFG_SETUP_URL" set "CFG_SETUP_URL=%%B"
    if "%%A"=="CFG_CERT_FILE" set "CFG_CERT_FILE=%%B"
    if "%%A"=="CFG_THUMB" set "CFG_THUMB=%%B"
)
if not defined CFG_ORIGIN goto bad_config
if not defined CFG_SETUP_URL goto bad_config
if not defined CFG_CERT_FILE goto bad_config
if not defined CFG_THUMB goto bad_config
echo [2/8] Package verified. Server: %CFG_ORIGIN%

REM -- 3) Trust the company root for THIS user (Windows shows its own Yes/No prompt).
set "LS_STAGE=cert"
call :stage cert
if defined LETTERSYS_SETUP_SKIP_CERT_STORE (
    echo [3/8] Certificate store step skipped by LETTERSYS_SETUP_SKIP_CERT_STORE.
    goto cert_done
)
set "LS_CERT_PATH=%PKG_DIR%%CFG_CERT_FILE%"
powershell -NoProfile -Command "function D($m) { Write-Output $m; try { [IO.File]::WriteAllText($env:LS_DETAIL, $m) } catch {} }; $ErrorActionPreference = 'Stop'; try { $c = New-Object Security.Cryptography.X509Certificates.X509Certificate2($env:LS_CERT_PATH); if ($c.Thumbprint -cne $env:CFG_THUMB) { D 'CERT_THUMBPRINT_MISMATCH'; exit 2 }; $s = New-Object Security.Cryptography.X509Certificates.X509Store('Root', 'CurrentUser'); $s.Open('ReadWrite'); try { if ($s.Certificates.Find('FindByThumbprint', $env:CFG_THUMB, $false).Count -eq 0) { $s.Add($c); Write-Output 'CERT_IMPORTED' } else { Write-Output 'CERT_ALREADY_PRESENT' } } finally { $s.Close() }; $v = New-Object Security.Cryptography.X509Certificates.X509Store('Root', 'CurrentUser'); $v.Open('ReadOnly'); $n = $v.Certificates.Find('FindByThumbprint', $env:CFG_THUMB, $false).Count; $v.Close(); if ($n -lt 1) { D 'CERT_NOT_PRESENT_AFTER_IMPORT'; exit 3 }; exit 0 } catch { D ('CERT_STORE_ERROR ' + $_.Exception.Message); exit 4 }"
if errorlevel 1 goto cert_store_failed
echo [3/8] Company root certificate is trusted for this user.
:cert_done

REM -- 4) Server reachability (soft: the server port may simply not be up yet).
set "LS_STAGE=server"
call :stage server
powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12; $n = 3; if ($env:LETTERSYS_SETUP_SERVER_ATTEMPTS -match '^[1-9]$') { $n = [int]$env:LETTERSYS_SETUP_SERVER_ATTEMPTS }; $state = 50; for ($i = 1; $i -le $n; $i++) { try { $q = [Net.HttpWebRequest]::Create($env:CFG_SETUP_URL); $q.Method = 'GET'; $q.AllowAutoRedirect = $false; $q.Timeout = 8000; $r = $q.GetResponse(); $r.Close(); $state = 0; break } catch [Net.WebException] { if ($_.Exception.Response) { $_.Exception.Response.Close(); $state = 0; break }; if ($_.Exception.Status -eq [Net.WebExceptionStatus]::TrustFailure -or $_.Exception.Status -eq [Net.WebExceptionStatus]::SecureChannelFailure) { $state = 51 } else { $state = 50 }; Write-Output ('SERVER_ATTEMPT ' + $i + ' ' + $_.Exception.Status) } catch { $state = 50; Write-Output ('SERVER_ATTEMPT ' + $i + ' ' + $_.Exception.Message) }; if ($i -lt $n) { Start-Sleep -Seconds 3 } }; exit $state"
set "LS_RC=%errorlevel%"
set "LS_SERVER_STATUS=unreachable"
if "%LS_RC%"=="0" set "LS_SERVER_STATUS=reachable"
if "%LS_RC%"=="51" set "LS_SERVER_STATUS=tls_error"
if "%LS_SERVER_STATUS%"=="reachable" echo [4/8] Server answered: %CFG_ORIGIN%
if not "%LS_SERVER_STATUS%"=="reachable" echo [4/8] NOTE: server %CFG_ORIGIN% did not answer now (%LS_SERVER_STATUS%). Installation continues; retry the device page later.

REM -- 5) Agent runtime + autostart shortcut via the existing per-user installer.
set "LS_STAGE=install"
call :stage install
set "LETTERSYS_INSTALL_NO_START=1"
echo [5/8] Installing scan agent for this user ...
powershell -NoProfile -Command "$ErrorActionPreference = 'Stop'; try { $startup = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup'; New-Item -ItemType Directory -Path $startup -Force | Out-Null } catch { $m = 'STARTUP_FOLDER_ERROR ' + $_.Exception.Message; Write-Output $m; [IO.File]::WriteAllText($env:LS_DETAIL, $m); exit 1 }"
if errorlevel 1 goto startup_failed
if "%LETTERSYS_SETUP_AUTO_APPROVE%"=="1" goto install_auto
call "%PKG_DIR%scan_agent\install_agent.bat" "%CFG_ORIGIN%"
set "LS_RC=%errorlevel%"
goto install_done
:install_auto
REM Setup.vbs already asked the user (approval dialog shows the same origin).
echo y| call "%PKG_DIR%scan_agent\install_agent.bat" "%CFG_ORIGIN%"
set "LS_RC=%errorlevel%"
:install_done
if "%LS_RC%"=="1" goto cancelled
if not "%LS_RC%"=="0" goto agent_install_failed

REM -- 6) Full NAPS2 portable: forced mirror (no stale files), checked exit code.
set "LS_STAGE=naps2"
call :stage naps2
echo [6/8] Copying bundled NAPS2 (console + GUI) ...
powershell -NoProfile -Command "Get-Process -Name 'NAPS2*' -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path.StartsWith($env:LS_NAPS2_DEST + '\', [StringComparison]::OrdinalIgnoreCase) } | Stop-Process -Force -ErrorAction SilentlyContinue"
robocopy "%PKG_DIR%naps2_portable" "%LS_NAPS2_DEST%" /MIR /IS /IT /R:3 /W:2 /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto naps2_copy_failed

REM -- 7) Verify the INSTALLED copy (python, scan_agent, NAPS2) against the manifest.
set "LS_STAGE=verify"
call :stage verify
powershell -NoProfile -Command "function D($m) { Write-Output $m; try { [IO.File]::WriteAllText($env:LS_DETAIL, $m) } catch {} }; try { $root = [IO.Path]::GetFullPath($env:PKG_DIR).TrimEnd('\'); $agent = [IO.Path]::GetFullPath($env:LS_AGENT_DIR).TrimEnd('\'); $naps = [IO.Path]::GetFullPath($env:LS_NAPS2_DEST).TrimEnd('\'); $listed = @{}; $count = 0; foreach ($line in [IO.File]::ReadAllLines((Join-Path $root 'SHA256SUMS.txt'))) { if ($line -cnotmatch '^([0-9A-F]{64})  (.+)$') { continue }; $h = $matches[1]; $rel = $matches[2]; if ($rel.StartsWith('naps2_portable\', [StringComparison]::OrdinalIgnoreCase)) { $dest = Join-Path $naps $rel.Substring(15) } elseif ($rel.StartsWith('python\', [StringComparison]::OrdinalIgnoreCase) -or $rel.StartsWith('scan_agent\', [StringComparison]::OrdinalIgnoreCase)) { $dest = Join-Path $agent $rel } else { continue }; $listed[[IO.Path]::GetFullPath($dest).ToUpperInvariant()] = 1; if (-not (Test-Path -LiteralPath $dest -PathType Leaf)) { D ('INSTALLED_MISSING ' + $dest); exit 1 }; if ((Get-FileHash -LiteralPath $dest -Algorithm SHA256).Hash -cne $h) { D ('INSTALLED_HASH_MISMATCH ' + $dest); exit 1 }; $count++ }; foreach ($f in Get-ChildItem -LiteralPath $naps -Recurse -Force -File) { if (-not $listed.ContainsKey($f.FullName.ToUpperInvariant())) { D ('STALE_NAPS2_FILE ' + $f.FullName); exit 1 } }; foreach ($req in @((Join-Path $agent 'python\pythonw.exe'), (Join-Path $agent 'scan_agent\__main__.py'), (Join-Path $naps 'NAPS2.exe'), (Join-Path $naps 'NAPS2.Console.exe'))) { if (-not (Test-Path -LiteralPath $req -PathType Leaf)) { D ('INSTALLED_REQUIRED_MISSING ' + $req); exit 1 } }; if (-not (Test-Path -LiteralPath (Join-Path $naps 'lib') -PathType Container)) { D 'INSTALLED_NAPS2_LIB_MISSING'; exit 1 }; Write-Output ('INSTALLED_OK files=' + $count); exit 0 } catch { D ('VERIFY_ERROR ' + $_.Exception.Message); exit 1 }"
if errorlevel 1 goto verify_failed
REM -- 7b) Managed all-in-one client: agent.json gets require_pairing=true (origins kept as
REM    validated by install_agent.bat) BEFORE the agent is started.
powershell -NoProfile -Command "function D($m) { Write-Output $m; try { [IO.File]::WriteAllText($env:LS_DETAIL, $m) } catch {} }; try { $f = Join-Path $env:LOCALAPPDATA 'LetterSys\agent.json'; $j = [IO.File]::ReadAllText($f, [Text.Encoding]::UTF8).TrimStart([char]0xFEFF) | ConvertFrom-Json; $o = @($j.allowed_origins | ForEach-Object { [string]$_ }); if ($o.Count -lt 1 -or $o -cnotcontains $env:CFG_ORIGIN) { D 'AGENT_JSON_ORIGIN_MISSING'; exit 1 }; $new = ConvertTo-Json -InputObject ([ordered]@{ allowed_origins = $o; require_pairing = $true }) -Depth 3; $tmp = $f + '.tmp'; [IO.File]::WriteAllText($tmp, $new, (New-Object Text.UTF8Encoding($false))); Move-Item -LiteralPath $tmp -Destination $f -Force; $chk = [IO.File]::ReadAllText($f, [Text.Encoding]::UTF8) | ConvertFrom-Json; if (-not ($chk.require_pairing -is [bool] -and $chk.require_pairing) -or (@($chk.allowed_origins) -join ' ') -cne ($o -join ' ')) { D 'AGENT_JSON_VERIFY_FAILED'; exit 1 }; Write-Output 'REQUIRE_PAIRING_SET'; exit 0 } catch { D ('AGENT_JSON_ERROR ' + $_.Exception.Message); exit 1 }"
if errorlevel 1 goto pairing_flag_failed
set "LS_AGENT_INSTALLED=1"
echo [7/8] Installed files verified in %LS_AGENT_DIR%

REM -- 8) Start the INSTALLED agent (never the package copy), then health + devices.
if defined LETTERSYS_SETUP_NO_START (
    echo [8/8] Agent start skipped by LETTERSYS_SETUP_NO_START.
    goto open_browser
)
set "LS_STAGE=agent"
call :stage agent
powershell -NoProfile -Command "function D($m) { Write-Output $m; try { [IO.File]::WriteAllText($env:LS_DETAIL, $m) } catch {} }; try { $port = [int]$env:LS_PORT; $init = [IO.File]::ReadAllText((Join-Path $env:LS_AGENT_DIR 'scan_agent\__init__.py')); if ($init -notmatch '__version__\s*=\s*.([0-9A-Za-z.+-]+).') { D 'AGENT_VERSION_UNKNOWN'; exit 1 }; $ver = $matches[1]; $exp = [IO.Path]::GetFullPath($env:LS_NAPS2_DEST).TrimEnd('\') + '\'; $p = $null; if ($env:LETTERSYS_SETUP_TEST_FAKE_AGENT -ne '1') { $pyw = Join-Path $env:LS_AGENT_DIR 'python\pythonw.exe'; if (-not (Test-Path -LiteralPath $pyw -PathType Leaf)) { D 'AGENT_PYTHONW_MISSING'; exit 1 }; $p = Start-Process -FilePath $pyw -ArgumentList '-m', 'scan_agent' -WorkingDirectory $env:LS_AGENT_DIR -WindowStyle Hidden -PassThru }; $secs = 45; if ($env:LETTERSYS_SETUP_HEALTH_SECONDS -match '^[1-9][0-9]{0,2}$') { $secs = [int]$env:LETTERSYS_SETUP_HEALTH_SECONDS }; $deadline = (Get-Date).AddSeconds($secs); $last = 'no answer'; while ((Get-Date) -lt $deadline) { if ($p -and $p.HasExited) { D ('AGENT_EXITED code=' + $p.ExitCode); exit 1 }; try { $r = Invoke-WebRequest -UseBasicParsing -Uri ('http://127.0.0.1:' + $port + '/agent/health') -TimeoutSec 5; $j = [Text.Encoding]::UTF8.GetString($r.RawContentStream.ToArray()) | ConvertFrom-Json; if ($j.ok -is [bool] -and $j.ok -and [string]$j.version -ceq $ver -and $j.naps2_available -is [bool] -and $j.naps2_available -and ([string]$j.naps2_path).StartsWith($exp, [StringComparison]::OrdinalIgnoreCase)) { Write-Output ('AGENT_HEALTHY version=' + $ver); exit 0 }; $last = 'unexpected health: version=' + $j.version + ' naps2_path=' + $j.naps2_path } catch { $last = $_.Exception.Message }; Start-Sleep -Milliseconds 700 }; D ('AGENT_HEALTH_FAILED ' + $last); exit 1 } catch { D ('AGENT_START_ERROR ' + $_.Exception.Message); exit 1 }"
if errorlevel 1 goto health_failed
set "LS_AGENT_STATUS=healthy"
echo [8/8] Agent is running from %LS_AGENT_DIR%. Listing scanners (up to 130 seconds) ...

set "LS_STAGE=devices"
call :stage devices
powershell -NoProfile -Command "function S($st, $names, $detail) { $o = [ordered]@{ status = $st; names = @($names); detail = [string]$detail }; [IO.File]::WriteAllText($env:LS_DEVSTATE, (ConvertTo-Json -InputObject $o -Depth 3), (New-Object Text.UTF8Encoding($false))); Write-Output ('DEVICES ' + $st + ' ' + $detail) }; try { $r = Invoke-WebRequest -UseBasicParsing -Uri ('http://127.0.0.1:' + [int]$env:LS_PORT + '/agent/devices') -Headers @{ Origin = $env:CFG_ORIGIN } -TimeoutSec 130 } catch { S 'error' @() ('request failed: ' + $_.Exception.Message); exit 42 }; try { $j = [Text.Encoding]::UTF8.GetString($r.RawContentStream.ToArray()) | ConvertFrom-Json } catch { S 'unknown' @() 'malformed response'; exit 41 }; if ($j -eq $null) { S 'unknown' @() 'empty response'; exit 41 }; if (-not ($j.ok -is [bool] -and $j.ok)) { S 'unknown' @() ('agent reported failure: ' + $j.error); exit 41 }; if ($j.PSObject.Properties['warning'] -and $j.warning) { S 'unknown' @() ('agent warning: ' + $j.warning); exit 41 }; if (-not $j.PSObject.Properties['devices'] -or $j.devices -isnot [array]) { S 'unknown' @() 'devices list missing'; exit 41 }; $names = @(); foreach ($d in $j.devices) { if ($d -eq $null -or -not $d.PSObject.Properties['name'] -or $d.name -isnot [string] -or $d.name.Trim() -eq '') { S 'unknown' @() 'device entry without name'; exit 41 }; $names += $d.name }; if ($names.Count -eq 0) { S 'no_device' @() ('driver=' + $j.driver); exit 40 }; S 'ready' $names ('driver=' + $j.driver); exit 0"
set "LS_RC=%errorlevel%"
set "LS_DEVICE_STATUS=error"
if "%LS_RC%"=="0" set "LS_DEVICE_STATUS=ready"
if "%LS_RC%"=="40" set "LS_DEVICE_STATUS=no_device"
if "%LS_RC%"=="41" set "LS_DEVICE_STATUS=unknown"
if "%LS_DEVICE_STATUS%"=="ready" echo Scanner(s) found - see install_result.json.
if "%LS_DEVICE_STATUS%"=="no_device" echo NOTE: the agent works but no scanner is listed. Turn the scanner on, connect it, install its TWAIN/WIA driver, then re-check from the device page.
if "%LS_DEVICE_STATUS%"=="unknown" echo WARNING: the scanner list could not be confirmed (agent warning or malformed answer). This is NOT the same as "no scanner".
if "%LS_DEVICE_STATUS%"=="error" echo WARNING: the scanner list request failed or timed out.

:open_browser
set "LS_STAGE=done"
call :stage done
if defined LETTERSYS_SETUP_NO_BROWSER goto after_browser
if not "%LS_SERVER_STATUS%"=="reachable" goto after_browser
start "" "%CFG_SETUP_URL%"
set "LS_BROWSER=1"
echo Opening device setup page: %CFG_SETUP_URL%
:after_browser
if not "%LS_SERVER_STATUS%"=="reachable" echo When the server is reachable, open: %CFG_SETUP_URL%
set "LS_EXIT=0"
if "%LS_DEVICE_STATUS%"=="no_device" set "LS_EXIT=31"
if "%LS_DEVICE_STATUS%"=="unknown" set "LS_EXIT=32"
if "%LS_DEVICE_STATUS%"=="error" set "LS_EXIT=32"
set "LS_MSG=agent installed"
goto finish

REM ---------------------------------------------------------------- helpers
:stage
>"%LS_STATUS%" echo %~1
goto :eof

:finish
powershell -NoProfile -Command "$dev = $null; if (Test-Path -LiteralPath $env:LS_DEVSTATE) { try { $dev = [IO.File]::ReadAllText($env:LS_DEVSTATE, [Text.Encoding]::UTF8) | ConvertFrom-Json } catch { $dev = $null } }; $names = @(); $ddetail = ''; if ($dev) { $names = @($dev.names | Where-Object { $_ -is [string] }); $ddetail = [string]$dev.detail }; $detail = ''; if (Test-Path -LiteralPath $env:LS_DETAIL) { $detail = [IO.File]::ReadAllText($env:LS_DETAIL) }; $o = [ordered]@{ schema = 1; run_id = [string]$env:LETTERSYS_SETUP_RUN_ID; exit_code = [int]$env:LS_EXIT; stage = [string]$env:LS_STAGE; message = [string]$env:LS_MSG; detail = $detail; agent_installed = ($env:LS_AGENT_INSTALLED -eq '1'); agent_status = [string]$env:LS_AGENT_STATUS; server_status = [string]$env:LS_SERVER_STATUS; device_status = [string]$env:LS_DEVICE_STATUS; device_names = $names; device_names_text = ($names -join ' | '); device_detail = $ddetail; server_origin = [string]$env:CFG_ORIGIN; device_setup_url = [string]$env:CFG_SETUP_URL; browser_opened = ($env:LS_BROWSER -eq '1'); finished_at = (Get-Date).ToString('s') }; [IO.File]::WriteAllText($env:LS_RESULT, (ConvertTo-Json -InputObject $o -Depth 4), (New-Object Text.UTF8Encoding($false)))"
if errorlevel 1 echo [ERROR] Could not write %LS_RESULT%
echo.
if "%LS_EXIT%"=="0" echo Workstation setup completed: agent healthy and a scanner is listed.
if not "%LS_EXIT%"=="0" echo Setup finished with code %LS_EXIT% at stage "%LS_STAGE%": %LS_MSG%
del /f /q "%LS_STATUS%" 2>nul
endlocal & exit /b %LS_EXIT%

REM ---------------------------------------------------------------- failures
:elevated
echo.
echo [ERROR] Elevated execution detected (Run as administrator).
echo   Run Setup normally as the logged-in employee. Nothing was written.
echo.
endlocal & exit /b 6

:no_localappdata
echo [ERROR] LOCALAPPDATA is not available for this user.
endlocal & exit /b 8

:missing_component
set "LS_EXIT=8"
set "LS_MSG=package component missing (SHA256SUMS.txt, scan_agent, python or full naps2_portable)"
echo [ERROR] %LS_MSG%
goto finish

:missing_config
set "LS_EXIT=2"
set "LS_MSG=config.json not found"
echo [ERROR] %LS_MSG%
goto finish

:integrity_failed
set "LS_EXIT=7"
set "LS_MSG=package integrity check failed (file changed, missing, unlisted or unsafe path) - nothing was installed"
echo [ERROR] %LS_MSG%
goto finish

:bad_config
set "LS_EXIT=2"
set "LS_MSG=config.json is invalid (origin, setup URL, schema or pins)"
echo [ERROR] %LS_MSG%
goto finish

:server_machine
set "LS_EXIT=11"
set "LS_MSG=this computer is the LetterSys SERVER - the client package is for employee computers; nothing was installed"
echo [REFUSED] %LS_MSG%
goto finish

:bad_cert
set "LS_EXIT=3"
set "LS_MSG=root certificate does not match the pinned SHA256/Thumbprint or is not a public .cer"
echo [ERROR] %LS_MSG%
goto finish

:cert_store_failed
set "LS_EXIT=9"
set "LS_MSG=root certificate was not added to the user's trusted roots (declined or store error)"
echo [ERROR] %LS_MSG%
goto finish

:cancelled
set "LS_EXIT=1"
set "LS_MSG=cancelled by the user - agent settings unchanged"
echo [CANCELLED] %LS_MSG%
goto finish

:startup_failed
set "LS_EXIT=4"
set "LS_MSG=Could not prepare this user's Startup folder"
goto finish

:agent_install_failed
set "LS_EXIT=4"
set "LS_MSG=install_agent.bat failed with code %LS_RC%"
echo [ERROR] %LS_MSG%
goto finish

:naps2_copy_failed
set "LS_EXIT=5"
set "LS_MSG=copying NAPS2 to %LS_NAPS2_DEST% failed (file in use or disk error)"
echo [ERROR] %LS_MSG%
goto finish

:verify_failed
set "LS_EXIT=10"
set "LS_MSG=installed files do not match the package manifest"
echo [ERROR] %LS_MSG%
goto finish

:pairing_flag_failed
set "LS_EXIT=12"
set "LS_MSG=could not mark agent.json as a managed client (require_pairing)"
echo [ERROR] %LS_MSG%
goto finish

:health_failed
set "LS_EXIT=30"
set "LS_AGENT_STATUS=unhealthy"
set "LS_MSG=the installed agent did not answer a valid health check on 127.0.0.1:%LS_PORT%"
echo [ERROR] %LS_MSG%
goto finish