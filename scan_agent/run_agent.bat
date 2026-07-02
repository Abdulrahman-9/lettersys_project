@echo off
REM تشغيل وكيل المسح صامتاً (بلا نافذة console) عبر pythonw من venv المشروع.
REM ضعه في مجلد بدء التشغيل (shell:startup) ليعمل تلقائياً مع ويندوز.
cd /d "%~dp0.."
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" -m scan_agent
) else (
    start "" pythonw -m scan_agent
)
