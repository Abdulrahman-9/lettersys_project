# Django Server Background Service Manager
# Usage: .\manage_server_background.ps1 -Action [start|stop|restart|status|logs]

param(
    [ValidateSet("start", "stop", "restart", "status", "logs")]
    [string]$Action = "status"
)

# ════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ════════════════════════════════════════════════════════════════════════════
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PidFile = Join-Path $ProjectDir "server.pid"
$LogDir = Join-Path $ProjectDir "logs"
$ServiceName = "LetterSysServer"
$PythonScript = Join-Path $ProjectDir "run_server_background.py"

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $Timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    $Color = @{
        "INFO"    = "Green"
        "ERROR"   = "Red"
        "WARNING" = "Yellow"
        "SUCCESS" = "Cyan"
    }
    Write-Host "[$Timestamp] [$Level] $Message" -ForegroundColor $Color[$Level]
}

function Get-ServerPid {
    if (Test-Path $PidFile) {
        try {
            return [int](Get-Content $PidFile -ErrorAction Stop)
        }
        catch {
            return $null
        }
    }
    return $null
}

function Is-ServerRunning {
    $ProcessId = Get-ServerPid
    if ($ProcessId) {
        try {
            $Process = Get-Process -Id $ProcessId -ErrorAction Stop
            return $true
        }
        catch {
            return $false
        }
    }
    return $false
}

# ════════════════════════════════════════════════════════════════════════════
# MAIN FUNCTIONS
# ════════════════════════════════════════════════════════════════════════════

function Start-Server {
    if (Is-ServerRunning) {
        $ProcessId = Get-ServerPid
        Write-Log "Server is already running (PID: $ProcessId)" "WARNING"
        return $true
    }
    
    Write-Log "Starting Django server in background..." "INFO"
    Write-Log "Project: $ProjectDir" "INFO"
    Write-Log "Logs will be saved to: $LogDir" "INFO"
    
    try {
        if (-not (Test-Path $LogDir)) {
            New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
        }
        
        $Process = Start-Process -FilePath "python" `
                                 -ArgumentList $PythonScript `
                                 -WorkingDirectory $ProjectDir `
                                 -WindowStyle Hidden `
                                 -PassThru `
                                 -ErrorAction Stop
        
        Start-Sleep -Seconds 2
        
        if (Is-ServerRunning) {
            Write-Log "Server started successfully (PID: $($Process.Id))" "SUCCESS"
            Write-Log "Access at: http://localhost:8000" "INFO"
            Write-Log "Server is running in background with auto-restart enabled" "INFO"
            return $true
        }
        else {
            Write-Log "Server failed to start" "ERROR"
            return $false
        }
    }
    catch {
        Write-Log "Error starting server: $_" "ERROR"
        return $false
    }
}

function Stop-Server {
    $ProcessId = Get-ServerPid
    if (-not $ProcessId) {
        Write-Log "Server is not running" "WARNING"
        return $true
    }
    
    Write-Log "Stopping server (PID: $ProcessId)..." "INFO"
    
    try {
        Stop-Process -Id $ProcessId -ErrorAction Stop
        Start-Sleep -Seconds 2
        
        if (Is-ServerRunning) {
            Write-Log "Process didn't stop gracefully, forcing termination..." "WARNING"
            Stop-Process -Id $ProcessId -Force -ErrorAction Stop
        }
        
        Write-Log "Server stopped successfully" "SUCCESS"
        
        if (Test-Path $PidFile) {
            Remove-Item $PidFile -Force
        }
        
        return $true
    }
    catch {
        Write-Log "Error stopping server: $_" "ERROR"
        return $false
    }
}

function Restart-Server {
    Write-Log "Restarting server..." "INFO"
    
    if (Is-ServerRunning) {
        Stop-Server | Out-Null
        Start-Sleep -Seconds 2
    }
    
    Start-Server
}

function Show-Status {
    Write-Host ""
    Write-Host ("=" * 70)
    Write-Host "  Django Server Status" -ForegroundColor Cyan
    Write-Host ("=" * 70)
    
    $IsRunning = Is-ServerRunning
    $ProcessId = Get-ServerPid
    
    if ($IsRunning) {
        Write-Host ""
        Write-Host "  [OK] Status: RUNNING" -ForegroundColor Green
        Write-Host "  PID: $ProcessId"
        
        $Process = Get-Process -Id $ProcessId
        $MemMB = [Math]::Round($Process.WorkingSet / 1MB, 2)
        Write-Host "  Memory: $MemMB MB"
        Write-Host "  CPU: $($Process.CPU) seconds"
        Write-Host "  Started: $($Process.StartTime)"
    }
    else {
        Write-Host ""
        Write-Host "  [STOPPED] Status: STOPPED" -ForegroundColor Red
        if ($ProcessId) {
            Write-Host "  Note: PID file exists but process not found"
        }
    }
    
    if (Test-Path $LogDir) {
        $LogFiles = Get-ChildItem $LogDir -Filter "*.log" | Sort-Object LastWriteTime -Descending
        if ($LogFiles) {
            Write-Host ""
            Write-Host "  Recent Logs:"
            $LogFiles | Select-Object -First 3 | ForEach-Object {
                $Time = Get-Date $_.LastWriteTime -Format 'yyyy-MM-dd HH:mm:ss'
                Write-Host "    - $($_.Name) ($Time)"
            }
        }
    }
    
    Write-Host ""
    Write-Host ("=" * 70)
}

function Show-Logs {
    Write-Host ""
    Write-Host ("=" * 70)
    Write-Host "  Recent Server Logs" -ForegroundColor Cyan
    Write-Host ("=" * 70)
    Write-Host ""
    
    if (-not (Test-Path $LogDir)) {
        Write-Log "No logs found yet" "WARNING"
        return
    }
    
    $LatestLog = Get-ChildItem $LogDir -Filter "*.log" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    
    if ($LatestLog) {
        Write-Host "File: $($LatestLog.Name)"
        Write-Host ""
        Get-Content $LatestLog.FullName -Tail 50
    }
    else {
        Write-Log "No logs found" "WARNING"
    }
    
    Write-Host ""
    Write-Host ("=" * 70)
    Write-Host ""
}

# EXECUTE ACTION
Write-Host ""

switch ($Action) {
    "start" {
        Start-Server
    }
    "stop" {
        Stop-Server
    }
    "restart" {
        Restart-Server
    }
    "status" {
        Show-Status
    }
    "logs" {
        Show-Logs
    }
    default {
        Show-Status
    }
}

Write-Host ""
