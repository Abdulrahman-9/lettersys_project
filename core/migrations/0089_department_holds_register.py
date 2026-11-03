# -*- coding: utf-8 -*-
"""الوحدةُ غيرُ السجلّ، ومجموعةُ موظّف التنفيذ (قرارُ المالك 2026‑11‑02).

البذرُ محافظ: لا يُسقط السجلَّ إلّا عن شعبةٍ أو وحدةٍ تحت أبٍ **لا كتبَ فيها ولا عدّادَ
استُعمل** — في الإنتاج ستُّ وحدات: ش.ت · و.ت · و.ت.ش · و.م · و.م.ب · و.ش.ت. والقاعدةُ
مجمَّدةٌ هنا عمداً: الهجرةُ لا تتبع تغيّرَ ``Department.default_holds_register`` لاحقاً.
"""
from django.db import migrations, models

NO_REGISTER_WORDS = ('شعبة', 'وحدة')
EXECUTOR_GROUP_NAME = 'موظّف التنفيذ'


def seed(apps, schema_editor):
    Department = apps.get_model('core', 'Department')
    Book = apps.get_model('core', 'Book')
    BookSequence = apps.get_model('core', 'BookSequence')
    Group = apps.get_model('auth', 'Group')

    Group.objects.get_or_create(name=EXECUTOR_GROUP_NAME)
    for department in Department.objects.exclude(parent=None):
        first = ((department.name or '').split() or [''])[0]
        if (first in NO_REGISTER_WORDS
                and not Book.objects.filter(department=department).exists()
                and not BookSequence.objects.filter(department=department, next_number__gt=1).exists()):
            department.holds_register = False
            department.save(update_fields=['holds_register'])


class Migration(migrations.Migration):

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
        ('core', '0088_useractivitylog_admin_actions'),
    ]

    operations = [
        migrations.AddField(
            model_name='department',
            name='holds_register',
            field=models.BooleanField(
                default=True, help_text='له ديوانُ بريدٍ وعدّادُ أرقامٍ ويُدخل الكتب.',
                verbose_name='يمسك سجلّاً'),
        ),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
