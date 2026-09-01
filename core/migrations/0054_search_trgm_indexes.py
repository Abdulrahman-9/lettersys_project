# -*- coding: utf-8 -*-
# كفاءة البحث: فهارس GIN pg_trgm على الأعمدة المبحوثة نصّياً/رقمياً.
# تُسرّع icontains + regex + TrigramSimilarity من مسحٍ كامل (O(n)) إلى بحث مفهرَس،
# فيبقى البحث سريعاً مع نموّ بيانات الجهة عبر السنين.
# محروسة لـPostgreSQL فقط (SQLite في الاختبارات يتجاهلها) — pg_trgm مُفعَّل منذ 0019.
from django.db import migrations

INDEXES = [
    ('book_title_trgm',         'title'),
    ('book_our_number_trgm',    'our_number'),
    ('book_sender_number_trgm', 'sender_number'),
    ('book_legacy_number_trgm', 'legacy_number'),
]


def create_indexes(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    with schema_editor.connection.cursor() as cur:
        for name, col in INDEXES:
            cur.execute(
                f'CREATE INDEX IF NOT EXISTS {name} '
                f'ON core_book USING gin ({col} gin_trgm_ops);'
            )


def drop_indexes(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    with schema_editor.connection.cursor() as cur:
        for name, _col in INDEXES:
            cur.execute(f'DROP INDEX IF EXISTS {name};')


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0053_alter_booksequence_year'),
    ]
    operations = [
        migrations.RunPython(create_indexes, drop_indexes),
    ]
