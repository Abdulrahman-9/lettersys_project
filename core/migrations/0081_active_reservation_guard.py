from django.db import migrations, models
from django.db.models import Q
from django.utils import timezone
from datetime import timedelta


def move_duplicate_live_reservations(apps, schema_editor):
    Reservation = apps.get_model('core', 'BookNumberReservation')
    live_statuses = {'active', 'reactivated'}
    grouped = {}
    for reservation in (
        Reservation.objects
        .filter(status__in=live_statuses)
        .order_by('user_id', 'department_id', 'kind', 'reserved_at', 'pk')
    ):
        key = (reservation.user_id, reservation.department_id, reservation.kind)
        if key not in grouped:
            grouped[key] = reservation.pk
            continue
        reservation.status = 'cooldown'
        reservation.void_reason = 'forced_disconnect'
        reservation.cooldown_until = timezone.now() + timedelta(minutes=15)
        reservation.save(update_fields=[
            'status', 'void_reason', 'cooldown_until',
        ])


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0080_reservation_department'),
    ]

    operations = [
        migrations.RunPython(
            move_duplicate_live_reservations,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name='booknumberreservation',
            constraint=models.UniqueConstraint(
                fields=('user', 'department', 'kind'),
                condition=Q(status__in=('active', 'reactivated')),
                name='uniq_live_reservation_user_department_kind',
            ),
        ),
    ]
