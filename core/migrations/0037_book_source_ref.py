# إضافة حقل source_ref لربط الكتاب بصفّه في قاعدة المصدر — يُمكّن الدمج/التحديث عند إعادة الاستعادة.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0036_booksequence_register_year'),
    ]

    operations = [
        migrations.AddField(
            model_name='book',
            name='source_ref',
            field=models.CharField(
                blank=True, default='', max_length=40, db_index=True,
                verbose_name='هوية المصدر',
                help_text='"{TABLE}#{ID}" في قاعدة المصدر — يربط الكتاب بصفّه الأصلي للدمج المستقبلي',
            ),
        ),
    ]
