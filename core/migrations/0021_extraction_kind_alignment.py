from django.db import migrations, models


BOOK_KIND_VALUES = [
    "outgoing_internal",
    "outgoing_external",
    "incoming_internal",
    "incoming_external",
]


def seed_book_kind_suggestions(apps, schema_editor):
    Category = apps.get_model("core", "SuggestionCategory")
    Item = apps.get_model("core", "SuggestionItem")

    category, _ = Category.objects.get_or_create(
        key="book_kind",
        defaults={
            "name": "نوع الكتاب",
            "description": "التصنيف الرباعي لمسار الكتاب",
            "is_active": True,
        },
    )
    category.name = "نوع الكتاب"
    category.description = "التصنيف الرباعي لمسار الكتاب"
    category.is_active = True
    category.save(update_fields=["name", "description", "is_active"])

    Item.objects.filter(category=category).delete()
    for order, value in enumerate(BOOK_KIND_VALUES):
        Item.objects.create(category=category, value=value, order=order, is_active=True)


def restore_direction_suggestions(apps, schema_editor):
    Category = apps.get_model("core", "SuggestionCategory")
    Item = apps.get_model("core", "SuggestionItem")

    category = Category.objects.filter(key="book_kind").first()
    if not category:
        return

    category.description = "وارد/صادر"
    category.save(update_fields=["description"])

    Item.objects.filter(category=category).delete()
    for order, value in enumerate(["incoming", "outgoing"]):
        Item.objects.create(category=category, value=value, order=order, is_active=True)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0020_remove_legacy_fields"),
    ]

    operations = [
        migrations.AlterField(
            model_name="dataextractionresult",
            name="book_kind",
            field=models.CharField(
                blank=True,
                choices=[
                    ("incoming", "وارد عام"),
                    ("outgoing", "صادر عام"),
                    ("outgoing_internal", "صادر داخلي"),
                    ("outgoing_external", "صادر خارجي"),
                    ("incoming_internal", "وارد داخلي"),
                    ("incoming_external", "وارد خارجي"),
                ],
                max_length=20,
                null=True,
            ),
        ),
        migrations.RunPython(seed_book_kind_suggestions, reverse_code=restore_direction_suggestions),
    ]