"""
restore_bak.py - يُشغَّل كعملية مستقلة في الخلفية
استعادة ARCHMDOC.bak إلى LocalDB ثم تصدير البيانات فور الاكتمال
"""
import pyodbc, time, json, os, sys
from pathlib import Path

PIPE    = r"np:\\.\pipe\LOCALDB#571D9B40\tsql\query"
BAK     = r"D:\Abdulrhman Backup\2026-05-03-14-09-01-قسم المتابعة.bak"
DB      = "ARCHMDOC_IMPORT"
OUT_DIR = Path(r"c:\Users\fwz\Downloads\lettersys_django_bootstrap_v4_scan\lettersys_django_bootstrap_v4_scan\lettersys_project\scripts\legacy_import\export")
OUT_DIR.mkdir(parents=True, exist_ok=True)
LOG     = OUT_DIR / "restore.log"

def log(msg):
    print(msg, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(msg + "\n")

def connect():
    return pyodbc.connect(
        f"DRIVER={{SQL Server}};SERVER={PIPE};Trusted_Connection=yes;",
        timeout=30
    )

# ── 1. استعادة قاعدة البيانات ─────────────────────────────────
log(f"[{time.strftime('%H:%M:%S')}] بدء الاستعادة...")

DATA_DIR = r"C:\Users\fwz\AppData\Local\Microsoft\Microsoft SQL Server Local DB\Instances\MSSQLLocalDB"
MDF = os.path.join(DATA_DIR, f"{DB}.mdf")
LDF = os.path.join(DATA_DIR, f"{DB}_log.ldf")

sql_restore = f"""
RESTORE DATABASE [{DB}]
FROM DISK = N'{BAK}'
WITH
    MOVE N'ARCHMDOC'     TO N'{MDF}',
    MOVE N'ARCHMDOC_log' TO N'{LDF}',
    REPLACE,
    RECOVERY,
    STATS = 5
"""

conn = connect()
conn.autocommit = True
cur = conn.cursor()
cur.execute(sql_restore)
while cur.nextset():
    pass
conn.close()
log(f"[{time.strftime('%H:%M:%S')}] اكتملت الاستعادة!")

# ── 2. انتظار حتى تكون ONLINE ────────────────────────────────
for _ in range(60):
    try:
        c = connect()
        c.cursor().execute(f"SELECT state_desc FROM sys.databases WHERE name='{DB}'")
        state = c.cursor().fetchone()
        c.close()
        if state and state[0] == "ONLINE":
            log("قاعدة البيانات ONLINE")
            break
    except:
        pass
    time.sleep(5)

# ── 3. استخراج قائمة الجداول والإحصائيات ────────────────────
log("استخراج بنية الجداول...")
conn = connect()
cur = conn.cursor()

cur.execute(f"USE [{DB}]")

# قائمة الجداول
cur.execute("""
    SELECT t.TABLE_NAME,
           COUNT(c.COLUMN_NAME) AS col_count
    FROM INFORMATION_SCHEMA.TABLES t
    JOIN INFORMATION_SCHEMA.COLUMNS c ON t.TABLE_NAME = c.TABLE_NAME
    WHERE t.TABLE_TYPE = 'BASE TABLE'
    GROUP BY t.TABLE_NAME
    ORDER BY t.TABLE_NAME
""")
tables = [(r[0], r[1]) for r in cur.fetchall()]
log(f"عدد الجداول: {len(tables)}")
with open(OUT_DIR / "tables_list.json", "w", encoding="utf-8") as f:
    json.dump([{"table": t, "columns": c} for t, c in tables], f, ensure_ascii=False, indent=2)

# بنية الأعمدة
cur.execute(f"""
    USE [{DB}];
    SELECT t.TABLE_NAME, c.COLUMN_NAME, c.DATA_TYPE,
           c.CHARACTER_MAXIMUM_LENGTH, c.IS_NULLABLE, c.ORDINAL_POSITION
    FROM INFORMATION_SCHEMA.TABLES t
    JOIN INFORMATION_SCHEMA.COLUMNS c ON t.TABLE_NAME = c.TABLE_NAME
    WHERE t.TABLE_TYPE = 'BASE TABLE'
    ORDER BY t.TABLE_NAME, c.ORDINAL_POSITION
""")
schema = [{"table": r[0], "column": r[1], "type": r[2],
           "max_len": r[3], "nullable": r[4], "pos": r[5]}
          for r in cur.fetchall()]
with open(OUT_DIR / "schema.json", "w", encoding="utf-8") as f:
    json.dump(schema, f, ensure_ascii=False, indent=2)
log(f"بنية الأعمدة محفوظة: {len(schema)} عمود")

# ── 4. إحصائيات عدد السجلات ─────────────────────────────────
log("إحصائيات عدد السجلات...")
counts = {}
for table, _ in tables:
    try:
        cur.execute(f"SELECT COUNT(*) FROM [{DB}].[dbo].[{table}]")
        counts[table] = cur.fetchone()[0]
    except Exception as e:
        counts[table] = f"ERROR: {e}"

with open(OUT_DIR / "row_counts.json", "w", encoding="utf-8") as f:
    json.dump(counts, f, ensure_ascii=False, indent=2)
log("إحصائيات السجلات:")
for t, c in sorted(counts.items(), key=lambda x: x[1] if isinstance(x[1], int) else 0, reverse=True):
    log(f"  {t}: {c}")

# ── 5. تصدير عينة (أول 200 سجل من كل جدول) ─────────────────
log("تصدير عينة البيانات...")
samples = {}
for table, _ in tables:
    try:
        cur.execute(f"SELECT TOP 200 * FROM [{DB}].[dbo].[{table}]")
        cols = [d[0] for d in cur.description]
        rows = []
        for row in cur.fetchall():
            record = {}
            for col, val in zip(cols, row):
                if hasattr(val, 'isoformat'):
                    record[col] = val.isoformat()
                elif isinstance(val, bytes):
                    record[col] = val.hex()
                else:
                    record[col] = val
            rows.append(record)
        samples[table] = rows
        log(f"  {table}: {len(rows)} سجل")
    except Exception as e:
        log(f"  {table}: ERROR - {e}")

with open(OUT_DIR / "sample_data.json", "w", encoding="utf-8") as f:
    json.dump(samples, f, ensure_ascii=False, indent=2, default=str)

log(f"\n[{time.strftime('%H:%M:%S')}] === اكتمل الاستخراج! ===")
log(f"الملفات في: {OUT_DIR}")
conn.close()
