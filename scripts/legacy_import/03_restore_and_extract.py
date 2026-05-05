"""
الخطوة 3: استعادة قاعدة البيانات وتصدير البيانات إلى JSON
يعمل بعد تشغيل 02_run_mssql_docker.bat
"""
import pymssql
import json
import time
import sys
from pathlib import Path
from datetime import datetime, date

OUTPUT_DIR = Path(__file__).parent / "extracted_data"
OUTPUT_DIR.mkdir(exist_ok=True)

CONN_PARAMS = {
    "server": "localhost",
    "port": 1433,
    "user": "sa",
    "password": "Legacy@Import2026!",
    "charset": "UTF-8",
}

# اسم الملف بداخل الـ container (ربطنا المجلد كـ /backup)
BAK_FILENAME = "2026-05-03-14-09-01-\u0642\u0633\u0645 \u0627\u0644\u0645\u062a\u0627\u0628\u0639\u0629.bak"
DB_NAME = "legacy_mataba3a"


def json_serial(obj):
    """تحويل أنواع Python غير قابلة للتسلسل إلى JSON."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, bytes):
        return obj.hex()
    raise TypeError(f"Type {type(obj)} not serializable")


def connect(db=None):
    params = {**CONN_PARAMS}
    if db:
        params["database"] = db
    for attempt in range(5):
        try:
            return pymssql.connect(**params)
        except Exception as e:
            print(f"  محاولة {attempt+1}/5 للاتصال... ({e})")
            time.sleep(5)
    raise RuntimeError("تعذر الاتصال بـ SQL Server بعد 5 محاولات")


def restore_database():
    print("\n" + "="*50)
    print("المرحلة 1: استعادة قاعدة البيانات")
    print("="*50)

    conn = connect()
    conn.autocommit(True)
    cursor = conn.cursor()

    # فحص ملف .bak لمعرفة أسماء الملفات المنطقية
    print("فحص محتوى ملف .bak...")
    try:
        cursor.execute(f"RESTORE FILELISTONLY FROM DISK = '/backup/{BAK_FILENAME}'")
        files = cursor.fetchall()
        print(f"  الملفات المنطقية في .bak:")
        logical_names = []
        for f in files:
            print(f"    {f[0]} → نوع: {f[2]}")
            logical_names.append((f[0], f[2]))  # (name, type: D/L)
    except Exception as e:
        print(f"  خطأ في فحص .bak: {e}")
        conn.close()
        return False

    # بناء أوامر MOVE ديناميكياً
    move_clauses = []
    for i, (name, ftype) in enumerate(logical_names):
        if ftype == 'D':
            move_clauses.append(f"MOVE N'{name}' TO N'/var/opt/mssql/data/{DB_NAME}.mdf'")
        elif ftype == 'L':
            move_clauses.append(f"MOVE N'{name}' TO N'/var/opt/mssql/data/{DB_NAME}_log.ldf'")

    move_sql = ",\n".join(move_clauses)
    restore_sql = f"""
    RESTORE DATABASE [{DB_NAME}]
    FROM DISK = '/backup/{BAK_FILENAME}'
    WITH
        {move_sql},
        REPLACE,
        RECOVERY,
        STATS = 10
    """

    print(f"\nاستعادة قاعدة البيانات '{DB_NAME}'...")
    print("(هذا قد يستغرق عدة دقائق للملفات الكبيرة)")
    try:
        cursor.execute(restore_sql)
        while cursor.nextset():
            pass
        print("  تمت الاستعادة بنجاح!")
    except Exception as e:
        print(f"  خطأ في الاستعادة: {e}")
        conn.close()
        return False

    conn.close()
    return True


def get_table_list():
    """الحصول على قائمة الجداول وإحصائياتها."""
    conn = connect(DB_NAME)
    cursor = conn.cursor(as_dict=True)

    cursor.execute("""
        SELECT
            t.TABLE_NAME,
            (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS c
             WHERE c.TABLE_NAME = t.TABLE_NAME
               AND c.TABLE_SCHEMA = t.TABLE_SCHEMA) AS col_count
        FROM INFORMATION_SCHEMA.TABLES t
        WHERE t.TABLE_TYPE = 'BASE TABLE'
        ORDER BY t.TABLE_NAME
    """)
    tables = cursor.fetchall()

    # عدد الصفوف لكل جدول
    result = []
    for t in tables:
        name = t['TABLE_NAME']
        try:
            cursor.execute(f"SELECT COUNT(*) AS cnt FROM [{name}]")
            row_count = cursor.fetchone()['cnt']
        except Exception:
            row_count = -1
        result.append({
            "table": name,
            "columns": t['col_count'],
            "rows": row_count
        })

    conn.close()
    return result


def export_table_sample(table_name, limit=200):
    """تصدير عينة من جدول معين."""
    conn = connect(DB_NAME)
    cursor = conn.cursor(as_dict=True)

    # الحصول على بنية الجدول
    cursor.execute(f"""
        SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME = '{table_name}'
        ORDER BY ORDINAL_POSITION
    """)
    schema = cursor.fetchall()

    # تصدير السجلات
    try:
        cursor.execute(f"SELECT TOP {limit} * FROM [{table_name}]")
        rows = cursor.fetchall()
    except Exception as e:
        print(f"    خطأ في تصدير {table_name}: {e}")
        conn.close()
        return None

    conn.close()
    return {
        "table": table_name,
        "schema": schema,
        "sample_rows": rows,
        "sample_size": len(rows)
    }


def main():
    print("\n" + "="*60)
    print("  أداة استخراج البيانات من قاعدة البيانات القديمة")
    print("="*60)

    # الخطوة 1: استعادة قاعدة البيانات
    if "--skip-restore" not in sys.argv:
        success = restore_database()
        if not success:
            print("\nفشل استعادة قاعدة البيانات. استخدم --skip-restore إذا كانت مستعادة مسبقاً.")
            return
    else:
        print("\n(تخطي الاستعادة — قاعدة البيانات موجودة مسبقاً)")

    # الخطوة 2: قائمة الجداول
    print("\n" + "="*50)
    print("المرحلة 2: فحص الجداول")
    print("="*50)

    tables = get_table_list()
    print(f"\nعدد الجداول: {len(tables)}")
    print(f"\n{'الجدول':<40} {'أعمدة':<8} {'صفوف':<12}")
    print("-" * 60)
    for t in sorted(tables, key=lambda x: x['rows'], reverse=True):
        print(f"{t['table']:<40} {t['columns']:<8} {t['rows']:,}")

    # حفظ قائمة الجداول
    with open(OUTPUT_DIR / "01_tables_inventory.json", "w", encoding="utf-8") as f:
        json.dump(tables, f, ensure_ascii=False, indent=2, default=json_serial)
    print(f"\nحُفظت في: {OUTPUT_DIR}/01_tables_inventory.json")

    # الخطوة 3: تصدير عينة من كل جدول
    print("\n" + "="*50)
    print("المرحلة 3: تصدير عينات البيانات")
    print("="*50)

    all_samples = {}
    for t in tables:
        name = t['table']
        if t['rows'] == 0:
            print(f"  ⊘ تخطي {name} (فارغ)")
            continue
        print(f"  → تصدير {name} ({t['rows']:,} صف)...")
        sample = export_table_sample(name, limit=100)
        if sample:
            all_samples[name] = sample
            # حفظ كل جدول منفرداً
            table_file = OUTPUT_DIR / f"table_{name}.json"
            with open(table_file, "w", encoding="utf-8") as f:
                json.dump(sample, f, ensure_ascii=False, indent=2, default=json_serial)
            print(f"    ✓ {len(sample['sample_rows'])} سجل → {table_file.name}")

    # الخطوة 4: ملخص شامل
    print("\n" + "="*50)
    print("المرحلة 4: تقرير التحليل الأولي")
    print("="*50)

    summary = {
        "extraction_date": datetime.now().isoformat(),
        "source_file": BAK_FILENAME,
        "database_name": DB_NAME,
        "total_tables": len(tables),
        "tables_with_data": len(all_samples),
        "tables": tables,
    }
    with open(OUTPUT_DIR / "00_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=json_serial)

    print(f"\nاكتمل الاستخراج!")
    print(f"الملفات محفوظة في: {OUTPUT_DIR}/")
    print(f"\nالخطوة التالية: شغّل  python 04_analyze_and_map.py")


if __name__ == "__main__":
    main()
