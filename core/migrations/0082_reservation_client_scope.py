from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0081_active_reservation_guard'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='booknumberreservation',
            name='uniq_live_reservation_user_department_kind',
        ),
        migrations.AddField(
            model_name='booknumberreservation',
            name='client_key',
            field=models.CharField(
                blank=True, default='', max_length=64,
                verbose_name='بصمة جلسة المتصفح',
            ),
        ),
        migrations.AddConstraint(
            model_name='booknumberreservation',
            constraint=models.UniqueConstraint(
                fields=('user', 'department', 'kind', 'client_key'),
                condition=Q(status__in=('active', 'reactivated')),
                name='uniq_live_reservation_client_scope',
            ),
        ),
    ]
