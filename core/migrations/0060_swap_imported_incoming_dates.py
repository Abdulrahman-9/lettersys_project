# -*- coding: utf-8 -*-
"""مبادلةُ عمودَي التاريخ في الوارد المستورد — تصويبُ انقلابِ دلالةٍ مقيس.

التعيين القديم في الاستيراد (`legacy_restore`) وضع حبرَ الجهة (`DATE`) في
`Book.date` وتاريخَ قيدنا (`CND`) في `Book.sender_date` — عكسَ دلالة الاسمين
في التطبيق («تاريخنا» / «تاريخ الجهة المصدرة»). مؤكَّدٌ عدائيّاً 2026-08-23
(سجلّ التقييم قسم D): رتابةُ سلسلة الختم، اتّجاهُ الفارق (92.5% موجباً)،
وبصمةُ العطل (الجمعة 0/11,050 في عمودنا).

النطاق: الوارد المستورد وحده (`source_ref` غير فارغ، `kind` وارد، والعمودان
موجودان — 11,048 صفّاً عند القياس). الصادر سليمٌ فلا يُمسّ، والكاتبيّ
(source_ref فارغ) دلالتُه مستقيمةٌ أصلاً.

المبادلة **ذاتيّةُ العكس** — الرجوعُ هو التطبيقُ نفسُه. ولقطةُ أمانٍ خارجيّة:
`D:\\migration\\lettersys_models\\backups\\date_swap_undo_20260823.csv`.
تعيينُ الاستيراد نفسُه أُصلح في `_legacy_dates` بنفس الإيداع فلا تتكرّر.
"""
from django.db import migrations
from django.db.models import F


def _swap(apps, schema_editor):
    Book = apps.get_model('core', 'Book')
    (Book.objects
     .exclude(source_ref='').exclude(source_ref__isnull=True)
     .filter(kind__in=('incoming_internal', 'incoming_external'),
             sender_date__isnull=False)
     .update(date=F('sender_date'), sender_date=F('date')))


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0059_scan_payload'),
    ]

    operations = [
        migrations.RunPython(_swap, _swap),   # ذاتيّةُ العكس
    ]
