from django.db import migrations, models


def assign_outgoing_external_series(apps, schema_editor):
    """Preserve office numbers and assign each department its own internal series."""
    alias = schema_editor.connection.alias
    Book = apps.get_model("core", "Book")
    BookSequence = apps.get_model("core", "BookSequence")

    next_by_department = {}
    counts = {}
    batch = []
    for book in (
        Book.objects.using(alias)
        .filter(kind="outgoing_external")
        .order_by("department_id", "pk")
        .iterator(chunk_size=1000)
    ):
        department_id = book.department_id
        number = next_by_department.get(department_id, 0) + 1
        next_by_department[department_id] = number
        counts[department_id] = number
        book.director_general_number = book.our_number
        book.our_number = str(number)
        batch.append(book)
        if len(batch) == 1000:
            Book.objects.using(alias).bulk_update(
                batch, ["our_number", "director_general_number"], batch_size=1000)
            batch.clear()

    if batch:
        Book.objects.using(alias).bulk_update(
            batch, ["our_number", "director_general_number"], batch_size=1000)

    for department_id, count in counts.items():
        sequence, _ = BookSequence.objects.using(alias).get_or_create(
            department_id=department_id,
            kind="outgoing_external",
            defaults={"next_number": count + 1, "year": 2026},
        )
        if sequence.next_number != count + 1:
            sequence.next_number = count + 1
            sequence.save(using=alias, update_fields=["next_number"])


def restore_office_numbers(apps, schema_editor):
    """Restore office identifiers, refusing to discard a sequence silently."""
    alias = schema_editor.connection.alias
    Book = apps.get_model("core", "Book")
    BookSequence = apps.get_model("core", "BookSequence")
    missing_office_number = (
        Book.objects.using(alias)
        .filter(kind="outgoing_external", our_number__gt="", director_general_number="")
        .values_list("pk", flat=True)
        .first()
    )
    if missing_office_number is not None:
        raise RuntimeError(
            "Cannot reverse outgoing-external numbering: "
            f"book {missing_office_number} has a sequence but no office number."
        )

    batch = []
    for book in Book.objects.using(alias).filter(kind="outgoing_external").iterator(
            chunk_size=1000):
        book.our_number = book.director_general_number
        book.director_general_number = ""
        batch.append(book)
        if len(batch) == 1000:
            Book.objects.using(alias).bulk_update(
                batch, ["our_number", "director_general_number"], batch_size=1000)
            batch.clear()
    if batch:
        Book.objects.using(alias).bulk_update(
            batch, ["our_number", "director_general_number"], batch_size=1000)
    BookSequence.objects.using(alias).filter(kind="outgoing_external").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0084_attachment_version_unique"),
    ]

    operations = [
        migrations.AddField(
            model_name="book",
            name="director_general_number",
            field=models.CharField(
                blank=True, default="", max_length=50,
                verbose_name="رقم مكتب المدير العام"),
        ),
        migrations.RemoveConstraint(
            model_name="book",
            name="uniq_book_number_kind_dept",
        ),
        migrations.RunPython(
            assign_outgoing_external_series,
            restore_office_numbers,
        ),
        migrations.AddConstraint(
            model_name="book",
            constraint=models.UniqueConstraint(
                condition=(~models.Q(our_number="")
                           & models.Q(source_ref="")
                           & models.Q(is_deleted=False)),
                fields=("department", "our_number", "kind"),
                name="uniq_book_number_kind_dept",
            ),
        ),
    ]
