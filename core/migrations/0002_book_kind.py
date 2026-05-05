from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='book',
            name='kind',
            field=models.CharField(default='incoming', max_length=10),
        ),
    ]

