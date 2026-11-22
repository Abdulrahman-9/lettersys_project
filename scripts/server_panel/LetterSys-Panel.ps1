<#
LetterSys desktop control panel - for the server computer only.

This file is ASCII on purpose: Windows PowerShell 5.1 misreads a .ps1 with Arabic text and no BOM, so every
Arabic label lives in strings.ar.json (UTF-8) next to it. The panel is installed by Install-Panel.ps1 under
Program Files (only administrators can change it, because the shortcut runs it elevated: starting and stopping
a service needs that). The browser is always opened through explorer.exe so the browser itself is NOT elevated.

  -SelfTest            print the status as JSON and exit (no window)
  -Snapshot <png>      draw the window off-screen into a PNG and exit (for review screenshots)
  -MakeReport <dir>    write the problem report zip into <dir> and exit (for tests)
  -DemoState <state>   with -Snapshot only: draw stopped/paused/noreply without touching the real service
#>
param([switch]$SelfTest, [string]$Snapshot = '', [string]$MakeReport = '', [string]$ConfigPath = '',
      [ValidateSet('', 'stopped', 'paused', 'noreply')][string]$DemoState = '')
$ErrorActionPreference = 'Stop'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path

function Read-Json([string]$Path) { [IO.File]::ReadAllText($Path, [Text.Encoding]::UTF8) | ConvertFrom-Json }

$S = Read-Json (Join-Path $Here 'strings.ar.json')
$C = [pscustomobject]@{
    service = 'LetterSys'; port = 1312; hostHeader = 'follow2'; officialUrl = 'http://follow2:1312'
    logDir = 'D:\lettersys\logs'; guidePath = 'D:\lettersys\app\var\guide\index.html'; appDir = 'D:\lettersys\app'
}
$cfgFile = if ($ConfigPath) { $ConfigPath } else { Join-Path $Here 'panel.config.json' }
if (Test-Path -LiteralPath $cfgFile) {
    foreach ($p in (Read-Json $cfgFile).PSObject.Properties) { $C | Add-Member -NotePropertyName $p.Name -NotePropertyValue $p.Value -Force }
}

# ---- Reading (no administrator needed) ----

function Get-Svc([string]$Name) {
    try { return Get-Service -Name $Name -ErrorAction Stop } catch { return $null }
}

function Get-PanelStatus {
    $app = Get-Svc $C.service
    $db = $null
    if ($app) { $db = $app.ServicesDependedOn | Select-Object -First 1 }
    $code = ''
    if ($app -and $app.Status -eq 'Running') {
        # Runs on the window's thread every 5 s: a hung server must not freeze the panel (Fable 11-22).
        $code = (& curl.exe -s -o NUL --connect-timeout 1 --max-time 2 -H ('Host: ' + $C.hostHeader) -w '%{http_code}' ('http://127.0.0.1:' + $C.port + '/login/'))
        $code = ($code | Out-String).Trim()
    }
    $state = 'stopped'
    if (-not $app) { $state = 'missing' }
    # Any 2xx/3xx answer means the application is serving: after HTTPS the login page answers 301.
    elseif ($app.Status -eq 'Running' -and $code -match '^[23]\d\d$') { $state = 'running' }
    elseif ($app.Status -eq 'Running') { $state = 'noreply' }
    elseif ($app.Status -eq 'Paused') { $state = 'paused' }
    elseif ([string]$app.Status -match 'Pending') { $state = 'starting' }
    $disks = @(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' -ErrorAction SilentlyContinue | Where-Object { $_.Size -gt 0 } |
        ForEach-Object { [pscustomobject]@{ name = $_.DeviceID; freeGB = [math]::Round($_.FreeSpace / 1GB, 1); freePct = [math]::Round($_.FreeSpace * 100 / $_.Size, 1) } })
    return [pscustomobject]@{
        state = $state
        app = $(if ($app) { [string]$app.Status } else { 'Missing' })
        appStart = $(if ($app) { [string]$app.StartType } else { '' })
        db = $(if ($db) { [string]$db.Status } else { 'Missing' })
        dbName = $(if ($db) { $db.Name } else { '' })
        dbStart = $(if ($db) { [string]$db.StartType } else { '' })
        http = $code
        disks = $disks
        url = $C.officialUrl
        checked = (Get-Date).ToString('HH:mm:ss')
    }
}

