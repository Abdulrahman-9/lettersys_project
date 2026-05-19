# إعادة هندسة الترقيم: قديم-X-Y → رقم فريد مركّب YYYY+SSSS+VVV
# يصحّح خطأ الترحيل السابق (0033) الذي دمج كتباً مختلفة تحت نفس our_number.

import re
from django.db import migrations, models


def recode_compound(apps, schema_editor):
    """
    يعيد قراءة legacy_number لكل كتاب ويعطيه رقماً فريداً:
    - قديم-X-Y  → our_number=f"{year}{X:04d}{Y:03d}", series_no=X, version=Y
    - قديم-X    → our_number=f"{year}{X:04d}", series_no=NULL, version=NULL
    - رقم نقي X → our_number=f"{year}{X:04d}", series_no=NULL, version=NULL
    - 20YYNNNN  → يُترك (legacy_number فارغ)
    - غير ذلك  → يُترك كما هو
    """
    Book = apps.get_model('core', 'Book')

    COMPOUND = re.compile(r'^قديم-(\d+)-(\d+)$')
    PLAIN    = re.compile(r'^قديم-(\d+)$')
    PURE     = re.compile(r'^(\d+)$')

    def fmt_compound(year, x, y):
        return f"{year}{x:04d}{y:03d}"

    def fmt_simple(year, n):
        return f"{year}{n:04d}"

    updates = []
    recoded_compound = 0
    recoded_simple = 0
    skipped = 0
    total = Book.objects.count()

    for book in Book.objects.iterator(chunk_size=2000):
        legacy = book.legacy_number or ''
        year = book.date.year if book.date else None

        # لا legacy → كان أصلاً بصيغة جديدة، اتركه
        if not legacy:
            if book.series_no is not None or book.version is not None:
                book.series_no = None
                book.version = None
                updates.append(book)
            continue

        m = COMPOUND.match(legacy)
        if m:
            x, y = int(m.group(1)), int(m.group(2))
            book.series_no = x
            book.version = y
            if year:
                book.our_number = fmt_compound(year, x, y)
            else:
                book.our_number = f"{x}-{y}"
            updates.append(book)
            recoded_compound += 1
        else:
            m2 = PLAIN.match(legacy) or PURE.match(legacy)
            if m2:
                n = int(m2.group(1))
                book.series_no = None
                book.version = None
                if year:
                    book.our_number = fmt_simple(year, n)
                updates.append(book)
                recoded_simple += 1
            else:
                # نمط غير معروف — اترك our_number لكن صفّر series/version
                if book.series_no is not None or book.version is not None:
                    book.series_no = None
                    book.version = None
                    updates.append(book)
                skipped += 1

        if len(updates) >= 1000:
            Book.objects.bulk_update(updates, ['our_number', 'series_no', 'version'])
            updates = []

    if updates:
        Book.objects.bulk_update(updates, ['our_number', 'series_no', 'version'])

    print(f'  → recoded: {recoded_compound} مركّب، {recoded_simple} بسيط، {skipped} متروك (من {total})')


def reverse_recode(apps, schema_editor):
    """عكس: يعيد our_number من legacy_number ويصفّر series_no/version."""
    Book = apps.get_model('core', 'Book')
    updates = []
    for book in Book.objects.exclude(legacy_number='').iterator(chunk_size=2000):
        book.our_number = book.legacy_number
        book.series_no = None
        book.version = None
        updates.append(book)
        if len(updates) >= 1000:
            Book.objects.bulk_update(updates, ['our_number', 'series_no', 'version'])
            updates = []
    if updates:
        Book.objects.bulk_update(updates, ['our_number', 'series_no', 'version'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0033_book_normalize_numbering'),
    ]

    operations = [
        migrations.AddField(
            model_name='book',
            name='series_no',
            field=models.PositiveIntegerField(
                blank=True, null=True, db_index=True,
                verbose_name='رقم السلسلة',
                help_text='الجزء الأول من الرقم المركّب (X في X-Y)',
            ),
        ),
        migrations.AlterField(
            model_name='book',
            name='version',
            field=models.PositiveSmallIntegerField(
                blank=True, null=True,
                verbose_name='الرقم الفرعي',
                help_text='الجزء الثاني من الرقم المركّب (Y في X-Y)',
            ),
        ),
        migrations.RunPython(recode_compound, reverse_code=reverse_recode),
    ]
