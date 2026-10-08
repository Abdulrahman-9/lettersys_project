from django.db import migrations, models
from django.utils import timezone
import django.db.models.deletion


def scope_existing_reservations(apps, schema_editor):
    Reservation = apps.get_model('core', 'BookNumberReservation')
    Department = apps.get_model('core', 'Department')

    default = (
        Department.objects.filter(code='ش13').first()
        or Department.objects.filter(is_active=True).order_by('id').first()
    )
    if default is None:
        return

    Reservation.objects.filter(book__isnull=True).update(department=default)
    for reservation in Reservation.objects.filter(book__isnull=False).select_related('book'):
        reservation.department_id = reservation.book.department_id or default.pk
        reservation.save(update_fields=['department'])

    Reservation.objects.filter(
        book__isnull=True,
        status__in=['active', 'reactivated', 'cooldown'],
    ).update(
        status='expired',
        void_reason='forced_disconnect',
        voided_at=timezone.now(),
    )


class Migration(migrations.Migration):

    atomic = False

    dependencies = [
        ('core', '0079_reservation_ttl'),
    ]

    operations = [
        migrations.AddField(
            model_name='booknumberreservation',
            name='department',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='number_reservations',
                to='core.department',
                verbose_name='القسم',
            ),
        ),
        migrations.RunPython(scope_existing_reservations, migrations.RunPython.noop),
        migrations.AddIndex(
            model_name='booknumberreservation',
            index=models.Index(
                fields=['department', 'kind', 'status'],
                name='core_booknu_departm_677f05_idx',
            ),
        ),
    ]