# ---- Problem report: status + the warning/error lines of the logs, redacted. Never .env, Caddy data,
# ---- the service environment, the declare code, backups or the application log.

function Protect-Line([string]$Line) {
    $l = [regex]::Replace($Line, '[A-Za-z0-9_\-]{16,}', '[...]')
    $l = [regex]::Replace($l, '\?\S*', '?[...]')
    $l = [regex]::Replace($l, '(?i)\b(user(name)?|login|for user)\b[=: ]+\S+', '$1=[...]')
    # Short secrets slip under the 16-character rule (a 5-digit pairing code, an 8-digit declare code).
    $l = [regex]::Replace($l, '(?i)\b(password|passwd|pwd|secret|token|code|key)\b\s*[=:]\s*\S+', '$1=[...]')
    $l = [regex]::Replace($l, '[\w.+-]+@[\w-]+\.[\w.]+', '[email]')
    return $l
}

function New-ProblemReport([string]$Into) {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $work = Join-Path $env:TEMP ('LetterSys-report-' + $stamp)
    New-Item -ItemType Directory -Path $work | Out-Null
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    try {
        [IO.File]::WriteAllText((Join-Path $work 'status.json'), (Get-PanelStatus | ConvertTo-Json -Depth 4), $utf8)
        $release = Join-Path $C.appDir 'var\release.json'
        if (Test-Path -LiteralPath $release) { Copy-Item -LiteralPath $release -Destination (Join-Path $work 'release.json') }
        foreach ($name in 'waitress.err.log', 'waitress.out.log') {
            $path = Join-Path $C.logDir $name
            if (-not (Test-Path -LiteralPath $path)) { continue }
            $lines = @(Get-Content -LiteralPath $path -Tail 600 -Encoding UTF8 |
                Where-Object { $_ -match '(?i)\b(warning|error|critical|exception|traceback)\b|^\s+File "|^\S+Error' -and $_ -notmatch '^INFO (REQUEST|RESPONSE):' } |
                ForEach-Object { Protect-Line $_ })
            [IO.File]::WriteAllLines((Join-Path $work ($name + '.txt')), [string[]]$lines, $utf8)
        }
        $zip = Join-Path $Into ('LetterSys-report-' + $stamp + '.zip')
        Compress-Archive -Path (Join-Path $work '*') -DestinationPath $zip -Force
        return $zip
    } finally {
        Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
    }
}

if ($SelfTest) { Get-PanelStatus | ConvertTo-Json -Depth 4; exit 0 }
if ($MakeReport) { New-ProblemReport $MakeReport; exit 0 }

# ---- The window ----

Add-Type -AssemblyName System.Windows.Forms, System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
$IsAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

function Hex([string]$h) { [System.Drawing.ColorTranslator]::FromHtml($h) }
$Teal = Hex '#0f766e'; $Ink = Hex '#14262b'; $Mute = Hex '#52656b'; $Line = Hex '#dfe7e5'; $Surf2 = Hex '#f6f9f8'
$Tone = @{
    ok = @{ fg = (Hex '#067647'); bg = (Hex '#ecfdf3') }
    warn = @{ fg = (Hex '#b54708'); bg = (Hex '#fffaeb') }
    bad = @{ fg = (Hex '#b42318'); bg = (Hex '#fef3f2') }
}
$FontBase = New-Object System.Drawing.Font('Segoe UI', 11)
$FontBold = New-Object System.Drawing.Font('Segoe UI', 11, [System.Drawing.FontStyle]::Bold)
$FontBig = New-Object System.Drawing.Font('Segoe UI', 18, [System.Drawing.FontStyle]::Bold)
$FontMain = New-Object System.Drawing.Font('Segoe UI', 14, [System.Drawing.FontStyle]::Bold)

