
# Scan-Book.ps1 — سحب من السكنر وحفظ في scan_inbox (يتطلب Windows Image Acquisition)
# التشغيل: كليك يمين > Run with PowerShell
Add-Type -AssemblyName System.Windows.Forms

# حدد مسار المشروع تلقائياً إذا كان السكربت داخل tools/
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$Inbox = Join-Path $ProjectRoot "scan_inbox"
if (!(Test-Path $Inbox)) { New-Item -ItemType Directory -Path $Inbox | Out-Null }

# اختيار اسم الملف
$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$OutFile = Join-Path $Inbox ("scan_" + $ts + ".jpg")

# كائن WIA
$wia = New-Object -ComObject WIA.CommonDialog
try {
    $device = $wia.ShowSelectDevice()
    if ($null -eq $device) { Write-Host "تم الإلغاء." ; exit }
    $item = $device.Items | Select-Object -First 1
    $image = $wia.ShowAcquireImage("Flatbed", "Color", "Item", "{B96B3CAB-0728-11D3-9D7B-0000F81EF32E}", $false, $true, $false)
    $image.SaveFile($OutFile)
    [System.Windows.Forms.MessageBox]::Show("تم الحفظ: `n$OutFile","Scan OK")
} catch {
    [System.Windows.Forms.MessageBox]::Show("خطأ: " + $_.Exception.Message, "Scan Error")
}
