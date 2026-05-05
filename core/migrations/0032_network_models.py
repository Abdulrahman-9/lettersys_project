"""
Migration: إضافة نماذج الربط الشبكي
  - NetworkSettings  (Singleton — إعدادات هذا الجهاز)
  - NetworkNode      (سجل الأجهزة المتصلة بالشبكة)
"""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0031_book_archived_issuing_names_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='NetworkSettings',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('role', models.CharField(
                    choices=[('standalone', 'مستقل'), ('master', 'ماستر (رئيسي)'), ('slave', 'تابع')],
                    default='standalone', max_length=20
                )),
                ('device_name', models.CharField(blank=True, help_text='اسم ودّي لهذا الجهاز', max_length=100)),
                ('this_host', models.GenericIPAddressField(blank=True, null=True, protocol='IPv4')),
                ('app_port', models.PositiveSmallIntegerField(default=8000)),
                ('master_host', models.CharField(blank=True, max_length=100)),
                ('master_db_port', models.PositiveSmallIntegerField(default=5432)),
                ('master_db_name', models.CharField(blank=True, default='lettersys', max_length=100)),
                ('master_db_user', models.CharField(blank=True, default='lettersys_user', max_length=100)),
                ('master_db_password', models.CharField(
                    blank=True, db_column='master_db_password', max_length=500,
                    help_text='كلمة المرور مشفّرة'
                )),
                ('is_configured', models.BooleanField(default=False)),
                ('configured_at', models.DateTimeField(blank=True, null=True)),
                ('configured_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='+',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'إعدادات الشبكة',
                'verbose_name_plural': 'إعدادات الشبكة',
            },
        ),
        migrations.CreateModel(
            name='NetworkNode',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('ip_address', models.GenericIPAddressField(protocol='IPv4')),
                ('app_port', models.PositiveSmallIntegerField(default=8000)),
                ('role', models.CharField(
                    choices=[('master', 'ماستر'), ('slave', 'تابع')],
                    default='slave', max_length=10
                )),
                ('is_online', models.BooleanField(db_index=True, default=False)),
                ('is_current', models.BooleanField(default=False, help_text='هذا هو الجهاز الذي تعمل عليه')),
                ('last_seen', models.DateTimeField(blank=True, null=True)),
                ('last_ping_ms', models.PositiveIntegerField(blank=True, null=True, help_text='زمن الاستجابة بالميلي ثانية')),
                ('app_version', models.CharField(blank=True, default='1.0', max_length=20)),
                ('registered_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'verbose_name': 'جهاز شبكي',
                'verbose_name_plural': 'أجهزة الشبكة',
                'ordering': ['-is_online', '-is_current', 'name'],
            },
        ),
        migrations.AddConstraint(
            model_name='networknode',
            constraint=models.UniqueConstraint(
                fields=['ip_address', 'app_port'],
                name='unique_network_node_endpoint',
            ),
        ),
    ]
