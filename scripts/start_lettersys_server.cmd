@echo off
rem ==========================================================
rem  LetterSys dev server — يعمل عبر «مجدول مهام Windows»
rem  (مهمّة LetterSysServer) مستقلاً عن أي جلسة طرفية،
rem  وحلقة إعادة التشغيل تعيده تلقائياً إن انهار.
rem  الإيقاف:  schtasks /End /TN LetterSysServer
rem  التشغيل:  schtasks /Run /TN LetterSysServer
rem ==========================================================
cd /d "C:\Users\fwz\Downloads\lettersys_django_bootstrap_v4_scan\lettersys_django_bootstrap_v4_scan\lettersys_project"
set PYTHONIOENCODING=utf-8
:loop
"C:\Users\fwz\AppData\Local\Programs\Python\Python311\python.exe" manage.py runserver 127.0.0.1:8000 --noreload >> logs\server_task.log 2>&1
rem انهار أو أُوقف؟ انتظر 5 ثوانٍ ثم أعد التشغيل (يمنع الدوران السريع)
timeout /t 5 /nobreak >nul
goto loop
