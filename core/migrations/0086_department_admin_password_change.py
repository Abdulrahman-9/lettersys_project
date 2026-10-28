from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0085_outgoing_external_sequence'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='must_change_password',
            field=models.BooleanField(
                default=False,
                verbose_name='تغيير كلمة المرور عند الدخول',
            ),
        ),
    ]
