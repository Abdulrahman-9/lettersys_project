# -*- coding: utf-8 -*-
"""فهرس مركّب (is_archived, due_date, kind) لتسريع الاستعلامات الكبيرة."""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0039_unify_followup_logic'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='book',
            index=models.Index(
                fields=['is_archived', 'due_date', 'kind'],
                name='followup_kind_idx',
            ),
        ),
    ]
