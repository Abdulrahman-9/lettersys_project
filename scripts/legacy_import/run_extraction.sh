#!/bin/bash
# ============================================================
# سكريبت استخراج بيانات النظام القديم من ملف .bak
# يعمل داخل Docker Container - SQL Server 2019
# ============================================================

SA_PASSWORD="LetterSys@Import2026"
BAK_FILE="/backup/legacy.bak"
DB_NAME="legacy_db"
EXPORT_DIR="/export"

echo "======================================="
echo " بدء استعادة قاعدة البيانات القديمة"
echo "======================================="

# انتظار حتى يكون SQL Server جاهزاً
echo "انتظار تشغيل SQL Server..."
for i in {1..30}; do
    /opt/mssql-tools18/bin/sqlcmd -S localhost -U SA -P "$SA_PASSWORD" \
        -No -Q "SELECT 1" > /dev/null 2>&1 && break
    sleep 2
    echo "  محاولة $i/30..."
done

echo ""
echo "--- الخطوة 1: فحص محتوى ملف .bak ---"
/opt/mssql-tools18/bin/sqlcmd -S localhost -U SA -P "$SA_PASSWORD" -No \
    -Q "RESTORE FILELISTONLY FROM DISK = '$BAK_FILE'" \
    2>&1 | tee /export/filelist.txt

echo ""
echo "--- الخطوة 2: استعادة قاعدة البيانات ---"
# استخراج المسارات اللوجيكية من الخطوة السابقة ثم استعادة
/opt/mssql-tools18/bin/sqlcmd -S localhost -U SA -P "$SA_PASSWORD" -No \
    -Q "
DECLARE @sql NVARCHAR(MAX);
DECLARE @files TABLE (LogicalName NVARCHAR(128), PhysicalName NVARCHAR(260), Type CHAR(1), FileGroupName NVARCHAR(128), Size BIGINT, MaxSize BIGINT, FileId INT, CreateLSN NUMERIC, DropLSN NUMERIC, UniqueId UNIQUEIDENTIFIER, ReadOnlyLSN NUMERIC, ReadWriteLSN NUMERIC, BackupSizeInBytes BIGINT, SourceBlockSize INT, FileGroupId INT, LogGroupGUID UNIQUEIDENTIFIER, DifferentialBaseLSN NUMERIC, DifferentialBaseGUID UNIQUEIDENTIFIER, IsReadOnly BIT, IsPresent BIT, TDEThumbprint VARBINARY(32), SnapshotUrl NVARCHAR(360));

INSERT INTO @files
EXEC('RESTORE FILELISTONLY FROM DISK = ''$BAK_FILE''');

SELECT LogicalName, Type FROM @files;
" 2>&1

/opt/mssql-tools18/bin/sqlcmd -S localhost -U SA -P "$SA_PASSWORD" -No \
    -Q "
RESTORE DATABASE [$DB_NAME]
FROM DISK = '$BAK_FILE'
WITH REPLACE, RECOVERY, STATS = 10;
" 2>&1

echo ""
echo "--- الخطوة 3: استكشاف الجداول ---"
/opt/mssql-tools18/bin/sqlcmd -S localhost -U SA -P "$SA_PASSWORD" -No \
    -d "$DB_NAME" \
    -Q "
SET NOCOUNT ON;
SELECT
    t.TABLE_SCHEMA + '.' + t.TABLE_NAME AS table_name,
    (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS c
     WHERE c.TABLE_NAME = t.TABLE_NAME) AS col_count
FROM INFORMATION_SCHEMA.TABLES t
WHERE t.TABLE_TYPE = 'BASE TABLE'
ORDER BY t.TABLE_NAME;
" 2>&1 | tee /export/tables_list.txt

echo ""
echo "--- الخطوة 4: تصدير بنية كل جدول ---"
/opt/mssql-tools18/bin/sqlcmd -S localhost -U SA -P "$SA_PASSWORD" -No \
    -d "$DB_NAME" \
    -Q "
SELECT
    t.TABLE_NAME,
    c.COLUMN_NAME,
    c.DATA_TYPE,
    c.CHARACTER_MAXIMUM_LENGTH,
    c.IS_NULLABLE
FROM INFORMATION_SCHEMA.TABLES t
JOIN INFORMATION_SCHEMA.COLUMNS c ON t.TABLE_NAME = c.TABLE_NAME
WHERE t.TABLE_TYPE = 'BASE TABLE'
ORDER BY t.TABLE_NAME, c.ORDINAL_POSITION;
" -o /export/schema.txt 2>&1

echo ""
echo "--- الخطوة 5: تصدير عينة JSON لكل جدول ---"
/opt/mssql-tools18/bin/sqlcmd -S localhost -U SA -P "$SA_PASSWORD" -No \
    -d "$DB_NAME" \
    -Q "
DECLARE @table_name NVARCHAR(128);
DECLARE @sql NVARCHAR(MAX);

DECLARE tbl_cursor CURSOR FOR
    SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES
    WHERE TABLE_TYPE = 'BASE TABLE'
    ORDER BY TABLE_NAME;

OPEN tbl_cursor;
FETCH NEXT FROM tbl_cursor INTO @table_name;

WHILE @@FETCH_STATUS = 0
BEGIN
    SET @sql = N'SELECT TOP 200 * FROM [' + @table_name + N'] FOR JSON AUTO';
    PRINT '=== TABLE: ' + @table_name + ' ===';
    EXEC sp_executesql @sql;
    FETCH NEXT FROM tbl_cursor INTO @table_name;
END

CLOSE tbl_cursor;
DEALLOCATE tbl_cursor;
" -o /export/sample_data.json 2>&1

echo ""
echo "--- الخطوة 6: إحصائيات البيانات ---"
/opt/mssql-tools18/bin/sqlcmd -S localhost -U SA -P "$SA_PASSWORD" -No \
    -d "$DB_NAME" \
    -Q "
DECLARE @table_name NVARCHAR(128);
DECLARE @sql NVARCHAR(MAX);
CREATE TABLE #counts (tbl NVARCHAR(128), cnt BIGINT);

DECLARE tbl_cursor CURSOR FOR
    SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = 'BASE TABLE';

OPEN tbl_cursor;
FETCH NEXT FROM tbl_cursor INTO @table_name;
WHILE @@FETCH_STATUS = 0
BEGIN
    SET @sql = 'INSERT INTO #counts SELECT ''' + @table_name + ''', COUNT(*) FROM [' + @table_name + ']';
    EXEC sp_executesql @sql;
    FETCH NEXT FROM tbl_cursor INTO @table_name;
END
CLOSE tbl_cursor;
DEALLOCATE tbl_cursor;

SELECT tbl AS [الجدول], cnt AS [عدد_السجلات]
FROM #counts ORDER BY cnt DESC;
DROP TABLE #counts;
" -o /export/row_counts.txt 2>&1

echo ""
echo "======================================="
echo " اكتمل الاستخراج! الملفات في /export:"
ls -lh /export/
echo "======================================="
