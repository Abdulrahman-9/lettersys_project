from django.db import migrations, models


def check_duplicate_versions(apps, schema_editor):
    Version = apps.get_model("core", "AttachmentVersion")
    duplicates = list(
        Version.objects.using(schema_editor.connection.alias)
        .values("attachment_id", "version_number")
        .annotate(total=models.Count("pk"))
        .filter(total__gt=1)
        .order_by("attachment_id", "version_number")[:10]
    )
    if duplicates:
        raise RuntimeError(
            "Duplicate attachment versions must be reviewed before migration; "
            f"no files or rows were removed. First groups: {duplicates}"
        )


class Migration(migrations.Migration):
    dependencies = [("core", "0083_alter_bookhistory_action_alter_bookreferral_status")]

    operations = [
        migrations.RunPython(check_duplicate_versions, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="attachmentversion",
            constraint=models.UniqueConstraint(
                fields=("attachment", "version_number"),
                name="uniq_attachment_version_number",
            ),
        ),
    ]
