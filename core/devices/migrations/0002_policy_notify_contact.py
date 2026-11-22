from django.db import migrations, models


class Migration(migrations.Migration):
    """جهةُ التبليغ حين يتوقّف الخادم: حقلان فارغان افتراضيّاً، فلا يتغيّر شيءٌ لصفٍّ قائم."""

    dependencies = [
        ('devices', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='devicepolicy',
            name='notify_name',
            field=models.CharField(blank=True, max_length=80, verbose_name='من يُبلَّغ حين يتوقّف الخادم'),
        ),
        migrations.AddField(
            model_name='devicepolicy',
            name='notify_phone',
            field=models.CharField(blank=True, max_length=40, verbose_name='رقمُه الداخليّ أو هاتفه'),
        ),
    ]
