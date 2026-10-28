' LetterSys workstation setup - GUI launcher (double-click this file).
' Pure ASCII on purpose (wscript cannot read a UTF-8 BOM). User-visible Arabic text
' lives in setup_messages.txt (UTF-8), read with ADODB.Stream; config.json and the
' result file are read the same way. The installer worker (Setup.cmd) runs in a
' HIDDEN console with stdin already answered; its only output to this launcher is the
' structured %LOCALAPPDATA%\LetterSys\install_result.json (matched by run_id).
' No text in the log is ever parsed to decide success.
Option Explicit

Const RTL_FLAGS = 1572864   ' vbMsgBoxRight + vbMsgBoxRtlReading

Dim fso, sh, procEnv, pkgDir, msgs, testDialogFile, testDialogs, rtl
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
Set procEnv = sh.Environment("Process")
pkgDir = fso.GetParentFolderName(WScript.ScriptFullName)
testDialogFile = procEnv("LETTERSYS_SETUP_GUI_TEST_DIALOG_FILE")
testDialogs = ""
Set msgs = CreateObject("Scripting.Dictionary")
LoadMessages
rtl = 0
If msgs.Exists("title") Then
    If msgs("title") <> "LetterSys workstation setup" Then rtl = RTL_FLAGS
End If

Main

' ---------------------------------------------------------------- helpers
Function ReadUtf8(path)
    Dim st, t
    Set st = CreateObject("ADODB.Stream")
    st.Type = 2
    st.Charset = "utf-8"
    st.Open
    st.LoadFromFile path
    t = st.ReadText(-1)
    st.Close
    If Len(t) > 0 Then
        If AscW(Left(t, 1)) = &HFEFF Then t = Mid(t, 2)
    End If
    ReadUtf8 = t
End Function

Sub WriteUtf8(path, text)
    Dim st
    Set st = CreateObject("ADODB.Stream")
    st.Type = 2
    st.Charset = "utf-8"
    st.Open
    st.WriteText text
    st.SaveToFile path, 2
    st.Close
End Sub

Sub SetDefaults()
    msgs("title") = "LetterSys workstation setup"
    msgs("approve") = "This computer will be prepared for scanning for your account only (no administrator rights): trust the company server certificate, install the scan agent with autostart, copy the bundled NAPS2, and check the server and connected scanners (no paper is scanned).\n\nServer:\n{origin}\n\nContinue?"
    msgs("cancelled") = "Nothing was changed."
    msgs("bad_config") = "The package configuration (config.json) is missing or invalid. Ask the administrator for a new package."
    msgs("progress_text") = "Setting up... this can take a few minutes."
    msgs("elapsed") = "Elapsed: {seconds} s"
    msgs("ok_ready") = "Setup completed.\n\nConnected scanners:\n{devices}"
    msgs("no_device") = "The scan agent is installed and running, but no scanner was found. Turn the scanner on, connect it, install its TWAIN/WIA driver, then re-check from the device setup page."
    msgs("device_unknown") = "The scan agent is installed and running, but the scanner list could not be confirmed (this is not 'no scanner').\n\nDetails: {detail}"
    msgs("not_started") = "The agent was installed but not started (test mode)."
    msgs("server_ok") = "The server answered. The device setup page was opened."
    msgs("server_ok_no_browser") = "The server answered."
    msgs("server_down") = "The server is not reachable right now ({status}). It may simply not be ready yet.\nWhen it is available open:\n{url}"
    msgs("failed") = "Setup could not be completed (code {code}, stage {stage}).\n\n{message}\n{detail}\n\nLog: {log}\n\nOpen the log?"
    msgs("no_result") = "Setup could not be completed (code {code}) and no result file was written.\n\nLog: {log}\n\nOpen the log?"
    msgs("server_machine") = "This computer ({name}) is the LetterSys SERVER. This package is for employee computers only - copy it to an employee PC and run it there. Nothing was changed. (Scanning on the server itself is a separate IT task.)"
    msgs("elevated") = "Setup was started as administrator. Close it and double-click Setup.vbs normally from your own account. Nothing was changed."
