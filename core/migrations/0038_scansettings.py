from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0037_book_source_ref'),
    ]

    operations = [
        migrations.CreateModel(
            name='ScanSettings',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('capture_exe_path', models.CharField(
                    blank=True, default='', max_length=500,
                    verbose_name='مسار CaptureOnTouch.exe',
                    help_text=r'مثال: C:\Program Files\Canon\CaptureOnTouch\CaptureOnTouch.exe',
                )),
                ('watch_folder', models.CharField(
                    blank=True, default='', max_length=500,
                    verbose_name='مجلد المسح الضوئي',
                    help_text='المجلد الذي يحفظ فيه CaptureOnTouch الملفات الممسوحة',
                )),
                ('auto_open_browser', models.BooleanField(
                    default=True,
                    verbose_name='فتح المتصفح تلقائياً بعد كل مسح',
                )),
                ('server_url', models.CharField(
                    default='http://localhost:8000', max_length=200,
                    verbose_name='عنوان الخادم المحلي',
                    help_text='يُستخدم لفتح صفحة الاستخراج بعد انتهاء المسح',
                )),
                ('window_topmost', models.BooleanField(
                    default=True,
                    verbose_name='نافذة CaptureOnTouch فوق التطبيق',
                    help_text='تُبقي نافذة المسح عائمة فوق المتصفح أثناء المسح',
                )),
                ('singleton', models.PositiveSmallIntegerField(default=1, editable=False, unique=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'إعدادات الماسح الضوئي',
                'verbose_name_plural': 'إعدادات الماسح الضوئي',
            },
        ),
    ]
