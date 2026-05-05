# P0-1: Convert IntegerField -> ForeignKey on DataExtractionResult.
# Simplified path: zero existing rows, so we drop+recreate columns safely.
# The new FK fields keep db_column equal to the original column names so all
# existing code that reads `instance.issuing_entity_id` keeps working unchanged.

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0027_phase3_set_null'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='dataextractionresult',
            name='issuing_entity_id',
        ),
        migrations.RemoveField(
            model_name='dataextractionresult',
            name='receiving_entity_id',
        ),
        migrations.AddField(
            model_name='dataextractionresult',
            name='issuing_entity',
            field=models.ForeignKey(
                blank=True,
                db_column='issuing_entity_id',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='+',
                to='core.entity',
            ),
        ),
        migrations.AddField(
            model_name='dataextractionresult',
            name='receiving_entity',
            field=models.ForeignKey(
                blank=True,
                db_column='receiving_entity_id',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='+',
                to='core.entity',
            ),
        ),
    ]
