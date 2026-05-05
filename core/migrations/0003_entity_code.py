from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0002_book_kind"),
    ]

    operations = [
        migrations.AddField(
            model_name="entity",
            name="code",
            field=models.CharField(
                blank=True, max_length=25, null=True, unique=True
            ),
        ),
    ]
