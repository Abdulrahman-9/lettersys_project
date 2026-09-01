# -*- coding: utf-8 -*-
"""
مزامنة الـmigrations مع النماذج (كان makemigrations --check يفشل):

1) NetworkSettings.master_db_password → master_db_password_enc
   تغيير اسم الحقل في Python فقط؛ عمود قاعدة البيانات لم يتغيّر
   (db_column='master_db_password'، نفس max_length=500). لذا تُستخدم
   SeparateDatabaseAndState لتحديث حالة Django دون أي عملية على القاعدة
   — يحفظ كلمات المرور المشفّرة الموجودة (لا Remove+Add يُسقط العمود).

2) NetworkNode: استبدال UniqueConstraint(unique_network_node_endpoint)
   بـ unique_together على نفس الحقول (ip_address, app_port) — نفس الفهرس
   الفريد منطقياً، بلا فقدان بيانات.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0041_entity_merged_into'),
    ]

    operations = [
        # ── (2) NetworkNode: قيد فريد → unique_together على نفس الحقول ──
        migrations.RemoveConstraint(
            model_name='networknode',
            name='unique_network_node_endpoint',
        ),
        migrations.AlterUniqueTogether(
            name='networknode',
            unique_together={('ip_address', 'app_port')},
        ),

        # ── (1) NetworkSettings: إعادة تسمية في حالة Django فقط (العمود ثابت) ──
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveField(
                    model_name='networksettings',
                    name='master_db_password',
                ),
                migrations.AddField(
                    model_name='networksettings',
                    name='master_db_password_enc',
                    field=models.CharField(
                        blank=True,
                        db_column='master_db_password',
                        help_text='كلمة المرور مشفّرة بـ django.core.signing',
                        max_length=500,
                    ),
                ),
            ],
            database_operations=[],
        ),
    ]
