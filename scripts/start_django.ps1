# ================================
# نظام إدارة الكتب - Django Server Launcher
# ================================
# سكربت تلقائي لتشغيل الخادم مع عرض معلومات الجهاز و IP

Set-Location (Split-Path $MyInvocation.MyCommand.Path)
$ProjectPath = "..\lettersys_project"

# تفعيل البيئة الافتراضية
& "..\.venv\Scripts\Activate.ps1"

# الانتقال لمجلد المشروع
Set-Location $ProjectPath

# جمع معلومات الجهاز
Write-Host ""
Write-Host "═════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "📊 معلومات الجهاز والشبكة" -ForegroundColor Cyan
Write-Host "═════════════════════════════════════════════════════════" -ForegroundColor Cyan

$ComputerName = $env:COMPUTERNAME
$Username = $env:USERNAME
Write-Host "👤 اسم المستخدم: $Username" -ForegroundColor White
Write-Host "💻 اسم الجهاز: $ComputerName" -ForegroundColor White

$OS = (Get-WmiObject win32_operatingsystem).caption
Write-Host "🖥️  نظام التشغيل: $OS" -ForegroundColor White

$PythonVersion = python --version 2>&1
Write-Host "🐍 إصدار Python: $PythonVersion" -ForegroundColor White

Write-Host ""
Write-Host "═════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "🌐 عناوين IP المتاحة" -ForegroundColor Cyan
Write-Host "═════════════════════════════════════════════════════════" -ForegroundColor Cyan

$IPAddresses = @()
$NetworkAdapters = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue

foreach ($Adapter in $NetworkAdapters) {
    if ($Adapter.IPAddress -ne "127.0.0.1" -and $Adapter.IPAddress -ne "::1") {
        $IPAddresses += $Adapter.IPAddress
    }
}

$IPAddresses += "127.0.0.1"

foreach ($IP in $IPAddresses | Select-Object -Unique) {
    $Protocol = if ($IP -eq "127.0.0.1") { "🔒 Localhost" } else { "🌍 LAN/Network" }
    Write-Host "$Protocol : $IP" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "═════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "🚀 الروابط المتاحة للوصول إلى التطبيق" -ForegroundColor Cyan
Write-Host "═════════════════════════════════════════════════════════" -ForegroundColor Cyan

Write-Host ""
Write-Host "📌 تسجيل الدخول:" -ForegroundColor Magenta
foreach ($IP in $IPAddresses | Select-Object -Unique) {
    Write-Host "   http://$IP`:8000/login/ " -ForegroundColor Cyan
}

Write-Host ""
Write-Host "📌 لوحة التحكم:" -ForegroundColor Magenta
foreach ($IP in $IPAddresses | Select-Object -Unique) {
    Write-Host "   http://$IP`:8000/dashboard/ " -ForegroundColor Cyan
}

Write-Host ""
Write-Host "⏳ جاري تشغيل الخادم... (اضغط Ctrl+C لإيقاف)" -ForegroundColor Cyan
Write-Host ""

# تشغيل الخادم
& python manage.py runserver 0.0.0.0:8000