function New-Button([string]$Text, [int]$X, [int]$Y, [int]$W, [int]$H, [bool]$Primary) {
    $b = New-Object System.Windows.Forms.Button
    $b.Text = $Text; $b.Location = New-Object System.Drawing.Point($X, $Y); $b.Size = New-Object System.Drawing.Size($W, $H)
    $b.FlatStyle = 'Flat'; $b.Cursor = [System.Windows.Forms.Cursors]::Hand
    if ($Primary) { $b.BackColor = $Teal; $b.ForeColor = [System.Drawing.Color]::White; $b.Font = $FontMain; $b.FlatAppearance.BorderSize = 0 }
    else { $b.BackColor = $Surf2; $b.ForeColor = $Ink; $b.Font = $FontBold; $b.FlatAppearance.BorderColor = $Line }
    return $b
}

function Show-Message([string]$Text, [string]$Kind = 'Information', [string]$Buttons = 'OK') {
    $opts = [System.Windows.Forms.MessageBoxOptions]::RtlReading -bor [System.Windows.Forms.MessageBoxOptions]::RightAlign
    return [System.Windows.Forms.MessageBox]::Show($Text, $S.title, $Buttons, $Kind, 'Button1', $opts)
}

$form = New-Object System.Windows.Forms.Form
$form.Text = $S.title; $form.ClientSize = New-Object System.Drawing.Size(544, 600)
$form.StartPosition = 'CenterScreen'; $form.FormBorderStyle = 'FixedDialog'; $form.MaximizeBox = $false
$form.RightToLeft = 'Yes'; $form.RightToLeftLayout = $true; $form.Font = $FontBase; $form.BackColor = [System.Drawing.Color]::White

$statusBox = New-Object System.Windows.Forms.Panel
$statusBox.Location = New-Object System.Drawing.Point(20, 16); $statusBox.Size = New-Object System.Drawing.Size(504, 96)
$lblState = New-Object System.Windows.Forms.Label
$lblState.Location = New-Object System.Drawing.Point(16, 12); $lblState.AutoSize = $true; $lblState.Font = $FontBig
$lblSub = New-Object System.Windows.Forms.Label
$lblSub.Location = New-Object System.Drawing.Point(16, 54); $lblSub.Size = New-Object System.Drawing.Size(472, 36); $lblSub.ForeColor = $Ink
$statusBox.Controls.AddRange(@($lblState, $lblSub))

$btnMain = New-Button '' 20 124 504 56 $true
$btnRestart = New-Button $S.btn_restart 20 190 504 44 $false

$rowsBox = New-Object System.Windows.Forms.Panel
$rowsBox.Location = New-Object System.Drawing.Point(20, 248); $rowsBox.Size = New-Object System.Drawing.Size(504, 222)
$rowsBox.BorderStyle = 'FixedSingle'
$rowNames = @($S.row_app, $S.row_db, $S.row_autostart, ($S.row_disk + ' C:'), $S.row_link)
$rowValues = @()
for ($i = 0; $i -lt $rowNames.Count; $i++) {
    $name = New-Object System.Windows.Forms.Label
    $name.Text = $rowNames[$i]; $name.Location = New-Object System.Drawing.Point(14, (10 + $i * 42)); $name.Size = New-Object System.Drawing.Size(220, 30)
    $name.TextAlign = 'MiddleLeft'
    $value = New-Object System.Windows.Forms.Label
    $value.Location = New-Object System.Drawing.Point(240, (10 + $i * 42)); $value.Size = New-Object System.Drawing.Size(250, 30)
    $value.TextAlign = 'MiddleRight'; $value.Font = $FontBold
    $rowsBox.Controls.AddRange(@($name, $value)); $rowValues += $value
}

$btnGuide = New-Button $S.btn_guide 20 486 162 44 $false
$btnReport = New-Button $S.btn_report 191 486 162 44 $false
$btnAuto = New-Button $S.btn_autostart 362 486 162 44 $false
$lblFoot = New-Object System.Windows.Forms.Label
$lblFoot.Location = New-Object System.Drawing.Point(20, 548); $lblFoot.Size = New-Object System.Drawing.Size(504, 28); $lblFoot.ForeColor = $Mute
$form.Controls.AddRange(@($statusBox, $btnMain, $btnRestart, $rowsBox, $btnGuide, $btnReport, $btnAuto, $lblFoot))

