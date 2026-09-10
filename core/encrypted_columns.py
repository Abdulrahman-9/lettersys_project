# -*- coding: utf-8 -*-
"""أعمدةُ الأسرار في القاعدة — مصدرٌ واحدٌ **يكتشفها من السجلّ** لا من قائمةٍ بيد.

**لماذا هذا الملفّ موجود** (Merge9 §8.6-ب): في 2026-09-08 أُنتج ملفُّ `dumpdata`
فكتب كلمتَي مرور البريد **صريحتين** بينما عمودُ القاعدة مشفَّرٌ سليمٌ ببادئة
``enc::`` — لأنّ ``EncryptedCharField.from_db_value`` يفكّ عند التحميل. والعطبُ
**صامت**: النظامُ يعمل بالصريح، فلا شيءَ يصرخ. ولا يُعيد ``loaddata`` تشفيرَه
(``raw=True`` يتخطّى ``save()``) فتستقرّ الكلمةُ صريحةً في القاعدة إلى الأبد.

فالحارسُ هنا يقرأ الخامَ من القاعدة **بـSQL لا بالـORM** — عمداً: أيُّ مرورٍ
عبر ``from_db`` يفكّ المشفَّرَ فيجعل الصريحَ والمشفَّرَ متشابهَين في الذاكرة،
وهو عينُ ما أخفى العطبَ أوّلَ مرّة.

**ولا شفاءَ ذاتيّاً**: لا يُعاد تشفيرُ الصفّ هنا ولا في مُستدعٍ. إعادةُ التشفير
تحتاج مفتاحاً، وسكُّ مفتاحٍ ثالثٍ صامتٍ على خادمٍ فقد مفتاحَه يُنتج بياناتٍ لا
يفكّها أحد. **الحارسُ يصرخ فقط.**

**ولا تُطبع قيمةٌ قطّ** — الاسمُ والعددُ فقط؛ السجلّاتُ تُقرأ وتُنسَخ.
"""
from __future__ import annotations

from collections import namedtuple

from django.db import DEFAULT_DB_ALIAS, connections

#: عمودٌ يجب أن يكون مشفَّراً: ``label`` نموذجُه · ``table``/``column`` في القاعدة
#: · ``field`` اسمُ الحقل في بايثون.
EncryptedColumn = namedtuple('EncryptedColumn', 'label table column field')


def encrypted_models():
    """النماذجُ التي تحمل ``EncryptedCharField`` — من سجلّ التطبيقات لا من قائمةٍ مكتوبة.

    قائمةٌ مكتوبةٌ بيدٍ تشيخ بصمتٍ عند إضافة نموذجٍ رابعٍ بأسرار؛ والسجلُّ لا يشيخ.
    """
    from django.apps import apps

    from core.fields import EncryptedCharField

    models = [
        model for model in apps.get_models()
        if any(isinstance(f, EncryptedCharField) for f in model._meta.get_fields()
               if hasattr(f, 'column'))
    ]
    return sorted(models, key=lambda m: m._meta.label_lower)


def encrypted_fields(model):
    """أسماءُ الحقول المشفَّرة في نموذج."""
    from core.fields import EncryptedCharField
    return tuple(f.name for f in model._meta.get_fields()
                 if hasattr(f, 'column') and isinstance(f, EncryptedCharField))


def encrypted_columns():
    """كلُّ (نموذج، جدول، عمود، حقل) مشفَّرٍ في المشروع."""
    columns = []
    for model in encrypted_models():
        for name in encrypted_fields(model):
            field = model._meta.get_field(name)
            columns.append(EncryptedColumn(
                label=model._meta.label_lower,
                table=model._meta.db_table,
                column=field.column,
                field=name,
            ))
    return tuple(columns)


def find_plaintext(using=DEFAULT_DB_ALIAS):
    """يُعيد ``[(EncryptedColumn, عددُ الصفوف), ...]`` لكلّ عمودٍ فيه نصٌّ صريح.

    الاستعلامُ هو نصُّ §8.6-ب حرفيّاً::

        count(*) WHERE col IS NOT NULL AND col <> '' AND col NOT LIKE 'enc::%'

    والجدولُ الغائبُ (قاعدةٌ قبل الهجرات) يُتخطّى: غيابُه عطبٌ آخرُ يصرخ في مكانه.
    """
    from core.encryption import ENCRYPTED_PREFIX

    connection = connections[using]
    quote = connection.ops.quote_name
    tables = set(connection.introspection.table_names())

    findings = []
    with connection.cursor() as cursor:
        for column in encrypted_columns():
            if column.table not in tables:
                continue
            name = quote(column.column)
            cursor.execute(
                f"SELECT COUNT(*) FROM {quote(column.table)} "
                f"WHERE {name} IS NOT NULL AND {name} <> '' AND {name} NOT LIKE %s",
                [ENCRYPTED_PREFIX + '%'],
            )
            rows = cursor.fetchone()[0]
            if rows:
                findings.append((column, rows))
    return findings


def plaintext_lines(findings):
    """أسطرُ تقريرٍ تُسمّي الجدولَ والعمودَ والعدد — **بلا قيمة**."""
    from core.encryption import ENCRYPTED_PREFIX

    return [
        f"{column.table}.{column.column} ({column.label}.{column.field}): "
        f"{rows} صفّاً بلا بادئة '{ENCRYPTED_PREFIX}' (نصٌّ صريح)"
        for column, rows in findings
    ]