End Sub

Sub LoadMessages()
    Dim p, t, lines, i, ln, k
    SetDefaults
    p = fso.BuildPath(pkgDir, "setup_messages.txt")
    If Not fso.FileExists(p) Then Exit Sub
    On Error Resume Next
    t = ReadUtf8(p)
    If Err.Number <> 0 Then
        Err.Clear
        On Error GoTo 0
        Exit Sub
    End If
    On Error GoTo 0
    lines = Split(Replace(t, vbCr, ""), vbLf)
    For i = 0 To UBound(lines)
        ln = lines(i)
        If Len(ln) > 0 And Left(ln, 1) <> "#" Then
            k = InStr(ln, "=")
            If k > 1 Then msgs(Trim(Left(ln, k - 1))) = Mid(ln, k + 1)
        End If
    Next
End Sub

Function M(key)
    Dim t
    t = ""
    If msgs.Exists(key) Then t = msgs(key)
    M = Replace(t, "\n", vbCrLf)
End Function

Function Ask(text, flags)
    If testDialogFile <> "" Then
        testDialogs = testDialogs & "[DIALOG flags=" & flags & "]" & vbCrLf & text & vbCrLf & "[/DIALOG]" & vbCrLf
        WriteUtf8 testDialogFile, testDialogs
        If (flags And 4) = 4 And LCase(procEnv("LETTERSYS_SETUP_GUI_TEST_ANSWER")) = "yes" And InStr(testDialogs, "[ANSWERED]") = 0 Then
            testDialogs = testDialogs & "[ANSWERED]" & vbCrLf
            Ask = vbYes
        Else
            Ask = vbNo
        End If
        Exit Function
    End If
    Ask = MsgBox(text, flags Or rtl, M("title"))
End Function

Function JsonUnescape(s)
    Dim r, out, i, c, n
    out = ""
    i = 1
    Do While i <= Len(s)
        c = Mid(s, i, 1)
        If c = "\" And i < Len(s) Then
            n = Mid(s, i + 1, 1)
            Select Case n
                Case "n": out = out & vbCrLf: i = i + 2
                Case "r": i = i + 2
                Case "t": out = out & " ": i = i + 2
                Case "u"
                    out = out & ChrW(CLng("&H" & Mid(s, i + 2, 4)))
                    i = i + 6
                Case Else
                    out = out & n: i = i + 2
            End Select
        Else
            out = out & c
            i = i + 1
        End If
    Loop
    JsonUnescape = out
End Function

