# -*- coding: utf-8 -*-
"""
PostgreSQL Full-Text Search & Trigram Extensions
- تفعيل pg_trgm لـ TrigramSimilarity (بحث ضبابي سريع)
- إنشاء فهارس GIN على حقول البحث الرئيسية
- آمن: يُنفّذ فقط على PostgreSQL.
"""

from django.db import migrations


def noop(apps, schema_editor):
    """No-op for reverse on non-PostgreSQL backends."""
    pass


def pg_only_forward(sql_statements):
    """Return a RunPython operation that only executes SQL on PostgreSQL."""
    def forward_func(apps, schema_editor):
        if schema_editor.connection.vendor != 'postgresql':
            return
        with schema_editor.connection.cursor() as cursor:
            for stmt in sql_statements:
                cursor.execute(stmt)
    return forward_func


class Migration(migrations.Migration):

    dependencies = [
        # Merge both migration chains
        ('core', '0018_seed_suggestions'),
        ('core', '0016_data_migrate_book_fields'),
    ]

    operations = [
        migrations.RunPython(
            pg_only_forward([
                "CREATE EXTENSION IF NOT EXISTS pg_trgm;",
                "CREATE INDEX IF NOT EXISTS book_title_trgm_idx ON core_book USING gin (title gin_trgm_ops);",
                "CREATE INDEX IF NOT EXISTS entity_name_trgm_idx ON core_entity USING gin (name gin_trgm_ops);",
                "CREATE INDEX IF NOT EXISTS entity_code_trgm_idx ON core_entity USING gin (code gin_trgm_ops) WHERE code IS NOT NULL;",
                """CREATE INDEX IF NOT EXISTS book_fts_idx ON core_book USING gin (
                    to_tsvector('simple',
                        coalesce(our_number, '') || ' ' ||
                        coalesce(sender_number, '') || ' ' ||
                        coalesce(book_number, '') || ' ' ||
                        coalesce(title, '') || ' ' ||
                        coalesce(margin, '')
                    )
                );""",
            ]),
            reverse_code=noop,
        ),
    ]
