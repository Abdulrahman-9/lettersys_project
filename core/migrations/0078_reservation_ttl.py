# -*- coding: utf-8 -*-
"""مدّةُ حجز الرقم تصير بياناً — إضافةٌ فقط.

عمليّةٌ واحدة على ``core_systemsettings`` (صفٌّ واحد). لا حذفَ ولا تعديلَ نوعٍ
ولا ``RunPython``؛ ``core_book`` وكلُّ الجداول الكبيرة لا تُقرأ ولا تُكتب. على
PostgreSQL 16 إضافةُ عمود NOT NULL بافتراضٍ ثابتٍ تغييرُ ميتاداتا (fast default
منذ PG 11) بلا إعادةِ كتابةِ جدول. القيمةُ السارية فعلاً اليوم 45 وافتراضُ
العمود 45 ⟵ الحالةُ محفوظةٌ بالبناء.

الرجوع: ``migrate core 0077`` يحذف العمود ومعه قيمتَه (لا بيانات كتب).
تُطبَّق في نافذةِ المالك: إيقافُ الخدمة ⟵ ``run_backup --force`` ⟵ ``migrate``
⟵ ``verify_backup --expect-live`` ⟵ تشغيل.
"""

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0077_archive_events_and_history'),
    ]

    operations = [
        migrations.AddField(
            model_name='systemsettings',
            name='reservation_expire_minutes',
            field=models.PositiveSmallIntegerField(default=45, help_text='تُطبَّق فوراً على الحجوزات الجديدة؛ والحجوزاتُ القائمة تُكمل مدّتها القديمة لأنّ وقتَ الانتهاء يُبصَم لحظةَ الحجز.', validators=[django.core.validators.MinValueValidator(5), django.core.validators.MaxValueValidator(480)], verbose_name='مدة صلاحية حجز الرقم (دقيقة)'),
        ),
    ]
