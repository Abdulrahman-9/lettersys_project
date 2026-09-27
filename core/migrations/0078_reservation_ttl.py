# -*- coding: utf-8 -*-
"""مدّةُ حجز الرقم تصير بياناً، والعمودُ الموروثُ للكلمة يُوسَم مهجوراً.

عمليّتان على جدولَين ذَوَي **صفٍّ واحد** لكلٍّ منهما:

1. ``AddField`` على ``core_systemsettings``: عمودٌ NOT NULL بافتراضٍ ثابتٍ 45.
   على PostgreSQL ≥ 11 هذا تغييرُ ميتاداتا (fast default) بلا إعادةِ كتابةِ
   جدول. ``core_book`` وكلُّ الجداول الكبيرة لا تُقرأ ولا تُكتب. القيمةُ
   السارية فعلاً اليوم 45 وافتراضُ العمود 45 ⟵ الحالةُ محفوظةٌ بالبناء.
2. ``AlterField`` على ``core_networksettings.master_db_password``: تغييرُ
   ``help_text``/``editable`` فقط. الاثنان في ``Field.non_db_attrs`` فلا
   يُصدِر مُحرِّرُ المخطَّط أيَّ SQL — تغييرُ حالةٍ محض. (كان ``help_text``
   يقول «مشفّرة بـ django.core.signing»، وذلك **توقيعٌ لا تعمية**.)

لا ``RunPython`` ولا نقلَ بيانات: العمودُ الموروثُ **لا يُفرَّغ بالهجرة** بل
بالكود (``network_save_config`` يُصفّره في كلّ حفظ). إن أراد المالكُ محوَ
نسخةٍ قديمةٍ فوراً فذلك سطرُ SQL واحدٌ في نافذته، لا هجرةٌ غيرُ قابلةٍ للرجوع.

الرجوع: ``migrate core 0077`` — يحذف عمودَ المدّة ومعه قيمتَه (لا بيانات كتب)،
ويُعيد ``help_text`` القديم. أَجرِ الرجوعَ **وهذا الفرعُ ما زال مسحوباً**: بعد
حذف ملفّ الهجرة لا يستطيع Django عكسَها.

⚠️ **تضاربُ الرقم 0078 — مقصودٌ إبقاؤه ظاهراً.** الفرعُ غيرُ المدموج
``feat/encrypted-char-field`` يحمل ``0078_encrypted_char_field`` على الأب نفسِه
(``0077_archive_events_and_history``). دمجُ الفرعين معاً يُعطي **ورقتين** في
الرسم البيانيّ ⟵ ``migrate`` يرفض («Conflicting migrations detected»)، وإنشاءُ
قاعدةِ الاختبار يفشل فتسقط الحزمةُ كلُّها، و``db_healthcheck`` يرفعه عطباً
صارماً عبر ``loader.detect_conflicts()``، و``makemigrations --check`` يفشل.
الحلُّ عند الدمج: **تُرقَّم الأخرى 0079** باعتمادٍ على هذه — لأنّها
``SeparateDatabaseAndState(database_operations=[])`` فإعادةُ ترقيمها لا أثرَ لها
على أيّ قاعدة، أمّا هذه فتغييرُ مخطَّطٍ حقيقيّ: إعادةُ ترقيمها بعد تطبيقها
تُعيد تنفيذَ ``ADD COLUMN`` فتفشل بـ``DuplicateColumn``. ولا
``makemigrations --merge`` (يُبقي معيّناً ويُبدّل ``core_head``). وتُحدَّث
عبارةُ البوّابة في ``docs/FABLE_MEMO4_2026-09-13.md`` من 0078 إلى 0079.

**لم تُطبَّق على أيّ قاعدة، ولا تدخل بناءَ الانطلاق.** قرارُ المالك
(2026-09-24): خدمةُ الانطلاق تعمل على ``main@1c65a75`` حرفيّاً، وهذا الفرعُ
ينتظر القبول. ترتيبُ نافذة المالك حين تُطبَّق:

1. ``nssm stop LetterSys`` (أو إيقافُ الخادم) — لا كاتبَ على القاعدة.
2. نسخةٌ مُعمّاةٌ للقاعدة والإعداد. **لا يوجد أمرُ ``run_backup`` في الشجرة**
   (مقيسٌ 2026-09-27: ``core/management/commands/`` فيه ``db_healthcheck``
   و``models_healthcheck`` و``verify_backup`` لا غير)، والنسخةُ اليوم تُؤخَذ
   بدالّتَي ``core/backup_service.py`` مباشرةً::

       python manage.py shell -c "from core.backup_service import create_encrypted_pg_backup, create_encrypted_config_backup; print(create_encrypted_pg_backup()); print(create_encrypted_config_backup())"

   (``scheduled_backup`` لا يصلح هنا: يحترم ``BackupSettings.enabled`` وهو
   مُطفأٌ الآن فيتخطّى صامتاً.) ومتى شُحن أمرُ ``run_backup`` تُحدَّث هذه
   الخطوةُ وخطوةُ 6 إليه.
3. ``python manage.py verify_backup <الملفّ> --expect-live`` **قبل** الهجرة.
   الترتيبُ هذا ليس تفضيلاً: ``backup_verify.LIVE_COMPARED`` يشمل
   ``('django_migrations','core_head')``، فالمقارنةُ بعد الهجرة تجد في النسخة
   ``0077…`` وفي القاعدة ``0078…`` وتُخرج 2 (عدمُ تطابق) على نسخةٍ سليمة —
   بوّابةٌ حمراءُ كاذبةٌ تُعلِّم المالكَ تجاهُلَ البوّابات.
4. ``python manage.py migrate core 0078``.
5. ``python manage.py db_healthcheck`` — **حارسُ «القراءةِ فقط» ليس فيه بعد**
   (مقيسٌ 2026-09-27)؛ فحتّى يُشحن، يُتحقّق من القفل يدويّاً::

       python manage.py shell -c "from django.db import connection; c=connection.cursor(); c.execute('show default_transaction_read_only'); print(c.fetchone()[0])"

6. تشغيلُ الخدمة، ثمّ نسخةٌ ثانية إن أُريد ختمُ ما بعد الهجرة (بالأمر نفسِه في
   الخطوة 2 ثمّ ``verify_backup … --expect-live`` وقد صار الرأسان 0078 كلاهما).
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
        migrations.AlterField(
            model_name='networksettings',
            name='master_db_password_enc',
            field=models.CharField(blank=True, db_column='master_db_password', editable=False, help_text='عمودٌ موروثٌ مهجور — لا يُكتب ولا يُقرأ. لا تُخزَّن كلمةُ مرور قاعدةِ البيانات في القاعدة: إقلاعُ الاتّصال في ملفّ البيئة بيد مدير النظام.', max_length=500),
        ),
    ]