' Top-level scalar from the flat JSON objects this package produces.
Function JsonGet(text, key)
    Dim re, mm
    Set re = New RegExp
    re.Pattern = """" & key & """\s*:\s*(""((?:[^""\\]|\\.)*)""|true|false|null|-?[0-9]+)"
    re.IgnoreCase = False
    Set mm = re.Execute(text)
    If mm.Count = 0 Then
        JsonGet = Null
    ElseIf Left(mm(0).SubMatches(0), 1) = """" Then
        JsonGet = JsonUnescape(mm(0).SubMatches(1))
    Else
        JsonGet = mm(0).SubMatches(0)
    End If
End Function

Function S(v)
    If IsNull(v) Then S = "" Else S = CStr(v)
End Function

Function RandomId()
    Dim i, t
    Randomize
    t = ""
    For i = 1 To 24
        t = t & Mid("0123456789abcdef", Int(Rnd * 16) + 1, 1)
    Next
    RandomId = t & Hex(Timer * 100)
End Function

Function IsElevated()
    If procEnv("LETTERSYS_INSTALL_ALLOW_ELEVATED") <> "" Then
        IsElevated = False
        Exit Function
    End If
    IsElevated = (sh.Run("%ComSpec% /d /c whoami /groups | findstr /c:""S-1-16-12288"" /c:""S-1-16-16384"" >nul", 0, True) = 0)
End Function

Sub StartProgressWindow(statusFile, doneFile)
    Dim stages, i, ps
    procEnv("LS_P_TITLE") = M("title")
    procEnv("LS_P_TEXT") = M("progress_text")
    procEnv("LS_P_ELAPSED") = M("elapsed")
    procEnv("LS_P_STATUS") = statusFile
    procEnv("LS_P_DONE") = doneFile
    stages = Array("validate", "cert", "server", "install", "naps2", "verify", "agent", "devices", "done")
    For i = 0 To UBound(stages)
        procEnv("LS_P_stage_" & stages(i)) = M("stage_" & stages(i))
    Next
    ' Inline command (no .ps1 file, so the machine's script policy is untouched).
    ' Not TopMost: the Windows root-certificate confirmation must stay visible above it.
    ps = "Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing; " & _
         "$f = New-Object Windows.Forms.Form; $f.Text = $env:LS_P_TITLE; $f.Width = 540; $f.Height = 200; " & _
         "$f.StartPosition = 'CenterScreen'; $f.ControlBox = $false; $f.FormBorderStyle = 'FixedDialog'; " & _
         "$f.RightToLeft = 'Yes'; $f.RightToLeftLayout = $true; " & _
         "$l = New-Object Windows.Forms.Label; $l.SetBounds(15, 12, 495, 40); $l.Text = $env:LS_P_TEXT; $f.Controls.Add($l); " & _
         "$s = New-Object Windows.Forms.Label; $s.SetBounds(15, 55, 495, 24); $f.Controls.Add($s); " & _
         "$b = New-Object Windows.Forms.ProgressBar; $b.SetBounds(15, 82, 495, 22); $b.Style = 'Marquee'; $b.MarqueeAnimationSpeed = 30; $f.Controls.Add($b); " & _
         "$e = New-Object Windows.Forms.Label; $e.SetBounds(15, 110, 495, 24); $f.Controls.Add($e); " & _
         "$t0 = Get-Date; $t = New-Object Windows.Forms.Timer; $t.Interval = 500; " & _
         "$t.Add_Tick({ if ((Test-Path -LiteralPath $env:LS_P_DONE) -or ((Get-Date) - $t0).TotalMinutes -gt 20) { $t.Stop(); $f.Close(); return }; " & _
         "try { $st = ([IO.File]::ReadAllText($env:LS_P_STATUS)).Trim(); $v = [Environment]::GetEnvironmentVariable('LS_P_stage_' + $st); if ($v) { $s.Text = $v } } catch {}; " & _
         "$e.Text = $env:LS_P_ELAPSED.Replace('{seconds}', [string][int]((Get-Date) - $t0).TotalSeconds) }); " & _
         "$t.Start(); [void]$f.ShowDialog()"
    sh.Run "powershell -NoProfile -WindowStyle Hidden -Command """ & ps & """", 0, False
End Sub

Sub Fail(text, code)
    Ask text, 16
    WScript.Quit code
End Sub

Sub Main()
    Dim cfgPath, cfg, origin, setupUrl, re, dataDir, logFile, resultFile, statusFile, doneFile
    Dim runId, rc, res, code, devStatus, srvStatus, text, icon, ans, srvName

    cfgPath = fso.BuildPath(pkgDir, "config.json")
    If Not fso.FileExists(cfgPath) Then Fail M("bad_config"), 2
    cfg = ReadUtf8(cfgPath)
    origin = S(JsonGet(cfg, "server_origin"))
    setupUrl = S(JsonGet(cfg, "device_setup_url"))
    Set re = New RegExp
    re.Pattern = "^https://[a-z0-9.-]+(:[0-9]{1,5})?$"
    re.IgnoreCase = False
    If Not re.Test(origin) Or setupUrl <> origin & "/books/device-setup/" Then Fail M("bad_config"), 2

    ' Novice mis-click guard (not a security control): the client package is never meant
    ' for the server computer itself. No override switch; server-side scanning is a
    ' separate IT action.
    If S(JsonGet(cfg, "package_role")) <> "client" Then Fail M("bad_config"), 2
    srvName = S(JsonGet(cfg, "server_machine_name"))
    If srvName = "" Then Fail M("bad_config"), 2
    If LCase(srvName) = LCase(sh.ExpandEnvironmentStrings("%COMPUTERNAME%")) Then Fail Replace(M("server_machine"), "{name}", srvName), 11

    If IsElevated() Then Fail M("elevated"), 6

    If Ask(Replace(M("approve"), "{origin}", origin), 4 + 32 + 256) <> vbYes Then
        Ask M("cancelled"), 64
        WScript.Quit 1
    End If

    dataDir = fso.BuildPath(sh.ExpandEnvironmentStrings("%LOCALAPPDATA%"), "LetterSys")
    If Not fso.FolderExists(dataDir) Then fso.CreateFolder dataDir
    logFile = fso.BuildPath(dataDir, "install_log.txt")
    resultFile = fso.BuildPath(dataDir, "install_result.json")
    statusFile = fso.BuildPath(dataDir, "install_status.txt")
    doneFile = fso.BuildPath(dataDir, "install_progress.done")
    If fso.FileExists(resultFile) Then fso.DeleteFile resultFile, True
    If fso.FileExists(doneFile) Then fso.DeleteFile doneFile, True

    runId = RandomId()
    procEnv("LETTERSYS_SETUP_AUTO_APPROVE") = "1"
    procEnv("LETTERSYS_SETUP_RUN_ID") = runId
    procEnv("LETTERSYS_SETUP_LOG") = logFile

    If testDialogFile = "" Then StartProgressWindow statusFile, doneFile
    rc = sh.Run("%ComSpec% /d /s /c """"" & fso.BuildPath(pkgDir, "Setup.cmd") & """ < nul > """ & logFile & """ 2>&1""", 0, True)
    fso.CreateTextFile(doneFile, True).Close

    If rc = 6 Then Fail M("elevated"), 6
    res = ""
    If fso.FileExists(resultFile) Then res = ReadUtf8(resultFile)
    If res = "" Or S(JsonGet(res, "run_id")) <> runId Then
        If Ask(Replace(Replace(M("no_result"), "{code}", rc), "{log}", logFile), 4 + 16) = vbYes Then sh.Run "notepad.exe """ & logFile & """", 1, False
        WScript.Quit IIf(rc = 0, 99, rc)
    End If

    code = CLng(S(JsonGet(res, "exit_code")))
    devStatus = S(JsonGet(res, "device_status"))
    srvStatus = S(JsonGet(res, "server_status"))
    If S(JsonGet(res, "agent_installed")) = "true" And (code = 0 Or code = 31 Or code = 32) And code = rc Then
        If devStatus = "ready" Then
            text = Replace(M("ok_ready"), "{devices}", S(JsonGet(res, "device_names_text")))
            icon = 64
        ElseIf devStatus = "no_device" Then
            text = M("no_device")
            icon = 48
        ElseIf devStatus = "not_checked" Then
            text = M("not_started")
            icon = 64
        Else
            text = Replace(M("device_unknown"), "{detail}", S(JsonGet(res, "device_detail")))
            icon = 48
        End If
        If srvStatus = "reachable" Then
            If S(JsonGet(res, "browser_opened")) = "true" Then
                text = text & vbCrLf & vbCrLf & M("server_ok")
            Else
                text = text & vbCrLf & vbCrLf & M("server_ok_no_browser")
            End If
        Else
            text = text & vbCrLf & vbCrLf & Replace(Replace(M("server_down"), "{status}", srvStatus), "{url}", setupUrl)
            icon = 48
        End If
        Ask text, icon
        WScript.Quit code
    End If

    text = Replace(M("failed"), "{code}", code)
    text = Replace(text, "{stage}", S(JsonGet(res, "stage")))
    text = Replace(text, "{message}", S(JsonGet(res, "message")))
    text = Replace(text, "{detail}", S(JsonGet(res, "detail")))
    text = Replace(text, "{log}", logFile)
    If Ask(text, 4 + 16) = vbYes Then sh.Run "notepad.exe """ & logFile & """", 1, False
    If code = 0 Then code = 98
    WScript.Quit code
End Sub

Function IIf(c, a, b)
    If c Then IIf = a Else IIf = b
End Function