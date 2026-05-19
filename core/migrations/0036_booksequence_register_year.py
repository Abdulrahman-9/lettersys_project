# إضافة حقل year لـ BookSequence + ضبط next_number على آخر رقم مُستورَد لكل سجل.

import re
from django.db import migrations, models


REGISTER_CODES = {
    'incoming_internal': '1',
    'incoming_external': '2',
    'outgoing_internal': '3',
    'outgoing_external': '4',
}


def seed_sequences(apps, schema_editor):
    """لكل نوع كتاب: year = أحدث سنة في الكتب، next_number = أكبر تسلسل لتلك السنة + 1."""
    Book = apps.get_model('core', 'Book')
    BookSequence = apps.get_model('core', 'BookSequence')

    from django.utils import timezone
    cur_year = timezone.now().year

    for kind, reg in REGISTER_CODES.items():
        # ابحث عن أكبر تسلسل في كتب هذا النوع للسنة الحالية: our_number = "{cur_year}{reg}{NNNN}"
        prefix = f"{cur_year}{reg}"
        max_seq = 0
        for onum in (Book.objects.filter(kind=kind, our_number__startswith=prefix)
                     .values_list('our_number', flat=True)):
            rest = onum[len(prefix):]
            # rest قد يكون NNNN أو NNNNVV (للأرقام المكررة) — نأخذ أول جزء رقمي
            m = re.match(r'^(\d+)', rest)
            if m:
                # إن كان طول rest > 4 وكان مركّباً (NNNN + VV)، خذ أول 4 خانات كأساس
                base = int(rest[:4]) if len(rest) >= 5 and rest[:4].isdigit() else int(m.group(1))
                if base > max_seq:
                    max_seq = base
        nxt = max_seq + 1 if max_seq else 1
        obj, created = BookSequence.objects.get_or_create(
            kind=kind, defaults={'next_number': nxt, 'year': cur_year, 'prefix': ''}
        )
        if not created:
            obj.year = cur_year
            obj.next_number = nxt
            obj.save(update_fields=['year', 'next_number'])
        print(f"  {kind}: year={cur_year} next_number={nxt} (max imported seq={max_seq})")


def unseed(apps, schema_editor):
    BookSequence = apps.get_model('core', 'BookSequence')
    BookSequence.objects.update(next_number=1)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0035_book_dedup_simple_numbers'),
    ]

    operations = [
        migrations.AddField(
            model_name='booksequence',
            name='year',
            field=models.PositiveSmallIntegerField(
                default=2026, verbose_name='سنة العدّاد',
                help_text='السنة التي يعدّ لها next_number — يتصفّر تلقائياً عند تغيّر السنة',
            ),
        ),
        migrations.AlterField(
            model_name='booksequence',
            name='prefix',
            field=models.CharField(
                blank=True, default='', max_length=20, verbose_name='البادئة (مهملة)',
                help_text='غير مستخدمة بعد التطبيع — يُحتفظ بها للتوافق',
            ),
        ),
        migrations.RunPython(seed_sequences, reverse_code=unseed),
    ]
