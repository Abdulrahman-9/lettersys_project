"""
PostgreSQL 16 Downloader with Auto-Resume
سكربت تحميل PostgreSQL 16 مع استئناف تلقائي

الاستخدام:
  python download_postgresql.py

يستأنف تلقائياً من آخر نقطة توقف. شغّله عدة مرات حتى يكتمل.
بعد الانتهاء، شغّل الملف المحمّل لتثبيت PostgreSQL.
ثم نفّذ: activate_postgresql.bat
"""

import urllib.request, ssl, os, sys, time

URL = 'https://get.enterprisedb.com/postgresql/postgresql-16.13-2-windows-x64.exe'
DEST = os.path.join(os.environ['USERPROFILE'], 'Downloads', 'postgresql-16-installer.exe')
TOTAL_SIZE = 363544856  # 346.7 MB
MAX_RETRIES = 500  # عدد كبير — سيستمر حتى يكتمل

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

downloaded = os.path.getsize(DEST) if os.path.exists(DEST) else 0

if downloaded >= TOTAL_SIZE:
    print(f'✅ الملف مكتمل بالفعل: {DEST}')
    print(f'   الحجم: {downloaded / 1024 / 1024:.1f} MB')
    print(f'\n🔧 الخطوة التالية: شغّل الملف لتثبيت PostgreSQL')
    print(f'   ثم نفّذ: activate_postgresql.bat')
    sys.exit(0)

print(f'📥 تحميل PostgreSQL 16 ({TOTAL_SIZE / 1024 / 1024:.1f} MB)')
print(f'   المسار: {DEST}')
print(f'   المحمّل: {downloaded / 1024 / 1024:.1f} MB ({downloaded / TOTAL_SIZE * 100:.1f}%)')
print(f'   يستأنف تلقائياً عند انقطاع الاتصال...\n')

retry = 0
start_time = time.time()

while downloaded < TOTAL_SIZE and retry < MAX_RETRIES:
    try:
        req = urllib.request.Request(URL, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Range': f'bytes={downloaded}-'
        })
        resp = urllib.request.urlopen(req, context=ctx, timeout=120)

        with open(DEST, 'ab' if downloaded > 0 else 'wb') as f:
            while True:
                chunk = resp.read(131072)  # 128 KB
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                pct = downloaded / TOTAL_SIZE * 100
                elapsed = time.time() - start_time
                speed = downloaded / elapsed / 1024 if elapsed > 0 else 0
                sys.stdout.write(
                    f'\r  ⏳ {downloaded / 1024 / 1024:.1f} / {TOTAL_SIZE / 1024 / 1024:.1f} MB '
                    f'({pct:.1f}%) | {speed:.0f} KB/s'
                )
                sys.stdout.flush()
        resp.close()
    except Exception as e:
        retry += 1
        sys.stdout.write(f'\n  🔄 إعادة محاولة {retry}: {e}\n')
        sys.stdout.flush()
        time.sleep(3)

print()
if downloaded >= TOTAL_SIZE:
    print(f'✅ اكتمل التحميل! {os.path.getsize(DEST) / 1024 / 1024:.1f} MB')
    print(f'\n🔧 الخطوات التالية:')
    print(f'   1. شغّل: {DEST}')
    print(f'   2. ثبّت PostgreSQL (اترك Port = 5432)')
    print(f'   3. نفّذ: activate_postgresql.bat')
else:
    print(f'❌ توقف عند {downloaded / 1024 / 1024:.1f} MB بعد {retry} محاولة')
    print(f'   شغّل السكربت مرة أخرى لاستئناف التحميل')
