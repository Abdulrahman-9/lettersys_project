from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0029_tag_alter_bookhistory_options_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='book',
            name='document_type',
            field=models.CharField(blank=True, default='', max_length=100, verbose_name='تصنيف المستند'),
        ),
    ]