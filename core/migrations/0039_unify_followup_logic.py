# -*- coding: utf-8 -*-
"""
توحيد منطق المتابعة:
  - حذف الحقول المكرّرة: needs_followup, is_overdue, final_status
  - إضافة حقل is_archived (افتراضي True)
  - ترحيل البيانات: done/hold/archived → is_archived=True ، pending → is_archived=False
  - تحديث الفهارس
"""
from django.db import migrations, models


def migrate_followup_data(apps, schema_editor):
    """ترحيل قيم final_status القديمة إلى is_archived الجديد + ضمان due_date للنشط."""
    Book = apps.get_model('core', 'Book')

    # done + hold + archived → مؤرشف (انتهت متابعته)
    Book.objects.filter(final_status__in=['done', 'hold', 'archived']).update(is_archived=True)

    # pending → نشط (قيد المتابعة) — لكن فقط إذا كان لديه due_date
    Book.objects.filter(final_status='pending', due_date__isnull=False).update(is_archived=False)

    # pending بلا due_date → مؤرشف (لا متابعة فعلية)
    Book.objects.filter(final_status='pending', due_date__isnull=True).update(is_archived=True)

    # القيم الشاذة 'today deserves' / 'late' غير المستخدمة فعلياً
    Book.objects.exclude(final_status__in=['done', 'hold', 'archived', 'pending']).update(is_archived=True)


def reverse_followup_data(apps, schema_editor):
    """عكس الترحيل (لو احتجنا rollback) — يستعيد final_status من is_archived."""
    Book = apps.get_model('core', 'Book')
    # is_archived=False ⇒ pending  ، True ⇒ archived
    Book.objects.filter(is_archived=False).update(final_status='pending')
    Book.objects.filter(is_archived=True).update(final_status='archived')


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0038_scansettings'),
    ]

    operations = [
        # 1) أضف is_archived (default=True فيُعتبر الجميع مؤرشفاً ابتداءً)
        migrations.AddField(
            model_name='book',
            name='is_archived',
            field=models.BooleanField(default=True, verbose_name='مؤرشف'),
        ),

        # 2) رحّل البيانات
        migrations.RunPython(migrate_followup_data, reverse_followup_data),

        # 3) أزل الفهارس القديمة (التي تعتمد على final_status / needs_followup / is_overdue)
        migrations.RemoveIndex(model_name='book', name='book_filters_idx'),
        migrations.RemoveIndex(model_name='book', name='due_date_idx'),
        migrations.RemoveIndex(model_name='book', name='followup_idx'),
        migrations.RemoveIndex(model_name='book', name='book_user_status_idx'),

        # 4) احذف الحقول القديمة
        migrations.RemoveField(model_name='book', name='final_status'),
        migrations.RemoveField(model_name='book', name='needs_followup'),
        migrations.RemoveField(model_name='book', name='is_overdue'),

        # 5) أعد الفهارس بصيغتها الجديدة
        migrations.AddIndex(
            model_name='book',
            index=models.Index(fields=['is_deleted', 'kind', 'is_archived'], name='book_filters_idx'),
        ),
        migrations.AddIndex(
            model_name='book',
            index=models.Index(fields=['due_date', 'is_archived'], name='due_date_idx'),
        ),
        migrations.AddIndex(
            model_name='book',
            index=models.Index(fields=['is_archived', 'due_date'], name='followup_idx'),
        ),
        migrations.AddIndex(
            model_name='book',
            index=models.Index(fields=['is_deleted', 'created_by', 'is_archived'], name='book_user_status_idx'),
        ),
    ]
