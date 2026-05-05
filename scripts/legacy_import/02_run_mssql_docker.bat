@echo off
REM =============================================
REM تشغيل SQL Server في Docker واستعادة النسخة الاحتياطية
REM =============================================

echo [1/4] إيقاف أي حاوية قديمة...
docker stop mssql_legacy 2>nul
docker rm mssql_legacy 2>nul

echo [2/4] تشغيل SQL Server...
docker run -d --name mssql_legacy ^
  -e "ACCEPT_EULA=Y" ^
  -e "SA_PASSWORD=Legacy@Import2026!" ^
  -p 1433:1433 ^
  -v "D:\Abdulrhman Backup:/backup" ^
  mcr.microsoft.com/mssql/server:2019-latest

echo [3/4] انتظار بدء تشغيل SQL Server (30 ثانية)...
timeout /t 30 /nobreak

echo [4/4] تجهيز مجلد البيانات...
docker exec mssql_legacy mkdir -p /var/opt/mssql/data/export

echo تم! الآن شغل: python 03_restore_and_extract.py
