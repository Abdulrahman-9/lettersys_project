from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0018_seed_suggestions'),
    ]

    operations = [
        migrations.CreateModel(
            name='AIIntegrationSettings',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('singleton', models.BooleanField(default=True, unique=True)),
                ('enabled', models.BooleanField(default=False, help_text='تفعيل الربط بمزود أونلاين')),
                ('provider', models.CharField(choices=[('offline', 'Offline (EasyOCR)'), ('azure', 'Azure Computer Vision')], default='offline', max_length=20)),
                ('fallback_on_low_confidence', models.BooleanField(default=True, help_text='استخدم المزود الأونلاين تلقائياً عند انخفاض الثقة من المزود المحلي')),
                ('low_confidence_threshold', models.FloatField(default=0.4, help_text='الحد الأدنى للثقة (0-1)')),
                ('azure_endpoint', models.CharField(blank=True, help_text='مثال: https://<res>.cognitiveservices.azure.com', max_length=255)),
                ('azure_key', models.CharField(blank=True, max_length=255)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'إعدادات الذكاء الاصطناعي',
                'verbose_name_plural': 'إعدادات الذكاء الاصطناعي',
            },
        ),
    ]
