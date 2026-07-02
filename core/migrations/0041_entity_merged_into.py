# إضافة Entity.merged_into — لدعم دمج الجهات المكرّرة (إزالة التكرار).
# مفصولة عمداً عن تغييرات النماذج الأخرى غير المهاجَرة (شبكة/إعدادات).

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0040_followup_kind_index'),
    ]

    operations = [
        migrations.AddField(
            model_name='entity',
            name='merged_into',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='merged_from', to='core.entity',
                verbose_name='مدموجة في',
                help_text='الجهة الأمّ التي استوعبت هذه الجهة عند إزالة التكرار',
            ),
        ),
    ]
