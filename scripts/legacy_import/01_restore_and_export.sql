-- =============================================
-- الخطوة 1: استعادة قاعدة البيانات القديمة
-- =============================================

-- فحص محتوى ملف .bak أولاً
RESTORE FILELISTONLY
FROM DISK = '/backup/legacy.bak';

-- استعادة قاعدة البيانات
RESTORE DATABASE [legacy_db]
FROM DISK = '/backup/legacy.bak'
WITH MOVE (SELECT logical_name FROM ...) TO '/var/opt/mssql/data/legacy_db.mdf',
     REPLACE,
     RECOVERY,
     STATS = 10;

-- =============================================
-- الخطوة 2: فحص الجداول الموجودة
-- =============================================
USE [legacy_db];

SELECT
    t.TABLE_NAME,
    COUNT(c.COLUMN_NAME) AS col_count,
    (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS c2
     WHERE c2.TABLE_NAME = t.TABLE_NAME) AS columns
FROM INFORMATION_SCHEMA.TABLES t
JOIN INFORMATION_SCHEMA.COLUMNS c ON t.TABLE_NAME = c.TABLE_NAME
WHERE t.TABLE_TYPE = 'BASE TABLE'
GROUP BY t.TABLE_NAME
ORDER BY t.TABLE_NAME;
