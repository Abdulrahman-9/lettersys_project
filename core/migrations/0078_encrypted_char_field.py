# Merge9 §8.6‑أ — نقلُ التشفير من ``save()`` إلى الحقل ``EncryptedCharField``.
#
# تغييرُ **حالةٍ** لا **قاعدة**: العمودُ varchar بالعرض نفسِه، والمحتوى ``enc::`` كما
# كان. فتُطبَّق بـ``SeparateDatabaseAndState`` بصفرِ عمليّةٍ على القاعدة — يضمن أن
# ``sqlmigrate`` يُخرج BEGIN/COMMIT فقط على كلّ المحرّكات (وSQLite لا يعيد بناءَ الجدول).
#
# ⚠️ تُدمَج بعد T‑0 حصراً: رأسُ الهجرة على الإنتاج بوّابةُ الترحيل (0077).

import core.fields
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0077_archive_events_and_history'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AlterField(
                    model_name='aiintegrationsettings',
                    name='azure_key',
                    field=core.fields.EncryptedCharField(blank=True, max_length=255),
                ),
                migrations.AlterField(
                    model_name='emailsettings',
                    name='imap_password',
                    field=core.fields.EncryptedCharField(blank=True, default='', help_text='تُخزَّن مشفرة', max_length=200, verbose_name='كلمة مرور IMAP'),
                ),
                migrations.AlterField(
                    model_name='emailsettings',
                    name='smtp_password',
                    field=core.fields.EncryptedCharField(blank=True, default='', help_text='تُخزَّن مشفرة', max_length=200, verbose_name='كلمة المرور'),
                ),
            ],
        ),
    ]
