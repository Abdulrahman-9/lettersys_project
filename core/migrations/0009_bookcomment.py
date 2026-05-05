# Generated migration for BookComment model
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('core', '0008_rename_password_userpassword_password_hash'),
    ]

    operations = [
        migrations.CreateModel(
            name='BookComment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('content', models.TextField(verbose_name='محتوى التعليق')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='تاريخ الإنشاء')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='تاريخ التعديل')),
                ('is_edited', models.BooleanField(default=False, verbose_name='تم التعديل')),
                ('book', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='comments', to='core.book', verbose_name='الكتاب')),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='book_comments', to=settings.AUTH_USER_MODEL, verbose_name='المستخدم')),
            ],
            options={
                'verbose_name': 'تعليق',
                'verbose_name_plural': 'التعليقات',
                'ordering': ['-created_at'],
            },
        ),
    ]
