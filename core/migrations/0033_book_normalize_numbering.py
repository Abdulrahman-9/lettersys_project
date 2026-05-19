# Generated migration: normalize book numbering to YYYYNNNN format
# Adds: legacy_number, version, and reformats our_number for legacy data.

import re
from django.db import migrations, models


def normalize_numbers(apps, schema_editor):
    """
    تطبيع our_number إلى صيغة YYYYNNNN موحّدة:
    - قديم-XXX-Y       → our_number=YYYYXXXX (year من date), version=Y, legacy=الأصل
    - قديم-XXX         → our_number=YYYYXXXX, legacy=الأصل
    - رقم نقي XXX      → our_number=YYYYXXXX (year من date), legacy=الأصل
    - 20YYNNNN موجود   → يُترك (الصيغة الجديدة)
    - أي شيء آخر       → يُحفظ في legacy_number كما هو
    """
    Book = apps.get_model('core', 'Book')

    LEGACY_VERSIONED = re.compile(r'^قديم-(\d+)-(\d+)$')
    LEGACY_PLAIN     = re.compile(r'^قديم-(\d+)$')
    LEGACY_OTHER     = re.compile(r'^قديم-(.+)$')
    NEW_FORMAT       = re.compile(r'^(20\d{2})(\d{4,})$')
    PURE_DIGITS      = re.compile(r'^\d+$')

    def fmt(year, seq):
        return f"{year}{seq:04d}"

    updates = []
    skipped = 0
    total = Book.objects.count()

    for book in Book.objects.iterator(chunk_size=2000):
        original = book.our_number or ''
        if not original:
            continue

        year = book.date.year if book.date else None
        changed = False

        # 1) Already in new YYYYNNNN format → leave our_number as-is, just record empty legacy
        m = NEW_FORMAT.match(original)
        if m and 2020 <= int(m.group(1)) <= 2099:
            if book.legacy_number != '':
                book.legacy_number = ''
                changed = True
            if changed:
                updates.append(book)
            continue

        # 2) Legacy with version (قديم-XXX-Y)
        m = LEGACY_VERSIONED.match(original)
        if m:
            seq = int(m.group(1))
            ver = int(m.group(2))
            book.legacy_number = original
            book.version = ver
            if year:
                book.our_number = fmt(year, seq)
            else:
                book.our_number = str(seq)
            updates.append(book)
            continue

        # 3) Legacy plain (قديم-XXX)
        m = LEGACY_PLAIN.match(original)
        if m:
            seq = int(m.group(1))
            book.legacy_number = original
            if year:
                book.our_number = fmt(year, seq)
            else:
                book.our_number = str(seq)
            updates.append(book)
            continue

        # 4) Legacy other (قديم-something not pure digit)
        m = LEGACY_OTHER.match(original)
        if m:
            book.legacy_number = original
            # Keep our_number as is (no clean numeric)
            updates.append(book)
            continue

        # 5) Pure digits — convert to YYYYNNNN using book.date.year
        if PURE_DIGITS.match(original):
            seq = int(original)
            book.legacy_number = original
            if year:
                book.our_number = fmt(year, seq)
            updates.append(book)
            continue

        # 6) Unknown format — keep original, record in legacy
        book.legacy_number = original
        updates.append(book)
        skipped += 1

        # Bulk update every 1000 to limit memory
        if len(updates) >= 1000:
            Book.objects.bulk_update(updates, ['our_number', 'legacy_number', 'version'])
            updates = []

    if updates:
        Book.objects.bulk_update(updates, ['our_number', 'legacy_number', 'version'])

    print(f'  → normalized {total} books, {skipped} kept as-is (unknown format)')


def revert_numbers(apps, schema_editor):
    """عكس العملية: يعيد our_number من legacy_number لو كان موجوداً."""
    Book = apps.get_model('core', 'Book')
    updates = []
    for book in Book.objects.exclude(legacy_number='').iterator(chunk_size=2000):
        book.our_number = book.legacy_number
        book.legacy_number = ''
        book.version = None
        updates.append(book)
        if len(updates) >= 1000:
            Book.objects.bulk_update(updates, ['our_number', 'legacy_number', 'version'])
            updates = []
    if updates:
        Book.objects.bulk_update(updates, ['our_number', 'legacy_number', 'version'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0032_network_models'),
    ]

    operations = [
        migrations.AddField(
            model_name='book',
            name='legacy_number',
            field=models.CharField(
                blank=True, default='', max_length=80,
                verbose_name='الرقم الأصلي قبل التطبيع',
                help_text='يحفظ النص الأصلي للرقم قبل عملية التطبيع — للتوافق التاريخي',
            ),
        ),
        migrations.AddField(
            model_name='book',
            name='version',
            field=models.PositiveSmallIntegerField(
                blank=True, null=True,
                verbose_name='نسخة الكتاب',
                help_text='عدّاد النسخ/الجوابات لنفس السجل (مثل -2, -3)',
            ),
        ),
        migrations.AlterField(
            model_name='book',
            name='our_number',
            field=models.CharField(
                db_index=True, default='', max_length=50,
                verbose_name='رقمنا (صادر/وارد)',
            ),
        ),
        migrations.AddIndex(
            model_name='book',
            index=models.Index(fields=['legacy_number'], name='legacy_number_idx'),
        ),
        migrations.RunPython(normalize_numbers, reverse_code=revert_numbers),
    ]