$script:Pending = $null
$script:MainAction = ''

function Set-Value([int]$Index, [string]$Text, [string]$ToneName) {
    $rowValues[$Index].Text = $Text
    $rowValues[$Index].ForeColor = $(if ($ToneName) { $Tone[$ToneName].fg } else { $Ink })
}

function Get-ServiceWord([string]$Status) {
    switch -Regex ($Status) {
        '^Running$' { return @($S.val_running, 'ok') }
        '^Paused$' { return @($S.val_paused, 'warn') }
        'Pending' { return @($S.val_pending, 'warn') }
        '^Missing$' { return @($S.val_missing, 'bad') }
        default { return @($S.val_stopped, 'bad') }
    }
}

function Update-View($st) {
    $map = @{
        running = @('ok', $S.state_running, $S.sub_running, $S.btn_open, 'open')
        noreply = @('warn', $S.state_noreply, $S.sub_noreply, $S.btn_restart, 'restart')
        starting = @('warn', $S.state_starting, $S.sub_starting, $S.btn_busy, '')
        paused = @('bad', $S.state_paused, $S.sub_paused, $S.btn_start, 'start')
        stopped = @('bad', $S.state_stopped, $S.sub_stopped, $S.btn_start, 'start')
        missing = @('bad', $S.state_missing, $S.sub_missing, $S.btn_start, '')
    }
    $m = $map[$st.state]
    if ($script:Pending) { $m = @('warn', $S.state_starting, $S.sub_starting, $S.btn_busy, '') }
    $statusBox.BackColor = $Tone[$m[0]].bg; $lblState.ForeColor = $Tone[$m[0]].fg
    $lblState.Text = $m[1]; $lblSub.Text = $m[2]; $btnMain.Text = $m[3]
    $script:MainAction = $m[4]; $btnMain.Enabled = [bool]$m[4]
    $btnRestart.Visible = ($st.state -eq 'running'); $btnRestart.Enabled = -not $script:Pending
    $w = Get-ServiceWord $st.app; Set-Value 0 $w[0] $w[1]
    $w = Get-ServiceWord $st.db; Set-Value 1 $w[0] $w[1]
    if ($st.appStart -eq 'Automatic' -and $st.dbStart -eq 'Automatic') { Set-Value 2 $S.val_auto 'ok' } else { Set-Value 2 $S.val_manual 'warn' }
    $c = $st.disks | Where-Object { $_.name -eq 'C:' } | Select-Object -First 1
    if ($c) {
        $diskTone = $(if ($c.freePct -lt 5) { 'bad' } elseif ($c.freePct -lt 10) { 'warn' } else { 'ok' })
        Set-Value 3 ([string]::Format($S.disk_value, $c.freeGB, $c.freePct)) $diskTone
    }
    Set-Value 4 $st.url ''
    $lblFoot.Text = [string]::Format($S.last_check, $st.checked)
}

function Refresh-View { Update-View (Get-PanelStatus) }

function Require-Admin {
    if ($IsAdmin) { return $true }
    Show-Message $S.need_admin 'Warning' | Out-Null
    return $false
}

function Open-Url([string]$Url) { Start-Process -FilePath 'explorer.exe' -ArgumentList $Url }

function Invoke-Sc([string[]]$ScArgs) {
    # No 2>&1: in Windows PowerShell 5.1 with ErrorActionPreference=Stop a stderr line becomes a terminating
    # NativeCommandError, and the exit code below would never be read. sc.exe reports its errors on stdout.
    $out = & sc.exe @ScArgs | Out-String
    return @($LASTEXITCODE, $out.Trim())
}

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 5000
$timer.Add_Tick({
    $st = Get-PanelStatus
    if ($script:Pending) {
        $p = $script:Pending
        if ($p.kind -eq 'stop' -and $st.app -eq 'Stopped') {
            Invoke-Sc @('start', $C.service) | Out-Null
            $script:Pending = @{ kind = 'start'; until = (Get-Date).AddSeconds(90) }
        } elseif ($p.kind -eq 'start' -and $st.state -eq 'running') {
            $script:Pending = $null; $timer.Interval = 5000
            Update-View $st; Show-Message $S.done_start | Out-Null; return
        } elseif ((Get-Date) -gt $p.until) {
            $script:Pending = $null; $timer.Interval = 5000
            Update-View $st; Show-Message $S.fail_start 'Error' | Out-Null; return
        }
    }
    Update-View $st
})

