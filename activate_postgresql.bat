@echo off
chcp 65001 >nul
echo ╔═══════════════════════════════════════════════════╗
echo ║    تفعيل PostgreSQL + البحث النصي الكامل         ║
echo ║    PostgreSQL + Full-Text Search Activation       ║
echo ╚═══════════════════════════════════════════════════╝
echo.

REM --- Check if PostgreSQL is installed ---
where psql >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo ❌ PostgreSQL غير مثبت!
    echo.
    echo 📥 حمّل PostgreSQL 16 من الرابط التالي:
    echo    https://www.postgresql.org/download/windows/
    echo.
    echo    أو مباشرة:
    echo    https://get.enterprisedb.com/postgresql/postgresql-16.8-1-windows-x64.exe
    echo.
    echo 🔧 أثناء التثبيت:
    echo    - اترك Port = 5432
    echo    - اختر كلمة مرور لـ postgres (تذكرها)
    echo    - فعّل "Stack Builder" لتثبيت الأدوات الإضافية
    echo.
    echo بعد التثبيت، أعد تشغيل هذا السكربت.
    pause
    exit /b 1
)

echo ✅ PostgreSQL موجود:
psql --version
echo.

REM --- Create database and user ---
echo 🔧 إنشاء قاعدة البيانات والمستخدم...
set PGPASSWORD=postgres

psql -U postgres -c "CREATE DATABASE lettersys ENCODING 'UTF8' TEMPLATE template0;" 2>nul
psql -U postgres -c "CREATE USER lettersys_user WITH PASSWORD 'lettersys_pass';" 2>nul
psql -U postgres -c "ALTER ROLE lettersys_user SET client_encoding TO 'utf8';"
psql -U postgres -c "ALTER ROLE lettersys_user SET default_transaction_isolation TO 'read committed';"
psql -U postgres -c "ALTER ROLE lettersys_user SET timezone TO 'Asia/Baghdad';"
psql -U postgres -c "GRANT ALL PRIVILEGES ON DATABASE lettersys TO lettersys_user;"
psql -U postgres -d lettersys -c "GRANT ALL ON SCHEMA public TO lettersys_user;"

echo.
echo ✅ تم إنشاء قاعدة البيانات

REM --- Run Django migrations ---
echo.
echo 🔧 تطبيق الهجرات...
set DB_NAME=lettersys
set DB_USER=lettersys_user
set DB_PASSWORD=lettersys_pass
set DB_HOST=localhost
set DB_PORT=5432
set PYTHONUTF8=1
.venv\Scripts\python.exe manage.py migrate

REM --- Import data ---
echo.
echo 📦 استيراد البيانات...
.venv\Scripts\python.exe manage.py loaddata data_backup.json

echo.
echo ✅ تم الترحيل بنجاح!
echo.
echo لتشغيل السيرفر:
echo   python manage.py runserver
echo.
pause
