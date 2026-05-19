# يُحوّل تكرارات الأرقام البسيطة إلى صيغة مركّبة فريدة.
# مثال: 3 كتب مختلفة كلها our_number=20250007 → 20250007001, 20250007002, 20250007003
# مع تجنّب التصادم مع المركّبات الحقيقية الموجودة (قديم-7-Y).

from django.db import migrations
from django.db.models import Count


def dedup_numbers(apps, schema_editor):
    Book = apps.get_model('core', 'Book')

    # كل our_number مكرّر
    dup_values = list(
        Book.objects.values('our_number')
        .annotate(c=Count('id'))
        .filter(c__gt=1)
        .exclude(our_number='')
        .values_list('our_number', flat=True)
    )

    fixed_groups = 0
    fixed_books = 0

    for our_num in dup_values:
        # نتعامل فقط مع الصيغة البسيطة: سنة (2020-2099) + أرقام
        if not (our_num.isdigit() and len(our_num) >= 8 and 2020 <= int(our_num[:4]) <= 2099):
            continue
        year = int(our_num[:4])
        base_n_str = our_num[4:]
        if not base_n_str.isdigit():
            continue
        base_n = int(base_n_str)

        books = list(Book.objects.filter(our_number=our_num).order_by('date', 'id'))
        if len(books) < 2:
            continue

        # القيم المحجوزة لـ (year, base_n) من المركّبات الحقيقية الموجودة
        taken = set(
            Book.objects.filter(series_no=base_n, our_number__startswith=str(year))
            .exclude(version__isnull=True)
            .values_list('version', flat=True)
        )

        next_v = 1
        updates = []
        for b in books:
            while next_v in taken:
                next_v += 1
            b.series_no = base_n
            b.version = next_v
            b.our_number = f"{year}{base_n:04d}{next_v:03d}"
            taken.add(next_v)
            next_v += 1
            updates.append(b)
        Book.objects.bulk_update(updates, ['our_number', 'series_no', 'version'])
        fixed_groups += 1
        fixed_books += len(updates)

    # تحقق نهائي
    remaining = (
        Book.objects.values('our_number')
        .annotate(c=Count('id'))
        .filter(c__gt=1)
        .exclude(our_number='')
        .count()
    )
    print(f'  → فُكّ {fixed_groups} مجموعة تكرار ({fixed_books} كتاب)؛ متبقٍّ غير قابل للفك: {remaining}')


def reverse_dedup(apps, schema_editor):
    """عكس جزئي: يعيد الكتب التي صار لها legacy_number بسيط رقمي."""
    Book = apps.get_model('core', 'Book')
    import re
    updates = []
    for b in Book.objects.exclude(version__isnull=True).iterator(chunk_size=2000):
        legacy = b.legacy_number or ''
        # نعكس فقط ما كان أصلاً رقماً نقياً أو قديم-X (لا قديم-X-Y)
        if re.match(r'^\d+$', legacy) or re.match(r'^قديم-\d+$', legacy):
            year = b.date.year if b.date else 2025
            n = b.series_no or 0
            b.our_number = f"{year}{n:04d}"
            b.series_no = None
            b.version = None
            updates.append(b)
            if len(updates) >= 1000:
                Book.objects.bulk_update(updates, ['our_number', 'series_no', 'version'])
                updates = []
    if updates:
        Book.objects.bulk_update(updates, ['our_number', 'series_no', 'version'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0034_book_compound_numbering'),
    ]

    operations = [
        migrations.RunPython(dedup_numbers, reverse_code=reverse_dedup),
    ]
