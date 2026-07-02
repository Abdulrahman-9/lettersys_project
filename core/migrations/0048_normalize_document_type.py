# -*- coding: utf-8 -*-
"""تطبيع Book.document_type المخزَّن ليوائم التطبيع الجديد في Book.save و_type_meta.

يُصلح تناقض «العدّاد يقول ≥1 والنتيجة 0» على القيم المستوردة/القديمة غير المطبَّعة
(مسافة داخلية مزدوجة/أطراف) التي تجاوزت BookForm.clean_document_type عبر legacy_restore أو Admin.
بعد هذه الهجرة: المخزَّن = المطبَّع = قيمة القائمة، فتبقى المطابقة الحرفية صحيحة.
"""
from django.db import migrations


def normalize_document_types(apps, schema_editor):
    from core.document_types import normalize_document_type_value
    Book = apps.get_model("core", "Book")
    # بثّ (iterator) لا تحميل كامل — احترام ذاكرة 8GB؛ تحديث الصفوف المتغيّرة فقط.
    qs = Book.objects.exclude(document_type="").values_list("pk", "document_type")
    for pk, dt in qs.iterator(chunk_size=2000):
        normalized = normalize_document_type_value(dt)
        if normalized != dt:
            Book.objects.filter(pk=pk).update(document_type=normalized)


def noop(apps, schema_editor):
    """عكسي بلا أثر — التطبيع لا يُفقد بيانات ولا يُعكَس (القيمة الأصلية غير محفوظة)."""


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0047_letterheadmemory"),
    ]

    operations = [
        migrations.RunPython(normalize_document_types, noop),
    ]