function Start-Pending([string]$Kind) {
    $script:Pending = @{ kind = $Kind; until = (Get-Date).AddSeconds(90) }
    $timer.Interval = 2000
    Refresh-View
}

$btnMain.Add_Click({
    switch ($script:MainAction) {
        'open' { Open-Url $C.officialUrl }
        'start' {
            if (-not (Require-Admin)) { return }
            $verb = $(if ((Get-Svc $C.service).Status -eq 'Paused') { 'continue' } else { 'start' })
            $r = Invoke-Sc @($verb, $C.service)
            if ($r[0] -ne 0 -and $r[1] -notmatch '1056') { Show-Message ([string]::Format($S.fail_action, $r[1])) 'Error' | Out-Null; return }
            Start-Pending 'start'
        }
        'restart' { $btnRestart.PerformClick() }
    }
})

$btnRestart.Add_Click({
    if (-not (Require-Admin)) { return }
    if ((Show-Message $S.confirm_restart 'Question' 'YesNo') -ne 'Yes') { return }
    $r = Invoke-Sc @('stop', $C.service)
    if ($r[0] -ne 0) { Show-Message ([string]::Format($S.fail_action, $r[1])) 'Error' | Out-Null; return }
    Start-Pending 'stop'
})

$btnAuto.Add_Click({
    if (-not (Require-Admin)) { return }
    if ((Show-Message $S.confirm_autostart 'Question' 'YesNo') -ne 'Yes') { return }
    $names = @($C.service) + @((Get-Svc $C.service).ServicesDependedOn | ForEach-Object { $_.Name })
    foreach ($n in $names) {
        $r = Invoke-Sc @('config', $n, 'start=', 'auto')
        if ($r[0] -ne 0) { Show-Message ([string]::Format($S.fail_action, $r[1])) 'Error' | Out-Null; Refresh-View; return }
    }
    Refresh-View; Show-Message $S.done_autostart | Out-Null
})

$btnGuide.Add_Click({
    if ((Get-PanelStatus).state -eq 'running') { Open-Url ($C.officialUrl.TrimEnd('/') + '/books/settings/server/guide/') }
    elseif (Test-Path -LiteralPath $C.guidePath) { Open-Url $C.guidePath }
    else { Show-Message $S.no_guide 'Warning' | Out-Null }
})

$btnReport.Add_Click({
    try {
        $zip = New-ProblemReport ([Environment]::GetFolderPath('Desktop'))
        Show-Message ([string]::Format($S.report_saved, $zip)) | Out-Null
    } catch {
        Show-Message ([string]::Format($S.fail_action, $_.Exception.Message)) 'Error' | Out-Null
    }
})

Refresh-View

if ($Snapshot) {
    if ($DemoState) {
        $demo = Get-PanelStatus
        $demo.state = $DemoState
        $demo.app = @{ stopped = 'Stopped'; paused = 'Paused'; noreply = 'Running' }[$DemoState]
        Update-View $demo
    }
    $form.StartPosition = 'Manual'; $form.Location = New-Object System.Drawing.Point(-4000, -4000); $form.ShowInTaskbar = $false
    $form.Show(); [System.Windows.Forms.Application]::DoEvents()
    $bmp = New-Object System.Drawing.Bitmap($form.Width, $form.Height)
    $form.DrawToBitmap($bmp, (New-Object System.Drawing.Rectangle(0, 0, $form.Width, $form.Height)))
    $bmp.Save($Snapshot, [System.Drawing.Imaging.ImageFormat]::Png)
    $form.Close(); exit 0
}

$timer.Start()
[void]$form.ShowDialog()
$timer.Stop()
